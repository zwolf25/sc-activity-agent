import json
import random

import pytest

from sc_activity_agent import planner
from sc_activity_agent.engine import Engine, add_plan
from sc_activity_agent.handlers import Runtime, make_handlers
from sc_activity_agent.store import Store

NOW = 1_761_220_800
CTX = dict(trade="HVAC", issue="Coil", location="HQ-NYC", sched_day="Monday", eta="9:00 AM", eta_end="11:00 AM",
           area="roof", equipment="RTU", amount="$40.00", nte=50)


class FakeApp:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls
        self.pstatus, self.istatus = "Pending", "OPEN"
        self.invoice_numbers = []

    def call(self, user, method, path, params=None, body=None, **kw):
        self.calls.append((self.name, user[0], method, path))
        if path == "/odata/proposals":
            return {"value": [{"Status": {"Primary": self.pstatus}}]}
        if path.startswith("/invoices/") and method == "GET":
            return {"Status": self.istatus}
        if path == "/invoices":
            self.invoice_numbers.append(body["InvoiceNumber"])
            return {"Id": 777}
        if path == "/proposals/CreateProposal":
            return 26954049
        if method == "GET" and path.startswith("/workorders/"):
            return {"Provider": {"Id": 2000078685}, "TradeId": 120881}
        return {}


def setup(tmp_path):
    s = Store(tmp_path)
    s.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c','x',NULL)")
    s.db.execute("INSERT INTO connections VALUES(2,'provider','P','c','x',2000078685)")
    sub_do = ["subscriber_note", "review", "invoice_decide", "proposal_decide", "create_wo"]
    prov_do = ["accept", "provider_note", "check_in", "check_out", "invoice_submit", "proposal_create"]
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(1,1,'sub_user',?,?)", (s.enc("pw"), json.dumps(sub_do)))
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(2,2,'prov_user',?,?)", (s.enc("pw"), json.dumps(prov_do)))
    s.db.execute("INSERT INTO locations(store_id,lat,lon) VALUES('HQ-NYC',40.7,-73.9)")
    s.db.commit()
    return s


def test_full_plan_uses_subscriber_and_provider_users_correctly(tmp_path):
    s = setup(tmp_path)
    calls = []
    rt = Runtime(s, {1: FakeApp("sub", calls), 2: FakeApp("prov", calls)}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 0})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
    for _ in range(len(plan) + 3):
        e.tick()
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state!='done'").fetchone()[0] == 0
    sub_paths = {c[3].split("/")[-1] if "workorders" in c[3] else c[3] for c in calls if c[0] == "sub"}
    assert all(c[1] == "sub_user" for c in calls if c[0] == "sub") and all(c[1] == "prov_user" for c in calls if c[0] == "prov")
    assert {"accept", "universalCheckIn", "universalCheckOut"} <= {c[3].split("/")[-1] for c in calls if c[0] == "prov"}
    assert any(c[3].endswith("/approve") and c[0] == "sub" for c in calls)
    assert json.loads(s.db.execute("SELECT ctx FROM work_orders").fetchone()[0])["invoice_id"] == 777


def test_missing_role_mapping_fails_step_not_crash(tmp_path):
    s = setup(tmp_path)
    s.db.execute("UPDATE users SET can_do='[]' WHERE id=2")
    s.db.commit()
    rt = Runtime(s, {1: FakeApp("sub", []), 2: FakeApp("prov", [])}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: NOW + 10 ** 7)
    assert e.tick() == [(1, "retry")]
    assert "no user is set to accept" in s.db.execute("SELECT error FROM steps WHERE id=1").fetchone()[0]


def test_cancel_wo_sets_completed_canceled_and_stops_plan(tmp_path):
    s = setup(tmp_path)
    calls = []
    rt = Runtime(s, {1: FakeApp("sub", calls), 2: FakeApp("prov", calls)}, random.Random(1))
    add_plan(s, "HQ-NYC", "HVAC", 5001, planner.build_plan(random.Random(4), NOW, {}), CTX, NOW)
    from sc_activity_agent.handlers import cancel_wo
    cancel_wo(rt, s.db.execute("SELECT * FROM work_orders").fetchone())
    assert calls == [("sub", "sub_user", "PUT", "/workorders/5001/status")]
    assert s.db.execute("SELECT state FROM work_orders").fetchone()[0] == "cancelled"
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state='pending'").fetchone()[0] == 0


