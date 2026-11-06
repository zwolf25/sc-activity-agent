"""Guards around every executor: read the live WO first (B-39), follow user changes, and end the plan when the WO was cancelled outside the agent."""
import datetime as dt
import json
import time

from ..client import Later, Park, ScError
from .common import end_plan


ALREADY_DONE_WHEN_COMPLETED = {"accept", "decline", "reassign", "reschedule", "check_in", "check_out", "proposal_create", "proposal_decide"}


KNOWN_STATUS = {"OPEN", "IN PROGRESS", "ON HOLD", "COMPLETED"}


def preflight(rt, call, wo, step, kind, snap=lambda ts: ts):
    """B-39: read the live WO before a write. A cancelled WO ends the plan; a WO a user already completed makes the field steps
    moot; a changed date, NTE or priority is followed (see `follow`). Returns True when the step must not run. A failed read
    changes nothing: the step runs and its own guard handles it."""
    try:
        w = call(wo, step, "GET", f"/workorders/{wo['sc_id']}") or {}
    except ScError:
        return False
    st = w.get("Status", {})
    if st.get("Extended") == "CANCELED":
        end_plan(rt, wo)
        return True
    if st.get("Primary") == "COMPLETED" and kind in ALREADY_DONE_WHEN_COMPLETED:
        return True
    follow(rt, wo, step, w, snap)
    return False


def follow(rt, wo, step, w, snap=lambda ts: ts):
    """B-39: bring the plan in line with what a user changed on the live WO. NTE and priority go into the saved context (invoice
    and proposal amounts and the notes read it). A later scheduled date moves the remaining steps by the same amount. A status
    the plan does not know, or a provider the plan did not assign, parks the plan: the step fails at once for the Errors page."""
    ctx = json.loads(wo["ctx"])
    prov = (w.get("Provider") or {}).get("Id")
    if w.get("Status", {}).get("Primary", "OPEN") not in KNOWN_STATUS:
        raise Park(f"WO status {w.get('Status')} is not one the plan knows. Skip the step to carry on, or cancel the WO.")
    if ctx.get("provider_id") and prov and prov != ctx["provider_id"]:
        raise Park(f"A user moved the WO to provider {prov}; the plan was built for {ctx['provider_id']}. Skip the step to carry on, or cancel the WO.")
    new = {k: v for k, v in (("nte", w.get("Nte")), ("priority", w.get("Priority"))) if v is not None and v != ctx.get(k)}
    live, later = w.get("ScheduledDate"), False
    if live:
        ts = dt.datetime.fromisoformat(live.replace("Z", "+00:00")).timestamp()
        known = ctx.get("sched")
        if known is not None and abs(ts - known) > 300:
            rows = rt.store.db.execute("SELECT id, kind, due_at FROM steps WHERE wo_id=? AND state='pending' AND seq>=? ORDER BY seq", (wo["id"], step["seq"])).fetchall()
            i = next((i for i, r in enumerate(rows) if r["kind"] == "check_in"), None)
            if i is not None:   # the visit and everything after it; earlier notes and the accept stay on time
                rows = rows[i:]
                # land the visit inside activity hours on a weekday, and move every step by that same amount so spacing and the check-out day hold
                delta = snap(rows[0]["due_at"] + ts - known) - rows[0]["due_at"]
                floor = step["due_at"]   # nothing moves before the running step
                for r in rows:   # shifted, never into the past, order kept
                    floor = max(r["due_at"] + delta, floor)
                    rt.store.db.execute("UPDATE steps SET due_at=? WHERE id=?", (floor, r["id"]))
                rt.store.db.commit()
                later = rows[0]["id"] == step["id"] and floor > step["due_at"]
        if known is None or abs(ts - known) > 300:
            new["sched"] = ts
    if new:
        rt.save_ctx(wo, **new)
    if later:
        raise Later()   # the running step itself moved (a check-in for the old date): it waits for its new time


FIELD = {"accept", "decline", "reassign", "reschedule", "prov_note", "sub_note", "check_in", "check_out", "proposal_create", "proposal_decide", "review"}


WATCH_EVERY, WATCH_MAX = 3600, 1   # on by default (setting status_check, Settings page); the preflight read alone only catches changes before a write


def watch(store, rt, clock=time.time):
    """B-39: read the live status of the WOs that still have pending steps, least recently read first. A WO the user cancelled
    ends its plan here instead of failing a step later. Returns [(sc_id, outcome)]."""
    if not store.get("status_check", True) or store.get("paused_at") is not None or clock() - store.get("watch_at", 0) < WATCH_EVERY:
        return []
    store.put("watch_at", clock())
    out = []
    for wo in store.db.execute(
            "SELECT w.* FROM work_orders w WHERE w.state='active' AND EXISTS (SELECT 1 FROM steps s WHERE s.wo_id=w.id AND s.state='pending') "
            "ORDER BY COALESCE(json_extract(w.ctx,'$.watched'),0) LIMIT ?", (WATCH_MAX,)).fetchall():
        try:
            app, user = rt.user_for(wo["location"], "sub_note", wo)
            st = (app.call(user, "GET", f"/workorders/{wo['sc_id']}", action="watch", wo=wo["sc_id"]) or {}).get("Status", {})
        except ScError as e:
            if e.status != 0:
                rt.save_ctx(wo, watched=clock())   # least-recently-read goes first: a WO that always fails to read (404) must not block every other WO
            continue   # a failed read changes nothing else; the next pass tries again
        rt.save_ctx(wo, watched=clock())
        if st.get("Extended") == "CANCELED":
            end_plan(rt, wo)
            out.append((wo["sc_id"], "cancelled by a user: plan ended"))
    return out


def guarded(rt, call, kind, fn):
    """If a write is refused, read the live WO. The user may have moved it on: a cancelled WO ends the plan, a completed
    WO makes the field steps moot, and a check-in/out the user already did is done. Anything else is a real failure."""
    def run(engine, wo, step):
        try:
            if preflight(rt, call, wo, step, kind, getattr(engine, "snap", lambda ts: ts)):
                return
            return fn(engine, wo, step)
        except ScError as e:
            if e.status not in (400, 403, 409):
                raise
            try:
                w = call(wo, step, "GET", f"/workorders/{wo['sc_id']}")
            except ScError:
                raise e from None
            st = w.get("Status", {})
            if st.get("Extended") == "CANCELED":
                end_plan(rt, wo)
            elif st.get("Primary") == "COMPLETED" and kind in FIELD:
                return
            elif kind == "check_in" and st.get("Extended") == "ON SITE":
                return
            else:
                raise
    return run
