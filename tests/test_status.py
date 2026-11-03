from sc_activity_agent.status import stage


def test_stage_follows_last_done_step():
    assert stage([]) == "Scheduled"
    assert stage([("accept", {}), ("check_in", {})]) == "On site"
    assert stage([("check_in", {}), ("check_out", {"final": False})]) == "Awaiting return"
    assert stage([("check_out", {"final": True})]) == "Awaiting review"
    assert stage([("invoice_submit", {}), ("invoice_decide", {"approve": False})]) == "Invoice rejected"
    assert stage([("invoice_decide", {"approve": True})]) == "Payment due"
    assert stage([("invoice_decide", {"approve": True}), ("invoice_pay", {})]) == "Closed"
    assert stage([("proposal_create", {}), ("proposal_decide", {"approve": True})]) == "Scheduled"


def test_in_stage_lists_wos_with_their_next_pending_step(tmp_path):
    import json
    from sc_activity_agent import status
    from sc_activity_agent.store import Store
    s = Store(tmp_path)
    s.db.execute("INSERT INTO work_orders(id,sc_id,location,trade,state,created_at) VALUES(1,100,'HQ','HVAC','active',0)")
    s.db.execute("INSERT INTO work_orders(id,sc_id,location,trade,state,created_at) VALUES(2,200,'HQ','DOORS','active',0)")
    for wo, seq, kind, due, state in ((1, 1, "check_in", 10, "done"), (1, 2, "check_out", 20, "done"), (1, 3, "review", 30, "pending"),
                                      (2, 1, "check_in", 10, "pending")):
        s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state,payload) VALUES(?,?,?,?,?,?)",
                     (wo, seq, kind, due, state, json.dumps({"final": True} if kind == "check_out" else {})))
    s.db.commit()
    rows = status.in_stage(s.db, "Awaiting review")
    assert [(r["sc_id"], r["next_kind"], r["next_due"]) for r in rows] == [(100, "review", 30)]
    assert [r["sc_id"] for r in status.in_stage(s.db, "Scheduled")] == [200]
