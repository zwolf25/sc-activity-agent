import pytest

from sc_activity_agent import smoke
from sc_activity_agent.store import Store

NOW = 1_800_000_000.0
OK = dict(ok=True, wo=7, steps=[(1, "check_in", "done", None)], calls=[], error="")


class Rec:
    def __init__(self):
        self.sent = []


@pytest.fixture
def sb2(tmp_path, monkeypatch):
    s = Store(tmp_path)
    s.put("env", "sb2")
    s.put("smoke", {"on": True})
    sent = []
    monkeypatch.setattr(smoke.Alerts, "send", lambda self, key, text, buttons=None, event=None: sent.append((event, text)))
    return s, sent


def test_runs_when_due_stores_the_result_and_alerts(sb2, monkeypatch):
    s, sent = sb2
    monkeypatch.setattr(smoke, "run", lambda *a, **k: OK)
    assert smoke.tick(s, None, None, clock=lambda: NOW)[0][0] == "smoke"
    assert s.get("smoke_last") == {"at": NOW, "ok": True, "text": "SB2 smoke run passed: WO 7, 1 steps."}
    assert sent == [("smoke", "SB2 smoke run passed: WO 7, 1 steps.")]
    assert smoke.tick(s, None, None, clock=lambda: NOW + 6 * 86400) == []   # not due for 7 days
    assert smoke.tick(s, None, None, clock=lambda: NOW + 7 * 86400)


def test_failure_names_the_first_bad_step(sb2, monkeypatch):
    s, sent = sb2
    bad = dict(ok=False, wo=9, steps=[(1, "check_in", "done", None), (2, "invoice", "failed", "error 1104")], calls=[], error="")
    monkeypatch.setattr(smoke, "run", lambda *a, **k: bad)
    smoke.tick(s, None, None, clock=lambda: NOW)
    assert sent[0][1] == "SB2 smoke run FAILED on WO 9: invoice failed: error 1104" and s.get("smoke_last")["ok"] is False


def test_an_exception_is_reported_not_raised(sb2, monkeypatch):
    s, sent = sb2
    monkeypatch.setattr(smoke, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    smoke.tick(s, None, None, clock=lambda: NOW)
    assert "RuntimeError: boom" in sent[0][1]


def test_never_runs_on_prod_when_off_or_paused(sb2, monkeypatch):
    s, sent = sb2
    monkeypatch.setattr(smoke, "run", lambda *a, **k: OK)
    s.put("env", "prod")
    assert smoke.tick(s, None, None, clock=lambda: NOW) == []
    s.put("env", "sb2")
    s.put("paused_at", NOW)
    assert smoke.tick(s, None, None, clock=lambda: NOW) == []
    s.put("paused_at", None)
    s.put("smoke", {"on": False})
    assert smoke.tick(s, None, None, clock=lambda: NOW) == [] and not sent


def test_settings_card_and_run_now_only_on_sb2(sb2):
    from fastapi.testclient import TestClient
    from sc_activity_agent.web.app import create_app
    s, _ = sb2
    c = TestClient(create_app(s))
    assert "<h3>SB2 smoke run</h3>" in c.get("/settings").text
    c.post("/smoke", data={"on": "off", "now": "1"})
    assert s.get("smoke")["on"] and s.get("smoke")["run_now"]
    s.put("env", "prod")
    s.put("smoke", {"on": False})
    c.post("/smoke", data={"on": "on"})
    assert not s.get("smoke")["on"] and "<h3>SB2 smoke run</h3>" not in c.get("/settings").text


def test_run_refuses_a_production_instance(tmp_path):
    s = Store(tmp_path)
    s.put("env", "prod")
    with pytest.raises(RuntimeError, match="SB2 only"):
        smoke.run(s, None, None)
