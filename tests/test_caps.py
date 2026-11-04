import json

from sc_activity_agent import caps, cli
from sc_activity_agent.store import Store

NOW = 1_800_000_000.0   # fixed clock; the store tz default is America/New_York


def log(store, n, action="x", http=200):
    for _ in range(n):
        store.db.execute("INSERT INTO api_log(ts, role, user, sc_wo, action, method, path, http, ms) VALUES(?,?,?,?,?,?,?,?,?)",
                         (NOW - 60, "subscriber", "u", None, action, "POST", "/p", http, 5))
    store.db.commit()


def test_nothing_happens_under_the_limits(tmp_path):
    s = Store(tmp_path)
    log(s, 5)
    assert caps.check(s, clock=lambda: NOW) == [] and s.get("paused_at") is None


def test_wo_limit_pauses_the_agent_and_records_why(tmp_path):
    s = Store(tmp_path)
    s.put("caps", {"wo_per_day": 2})
    log(s, 2, action="create_wo")
    log(s, 3, action="create_wo", http=502)   # a failed create is not a WO
    out = caps.check(s, clock=lambda: NOW)
    assert out and "2 work orders created today (limit 2)" in out[0][1]
    assert s.get("paused_at") == NOW and s.get("cap_hit")["why"].startswith("2 work orders")
    assert caps.check(s, clock=lambda: NOW) == []   # already paused: no second pause or alert


def test_call_limit_and_zero_turns_a_limit_off(tmp_path):
    s = Store(tmp_path)
    s.put("caps", {"wo_per_day": 0, "calls_per_day": 10})
    log(s, 10, action="create_wo")
    assert "API calls today" in caps.reached(s, NOW) and caps.limits(s)["wo_per_day"] == 0
    s.put("caps", {"wo_per_day": 0, "calls_per_day": 0})
    assert caps.reached(s, NOW) is None


def test_yesterdays_calls_do_not_count(tmp_path):
    s = Store(tmp_path)
    s.put("caps", {"calls_per_day": 5})
    log(s, 9)
    assert caps.reached(s, NOW + 2 * 86400) is None


def test_the_warning_clears_once_the_agent_is_resumed_under_the_limit(tmp_path):
    s = Store(tmp_path)
    s.put("caps", {"calls_per_day": 5})
    log(s, 6)
    caps.check(s, clock=lambda: NOW)
    s.put("paused_at", None)
    s.put("caps", {"calls_per_day": 50})
    caps.check(s, clock=lambda: NOW)
    assert s.get("cap_hit") is None


def test_get_masks_secrets(tmp_path, capsys):
    s = Store(tmp_path)
    s.put("alerts_token", s.enc("123:abc"))
    s.put("alerts", {"bot": "mybot", "chat_id": 5, "webhook_secret": "plain"})
    cli.cmd_get(type("A", (), {"key": None})(), s)
    out = capsys.readouterr().out
    assert "123:abc" not in out and "plain" not in out and "mybot" in out and json.loads(out)["alerts_token"] == "***"
    cli.cmd_get(type("A", (), {"key": "alerts_token"})(), s)
    assert capsys.readouterr().out.strip() == '"***"'


def test_settings_page_saves_the_limits(tmp_path):
    from fastapi.testclient import TestClient
    from sc_activity_agent.web.app import create_app
    s = Store(tmp_path)
    c = TestClient(create_app(s))
    assert "Daily limits" in c.get("/settings").text and "Daily limits" not in c.get("/behavior").text
    r = c.post("/caps", data={"wo_per_day": "55", "calls_per_day": "0"}, follow_redirects=False)
    assert r.headers["location"] == "/settings" and s.get("caps") == {"wo_per_day": 55, "calls_per_day": 0}
