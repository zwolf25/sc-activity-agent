import json
import random

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

    def call(self, user, method, path, params=None, body=None, **kw):
        self.calls.append((self.name, user[0], method, path))
        if path == "/odata/proposals":
            return {"value": [{"Status": {"Primary": self.pstatus}}]}
        if path.startswith("/invoices/") and method == "GET":
            return {"Status": self.istatus}
        if path == "/invoices":
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
    s.db.execute("INSERT INTO users VALUES(1,1,'sub_user',?, '',NULL)", (s.enc("pw"),))
    s.db.execute("INSERT INTO users VALUES(2,2,'prov_user',?, '',NULL)", (s.enc("pw"),))
    for a in ("subscriber_note", "review", "invoice_decide"):
        s.db.execute("INSERT INTO roles VALUES('*',?,'[1]','single')", (a,))
    for a in ("accept", "provider_note", "check_in", "check_out", "invoice_submit"):
        s.db.execute("INSERT INTO roles VALUES('*',?,'[2]','single')", (a,))
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
    s.db.execute("DELETE FROM roles WHERE action='accept'")
    s.db.commit()
    rt = Runtime(s, {1: FakeApp("sub", []), 2: FakeApp("prov", [])}, random.Random(1))
    plan = planner.build_plan(random.Random(4), NOW, {})
    add_plan(s, "HQ-NYC", "HVAC", 5001, plan, CTX, NOW)
    e = Engine(s, make_handlers(rt), clock=lambda: NOW + 10 ** 7)
    assert e.tick() == [(1, "retry")]
    assert "no user mapped to accept" in s.db.execute("SELECT error FROM steps WHERE id=1").fetchone()[0]


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
    s.db.execute("INSERT INTO roles VALUES('*','proposal_create','[2]','single')")
    s.db.execute("INSERT INTO roles VALUES('*','proposal_decide','[1]','single')")
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
    s.db.execute("INSERT INTO roles VALUES('*','proposal_create','[2]','single')")
    s.db.execute("INSERT INTO roles VALUES('*','proposal_decide','[1]','single')")
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