def test_check_in_permission_error_names_the_cause():
    import pytest

    from sc_activity_agent.client import ScError
    from sc_activity_agent.handlers import make_handlers

    class Boom:
        def call(self, *a, **k):
            raise ScError(403, '{"ErrorCode":804}', "/x")

    class Rt:
        def user_for(self, *a):
            return Boom(), ("u", "p")

        def location(self, _):
            return {"lat": 1, "lon": 2}
    h = make_handlers(Rt())
    wo = {"sc_id": 5, "location": "HQ"}
    with pytest.raises(ScError, match="permission for this Subscriber and Provider"):
        h["check_in"](None, wo, {"kind": "check_in", "due_at": 1_761_566_400})


def test_proposal_is_created_by_provider_and_linked_then_approved_by_subscriber(tmp_path):
    s = setup(tmp_path)
    s.db.commit()
    calls = []
    rt = Runtime(s, {1: FakeApp("sub", calls), 2: FakeApp("prov", calls)}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 100, "proposal_approval": 100})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
    for _ in range(len(plan) + 3):
        e.tick()
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state!='done'").fetchone()[0] == 0
    assert ("prov", "prov_user", "POST", "/proposals/CreateProposal") in calls
    assert ("sub", "sub_user", "PUT", "/proposals/26954049/assignWO") in calls
    assert ("sub", "sub_user", "PUT", "/proposals/26954049/approve") in calls


def _proposal_plan(tmp_path, pstatus, approval):
    s = setup(tmp_path)
    s.db.commit()
    calls = []
    sub = FakeApp("sub", calls)
    sub.pstatus = pstatus
    rt = Runtime(s, {1: sub, 2: FakeApp("prov", calls)}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 100, "proposal_approval": approval})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    t = [plan[-1]["due_at"] + 10 ** 6]
    e = Engine(s, make_handlers(rt), clock=lambda: t[0], per_tick=50)
    for _ in range(len(plan) + 40):
        e.tick()
        t[0] += 10 ** 5   # clear any retry backoff
    return s, calls


def test_user_already_approved_proposal_plan_continues_without_new_calls(tmp_path):
    s, calls = _proposal_plan(tmp_path, "Approved", 100)
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state NOT IN ('done')").fetchone()[0] == 0
    assert not any(c[3].endswith("/assignWO") or c[3].endswith("/approve") and "proposals" in c[3] for c in calls)


def test_user_rejected_planned_approval_adds_revised_proposal_and_never_overturns(tmp_path):
    s, calls = _proposal_plan(tmp_path, "Rejected", 100)
    kinds = [r["kind"] for r in s.db.execute("SELECT kind FROM steps ORDER BY seq")]
    assert kinds.count("proposal_create") > 1   # revised proposals were added
    assert not any(c[3].endswith("/approve") and "proposals" in c[3] for c in calls)
    assert s.db.execute("SELECT 1 FROM steps WHERE error LIKE '%needs attention%'").fetchone()   # stops after 3 rejections


def test_invoice_already_decided_by_user_is_not_overturned(tmp_path):
    s = setup(tmp_path)
    calls = []
    sub = FakeApp("sub", calls)
    sub.istatus = "REJECTED"
    rt = Runtime(s, {1: sub, 2: FakeApp("prov", calls)}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 0})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
    for _ in range(len(plan) + 3):
        e.tick()
    assert not any(c[3].endswith("/approve") and "invoices" in c[3] for c in calls)
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state!='done'").fetchone()[0] == 0


class RefusingApp(FakeApp):
    """Refuses every write with 400 and reports the WO as the user left it."""
    def __init__(self, name, calls, status):
        super().__init__(name, calls)
        self.status = status

    def call(self, user, method, path, params=None, body=None, **kw):
        if method == "GET" and path.startswith("/workorders/"):
            return {"Status": self.status}
        if method != "GET":
            from sc_activity_agent.client import ScError
            raise ScError(400, "refused", path)
        return super().call(user, method, path, params, body, **kw)


