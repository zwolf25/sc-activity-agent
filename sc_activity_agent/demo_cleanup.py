"""B-119: one-time Demo cleanup. Clears old work orders, proposals and invoices the agent did not create, at all of the Subscriber's
locations. Preview (reads only), then one confirmed job that runs now or every night until the frozen list is done.
ServiceChannel has no delete and no undo: WOs are cancelled or confirmed, open proposals and invoices are rejected.

The job lives in the `demo_job` setting and the demo_cleanup_items table, so it survives restarts. The web pages only change the
job; `tick` (agent loop) starts the one worker thread that does the work."""
import copy
import datetime as dt
import threading
import time
from zoneinfo import ZoneInfo

from . import cleanup, locations, update
from .alerts import Alerts
from .client import RateLimiter, ScError, is_network
from .handlers.common import answer_refrigerant

NOTE = "Closed: outdated record."   # shows on the record in a demo, so it does not name the agent
ACTIVE = cleanup.ACTIVE
HELD = ("PENDING CONFIRMATION", "PENDING REFRIGERANT USE", "PENDING COMPLIANCE DETAILS", "")   # COMPLETED sub-statuses we confirm
RECENT_DAYS = 30
EXPIRES = 86400          # a preview can start a run for this long
BATCH = 50
STOP_AFTER_ERRORS = 10
RATE, FAST_RATE = 10, 15   # calls a minute; 10 leaves the agent room under the app's 15
RUN_LIMIT = 2000         # default stop-after for "Run now"; a nightly job has no count limit unless one is set
REACH_DAYS = 330         # a one-sided "lt" filter lists all history, but a bound older than about a year returns nothing (Prod, 2026-11-27)
WORKING = ("previewing", "running", "scheduled")

_thread = None


def job(store):
    return store.get("demo_job") or {}


def _set(store, **kw):
    j = {**job(store), **kw}
    store.put("demo_job", j)
    return j


def live():
    """True only while the worker thread runs: a restart never leaves a stuck flag."""
    return _thread is not None and _thread.is_alive()


def halt(store, why="Stopped."):
    if job(store).get("state") in WORKING:
        _set(store, state="stopped", message=why)


def _iso(t):
    return cleanup._iso(t)


def _epoch(s):
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return 0
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()


class Api:
    """Subscriber calls for one worker: its own call rate, and its own idea of "paused" (fast mode pauses the agent, not itself)."""

    def __init__(self, store, rt, per_min=RATE, limiter=None):
        self.store, self.rt = store, rt
        self.limiter = limiter or (RateLimiter(per_min) if per_min < FAST_RATE else None)

    def operator_paused(self):
        at = self.store.get("paused_at")
        return at is not None and at != job(self.store).get("own_pause")

    def who(self, kind):
        u = self.rt.candidates("(any location)", kind, {})
        u = next((r for r in u if r["side"] == "subscriber"), None)
        if u is None:
            raise ScError(409, f"No Subscriber user can {kind}. Tick it under Can do on Connections.", "")
        app = copy.copy(self.rt.apps[u["conn_id"]])   # same rate limiter and tokens, different pause rule
        app.paused = self.operator_paused
        return app, (u["username"], self.store.dec(u["password"]))

    def call(self, method, path, params=None, body=None, action="demo_check", wo=None, kind="sub_note", write=None):
        app, user = self.who(kind)
        if self.limiter:
            self.limiter.wait()
        return app.call(user, method, path, params=params, body=body, action=action, wo=wo, write=write)

    def read(self, path, params=None, tries=3):
        for n in range(tries):
            try:
                return self.call("GET", path, params, action="demo_list")
            except OSError as e:
                if n == tries - 1 or not is_network(e):
                    raise

    def keyset(self, path, flt, extra=None):
        """All rows matching flt, oldest Id first. Deep $skip times out on this data, so page by Id."""
        last = 0
        while True:
            rows = self.read(path, {"$filter": f"Id gt {last} and {flt}", "$orderby": "Id asc", "$top": BATCH, **(extra or {})})["value"]
            yield from rows
            if len(rows) < BATCH:
                return
            last = rows[-1]["Id"]


