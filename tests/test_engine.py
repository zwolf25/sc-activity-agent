import json
import random

from sc_activity_agent import planner
from sc_activity_agent.client import ScError
from sc_activity_agent.engine import Engine, add_plan
from sc_activity_agent.store import Store

NOW = 1_761_220_800


def setup(tmp_path, handlers, clock):
    s = Store(tmp_path)
    plan = planner.build_plan(random.Random(5), NOW, {})
    add_plan(s, "HQ-NYC", "HVAC", 1001, plan, {}, NOW)
    return s, Engine(s, handlers, clock=clock, per_tick=50), plan


def ok(*a):
    ok.calls.append(a[2]["kind"])


ok.calls = []


def test_steps_run_in_order_and_plan_completes(tmp_path):
    ok.calls = []
    t = [NOW]
    kinds = {k: ok for k in ["accept", "prov_note", "sub_note", "proposal_create", "proposal_decide", "check_in",
                             "check_out", "review", "invoice_submit", "invoice_decide", "invoice_pay"]}
    s, e, plan = setup(tmp_path, kinds, lambda: t[0])
    t[0] = plan[-1]["due_at"] + 10
    for _ in range(len(plan) + 5):
        e.tick()
    assert ok.calls == [p["kind"] for p in plan]
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state='done'").fetchone()[0] == len(plan)


def test_retry_then_fail_then_operator_retry(tmp_path):
    def bad(*a):
        raise ScError(500, "boom", "/x")
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, {"accept": bad}, lambda: t[0])
    for _ in range(8):  # ticks under the gap threshold, so backoff is real time, not a sleep gap
        e.tick()
        t[0] += 500
    row = s.db.execute("SELECT * FROM steps WHERE kind='accept'").fetchone()
    assert row["state"] == "failed" and "boom" in row["error"]
    e.retry(row["id"])
    assert s.db.execute("SELECT state,attempts FROM steps WHERE kind='accept'").fetchone()["state"] == "pending"


def test_later_steps_wait_for_failed_earlier_step(tmp_path):
    ok.calls = []

    def bad(*a):
        raise ScError(500, "boom", "/x")
    handlers = {"accept": bad, "prov_note": ok, "sub_note": ok}
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, handlers, lambda: t[0])
    for _ in range(12):
        e.tick()
        t[0] += 500
    assert ok.calls == []


def test_pause_blocks_and_resume_policies(tmp_path):
    ok.calls = []
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, {k: ok for k in ["accept", "prov_note", "sub_note"]}, lambda: t[0])
    e.pause()
    assert e.tick() == []
    first = s.db.execute("SELECT due_at FROM steps WHERE seq=0").fetchone()[0]
    t[0] += 1000
    e.resume("push")
    assert s.db.execute("SELECT due_at FROM steps WHERE seq=0").fetchone()[0] == first + 1000
    e.pause()
    t[0] += 500
    e.resume("catch_up")
    d = s.db.execute("SELECT due_at FROM steps WHERE seq=0").fetchone()[0]
    assert t[0] <= d <= t[0] + 3600


def test_cancelled_wo_is_not_run(tmp_path):
    ok.calls = []
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, {"accept": ok}, lambda: t[0])
    e.cancel_plan(1)
    assert e.tick() == [] and ok.calls == []


def test_non_api_error_fails_the_step_instead_of_looping(tmp_path):
    def bug(*a):
        raise KeyError("ProviderId")
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, {"accept": bug}, lambda: t[0])
    for _ in range(8):
        e.tick()
        t[0] += 500
    row = s.db.execute("SELECT * FROM steps WHERE kind='accept'").fetchone()
    assert row["state"] == "failed" and "ProviderId" in row["error"]


def _limit_handler(bad_user):
    def run(engine, wo, st):
        user = json.loads(engine.store.db.execute("SELECT payload FROM steps WHERE id=?", (st["id"],)).fetchone()[0]).get("user", 1)
        if user == bad_user:
            raise ScError(403, '{"ErrorCode":101,"ErrorMessage":"No permission for this user"}', "/x")
    return run


def test_user_bound_failure_switches_user_after_three_fails_and_alerts_only_when_all_failed(tmp_path):
    t = [NOW]
    s, e, plan = setup(tmp_path, {p["kind"]: _limit_handler(1) for p in planner.build_plan(random.Random(5), NOW, {})}, lambda: t[0])
    picks = iter([2, 3])   # the next user rotate_user would hand the step
    def rotate(wo, st):
        p = json.loads(s.db.execute("SELECT payload FROM steps WHERE id=?", (st["id"],)).fetchone()[0])
        nxt = next(picks, None)
        if nxt is None:
            return False
        s.db.execute("UPDATE steps SET payload=? WHERE id=?", (json.dumps({**p, "user": nxt, "tried": p.get("tried", []) + [p.get("user", 1)]}), st["id"]))
        return True
    e.rotate = rotate
    s.db.execute("UPDATE steps SET payload=json_set(payload,'$.user',1) WHERE seq=0")
    s.db.commit()
    first = s.db.execute("SELECT id FROM steps WHERE seq=0").fetchone()[0]
    t[0] = plan[0]["due_at"] + 10
    outs = []
    for _ in range(12):   # small steps: a jump over 600 s counts as a sleep gap and shifts the plan
        outs += e.tick()
        t[0] += 400
    assert [o for o in outs if o[0] == first] == [(first, "retry"), (first, "retry"), (first, "switch"), (first, "done")]
    assert (first, "done") in outs
    row = s.db.execute("SELECT state, attempts FROM steps WHERE id=?", (first,)).fetchone()
    assert (row["state"], row["attempts"]) == ("done", 0)


