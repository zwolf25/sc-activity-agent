from fastapi.testclient import TestClient

from sc_activity_agent.alerts import Alerts, AlertError
from sc_activity_agent.client import ScError
from sc_activity_agent.engine import Engine
from sc_activity_agent.store import Store
from sc_activity_agent.web.app import create_app


class Fake:
    """Stands in for the Telegram API: records calls, replies from `replies`."""
    def __init__(self):
        self.calls, self.replies = [], {}

    def __call__(self, token, method, **kw):
        self.calls.append((method, kw))
        r = self.replies.get(method, {})
        if isinstance(r, Exception):
            raise r
        return r


def mk(tmp_path, **cfg):
    s = Store(tmp_path)
    s.put("env", "prod")
    s.put("alerts_token", s.enc("123:abc"))
    f = Fake()
    a = Alerts(s, f)
    a.save(enabled=True, chat_id=42, chat_name="Zac", **cfg)
    return s, a, f


def wo_step(s):
    s.db.execute("INSERT INTO work_orders(id, sc_id, location, trade, state, created_at) VALUES(1, 5001, 'HQ-NYC', 'HVAC', 'active', 0)")
    s.db.execute("INSERT INTO steps(id, wo_id, seq, kind, due_at, state, attempts) VALUES(7, 1, 0, 'check_in', 0, 'failed', 2)")
    s.db.commit()
    return (s.db.execute("SELECT * FROM work_orders").fetchone(), s.db.execute("SELECT * FROM steps").fetchone())


def test_off_by_default_sends_nothing(tmp_path):
    s = Store(tmp_path)
    f = Fake()
    assert Alerts(s, f).send("k", "hello") is False and f.calls == []


def test_step_failure_names_wo_and_has_buttons_only_when_enabled(tmp_path):
    s, a, f = mk(tmp_path, buttons=True)
    wo, st = wo_step(s)
    a.step_failed(wo, st, ScError(500, "boom", "/x"))
    m, kw = f.calls[0]
    assert m == "sendMessage" and kw["text"].startswith("[PROD] WO 5001 at HQ-NYC: check_in failed after 3 tries")
    assert "Retry" in str(kw["reply_markup"]) and "Cancel WO" in str(kw["reply_markup"])
    s2, a2, f2 = mk(tmp_path / "b")
    a2.step_failed(*wo_step(s2), ScError(500, "boom", "/x"))
    assert "reply_markup" not in f2.calls[0][1]


def test_checkin_804_gets_support_text_once_and_no_buttons(tmp_path):
    s, a, f = mk(tmp_path, buttons=True)
    wo, st = wo_step(s)
    e = ScError(403, "804 User has no permissions", "/universalCheckIn")
    a.step_failed(wo, st, e)
    a.step_failed(wo, st, e)   # cooldown: one message
    assert len(f.calls) == 1 and "804" in f.calls[0][1]["text"] and "reply_markup" not in f.calls[0][1]


def test_hourly_cap_sends_one_summary_then_stays_quiet(tmp_path):
    s, a, f = mk(tmp_path)
    for i in range(14):
        a.send(f"k{i}", "x")
    texts = [c[1]["text"] for c in f.calls]
    assert len(texts) == 11 and "held back" in texts[-1]


def test_send_failure_never_raises_and_is_recorded(tmp_path):
    s, a, f = mk(tmp_path)
    f.replies["sendMessage"] = AlertError("chat not found")
    assert a.send("k", "x") is False and "chat not found" in s.get("alert_error")


def test_only_the_saved_chat_may_tap_and_stale_taps_do_nothing(tmp_path):
    s, a, f = mk(tmp_path, buttons=True)
    wo, st = wo_step(s)
    e = Engine(s, {}, clock=lambda: 100.0)
    assert a.tap({"message": {"chat": {"id": 999}}, "data": "r:7"}, e, None) is None   # someone else
    assert a.tap({"message": {"chat": {"id": 42}}, "data": "r:7"}, e, None)[1] == "Retrying now."
    assert s.db.execute("SELECT state FROM steps WHERE id=7").fetchone()[0] == "pending"
    assert "already pending" in a.tap({"message": {"chat": {"id": 42}}, "data": "r:7"}, e, None)[1]   # stale button
    assert s.get("changes")[-1]["what"].startswith("telegram: r:7")


def test_cancel_asks_first_then_cancels_through_the_handler(tmp_path, monkeypatch):
    s, a, f = mk(tmp_path, buttons=True)
    wo_step(s)
    e = Engine(s, {}, clock=lambda: 100.0)
    ask = a.tap({"message": {"chat": {"id": 42}}, "data": "c:1"}, e, None)
    assert ask[0] == "ask" and "cy:1" in str(ask[2])
    called = []
    monkeypatch.setattr("sc_activity_agent.handlers.cancel_wo", lambda rt, wo, note: called.append(wo["sc_id"]))
    assert "cancelled" in a.tap({"message": {"chat": {"id": 42}}, "data": "cy:1"}, e, None)[1] and called == [5001]


def test_setup_flow_in_the_console(tmp_path):
    s = Store(tmp_path)
    s.put("env", "prod")
    f = Fake()
    import sc_activity_agent.web.app as webapp
    webapp.Alerts = lambda store: Alerts(store, f)
    c = TestClient(create_app(s))
    f.replies["getMe"] = {"username": "my_test_bot"}
    c.post("/alerts/token", data={"token": "123:abc"}, follow_redirects=False)
    assert Alerts(s).token() == "123:abc" and "my_test_bot" in c.get("/settings").text
    assert "123:abc" not in s.db.execute("SELECT value FROM settings WHERE key='alerts_token'").fetchone()[0]   # stored encrypted
    f.replies["getUpdates"] = []
    assert "No message found" in c.post("/alerts/find-chat").text
    f.replies["getUpdates"] = [{"update_id": 1, "message": {"chat": {"id": 42, "first_name": "Zac"}}}]
    c.post("/alerts/find-chat")
    assert Alerts(s).cfg["chat_id"] == 42
    c.post("/alerts/save", data={"enabled": "on", "ev_step_failed": "on"})
    assert Alerts(s).cfg["enabled"] and Alerts(s).cfg["events"]["offline"] is False
