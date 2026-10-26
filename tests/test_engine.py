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
    return s, Engine(s, handlers, clock=clock), plan


def ok(*a):
    ok.calls.append(a[2]["kind"])


ok.calls = []


def test_steps_run_in_order_and_plan_completes(tmp_path):
    ok.calls = []
    t = [NOW]
    kinds = {k: ok for k in ["accept", "prov_note", "sub_note", "proposal_create", "proposal_decide", "check_in",
                             "check_out", "review", "invoice_submit", "invoice_decide"]}
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
    row = s.db.execute("SELECT * FROM steps WHERE seq=0").fetchone()
    assert row["state"] == "failed" and "boom" in row["error"]
    e.retry(row["id"])
    assert s.db.execute("SELECT state,attempts FROM steps WHERE seq=0").fetchone()["state"] == "pending"


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
    row = s.db.execute("SELECT * FROM steps WHERE seq=0").fetchone()
    assert row["state"] == "failed" and "ProviderId" in row["error"]