def _labelled(api, protect, flt):
    if not protect:
        return set()
    name = protect.replace("'", "''")
    return {w["Id"] for w in api.keyset("/odata/workorders", f"Labels/any(l: l/Label eq '{name}') and {flt}", {"$select": "Id"})}


def _wos(api, ids, now):
    """{WO id: row}, read from the WO list. GET /workorders/{id} and a proposal's expanded WorkOrder return LocationId 0 (SB2, 2026-11-28)."""
    ids, out = sorted({i for i in ids if i}), {}
    for k in range(0, len(ids), BATCH):
        q = " or ".join(f"Id eq {i}" for i in ids[k:k + BATCH])
        rows = api.read("/odata/workorders", {"$filter": f"({q}) and CallDate lt {_iso(now + 86400)}", "$top": BATCH,
                                              "$select": "Id,ScheduledDate,LocationId"})["value"]
        out.update({r["Id"]: r for r in rows})
    return out


def start_preview(store, months, protect, clock=time.time, any_env=False):
    """Validate the request and queue a preview. Returns an error text, or ''."""
    if not any_env and store.get("env") != "prod":
        return "Demo cleanup runs on Production instances only."
    subscriber_id = store.get("subscriber_id")   # the one saved on Connections; without it the location read is not limited to one Subscriber
    if not subscriber_id:
        return "Save the Subscriber ID on the Connections page first."
    if not 1 <= months <= 60:
        return "Months must be 1 to 60."
    if live():
        return "Demo cleanup is busy. Press Stop first."
    store.db.execute("DELETE FROM demo_cleanup_items")
    store.db.commit()
    store.put("demo_job", {"state": "previewing", "months": months, "subscriber_id": subscriber_id, "protect": protect.strip(),
                           "requested_at": clock()})
    return ""