def test_non_user_bound_failure_never_switches(tmp_path):
    from sc_activity_agent.engine import user_bound
    assert user_bound(ScError(403, '{"ErrorCode":100}')) and user_bound(ScError(400, '{"ErrorCode":921}')) and user_bound(ScError(500, '{"ErrorCode":501,"ErrorMessage":"Unspecified error"}'))
    assert not user_bound(ScError(500, '{"ErrorCode":501,"ErrorMessage":"Invalid WorkOrder status"}')) and not user_bound(ScError(500, "boom")) and not user_bound(ValueError("x"))


def test_a_wo_waiting_for_refrigerant_usage_fails_at_once_without_retries(tmp_path):
    def held(*a):
        raise ScError(400, '{"ErrorCode":904,"ErrorMessage":"Invalid State (COMPLETED/PENDING REFRIGERANT USE)"}', "/invoices")
    t = [NOW + 10 ** 7]
    s, e, plan = setup(tmp_path, {"accept": held}, lambda: t[0])
    e.tick()
    row = s.db.execute("SELECT state, attempts FROM steps WHERE kind='accept'").fetchone()
    assert row["state"] == "failed" and row["attempts"] == 3   # a retry cannot clear it, only a person in ServiceChannel


def test_over_limit_403_is_recognised_so_the_step_switches_user_on_the_first_failure():
    from sc_activity_agent.engine import over_limit, user_bound
    e = ScError(403, '{"ErrorCodes":[100],"ErrorCode":100,"ErrorMessage":"Invoice Amount exceeds user Limit"}')
    assert over_limit(e) and user_bound(e)
    assert not over_limit(ScError(403, '{"ErrorCode":100,"ErrorMessage":"No permission"}')) and not over_limit(ScError(500, "boom"))


def test_an_overdue_step_behind_a_later_one_is_not_starved_by_the_steps_queued_after_it(tmp_path):
    """SB2 2026-11-08: step 113 was due after its successors (a gap shift), so the 10 slots per tick filled with its blocked successors."""
    s = Store(tmp_path)
    steps = [{"kind": "sub_note", "due_at": NOW + 100, "payload": {}}] + [{"kind": "check_in", "due_at": NOW + i, "payload": {}} for i in range(1, 8)]
    for w in range(3):
        add_plan(s, "HQ-NYC", "HVAC", 2000 + w, steps, {}, NOW)
    ran = []
    e = Engine(s, {"sub_note": lambda *a: ran.append(a[2]["wo_id"]), "check_in": lambda *a: None}, clock=lambda: NOW + 500, per_tick=3)
    e.tick()
    assert len(ran) == 3   # the three first steps run, not three of their blocked successors


def test_network_failures_open_a_breaker_use_no_attempts_and_a_probe_closes_it(tmp_path):
    import ssl
    from sc_activity_agent.engine import NET_PROBE
    up, calls, t = [False], [], [NOW]

    def h(e, wo, st):
        calls.append(st["id"])
        if not up[0]:
            raise ssl.SSLEOFError("EOF occurred in violation of protocol")

    kinds = ["accept", "prov_note", "sub_note", "proposal_create", "proposal_decide", "check_in", "check_out", "review", "invoice_submit", "invoice_decide", "invoice_pay"]
    s, e, plan = setup(tmp_path, {k: h for k in kinds}, lambda: t[0])
    for i in range(3):   # a WO runs one step at a time, so add two more WOs to get three failures in one tick
        add_plan(s, "HQ-NYC", "HVAC", 2000 + i, plan[:1], {}, NOW)
    t[0] = plan[-1]["due_at"] + 10
    e.tick()
    assert e.net_down and s.get("net_down") == t[0]
    assert s.db.execute("SELECT MAX(attempts) FROM steps").fetchone()[0] == 0   # network errors never use an attempt
    n = len(calls)
    t[0] += 30
    e.tick()
    assert len(calls) == n   # open: nothing runs inside the minute
    t[0] += NET_PROBE
    e.tick()
    assert len(calls) == n + 1   # exactly one probe, still down
    up[0] = True
    t[0] += NET_PROBE
    e.tick()
    assert e.net_down is None and s.get("net_down") is None
    t[0] += 1
    e.tick()
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state='failed'").fetchone()[0] == 0


def test_a_refusal_from_servicechannel_is_not_a_network_fault(tmp_path):
    def bad(*a):
        raise ScError(403, "no", "/x")
    s, e, plan = setup(tmp_path, {"accept": bad}, lambda: plan_end[0])
    plan_end = [plan[-1]["due_at"] + 10]
    e.tick()
    assert e.net_down is None and s.db.execute("SELECT attempts FROM steps WHERE seq=0").fetchone()[0] == 1