def _run_refused(tmp_path, status):
    s = setup(tmp_path)
    calls = []
    rt = Runtime(s, {1: RefusingApp("sub", calls, status), 2: RefusingApp("prov", calls, status)}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 0})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
    for _ in range(len(plan) + 3):
        e.tick()
    return s


def test_user_cancelled_wo_ends_the_plan_quietly(tmp_path):
    s = _run_refused(tmp_path, {"Primary": "COMPLETED", "Extended": "CANCELED"})
    assert s.db.execute("SELECT state FROM work_orders").fetchone()[0] == "cancelled"
    assert s.db.execute("SELECT COUNT(*) FROM steps WHERE state='failed'").fetchone()[0] == 0


def test_user_completed_wo_skips_field_steps(tmp_path):
    s = _run_refused(tmp_path, {"Primary": "COMPLETED", "Extended": "CONFIRMED"})
    done = [r[0] for r in s.db.execute("SELECT kind FROM steps WHERE state='done'")]
    assert "accept" in done and "check_in" in done and "review" in done


def test_resubmitted_invoice_gets_a_new_number(tmp_path):
    s = setup(tmp_path)
    prov = FakeApp("prov", [])
    rt = Runtime(s, {1: FakeApp("sub", []), 2: prov}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 0, "invoice_approval": 0})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
    for _ in range(len(plan) + 3):
        e.tick()
    assert prov.invoice_numbers == ["INV-5001-1", "INV-5001-2"]


def test_approved_invoice_is_paid_once_and_paid_or_rejected_is_left_alone(tmp_path):
    for status, expect in (("APPROVED", 1), ("PAID", 0), ("REJECTED", 0)):
        s = setup(tmp_path / status)
        calls = []
        sub = FakeApp("sub", calls)
        sub.istatus = status
        rt = Runtime(s, {1: sub, 2: FakeApp("prov", calls)}, random.Random(1))
        plan = planner.build_plan(random.Random(4), NOW, {"proposal_rate": 0})
        add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
        s.db.execute("UPDATE work_orders SET ctx=json_set(ctx,'$.invoice_id',777)")
        s.db.commit()
        e = Engine(s, make_handlers(rt), clock=lambda: plan[-1]["due_at"] + 10, per_tick=50)
        for _ in range(len(plan) + 3):
            e.tick()
        assert sum(c[3] == "/invoices/777/Payment" for c in calls) == expect


def _wo(s, **ctx):
    s.db.execute("INSERT INTO work_orders(sc_id,location,state,created_at,ctx) VALUES(9,'HQ-NYC','active',0,?)", (json.dumps({**CTX, **ctx}),))
    s.db.commit()
    return s.db.execute("SELECT * FROM work_orders WHERE sc_id=9").fetchone()


def _tech(s, uid, conn, can=("check_in", "check_out")):
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(?,?,?,?,?)", (uid, conn, f"t{uid}", s.enc("pw"), json.dumps(list(can))))
    s.db.commit()


def step(kind, **p):
    return {"kind": kind, "payload": json.dumps(p)}


def test_provider_steps_only_use_users_of_the_wos_provider(tmp_path):
    from sc_activity_agent.client import ScError
    s = setup(tmp_path)
    s.db.execute("INSERT INTO connections VALUES(3,'provider','P2','c','x',555)")
    _tech(s, 3, 3)
    rt = Runtime(s, {1: 1, 2: 2, 3: 3}, random.Random(1))
    wo = _wo(s, provider_id=555)
    assert {rt.user_for("HQ-NYC", "check_in", wo, step("check_in", visit=1))[1][0] for _ in range(1)} == {"t3"}
    with pytest.raises(ScError, match="provider 999"):
        rt.user_for("HQ-NYC", "accept", _wo_with(s, 999), step("accept"))


def _wo_with(s, pid):
    s.db.execute("UPDATE work_orders SET ctx=? WHERE sc_id=9", (json.dumps({**CTX, "provider_id": pid}),))
    s.db.commit()
    return s.db.execute("SELECT * FROM work_orders WHERE sc_id=9").fetchone()


