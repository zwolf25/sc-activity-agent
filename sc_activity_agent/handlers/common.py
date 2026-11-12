"""Shared by the step executors."""
import datetime as dt
import json

ACTION = {"accept": "accept", "prov_note": "provider_note", "sub_note": "subscriber_note", "review": "review",
          "proposal_create": "proposal_create", "proposal_decide": "proposal_decide", "check_in": "check_in",
          "check_out": "check_out", "invoice_submit": "invoice_submit", "invoice_decide": "invoice_decide",
          "invoice_pay": "invoice_decide",   # the same Subscriber user decides and pays; no new role row for existing instances
          "decline": "accept", "reschedule": "accept", "reassign": "subscriber_note", "cancel": "subscriber_note",   # a provider who can accept can also decline and reschedule
          "create": "create_wo"}


from ..client import Skip  # noqa: F401  (Runtime.user_for raises it; the engine ends the step as done)



def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_steps(store, wo_id, after_seq, steps):
    """Add steps right after `after_seq` of a WO, shifting later steps down. steps: [(kind, due_at, payload)]."""
    store.db.execute("UPDATE steps SET seq=seq+? WHERE wo_id=? AND seq>?", (len(steps), wo_id, after_seq))
    for i, (kind, due, payload) in enumerate(steps, 1):
        store.db.execute("INSERT INTO steps(wo_id, seq, kind, due_at, payload) VALUES(?,?,?,?,?)",
                         (wo_id, after_seq + i, kind, due, json.dumps(payload)))
    store.db.commit()


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
