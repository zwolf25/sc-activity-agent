from sc_activity_agent.status import stage


def test_stage_follows_last_done_step():
    assert stage([]) == "Scheduled"
    assert stage([("accept", {}), ("check_in", {})]) == "On site"
    assert stage([("check_in", {}), ("check_out", {"final": False})]) == "Awaiting return"
    assert stage([("check_out", {"final": True})]) == "Awaiting review"
    assert stage([("invoice_submit", {}), ("invoice_decide", {"approve": False})]) == "Invoice rejected"
    assert stage([("invoice_decide", {"approve": True})]) == "Closed"
    assert stage([("proposal_create", {}), ("proposal_decide", {"approve": True})]) == "Scheduled"