def test_check_out_reuses_the_check_in_tech_and_second_tech_differs(tmp_path):
    s = setup(tmp_path)
    for uid in (3, 4):
        _tech(s, uid, 2)
    rt = Runtime(s, {1: 1, 2: 2}, random.Random(3))
    for _ in range(20):   # pick is random, so repeat until the same-tech rule is the only thing that explains the result
        s.db.execute("DELETE FROM work_orders")
        wo = _wo(s, provider_id=2000078685)
        a = rt.user_for("HQ-NYC", "check_in", wo, step("check_in", visit=1))[1][0]
        wo = s.db.execute("SELECT * FROM work_orders").fetchone()
        b = rt.user_for("HQ-NYC", "check_in", wo, step("check_in", visit=1, tech=1))[1][0]
        wo = s.db.execute("SELECT * FROM work_orders").fetchone()
        assert a != b
        assert rt.user_for("HQ-NYC", "check_out", wo, step("check_out", visit=1))[1][0] == a
        assert rt.user_for("HQ-NYC", "check_out", wo, step("check_out", visit=1, tech=1))[1][0] == b


def test_second_tech_is_skipped_when_the_provider_has_one_tech(tmp_path):
    from sc_activity_agent.handlers import Skip
    s = setup(tmp_path)
    s.db.execute("UPDATE users SET can_do='[\"accept\",\"check_in\",\"check_out\"]' WHERE id=2")
    rt = Runtime(s, {1: 1, 2: 2}, random.Random(1))
    wo = _wo(s, provider_id=2000078685)
    rt.user_for("HQ-NYC", "check_in", wo, step("check_in", visit=1))
    wo = s.db.execute("SELECT * FROM work_orders").fetchone()
    with pytest.raises(Skip):
        rt.user_for("HQ-NYC", "check_in", wo, step("check_in", visit=1, tech=1))
    with pytest.raises(Skip):
        rt.user_for("HQ-NYC", "check_out", wo, step("check_out", visit=1, tech=1))


def test_first_tech_out_of_a_crew_visit_does_not_complete_the_wo(tmp_path):
    s = setup(tmp_path)
    calls = []
    rt = Runtime(s, {1: FakeApp("sub", calls), 2: FakeApp("prov", calls)}, random.Random(1))
    h = make_handlers(rt)
    out = lambda wo: h["check_out"](None, wo, {"kind": "check_out", "due_at": 1_761_566_400,
                                               "payload": json.dumps({"visit": 1, "final": True, "situation": "complete", "partial": True})})
    bodies = []
    rt.apps[2].call = lambda user, method, path, params=None, body=None, **kw: bodies.append(body) or {}
    out(_wo(s, provider_id=2000078685, techs={"1.0": 2}))
    assert bodies[-1]["PrimaryStatus"] == "Completed"   # no second tech checked in: nobody else to wait for
    s.db.execute("DELETE FROM work_orders")
    out(_wo(s, provider_id=2000078685, techs={"1.0": 2, "1.1": 2}))
    assert bodies[-1]["PrimaryStatus"] == "PartsOnOrder"


def test_watch_ends_the_plan_of_a_wo_cancelled_by_a_user(tmp_path):
    from sc_activity_agent.handlers import watch
    s = setup(tmp_path)
    plan = planner.build_plan(random.Random(4), NOW, {})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, {**CTX}, NOW)
    add_plan(s, "HQ-NYC", "HVAC", 5002, plan, {**CTX}, NOW)

    class App(FakeApp):
        def call(self, user, method, path, params=None, body=None, **kw):
            if method == "GET" and path.startswith("/workorders/"):
                return {"Status": {"Primary": "COMPLETED", "Extended": "CANCELED" if path.endswith("5002") else "OPEN"}}
            return super().call(user, method, path, params, body, **kw)
    rt = Runtime(s, {1: App("sub", []), 2: App("prov", [])}, random.Random(1))
    assert watch(s, rt, lambda: 1000) == [(5002, "cancelled by a user: plan ended")]
    assert s.db.execute("SELECT state FROM work_orders WHERE sc_id=5002").fetchone()[0] == "cancelled"
    assert s.db.execute("SELECT state FROM work_orders WHERE sc_id=5001").fetchone()[0] == "active"
    assert watch(s, rt, lambda: 1100) == []   # throttled: not again within 15 minutes
