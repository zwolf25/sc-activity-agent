"""Shared by the step executors."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from .. import planner

ACTION = {"accept": "accept", "prov_note": "provider_note", "sub_note": "subscriber_note", "review": "review",
          "proposal_create": "proposal_create", "proposal_decide": "proposal_decide", "check_in": "check_in",
          "check_out": "check_out", "invoice_submit": "invoice_submit", "invoice_decide": "invoice_decide",
          "invoice_pay": "invoice_decide",   # the same Subscriber user decides and pays; no new role row for existing instances
          "decline": "accept", "reschedule": "accept", "reassign": "subscriber_note", "cancel": "subscriber_note",   # a provider who can accept can also decline and reschedule
          "create": "create_wo"}


from ..client import Skip  # noqa: F401  (Runtime.user_for raises it; the engine ends the step as done)



def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def answer_refrigerant(rt, wo, action="rt_answer", app=None):
    """Answer the refrigerant prompt "no refrigerant used, no leak" on the WO. Only a Subscriber user may (a Provider gets 804, SB2 2026-11-27).
    Before check-out it keeps the WO out of PENDING REFRIGERANT USE; after, it lets the review and the invoice through (the status text
    stays PENDING until the review, so never read it back as proof)."""
    picked, user = rt.user_for(wo["location"], "sub_note", wo)
    (app or picked).call(user, "PUT", f"/workorders/{wo['sc_id']}/UpdateWorkOrderLeakInspectionInfo", params={"refrigerantWasUsed": "false", "leakWasDetected": "false"},
             body={}, action=action, wo=wo["sc_id"], write=True)


def insert_steps(store, wo_id, after_seq, steps):
    """Add steps right after `after_seq` of a WO, shifting later steps down. steps: [(kind, due_at, payload)]."""
    store.db.execute("UPDATE steps SET seq=seq+? WHERE wo_id=? AND seq>?", (len(steps), wo_id, after_seq))
    for i, (kind, due, payload) in enumerate(steps, 1):
        store.db.execute("INSERT INTO steps(wo_id, seq, kind, due_at, payload) VALUES(?,?,?,?,?)",
                         (wo_id, after_seq + i, kind, due, json.dumps(payload)))
    store.db.commit()


def move_after(rt, wo, after_seq, delta, snap):
    """Move every pending step after `after_seq` later by one shared amount, so their spacing holds. The first one lands in activity hours."""
    rows = rt.store.db.execute("SELECT id, due_at FROM steps WHERE wo_id=? AND seq>? AND state='pending' ORDER BY seq", (wo["id"], after_seq)).fetchall()
    if rows and delta > 0:
        delta = snap(rows[0]["due_at"] + delta) - rows[0]["due_at"]
        for r in rows:
            rt.store.db.execute("UPDATE steps SET due_at=? WHERE id=?", (r["due_at"] + delta, r["id"]))
        rt.store.db.commit()


def next_decision(rt, wo, submitted, key):
    """(due_at, review days) for a Subscriber decision on something submitted at `submitted`. key: the behavior setting with the average."""
    c = {**planner.DEFAULTS, **rt.store.get("behavior", {})}
    k = planner.review_days(rt.rng, c[key])
    return planner.decision_at(submitted, k, c, _tz(rt, wo), rt.rng), k


def hold_decision(rt, wo, step, kind, engine):
    """The review time counts from the real submission. When a retry, a pause or a gap made the submission late, move the planned
    decision (and everything after it) so the Subscriber still takes its planned number of activity days. Old plans have no after_days."""
    row = rt.store.db.execute("SELECT * FROM steps WHERE wo_id=? AND seq>? AND kind=? AND state='pending' ORDER BY seq LIMIT 1",
                              (wo["id"], step["seq"], kind)).fetchone()
    k = row and json.loads(row["payload"]).get("after_days")
    if not k:
        return
    c = {**planner.DEFAULTS, **rt.store.get("behavior", {})}
    z = _tz(rt, wo)
    now = engine.clock()
    due = planner.decision_at(now, k, c, z, rt.rng)
    day = lambda ts: dt.datetime.fromtimestamp(ts, ZoneInfo(z)).date()
    if day(row["due_at"]) < day(due):
        rt.store.db.execute("UPDATE steps SET due_at=? WHERE id=?", (due, row["id"]))
        move_after(rt, wo, row["seq"], due - row["due_at"], lambda ts: engine.snap(ts, wo["location"]))
        rt.store.db.commit()


def _tz(rt, wo):
    r = rt.store.db.execute("SELECT tz FROM locations WHERE store_id=?", (wo["location"],)).fetchone()
    return (r and r["tz"]) or rt.store.get("tz", "America/New_York")


def end_plan(rt, wo):
    """Stop a WO's plan because the WO itself was cancelled outside the agent."""
    rt.store.db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?", (wo["id"],))
    rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],))
    rt.store.db.commit()


def cancel_wo(rt, wo, note="Cancelled by SC Activity Agent cleanup"):
    """Cancel a WO as the Subscriber and stop its plan. SC has no API path to VOID, so use COMPLETED/CANCELED."""
    app, user = rt.user_for(wo["location"], "sub_note")
    app.call(user, "PUT", f"/workorders/{wo['sc_id']}/status", action="cancel", wo=wo["sc_id"], write=True,
             body={"Status": {"Primary": "COMPLETED", "Extended": "CANCELED"}, "Note": note})
    rt.store.db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?", (wo["id"],))
    rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],))
    rt.store.db.commit()
