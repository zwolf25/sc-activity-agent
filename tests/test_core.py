import json
import random
import re

import pytest

from sc_activity_agent import content, planner
from sc_activity_agent.client import RateLimiter, ScApp, ScError
from sc_activity_agent.store import Store

NOW = 1_761_220_800  # Thu 2025-10-23 08:00 America/New_York


def plans(n=400, **cfg):
    return [planner.build_plan(random.Random(i), NOW, cfg) for i in range(n)]


def test_plan_is_ordered_and_ends_in_approved_invoice():
    for p in plans(100):
        assert [s["due_at"] for s in p] == sorted(s["due_at"] for s in p)
        assert [s["kind"] for s in p[-2:]] == ["invoice_decide", "invoice_pay"] and p[-2]["payload"]["approve"] is True


def test_every_check_in_has_later_check_out_same_day_and_precedes_review():
    for p in plans(100):
        ins = [s for s in p if s["kind"] == "check_in"]
        outs = [s for s in p if s["kind"] == "check_out"]
        assert len(ins) == len(outs) >= 1
        for i, o in zip(ins, outs):
            assert o["due_at"] >= i["due_at"]
            assert o["due_at"] - i["due_at"] < 86400
        review = next(s for s in p if s["kind"] == "review")
        assert review["due_at"] > outs[-1]["due_at"]


def test_proposal_rate_and_check_in_after_proposal_approval():
    ps = plans(1000, proposal_rate=10)
    with_prop = [p for p in ps if any(s["kind"] == "proposal_create" for s in p)]
    assert 0.06 < len(with_prop) / 1000 < 0.14
    for p in with_prop:
        approved = [s for s in p if s["kind"] == "proposal_decide" and s["payload"]["approve"]][-1]
        first_in = next(s for s in p if s["kind"] == "check_in")
        assert first_in["due_at"] > approved["due_at"]


def test_first_time_fix_controls_visit_count():
    first = lambda p: [s for s in p if s["kind"] == "check_in" and not s["payload"].get("tech")]
    assert sum(len(first(p)) > 1 for p in plans(1000, first_time_fix=100)) == 0
    assert 400 < sum(len(first(p)) > 1 for p in plans(1000, first_time_fix=50)) < 600


def test_multi_tech_visits_pair_a_second_tech_inside_the_first():
    ps = plans(1000, multi_tech=100)
    assert sum(any(s["payload"].get("tech") for s in p) for p in ps) > 900
    assert not any(s["payload"].get("tech") for p in plans(300, multi_tech=0) for s in p)
    for p in ps:
        by = {}
        for s in p:
            if s["kind"] in ("check_in", "check_out"):
                by[(s["kind"], s["payload"]["visit"], s["payload"].get("tech", 0))] = s["due_at"]
        for (kind, v, t), at in by.items():
            if kind == "check_in" and t:
                assert by[("check_in", v, 0)] < at < by[("check_out", v, 0)] and at < by[("check_out", v, t)]


def test_rejected_invoice_is_resubmitted():
    for p in plans(300, invoice_approval=0):
        kinds = [(s["kind"], s["payload"].get("approve")) for s in p if s["kind"].startswith("invoice")]
        assert kinds == [("invoice_submit", None), ("invoice_decide", False), ("invoice_submit", None),
                         ("invoice_decide", True), ("invoice_pay", None)]


def test_notes_fill_every_slot_for_every_situation():
    ctx = dict(trade="HVAC", issue="Unit not cooling", location="HQ-NYC", sched_day="Monday", eta="9:00 AM",
               eta_end="11:00 AM", area="mechanical room", equipment="rooftop unit", amount="$450.00", nte="$300.00")
    rng = random.Random(1)
    for (role, situation) in content.T:
        for _ in range(20):
            out = content.note(role, situation, ctx, rng)
            assert out and not re.search(r"[{}]", out)


def test_note_reports_missing_slot():
    with pytest.raises(ValueError):
        content.note("provider", "ack", {}, random.Random(1))


