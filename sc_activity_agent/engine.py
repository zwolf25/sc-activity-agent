"""Tick loop: run due plan steps through role handlers, record results, retry or fail, handle pause/resume."""
import datetime as dt
import json
import random
import time
from zoneinfo import ZoneInfo

from .alerts import Alerts
from .client import Later, Park, ScError

MERGE_SECONDS = 1800  # a new gap starting this soon after an unread one extends it
GAP_SECONDS = 600  # silence longer than this between ticks is a gap (sleep, shutdown, crash)
MAX_ATTEMPTS = 3
BACKOFF = (120, 600, 1800)


def user_bound(e):
    """A refusal that another user may not get: no permission or over the approval limit (403), an opaque 501, a status change refused for this user (921).
    "Invalid WorkOrder status" is about the WO, so it never rotates."""
    b = str(getattr(e, "body", ""))
    return isinstance(e, ScError) and (e.status == 403 or '"ErrorCode":921' in b or ('"ErrorCode":501' in b and "Invalid WorkOrder status" not in b))


class Engine:
    def __init__(self, store, handlers, clock=time.time, per_tick=10):
        """handlers: {step_kind: fn(engine, wo_row, step_row) -> None}. Raise ScError to fail a step."""
        self.store, self.handlers, self.clock, self.per_tick = store, handlers, clock, per_tick
        self.paused_at = store.get("paused_at")
        self.rng = random.Random()
        self.rotate = None   # fn(wo, step) -> bool, set by the CLI: pick another user for a step

    @property
    def paused(self):
        return self.paused_at is not None

    def pause(self):
        self.paused_at = self.clock()
        self.store.put("paused_at", self.paused_at)

    def resume(self, policy="catch_up"):
        """push: shift every pending step by the pause length. catch_up: spread overdue steps over the next hour."""
        now = self.clock()
        if self.paused_at is not None:
            if policy == "push":
                self.store.db.execute("UPDATE steps SET due_at=due_at+? WHERE state='pending'", (now - self.paused_at,))
            else:
                rows = self.store.db.execute(
                    "SELECT id FROM steps WHERE state='pending' AND due_at<? ORDER BY due_at", (now,)).fetchall()
                for r in rows:
                    self.store.db.execute("UPDATE steps SET due_at=? WHERE id=?", (now + self.rng.uniform(0, 3600), r["id"]))
            self.store.db.commit()
        self.paused_at = None
        self.store.put("paused_at", None)

    def due(self, now):
        return self.store.db.execute(
            """SELECT s.*, w.sc_id, w.location, w.state AS wo_state FROM steps s JOIN work_orders w ON w.id=s.wo_id
               WHERE s.state='pending' AND s.due_at<=? AND w.state NOT IN ('cancelled','closed')
                 AND NOT EXISTS (SELECT 1 FROM steps e WHERE e.wo_id=s.wo_id AND e.seq<s.seq
                                 AND (e.state='failed' OR (e.state='pending' AND e.due_at>?)))
               ORDER BY s.due_at LIMIT ?""", (now, now, self.per_tick)).fetchall()   # B-66: a step behind a failed or future one cannot run, so it must not take a slot

    def zone(self, location=None):
        """B-74: the time zone of a location's store, else the instance zone."""
        r = self.store.db.execute("SELECT tz FROM locations WHERE store_id=?", (location,)).fetchone() if location else None
        return ZoneInfo((r and r["tz"]) or self.store.get("tz", "America/New_York"))

    def snap(self, ts, location=None):
        """Move ts to the next moment inside activity hours on an activity day (unchanged if already inside).
        Hours and days are read in the location's time zone."""
        tz = self.zone(location)
        h0, h1 = self.store.get("hours_start", 8), self.store.get("hours_end", 17)
        days = self.store.get("days", [0, 1, 2, 3, 4])
        d = dt.datetime.fromtimestamp(ts, tz)
        start = d.replace(hour=h0, minute=0, second=0, microsecond=0)
        if d.weekday() in days and start <= d < d.replace(hour=h1, minute=0, second=0, microsecond=0):
            return ts
        if d.weekday() in days and d < start:
            return start.timestamp()
        d = start + dt.timedelta(days=1)
        while d.weekday() not in days:
            d += dt.timedelta(days=1)
        return d.timestamp()

    def apply_gap(self, start, end, policy="shift"):
        """Re-time pending steps after a gap. shift: move each affected WO's remaining steps by the gap, snapped to activity
        hours, order kept, check-out stays after and on the day of its check-in. catch_up: spread overdue steps over the next
        hour. skip_stale: skip overdue notes, then shift. Returns {step_id: old_due_at} so the choice can be undone."""
        db, undo = self.store.db, {}
        rows = db.execute("SELECT s.*, w.id AS wid, w.location AS loc FROM steps s JOIN work_orders w ON w.id=s.wo_id "
                          "WHERE s.state='pending' AND w.state='active' ORDER BY s.wo_id, s.seq").fetchall()
        overdue_wos = {r["wid"] for r in rows if r["due_at"] <= end}
        if policy == "skip_stale":
            for r in rows:
                if r["due_at"] <= end and r["kind"] in ("prov_note", "sub_note"):
                    undo[r["id"]] = r["due_at"]
                    db.execute("UPDATE steps SET state='skipped' WHERE id=?", (r["id"],))
            rows = [r for r in rows if r["id"] not in undo]
        wo_last, ci = {}, {}
        for r in rows:
            if r["wid"] not in overdue_wos:
                continue
            old = r["due_at"]
            if policy == "catch_up":
                new = end + self.rng.uniform(0, 3600) if old <= end else old
            else:
                new = self.snap(old + (end - start), r["loc"])
                if r["kind"] == "check_in":
                    ci[r["wid"]] = (old, new)
                elif r["kind"] == "check_out" and r["wid"] in ci:
                    o, n = ci[r["wid"]]
                    day_end = dt.datetime.fromtimestamp(n, self.zone(r["loc"])).replace(hour=self.store.get("hours_end", 17), minute=0, second=0).timestamp()
                    new = min(n + (old - o), day_end)
                new = max(new, wo_last.get(r["wid"], 0))
            wo_last[r["wid"]] = new
            undo[r["id"]] = old
            db.execute("UPDATE steps SET due_at=? WHERE id=?", (new, r["id"]))
        db.commit()
        return undo

    def _check_gap(self, now):
        last = self.store.get("last_tick")
        self.store.put("last_tick", now)
        if last is None or now - last <= GAP_SECONDS:
            return
        Alerts(self.store).offline(last, now)
        undo = self.apply_gap(last, now, "shift")
        gaps = self.store.get("gaps", [])
        prev = gaps[-1] if gaps else None
        if prev and not prev["acked"] and last - prev["end"] <= MERGE_SECONDS:
            # a sleeping laptop wakes and dozes again and again; one notice covers the whole stretch
            prev["undo"] = {**undo, **prev["undo"]}   # the earliest original time of each step wins
            prev.update(end=now, steps=len(prev["undo"]))
        else:
            gaps.append({"start": last, "end": now, "policy": "shift", "steps": len(undo), "undo": undo, "acked": False})
        self.store.put("gaps", gaps[-50:])

    def resolve_gap(self, index, policy):
        """Dashboard card choice: restore the gap's original times, then apply the chosen policy."""
        gaps = self.store.get("gaps", [])
        g = gaps[index]
        for sid, old in g["undo"].items():
            self.store.db.execute("UPDATE steps SET due_at=?, state='pending' WHERE id=? AND state IN ('pending','skipped')", (old, int(sid)))
        self.store.db.commit()
        g["undo"] = {str(k): v for k, v in self.apply_gap(g["start"], g["end"], policy).items()}
        g.update(policy=policy, acked=True)
        self.store.put("gaps", gaps)

    def tick(self):
        """Run up to per_tick due steps in order. Returns list of (step_id, outcome)."""
        if self.paused:
            self.store.put("last_tick", self.clock())
            return []
        now, out = self.clock(), []
        self._check_gap(now)
        for st in self.due(now):
            # an earlier step in this tick may have inserted steps (rework, resubmit), moved this one or ended the plan: use its current row
            cur = self.store.db.execute("SELECT * FROM steps WHERE id=?", (st["id"],)).fetchone()
            if not cur or cur["state"] != "pending":
                continue
            st = {**dict(st), **dict(cur)}
            # a WO's steps run in sequence: skip if an earlier step of the same WO is still unfinished
            earlier = self.store.db.execute(
                "SELECT 1 FROM steps WHERE wo_id=? AND seq<? AND state IN ('pending','failed')", (st["wo_id"], st["seq"])).fetchone()
            if earlier:
                continue
            wo = self.store.db.execute("SELECT * FROM work_orders WHERE id=?", (st["wo_id"],)).fetchone()
            try:
                self.handlers[st["kind"]](self, wo, st)
                self.store.db.execute("UPDATE steps SET state='done', done_at=?, error=NULL WHERE id=?", (now, st["id"]))
                out.append((st["id"], "done"))
            except Later:
                pass   # follow() already re-timed the step
            except Exception as e:  # a handler bug must fail its step, not loop forever on it
                if isinstance(e, ScError) and e.status == 0:  # paused mid-tick
                    break
                n = MAX_ATTEMPTS if isinstance(e, Park) else st["attempts"] + 1
                if n >= MAX_ATTEMPTS and self.rotate and user_bound(e) and self.rotate(wo, st):
                    self.store.db.execute("UPDATE steps SET attempts=0, error=?, due_at=? WHERE id=?", (f"{e} (switching to another user after {n} failures)", now, st["id"]))
                    out.append((st["id"], "switch"))
                elif n >= MAX_ATTEMPTS:
                    self.store.db.execute("UPDATE steps SET state='failed', attempts=?, error=? WHERE id=?", (n, str(e), st["id"]))
                    out.append((st["id"], "failed"))
                    Alerts(self.store).step_failed(wo, st, e)
                else:
                    self.store.db.execute("UPDATE steps SET attempts=?, error=?, due_at=? WHERE id=?",
                                          (n, str(e), now + BACKOFF[n - 1], st["id"]))
                    out.append((st["id"], "retry"))
            self.store.db.commit()
        return out

    # operator actions from the Errors page
    def retry(self, step_id):
        p = {k: v for k, v in json.loads(self.store.db.execute("SELECT payload FROM steps WHERE id=?", (step_id,)).fetchone()[0]).items() if k not in ("user", "tried")}   # re-pick: the account may be fixed
        self.store.db.execute("UPDATE steps SET state='pending', attempts=0, due_at=?, payload=? WHERE id=?", (self.clock(), json.dumps(p), step_id))
        self.store.db.commit()

    def skip(self, step_id):
        self.store.db.execute("UPDATE steps SET state='skipped' WHERE id=?", (step_id,))
        self.store.db.commit()

    def cancel_plan(self, wo_id):
        self.store.db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?", (wo_id,))
        self.store.db.commit()


def add_plan(store, location, trade, sc_id, plan, ctx, now):
    """Persist a WO and its plan steps (from planner.build_plan)."""
    cur = store.db.execute("INSERT INTO work_orders(sc_id, location, trade, state, created_at, ctx) VALUES(?,?,?,?,?,?)",
                           (sc_id, location, trade, "active", now, json.dumps(ctx)))
    wo_id = cur.lastrowid
    for i, s in enumerate(plan):
        store.db.execute("INSERT INTO steps(wo_id, seq, kind, due_at, payload) VALUES(?,?,?,?,?)",
                         (wo_id, i, s["kind"], s["due_at"], json.dumps(s["payload"])))
    store.db.commit()
    return wo_id