def preview(store, rt, clock=time.time, api=None):
    """Reads only. Freezes the list of records the job may change."""
    api = api or Api(store, rt)
    j = job(store)
    now = clock()
    cutoff = now - j["months"] * 30.44 * 86400
    bound = _iso(max(cutoff, now - REACH_DAYS * 86400))
    store.db.execute("DELETE FROM demo_cleanup_items")
    locs = {r["db_id"]: r["store_id"] for r in locations.fetch(lambda p, q: api.read(p, q), j["subscriber_id"])}
    own = {r[0] for r in store.db.execute("SELECT sc_id FROM work_orders")}
    protected = _labelled(api, j["protect"], f"CallDate lt {_iso(now + 86400)}")
    skips, seen, looked = {}, 0, 0

    def still_wanted():
        if job(store).get("state") != "previewing":
            raise _End

    def skip_reason(wo_id, loc_id, scheduled, updated):
        if loc_id not in locs:
            return "not this Subscriber, or no linked work order"
        if wo_id in own:
            return "created or picked up by the agent"
        if wo_id in protected:
            return "has the protect label"
        if _epoch(scheduled) > now:
            return "scheduled in the future"
        if _epoch(updated) > now - RECENT_DAYS * 86400:
            return f"updated in the last {RECENT_DAYS} days"

    def add(kind, rid, wo_id, loc_id, status, action, created, provider, reason):
        nonlocal seen, looked
        looked += 1
        if looked % BATCH == 0:
            still_wanted()
        if reason:
            skips[reason] = skips.get(reason, 0) + 1
            return
        store.db.execute("INSERT OR IGNORE INTO demo_cleanup_items(kind, rid, wo_id, location, status, action, created, provider) "
                         "VALUES(?,?,?,?,?,?,?,?)", (kind, rid, wo_id, locs[loc_id], status, action, (created or "")[:10], provider or ""))
        seen += 1
        if seen % 500 == 0:
            store.db.commit()
            _set(store, found=seen)

    proposals = [p for p in api.keyset("/odata/proposals", f"CreatedDate lt {bound} and (Status/Primary eq 'Open' or Status/Primary eq 'On Hold')",
                                       {"$expand": "WorkOrder"}) if _epoch(p.get("CreatedDate")) < cutoff]
    invoices = [i for i in api.keyset("/odata/invoices", f"PostedDate lt {bound} and (Status eq 'Open' or Status eq 'On Hold')")
                if _epoch(i.get("PostedDate")) < cutoff]
    still_wanted()
    linked = _wos(api, [(p.get("WorkOrder") or {}).get("Id") for p in proposals] + [i.get("WoTrackingNumber") for i in invoices], now)
    for p in proposals:
        wo_id = (p.get("WorkOrder") or {}).get("Id")
        w = linked.get(wo_id, {})
        add("proposal", p["Id"], wo_id, w.get("LocationId"), p["Status"]["Primary"], "reject", p.get("CreatedDate"), "",
            skip_reason(wo_id, w.get("LocationId"), w.get("ScheduledDate"), p["Status"].get("ModifiedDate")))
    for i in invoices:
        wo_id = i.get("WoTrackingNumber")   # invoice rows carry no location
        w = linked.get(wo_id, {})
        add("invoice", i["Id"], wo_id, w.get("LocationId"), i.get("Status") or "", "reject", i.get("PostedDate"), "",
            skip_reason(wo_id, w.get("LocationId"), w.get("ScheduledDate"), i.get("UpdatedDate")))
    statuses = " or ".join([f"Status/Primary eq '{s}'" for s in ACTIVE] +
                           [f"(Status/Primary eq 'COMPLETED' and Status/Extended eq '{s}')" for s in HELD])
    for w in api.keyset("/odata/workorders", f"CallDate lt {bound} and ({statuses})",
                        {"$select": "Id,CallDate,UpdatedDate,ScheduledDate,Status,LocationId", "$expand": "Provider($select=Id,Name)"}):
        if _epoch(w.get("CallDate")) >= cutoff:
            continue
        primary, ext = w["Status"]["Primary"], w["Status"].get("Extended") or ""
        if primary in ACTIVE:
            action = "cancel"
        elif primary == "COMPLETED" and ext in HELD:
            action = "refrigerant_confirm" if ext == "PENDING REFRIGERANT USE" else "confirm"
        else:
            continue
        add("wo", w["Id"], w["Id"], w.get("LocationId"), primary if primary in ACTIVE else f"{primary}/{ext}", action, w.get("CallDate"),
            (w.get("Provider") or {}).get("Name"), skip_reason(w["Id"], w.get("LocationId"), w.get("ScheduledDate"), w.get("UpdatedDate")))
    store.db.commit()
    still_wanted()
    _set(store, state="ready", preview_at=clock(), found=seen, skips=skips, locations=len(locs), message="")


def counts(store):
    """{'pending': n, 'done': n, 'skipped': n, 'error': n, 'total': n}"""
    c = dict.fromkeys(("pending", "done", "skipped", "error"), 0)
    c.update({r[0]: r[1] for r in store.db.execute("SELECT state, COUNT(*) FROM demo_cleanup_items GROUP BY state")})
    c["total"] = sum(c.values())
    return c


def breakdown(store):
    q = "SELECT {} AS k, COUNT(*) AS n FROM demo_cleanup_items GROUP BY k ORDER BY n DESC"
    return [(title, [tuple(r) for r in store.db.execute(q.format(col))]) for title, col in
            (("Type and action", "kind || ': ' || action"), ("Status now", "status"), ("Year created", "substr(created,1,4)"),
             ("Location", "location"), ("Provider", "provider"))]


def minutes(start, end):
    """Length of the nightly window in minutes; it may cross midnight."""
    m = lambda s: int(s[:2]) * 60 + int(s[3:])
    return (m(end) - m(start)) % 1440