def test_rate_limiter_waits_when_window_full():
    t = [0.0]
    slept = []
    rl = RateLimiter(per_min=3, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    for _ in range(3):
        rl.wait()
    assert not slept
    rl.wait()
    assert slept and 59 < slept[0] < 61


def fake(responses):
    calls = []

    def transport(method, url, headers, data):
        calls.append((method, url, data))
        r = responses.pop(0) if responses else (200, "{}")
        return r
    return transport, calls


def test_auth_error_mapping_and_token_cache(tmp_path):
    tok = (200, json.dumps({"access_token": "T", "expires_in": 600}))
    tr, calls = fake([tok, (200, '{"a":1}'), (200, '{"a":2}')])
    app = ScApp("sb2", "id", "sec", transport=tr)
    assert app.call(("u", "p"), "GET", "/x") == {"a": 1}
    assert app.call(("u", "p"), "GET", "/x") == {"a": 2}
    assert sum("oauth/token" in c[1] for c in calls) == 1  # token cached
    with pytest.raises(ScError, match="Client ID or secret"):
        ScApp("sb2", "id", "sec", transport=fake([(302, "")])[0]).token("u", "p")
    with pytest.raises(ScError, match="Username or password"):
        ScApp("sb2", "id", "sec", transport=fake([(400, "")])[0]).token("u", "p")


def test_paused_blocks_writes_not_reads():
    tok = (200, json.dumps({"access_token": "T"}))
    app = ScApp("sb2", "id", "sec", transport=fake([tok, (200, "{}")])[0])
    app.paused = lambda: True
    with pytest.raises(ScError):
        app.call(("u", "p"), "POST", "/workorders", body={})
    assert app.call(("u", "p"), "GET", "/x") == {}


def test_secrets_encrypted_at_rest(tmp_path):
    s = Store(tmp_path)
    token = s.enc("hunter2")
    assert "hunter2" not in token and s.dec(token) == "hunter2"
    s.put("k", {"a": 1})
    assert s.get("k") == {"a": 1}


def test_cli_init_locks_environment(tmp_path, capsys):
    from sc_activity_agent.cli import main
    main(["--data-dir", str(tmp_path), "init", "--env", "sb2"])
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path), "init", "--env", "prod"])
    main(["--data-dir", str(tmp_path), "status"])
    assert "env=sb2" in capsys.readouterr().out


def test_check_out_never_before_check_in_with_rejected_proposal():
    import random
    from sc_activity_agent.planner import build_plan
    for seed in range(300):
        plan = build_plan(random.Random(seed), 1_761_220_800, {"proposal_rate": 100, "proposal_approval": 0})
        by = {}
        for st in plan:
            if st["kind"] in ("check_in", "check_out"):
                by.setdefault(st["payload"]["visit"], {})[st["kind"]] = st["due_at"]
        assert all(v["check_in"] < v["check_out"] for v in by.values()), seed


def test_every_step_falls_in_activity_hours_on_a_weekday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    # created Mon evening, Sat night, Sun noon and Wed morning
    for created in (datetime(2026, 10, 26, 19, 44), datetime(2026, 10, 24, 2, 0), datetime(2026, 10, 25, 12, 0), datetime(2026, 10, 28, 9, 0)):
        now = created.replace(tzinfo=tz).timestamp()
        for seed in range(150):
            plan = planner.build_plan(random.Random(seed), now, {"proposal_rate": 40, "first_time_fix": 50})
            times = [s["due_at"] for s in plan]
            assert times == sorted(times)
            for s in plan:
                d = datetime.fromtimestamp(s["due_at"], tz)
                assert d.weekday() < 5 and 8 <= d.hour + d.minute / 60 <= 17, (seed, s["kind"], d)
            ins = [s for s in plan if s["kind"] == "check_in"]
            outs = [s for s in plan if s["kind"] == "check_out"]
            assert all(o["due_at"] > i["due_at"] and datetime.fromtimestamp(o["due_at"], tz).date() == datetime.fromtimestamp(i["due_at"], tz).date()
                       for i, o in zip(ins, outs))


def test_desktop_app_versions_match_python_version():
    import json
    from pathlib import Path

    from sc_activity_agent import __version__
    root = Path(__file__).parent.parent
    assert json.loads((root / "src-tauri/tauri.conf.json").read_text())["version"] == __version__
    assert json.loads((root / "package.json").read_text())["version"] == __version__
    assert f'version = "{__version__}"' in (root / "src-tauri/Cargo.toml").read_text()


def test_update_banner_clears_once_the_running_version_catches_up(tmp_path):
    from sc_activity_agent import __version__, update
    from sc_activity_agent.store import Store
    s = Store(tmp_path)
    s.put("update_check", {"at": 1, "found": {"tag": "v99.0.0", "notes": ""}})
    assert update.pending(s)["tag"] == "v99.0.0"
    s.put("update_check", {"at": 1, "found": {"tag": "v" + __version__, "notes": ""}})
    assert update.pending(s) is None


def test_each_thread_gets_its_own_db_connection(tmp_path):
    import threading
    from sc_activity_agent.store import Store
    s = Store(tmp_path)
    errs = []

    def hammer(n):
        try:
            for i in range(200):
                s.put(f"k{n}", i)
                s.get(f"k{n}")
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and s.get("k3") == 199


def test_emergency_plan_visits_within_hours_with_an_availability_exchange():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 10, 28, 9, 0, tzinfo=tz).timestamp()   # Wednesday morning
    for seed in range(200):
        p = planner.build_plan(random.Random(seed), now, {"proposal_rate": 100, "late_checkin": 100}, emergency=True)
        first_in = next(s for s in p if s["kind"] == "check_in")["due_at"]
        assert first_in - now <= 8 * 3600
        assert not any(s["kind"] == "proposal_create" for s in p)
        early = [s["kind"] for s in p if s["due_at"] < first_in]
        assert early[0] == "accept" and {"sub_note", "prov_note"} <= set(early)   # random notes may interleave
        d = datetime.fromtimestamp(first_in, tz)
        assert 8 <= d.hour + d.minute / 60 <= 17 and d.weekday() < 5