def estimate(store, per_min=RATE, start="20:00", end="06:00"):
    """(API calls, hours, nights) for what is still pending: one write each, one extra for refrigerant, two reads per 50 WOs, and one
    read for each proposal and invoice."""
    n = {r[0]: r[1] for r in store.db.execute("SELECT kind || ':' || action, COUNT(*) FROM demo_cleanup_items WHERE state='pending' GROUP BY 1")}
    wos = sum(v for k, v in n.items() if k.startswith("wo:"))
    other = sum(n.values()) - wos
    calls = wos + n.get("wo:refrigerant_confirm", 0) + 2 * -(-wos // BATCH) + 3 * other
    mins = calls / per_min
    window = minutes(start, end) or 1440
    return calls, mins / 60, int(-(-mins // window))


def expired(store, clock=time.time):
    return clock() - job(store).get("preview_at", 0) > EXPIRES


def start_run(store, understood, mode="nightly", start="20:00", end="06:00", limit=0, fast=False, clock=time.time):
    """The one confirmation for the whole job. Also used by Resume, which skips the 24-hour preview limit."""
    j = job(store)
    if j.get("state") not in ("ready", "stopped", "error") or not j.get("preview_at"):
        return "Run a preview first."
    if not j.get("started_at") and expired(store, clock):
        return "The preview is more than 24 hours old. Run a new preview."
    if j["subscriber_id"] != store.get("subscriber_id"):
        return "The Subscriber ID on Connections changed after this preview. Run a new preview."
    if not understood:
        return "Tick the box to confirm."
    try:
        window = minutes(start, end)
    except ValueError:
        return "Enter the times as HH:MM."
    if mode not in ("nightly", "now") or (mode == "nightly" and not window):
        return "The nightly start and end times must differ."
    if not counts(store)["pending"]:
        return "Nothing is left to do."
    update.backup(store)
    _set(store, state="scheduled" if mode == "nightly" else "running", mode=mode, start=start, end=end, limit=max(0, int(limit)),
         fast=bool(fast), errors_in_a_row=0, started_at=j.get("started_at") or clock(), run_done=0, night=None, night_done=0, skip_night=None, message="")
    return ""


def night_of(store, j, now):
    """The date the current window opened on, or None outside the window."""
    local = dt.datetime.fromtimestamp(now, ZoneInfo(store.get("tz", "America/New_York")))
    h, m = int(j["start"][:2]), int(j["start"][3:])
    since = (local.hour * 60 + local.minute - h * 60 - m) % 1440
    return (local - dt.timedelta(minutes=since)).date().isoformat() if since < minutes(j["start"], j["end"]) else None


class _End(Exception):
    """Ends this session. The remaining items stay pending."""


def session(store, rt, engine=None, clock=time.time, api=None):
    """Work through pending items until the list, the window or the count limit ends, or something says stop."""
    j = job(store)
    state, mode = j["state"], j["mode"]
    night = night_of(store, j, clock()) if mode == "nightly" else None
    if mode == "nightly":
        if night is None:
            return
        if night != j.get("night"):
            _set(store, night=night, night_done=0)
    api = api or Api(store, rt, FAST_RATE if j.get("fast") else RATE)
    done_key = "night_done" if mode == "nightly" else "run_done"
    cap = j.get("limit", 0)

    def left():
        return cap - job(store).get(done_key, 0) if cap else BATCH

    def check():
        if job(store).get("state") != state or api.operator_paused():
            raise _End
        if mode == "nightly" and night_of(store, job(store), clock()) != night:
            raise _End
        if left() <= 0:
            raise _End

    def mark(item, result, reason=""):
        store.db.execute("UPDATE demo_cleanup_items SET state=?, reason=?, done_at=? WHERE id=?", (result, reason[:200], clock(), item["id"]))
        store.db.commit()
        if result == "done":
            _set(store, **{done_key: job(store).get(done_key, 0) + 1})

    def fail(item, e):
        mark(item, "error", str(e))
        n = job(store).get("errors_in_a_row", 0) + 1
        _set(store, errors_in_a_row=n)
        if n >= STOP_AFTER_ERRORS:
            _set(store, state="error", message=f"Stopped after {n} errors in a row. Last: {str(e)[:200]}")
            raise _End

    own_pause = None
    if j.get("fast") and engine is not None and store.get("paused_at") is None:
        engine.pause()
        own_pause = store.get("paused_at")
        _set(store, own_pause=own_pause)
    network = False
    try:
        while True:
            check()
            first = store.db.execute("SELECT kind FROM demo_cleanup_items WHERE state='pending' "
                                     "ORDER BY CASE kind WHEN 'proposal' THEN 1 WHEN 'invoice' THEN 2 ELSE 3 END, rid LIMIT 1").fetchone()
            if not first:
                break
            kind = first["kind"]
            size = min(BATCH if kind == "wo" else 1, left())
            batch = store.db.execute(f"SELECT * FROM demo_cleanup_items WHERE state='pending' AND kind=? ORDER BY rid LIMIT ?",
                                     (kind, size)).fetchall()
            try:
                fresh, shielded = _reread(api, job(store), kind, batch, clock())
            except ScError as e:
                if e.status == 0 or e.path == "token":
                    raise
                for item in batch:
                    fail(item, e)
                continue
            for item in batch:
                check()
                why = _changed(item, fresh.get(item["rid"]), shielded, clock())
                if why:
                    mark(item, "skipped", why)
                    continue
                try:
                    _write(api, store, rt, item)
                except ScError as e:
                    if e.status == 0 or e.path == "token":
                        raise
                    # 921 is ServiceChannel refusing this record (invoiced, or locked as completed); a 400 on a confirm means a hold we cannot clear
                    if e.status == 400 and ('"ErrorCode":921' in str(e.body) or item["action"].endswith("confirm")):
                        mark(item, "skipped", f"refused by ServiceChannel: {e.body}")
                    else:
                        fail(item, e)
                else:
                    mark(item, "done")
                    _set(store, errors_in_a_row=0)
    except _End:
        pass
    except ScError as e:
        if e.path == "token":   # never retry a rejected sign-in: ServiceChannel locks the login after a few
            _set(store, state="error", message=f"Sign-in failed, so the job stopped: {str(e)[:200]}")
        elif e.status != 0:
            _set(store, state="error", message=str(e)[:300])
    except OSError as e:
        network = True
        _set(store, message=f"Network problem: {type(e).__name__}. Pending items are unchanged or will be re-checked.")
    finally:
        if own_pause is not None and store.get("paused_at") == own_pause:
            engine.resume(store.get("resume_policy", "catch_up"))
        _set(store, own_pause=None)
        _finish(store, state, mode, night, network, clock)


def _reread(api, j, kind, batch, now):
    """Live state of the batch, read immediately before its writes. Returns ({record id: live row}, WO ids that carry the label)."""
    bound = _iso(now + 86400)   # without a date filter the lists cover only 90 days
    if kind == "invoice":
        i = batch[0]
        row = api.call("GET", f"/invoices/{i['rid']}")
        fresh = {i["rid"]: row} if row else {}
    else:
        ids = "(" + " or ".join(f"Id eq {i['rid']}" for i in batch) + ")"
        path = "/odata/workorders" if kind == "wo" else "/odata/proposals"
        extra = {"$select": "Id,Status,ScheduledDate"} if kind == "wo" else {}
        rows = api.call("GET", path, {"$filter": f"{ids} and {'CallDate' if kind == 'wo' else 'CreatedDate'} lt {bound}", "$top": BATCH, **extra})
        fresh = {r["Id"]: r for r in rows["value"]}
    wos = "(" + " or ".join(f"Id eq {i['wo_id']}" for i in batch) + ")"
    return fresh, _labelled(api, j["protect"], f"{wos} and CallDate lt {bound}")


def _changed(item, row, shielded, now):
    """Why this record must be left alone now, or None."""
    if row is None:
        return "no longer listed"
    if item["wo_id"] in shielded:
        return "protect label added"
    status = row.get("Status")
    if isinstance(status, dict):
        primary, ext = status.get("Primary") or "", status.get("Extended") or ""
        seen = primary if item["kind"] != "wo" or item["status"] in ACTIVE else f"{primary}/{ext}"
    else:
        seen = status or ""
    if seen.upper() != item["status"].upper():   # sub-status of an active WO may move: rejecting its proposal changes it
        return f"status is now {seen}"
    if item["kind"] == "wo" and _epoch(row.get("ScheduledDate")) > now:
        return "now scheduled in the future"


def _write(api, store, rt, item):
    rid, wo = item["rid"], item["wo_id"]
    if item["kind"] == "proposal":
        api.call("PUT", f"/proposals/{rid}/reject", params={"useProposalAlertEmails": "false"}, action="demo_reject", wo=wo,
                 kind="proposal_decide", body={"Comment": NOTE, "ActionSource": "Standard", "RejectReasonCodeId": 7})
    elif item["kind"] == "invoice":
        api.call("PUT", f"/invoices/{rid}/reject", params={"comments": NOTE, "isNotifyProvider": "false"}, action="demo_reject", wo=wo,
                 kind="invoice_decide")
    else:
        if item["action"] == "refrigerant_confirm":
            if api.limiter:
                api.limiter.wait()
            app = api.who("sub_note")[0]
            answer_refrigerant(rt, {"sc_id": rid, "location": item["location"], "ctx": "{}"}, action="demo_answer", app=app)
        status = "CANCELED" if item["action"] == "cancel" else "CONFIRMED"
        api.call("PUT", f"/workorders/{rid}/status", action=f"demo_{item['action']}", wo=rid,
                 body={"Status": {"Primary": "COMPLETED", "Extended": status}, "Note": NOTE})


def _summary(store):
    c = counts(store)
    return f"{c['done']} done, {c['skipped']} skipped, {c['error']} errors, {c['pending']} left"


def _finish(store, state, mode, night, network, clock):
    j = job(store)
    ended = j["state"] == state
    if ended and not counts(store)["pending"]:
        j = _set(store, state="done", message="")
    elif ended and mode == "now" and (network or (j.get("limit") and j.get("run_done", 0) >= j["limit"])):
        j = _set(store, state="stopped", message=j.get("message") or f"Stopped after {j['run_done']} records. Resume to continue.")
    elif ended and mode == "nightly":
        # a network failure or a used-up count limit ends this night; the window end needs no marker
        if network or (j.get("limit") and j.get("night_done", 0) >= j["limit"]):
            _set(store, skip_night=night)
    j = job(store)
    if j["state"] in ("done", "error") or (mode == "nightly" and j["state"] == "scheduled"):
        text = {"done": "Demo cleanup finished", "error": "Demo cleanup stopped on errors"}.get(j["state"], f"Demo cleanup, night of {night}")
        text += f": {_summary(store)}." + (f" {j['message']}" if j.get("message") else "")
        Alerts(store).send(f"demo-{j['state']}-{night}", text)
    log = store.get("changes", [])[-49:]
    log.append({"at": clock(), "what": f"demo cleanup {j['state']}: {_summary(store)}"})
    store.put("changes", log)


def due(store, clock=time.time):
    """What the worker should do now: 'preview', 'session' or None."""
    j = job(store)
    state = j.get("state")
    if state == "previewing":
        return "preview"
    if state not in ("running", "scheduled") or (store.get("cleanup_run") or {}).get("running"):
        return None
    at = store.get("paused_at")
    if at is not None and at != j.get("own_pause"):
        return None
    if state == "scheduled" and night_of(store, j, clock()) in (None, j.get("skip_night")):
        return None
    return "session"


def tick(store, rt, engine=None, clock=time.time):
    """Agent loop piece. One worker thread at a time; the long calls never block the step loop."""
    global _thread
    if live():
        return []
    own = job(store).get("own_pause")
    if own is not None:   # the agent restarted during a fast-mode session: give the agent back
        if store.get("paused_at") == own and engine is not None:
            engine.resume(store.get("resume_policy", "catch_up"))
        _set(store, own_pause=None)
    what = due(store, clock)
    if not what:
        return []

    def go():
        try:
            if what == "preview":
                try:
                    preview(store, rt, clock)
                except Exception as e:  # noqa: BLE001
                    if job(store).get("state") == "previewing":
                        _set(store, state="preview_failed", message=f"{type(e).__name__}: {str(e)[:200]}")
            else:
                session(store, rt, engine, clock)
        except Exception as e:  # noqa: BLE001
            _set(store, state="error", message=f"{type(e).__name__}: {str(e)[:200]}")
        finally:
            store.settle("demo cleanup")
    _thread = threading.Thread(target=go, daemon=True, name="demo-cleanup")
    _thread.start()
    return [("start", what)]
