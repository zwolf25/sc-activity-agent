import json
import pytest
from fastapi.testclient import TestClient

from sc_activity_agent.store import Store
from sc_activity_agent.web.app import create_app


@pytest.fixture(autouse=True)
def login_works(monkeypatch):
    """Adding a user signs in first; no test may reach the real login server."""
    from sc_activity_agent.client import ScApp
    monkeypatch.setattr(ScApp, "token", lambda self, user, pw: "tok")

    def no_network(method, url, headers, data):   # adding a Subscriber user also reads its dashboard: a real call that stalled 60 s+ on slow networks (B-107)
        raise OSError("no network in tests")
    monkeypatch.setattr(ScApp, "_http", staticmethod(no_network))


def client(tmp_path):
    s = Store(tmp_path)
    s.put("env", "sb2")
    return s, TestClient(create_app(s))


def test_home_redirects_to_setup_until_complete(tmp_path):
    _, c = client(tmp_path)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert "To do" in c.get("/setup").text


def test_add_connection_encrypts_secret_and_lists_user_without_password(tmp_path):
    s, c = client(tmp_path)
    c.post("/connections/add", data={"side": "subscriber", "name": "Main", "client_id": "cid", "client_secret": "topsecret"})
    c.post("/connections/1/users", data={"username": "alice", "password": "pw123"})
    raw = s.db.execute("SELECT client_secret FROM connections").fetchone()[0]
    assert "topsecret" not in raw
    page = c.get("/connections").text
    assert "alice" in page and "pw123" not in page and "topsecret" not in page and "SB2" in page


def test_one_subscriber_connection_only(tmp_path):
    s, c = client(tmp_path)
    for _ in range(2):
        c.post("/connections/add", data={"side": "subscriber", "name": "x", "client_id": "a", "client_secret": "b"})
    assert s.db.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 1


def test_dashboard_audit_errors_render_and_pause_toggles(tmp_path):
    s, c = client(tmp_path)
    for p in ("/dashboard", "/audit", "/errors"):
        assert c.get(p).status_code == 200
    c.post("/pause")
    assert "Paused" in c.get("/dashboard").text
    c.post("/resume")
    assert s.get("paused_at") is None


def test_new_pages_render_and_save(tmp_path):
    s, c = client(tmp_path)
    for p in ("/behavior", "/locations", "/connections", "/cleanup", "/settings"):
        assert c.get(p).status_code == 200
    c.post("/behavior", data={"wo_per_month": "60", "hours_start": "9"})
    assert s.get("behavior")["wo_per_month"] == 60 and s.get("hours_start") == 9
    s.put("locations_cache", [{"store_id": "HQ", "db_id": 1, "subscriber_id": 2, "name": "", "lat": 1, "lon": 2, "tz": "America/New_York", "city": "", "state": "", "status": ""}])
    c.post("/locations/add", data={"store_id": "HQ"})
    c.post("/connections/add", data={"side": "subscriber", "name": "m", "client_id": "a", "client_secret": "b"})
    c.post("/connections/1/users", data={"username": "u1", "password": "p"})
    assert "u1" in c.get("/connections").text and "HQ" in c.get("/locations").text


def test_wizard_points_to_next_step_and_dashboard_check(tmp_path):
    s, c = client(tmp_path)
    assert "Next: Subscriber connection with a user" in c.get("/setup").text
    r = c.post("/dashboards/load", data={"subscriber_id": "5"}, follow_redirects=False)
    assert "Add%20a%20Subscriber%20user%20next" in r.headers["location"]
    assert s.get("subscriber_id") == 5


def test_test_instance_creates_locked_sb2_twin(tmp_path, monkeypatch):
    from sc_activity_agent import launcher
    monkeypatch.setattr(launcher, "ensure_running", lambda d, p: True)
    s = Store(tmp_path / "main")
    s.put("env", "prod")
    s.put("port", 8080)
    c = TestClient(create_app(s))
    r = c.post("/test-instance", follow_redirects=False)
    assert r.headers["location"] == "http://127.0.0.1:8081/dashboard"
    twin = Store(tmp_path / "main-sb2")
    assert twin.get("env") == "sb2" and twin.get("twin_port") == 8080
    assert "Open SB2 test instance" in c.get("/connections").text
    assert "Open Production" in TestClient(create_app(twin)).get("/dashboard").text


def test_audit_failures_filter(tmp_path):
    from sc_activity_agent.store import Store
    from sc_activity_agent.web.app import create_app
    from starlette.testclient import TestClient
    s = Store(tmp_path)
    s.log(ts=1, role="subscriber", user="u", action="a", method="GET", path="/okpath", http=200)
    s.log(ts=2, role="subscriber", user="u", action="a", method="GET", path="/badpath", http=502)
    c = TestClient(create_app(s))
    assert "/okpath" in c.get("/audit").text
    t = c.get("/audit?failed=1").text
    assert "/badpath" in t and "/okpath" not in t


def test_locations_load_search_add(tmp_path, monkeypatch):
    from sc_activity_agent import locations
    s, c = client(tmp_path)
    rows = [{"Id": 11, "SubscriberId": 5, "StoreId": "HQ-NYC", "Name": "Union Square", "Latitude": 40.7, "Longitude": -73.9,
             "TimeZoneIanaName": "America/New_York", "City": "New York", "State": "NY", "Status": "Open"},
            {"Id": 12, "SubscriberId": 5, "StoreId": "ST-2", "Name": "Other", "Latitude": 1.0, "Longitude": 2.0, "City": "Austin", "State": "TX"}]
    assert "Add a Subscriber user" in c.post("/locations/load", follow_redirects=True).text
    s.put("locations_cache", locations.fetch(lambda path, params: rows if params["$skip"] == 0 else [], 5))
    page = c.get("/locations?q=austin").text
    assert "ST-2" in page and "HQ-NYC" not in page
    c.post("/locations/add", data={"store_id": "HQ-NYC"})
    row = s.db.execute("SELECT * FROM locations").fetchone()
    assert (row["db_id"], row["subscriber_id"], row["tz"]) == (11, 5, "America/New_York")
    assert "HQ-NYC" not in c.get("/locations?q=nyc").text.split("Add locations")[1]


def test_fetch_pages_and_filters_other_subscribers():
    from sc_activity_agent import locations
    data = [{"Id": i, "SubscriberId": 5 if i % 2 else 9, "StoreId": f"S{i}", "Latitude": 1, "Longitude": 2} for i in range(120)]
    got = locations.fetch(lambda path, p: data[p["$skip"]:p["$skip"] + p["$top"]], 5)
    assert len(got) == 60 and all(g["subscriber_id"] == 5 for g in got)


def test_locations_page_lists_rank_one_trades(tmp_path):
    s, c = client(tmp_path)
    s.put("rank1", {"HQ": {"at": 1, "trades": ["HVAC", "DOORS"]}})
    page = c.get("/locations").text
    assert "HVAC" in page and "DOORS" in page


def test_dashboard_this_week_paginates_and_hides_done(tmp_path):
    s, c = client(tmp_path)
    s.put("tz", "UTC")
    s.db.execute("INSERT INTO work_orders(id,sc_id,location,trade,state,created_at) VALUES(1,999,'HQ','HVAC','active',0)")
    # Wednesday noon of the current week, UTC, so every row sits inside the Monday-to-Sunday window
    import datetime as dt
    d = dt.datetime.now(dt.timezone.utc)
    wed = (d - dt.timedelta(days=d.weekday() - 2)).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
    for i in range(12):
        s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state) VALUES(1,?,?,?,?)", (i, "prov_note", wed + i, "done" if i < 3 else "pending"))
    s.db.commit()
    p1, p2 = c.get("/dashboard?f=1").text, c.get("/dashboard?page=2&f=1").text   # f=1: filter form submitted, nothing hidden
    assert "This week" in p1 and "Page 1 of 2" in p1 and p1.count("prov note") == 10 and p2.count("prov note") == 2
    assert "API calls in the last hour" not in p1
    s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state) VALUES(1,99,'sub_note',?, 'skipped')", (wed,))
    s.db.commit()
    assert "skipped</span>" in c.get("/dashboard").text   # B-59: the last submitted choice (nothing hidden) is remembered
    assert "skipped</span>" not in c.get("/dashboard?f=1&hide_skipped=1").text and "skipped</span>" not in c.get("/dashboard").text
    hidden = c.get("/dashboard?f=1&hide_done=1&hide_skipped=1").text
    assert hidden.count("prov note") == 9 and "Page 1 of" not in hidden and "done</span>" not in hidden


def test_dashboard_hides_done_and_skipped_until_the_choice_is_changed(tmp_path):
    s, c = client(tmp_path)
    assert c.get("/dashboard").text.count('checked') >= 2   # first visit: both hidden
    c.get("/dashboard?f=1&hide_done=1")
    assert s.get("dashboard_hide") == {"done": True, "skipped": False}


def test_activity_hours_are_one_row_of_selects_and_end_follows_start(tmp_path):
    s, c = client(tmp_path)
    page = c.get("/behavior").text
    assert 'name="hours_start"' in page and 'type="range" name="hours_start"' not in page
    c.post("/behavior", data={"hours_start": "10", "hours_end": "9"})
    assert s.get("hours_start") == 10 and s.get("hours_end") == 11


def test_activity_days_and_12_hour_labels(tmp_path):
    s, c = client(tmp_path)
    page = c.get("/behavior").text
    assert "8:00 AM" in page and "5:00 PM" in page and "12:00 PM" in page and "08:00" not in page
    assert page.count('name="days"') == 7 and page.count('name="days" value="') == 7
    c.post("/behavior", data={"days": ["5", "6"], "photo_before": "30"})
    assert s.get("days") == [5, 6] and s.get("behavior")["days"] == [5, 6] and s.get("behavior")["photo_before"] == 30
    c.post("/behavior", data={"hours_start": "9"})   # no day ticked: fall back to Monday to Friday, never an empty week
    assert s.get("days") == [0, 1, 2, 3, 4]


def test_users_carry_their_capabilities(tmp_path):
    s, c = client(tmp_path)
    c.post("/connections/add", data={"side": "provider", "name": "p", "client_id": "a", "client_secret": "b", "provider_id": "7"})
    c.post("/connections/1/users", data={"username": "u1", "password": "p"})
    c.post("/connections/1/users", data={"username": "u2", "password": "p"})
    can = lambda i: json.loads(s.db.execute("SELECT can_do FROM users WHERE id=?", (i,)).fetchone()[0])
    assert "check_in" in can(1) and can(2) == []   # the first user on a connection gets everything, later ones start empty
    c.post("/users/2/can-do", data={"can_do": ["check_in", "nonsense"]})
    assert can(2) == ["check_in"]
    page = c.get("/connections").text
    assert "Can do" in page and "No user can do" not in page


def test_setup_checklist_flags_actions_nobody_can_do(tmp_path):
    s, c = client(tmp_path)
    c.post("/connections/add", data={"side": "provider", "name": "p", "client_id": "a", "client_secret": "b", "provider_id": "7"})
    c.post("/connections/1/users", data={"username": "u1", "password": "p"})
    c.post("/users/1/can-do", data={"can_do": ["accept"]})
    page = c.get("/connections").text
    assert "No user can do" in page and "No check-in tech" in page


def test_step_context_text():
    from sc_activity_agent.status import detail
    assert detail("proposal_decide", {"approve": False}) == "Will reject"
    assert detail("check_in", {"visit": 1, "late": True}) == "Visit 1, late" and detail("check_in", {"visit": 2}) == "Visit 2"
    assert detail("prov_note", {"situation": "parts"}) == "Note: parts needed"
    assert detail("check_out", {"visit": 1, "final": False}).endswith("return visit") and detail("review", {}) == ""


def test_setup_shows_checkin_permission_request_and_status(tmp_path):
    s, c = client(tmp_path)
    s.put("subscriber_id", 2014917582)
    c.post("/connections/add", data={"side": "provider", "name": "SydeTech", "client_id": "c", "client_secret": "x", "provider_id": "2000078685"})
    c.post("/connections/1/users", data={"username": "pu", "password": "pw"})
    t = c.get("/setup").text
    assert "Not confirmed yet" in t and "Subscriber ID 2014917582 with Provider ID 2000078685 (SydeTech)" in t and "SB2" in t
    s.log(ts=1, role="provider", user="pu", action="check_in", method="POST", path="/workorders/1/universalCheckIn", http=403, detail='{"ErrorCode":901,"Message":"WO not assigned"}')
    t = c.get("/setup").text   # a 403 that is not error 804 does not say the pair needs linking
    assert "Blocked (error 804)" not in t and "Please link" not in t and "WO not assigned" in t and "Check-in is blocked" not in c.get("/dashboard").text
    s.log(ts=1.5, role="provider", user="pu", action="check_in", method="POST", path="/workorders/1/universalCheckIn", http=403, detail='{"ErrorCode":804}')
    assert "Blocked (error 804)" in c.get("/setup").text and "Check-in is blocked for SydeTech" in c.get("/dashboard").text
    s.log(ts=2, role="provider", user="pu", action="check_in", method="POST", path="/workorders/2/universalCheckIn", http=200)
    t = c.get("/setup").text
    assert "Confirmed" in t and "Please link" not in t and "Check-in is blocked" not in c.get("/dashboard").text


def test_offline_notice_is_readable_and_can_be_dismissed(tmp_path):
    s, c = client(tmp_path)
    s.put("gaps", [{"start": 1793068087, "end": 1793069068, "policy": "shift", "steps": 0, "undo": [], "acked": False}])
    text = c.get("/dashboard").text
    assert "1793068087" not in text and "16 min" in text and "No scheduled steps were affected" in text
    c.post("/gap/0/dismiss", follow_redirects=False)
    assert "was not running" not in c.get("/dashboard").text


def test_add_many_locations_from_ticks_and_pasted_ids(tmp_path):
    s, c = client(tmp_path)
    s.put("locations_cache", [{"store_id": f"S{i}", "db_id": i, "subscriber_id": 5, "name": f"Store {i}", "lat": 1.0, "lon": 2.0,
                               "tz": "America/New_York", "city": "X", "state": "NY", "status": "Open"} for i in range(1, 6)])
    r = c.post("/locations/add-many", data={"store_ids": ["S1", "S2"], "pasted": "S2, S3\nS4 NOPE"}, follow_redirects=True)
    assert {r["store_id"] for r in s.db.execute("SELECT store_id FROM locations")} == {"S1", "S2", "S3", "S4"}
    assert "Added 4" in r.text and "NOPE" in r.text
    s.db.execute("UPDATE locations SET enabled=0 WHERE store_id='S1'")
    s.db.commit()
    c.post("/locations/add-many", data={"store_ids": ["S1"]})
    assert s.db.execute("SELECT enabled FROM locations WHERE store_id='S1'").fetchone()[0] == 0   # re-adding keeps the flag


def test_locations_page_shows_skipped_trades_and_refresh_button(tmp_path):
    s, c = client(tmp_path)
    s.put("rank1", {"HQ": {"at": 1, "trades": ["HVAC"], "skipped": ["ROOFING"]}})
    page = c.get("/locations").text
    assert "ROOFING" in page and "Refresh now" in page


def test_user_label_can_be_edited_after_adding(tmp_path):
    s = Store(tmp_path)
    s.put("env", "sb2")
    s.db.execute("INSERT INTO connections VALUES(1,'provider','P','c','x',77)")
    s.db.execute("INSERT INTO users(id,conn_id,username,password,label) VALUES(1,1,'tech1',?,'old')", (s.enc("pw"),))
    s.db.commit()
    c = TestClient(create_app(s))
    c.post("/users/1/label", data={"label": " Maria, HVAC tech "}, follow_redirects=False)
    assert s.db.execute("SELECT label FROM users WHERE id=1").fetchone()[0] == "Maria, HVAC tech"
    assert "Maria, HVAC tech" in c.get("/connections").text


def test_new_user_is_saved_only_if_login_works(tmp_path, monkeypatch):
    from sc_activity_agent.client import ScApp, ScError
    s = Store(tmp_path)
    s.put("env", "sb2")
    s.db.execute("INSERT INTO connections VALUES(1,'provider','P','c',?,77)", (s.enc("sec"),))
    s.db.commit()
    c = TestClient(create_app(s))

    def bad(self, user, pw):
        raise ScError(400, "Wrong user or password", "/oauth/token")
    monkeypatch.setattr(ScApp, "token", bad)
    r = c.post("/connections/1/users", data={"username": "tech1", "password": "x"}, follow_redirects=False)
    assert s.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 and "was not added" in r.headers["location"].replace("%20", " ")
    monkeypatch.setattr(ScApp, "token", lambda self, user, pw: "tok")
    c.post("/connections/1/users", data={"username": "tech1", "password": "x", "label": "Maria"}, follow_redirects=False)
    assert s.db.execute("SELECT username FROM users").fetchone()[0] == "tech1"


def test_update_button_starts_one_installer_and_shows_progress(tmp_path, monkeypatch):
    from sc_activity_agent import __version__, update
    from sc_activity_agent.web import app as webapp
    s, c = client(tmp_path)
    started = []
    monkeypatch.setattr(update, "check", lambda store, force=False: {"tag": "v99.0.0", "notes": "- **Fix** one thing\n- Fix `two`"})
    monkeypatch.setattr(webapp.subprocess, "Popen", lambda *a, **k: started.append(a))
    for _ in range(3):   # a second and third click must not start more installers
        r = c.post("/update", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/updating"
    assert len(started) == 1
    page = c.get("/updating").text
    assert "Updating to v99.0.0" in page and "/api/update-status" in page
    assert "What is new in v99.0.0" in page and "<li>Fix one thing</li>" in page and "<li>Fix two</li>" in page
    assert c.get("/api/update-status").json()["state"] == "installing" and c.get("/api/update-status").json()["version"] == __version__
    s.put("update_status", {**s.get("update_status"), "state": "failed", "msg": "Install failed"})
    assert c.post("/update", follow_redirects=False).headers["location"] == "/updating" and len(started) == 2   # a failed run can be retried
    s.put("update_status", {**s.get("update_status"), "at": 0})
    assert update.in_progress(s) is None   # a run older than 15 minutes is dead


def test_dashboard_switches_to_next_week_remembers_it_and_resets_with_the_new_week(tmp_path):
    import datetime as dt
    from sc_activity_agent import status
    s, c = client(tmp_path)
    s.db.execute("INSERT INTO work_orders(id,sc_id,location,trade,state,created_at) VALUES(1,999,'HQ','HVAC','active',0)")
    mon = status.week_start(s.get("tz", "America/New_York"))
    this_wk, next_wk = mon.timestamp() + 2 * 86400 + 43200, mon.timestamp() + 9 * 86400 + 43200
    s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state) VALUES(1,1,'accept',?,'pending')", (this_wk,))
    s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state) VALUES(1,2,'check_in',?,'pending')", (next_wk,))
    s.db.commit()
    assert "<td>accept</td>" in c.get("/dashboard").text and "<td>check in</td>" not in c.get("/dashboard").text
    nxt = c.get("/dashboard?w=next").text
    assert "Next week" in nxt and "<td>check in</td>" in nxt and "<td>accept</td>" not in nxt
    assert "<td>check in</td>" in c.get("/dashboard").text   # remembered with no parameter
    assert "<td>accept</td>" in c.get("/dashboard?w=this").text and "<td>accept</td>" in c.get("/dashboard").text
    c.get("/dashboard?w=next")
    s.put("dashboard_week", {**s.get("dashboard_week"), "monday": "2000-01-03"})   # chosen in an earlier week
    assert "<td>accept</td>" in c.get("/dashboard").text   # a new week starts on this week


def test_stage_page(tmp_path):
    s, c = client(tmp_path)
    assert c.get("/stage?s=Awaiting+review").status_code == 200
    assert "Unknown stage" in c.get("/stage?s=Nope").text


def test_unseeded_assets_banner_follows_seeding_and_can_be_dismissed(tmp_path):
    s, c = client(tmp_path)
    s.db.execute("INSERT INTO locations(store_id, db_id, subscriber_id, name) VALUES('HQ-NYC', 1, 2, 'HQ')")
    s.put("rank1", {"HQ-NYC": {"at": 0, "trades": ["HVAC", "DOORS"], "owners": {}}})
    assert "No assets seeded yet: HQ-NYC (HVAC)" in c.get("/dashboard").text   # DOORS carries no assets
    assert "No assets seeded yet" not in c.get("/audit").text                    # only Dashboard and Locations show it
    s.db.execute("INSERT INTO assets(id, location, tag, trade, type, created_at) VALUES(1,'HQ-NYC','T','HVAC','RTU',0)")
    s.db.commit()
    assert "No assets seeded yet" not in c.get("/dashboard").text
    s.db.execute("DELETE FROM assets")
    s.db.commit()
    c.post("/assets/dismiss", headers={"referer": "/dashboard"})
    assert "No assets seeded yet" not in c.get("/dashboard").text


def test_errors_page_groups_repeats_and_acts_on_a_group(tmp_path):
    from sc_activity_agent.engine import add_plan
    s = Store(tmp_path)
    for n in (111111, 222222):
        add_plan(s, "HQ", "HVAC", n, [{"kind": "invoice", "due_at": 1.0, "payload": {}}], {}, 1.0)
    add_plan(s, "HQ", "HVAC", 333333, [{"kind": "check_in", "due_at": 1.0, "payload": {}}], {}, 1.0)
    s.db.execute("UPDATE steps SET state='failed', error=CASE kind WHEN 'invoice' THEN 'POST /invoices 400: error 1104 over NTE for WO ' || (SELECT sc_id FROM work_orders w WHERE w.id=wo_id) ELSE 'boom' END")
    s.db.commit()
    c = TestClient(create_app(s))
    page = c.get("/errors").text
    assert "over the NTE" in page and "Retry all" in page and page.count("<tr><td>invoice") == 1
    ids = [r["id"] for r in s.db.execute("SELECT id FROM steps WHERE kind='invoice'")]
    c.post("/steps/group/skip", data={"id": ids})
    assert [r["state"] for r in s.db.execute("SELECT state FROM steps ORDER BY id")] == ["skipped", "skipped", "failed"]


def test_close_out_ends_a_wos_plan_without_a_call(tmp_path):
    from sc_activity_agent.engine import add_plan
    s = Store(tmp_path)
    add_plan(s, "HQ", "HVAC", 111111, [{"kind": "invoice", "due_at": 1.0, "payload": {}}, {"kind": "invoice_pay", "due_at": 2.0, "payload": {}}], {}, 1.0)
    s.db.execute("UPDATE steps SET state='failed', error='x' WHERE seq=1")
    s.db.commit()
    c = TestClient(create_app(s))
    assert "Close out WO" in c.get("/errors").text
    c.post("/wos/close", data={"wo": ["111111"]})
    assert s.db.execute("SELECT state FROM work_orders").fetchone()[0] == "cancelled"
    assert {r[0] for r in s.db.execute("SELECT state FROM steps")} == {"skipped"}


def test_errors_row_counts_the_steps_waiting_behind_it_and_the_banner_shows_a_network_outage(tmp_path):
    from sc_activity_agent.engine import add_plan
    s = Store(tmp_path)
    add_plan(s, "HQ", "HVAC", 111111, [{"kind": "check_in", "due_at": 1.0, "payload": {}}] + [{"kind": "note", "due_at": 2.0, "payload": {}}] * 3, {}, 1.0)
    s.db.execute("UPDATE steps SET state='failed', error='boom' WHERE seq=0")
    s.db.commit()
    c = TestClient(create_app(s))
    assert "3 later steps waiting" in c.get("/errors").text and "Network is down" not in c.get("/dashboard").text
    s.put("net_down", 1_761_220_800)
    assert "Network is down since" in c.get("/dashboard").text


def test_factory_reset_needs_confirmation_and_clears(tmp_path):
    store, c = client(tmp_path)
    store.put("subscriber_id", 1)
    store.put("env", "sb2")
    assert "RESET" in c.get("/reset").text
    c.post("/reset", data={"confirm": "no", "understood": "1"}, follow_redirects=False)
    assert store.get("subscriber_id") == 1
    r = c.post("/reset", data={"confirm": "RESET", "understood": "1"}, follow_redirects=False)
    assert r.headers["location"].startswith("/setup")
    assert store.get("subscriber_id") is None and store.get("env") == "sb2"
    assert list((store.dir / "backups").glob("*"))


def test_provider_needs_numeric_id(tmp_path):
    store, c = client(tmp_path)
    r = c.post("/connections/add", data=dict(side="provider", name="P", client_id="a", client_secret="b", provider_id=""), follow_redirects=False)
    assert "Provider ID" in r.headers["location"] or "Provider%20ID" in r.headers["location"]
    assert not store.db.execute("SELECT 1 FROM connections").fetchone()


def test_create_error_hint():
    from sc_activity_agent.web.app import hint
    assert "Rank 1" in hint("409 no eligible trade at ZW123 (no Rank 1 provider connection)")
    assert "RequireAttachment" in hint('400 /workorders: {"ErrorCodes":[916],"ErrorMessage":"At least one attachment required to create this WorkOrder"}')


def test_setup_check_reports_each_problem(tmp_path, monkeypatch):
    from sc_activity_agent import setupcheck
    from sc_activity_agent.client import ScApp, ScError
    store, c = client(tmp_path)
    store.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c',?,NULL)", (store.enc("x"),))
    store.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(1,1,'sub',?,'[]')", (store.enc("pw"),))
    store.db.commit()
    store.put("subscriber_id", 5)
    def boom(self, *a, **k):
        raise ScError(403, "forbidden", "x")
    monkeypatch.setattr(ScApp, "call", boom)
    class RT:
        rng = None
    res = setupcheck.run(store, RT())
    labels = {r["label"]: r for r in res["rows"]}
    assert labels["Sign in: sub (subscriber, S)"]["ok"]
    assert not labels["Issue list dashboard: sub"]["ok"]
    assert not labels["Locations"]["ok"]
    assert "Run check" in c.get("/setup").text


def test_restore_live_brings_back_rows_and_keeps_environment(tmp_path):
    from sc_activity_agent import reset, update
    store, c = client(tmp_path)
    store.put("env", "prod")
    store.put("subscriber_id", 7)
    store.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c',?,NULL)", (store.enc("x"),))
    store.db.commit()
    update.backup(store)
    name = update.backups(store)[0][0]
    store.put("subscriber_id", 9)
    store.put("env", "sb2")
    store.db.execute("DELETE FROM connections")
    store.db.commit()
    assert "RESTORE" in c.get(f"/restore/{name}").text
    c.post(f"/restore/{name}", data={"confirm": "no", "understood": "1"})
    assert store.get("subscriber_id") == 9
    r = c.post(f"/restore/{name}", data={"confirm": "RESTORE", "understood": "1"}, follow_redirects=False)
    assert "Restored" in r.headers["location"]
    assert store.get("subscriber_id") == 7 and store.get("env") == "sb2"
    assert store.db.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 1


def test_quiesced_refuses_while_a_pass_runs_and_unpauses():
    from sc_activity_agent import reset
    class E:
        paused, running = False, True
        def pause(self): self.paused = True
        def resume(self, p): self.paused = False
    e = E()
    with pytest.raises(reset.Busy):
        with reset.quiesced(e, wait=0.3):
            pass
    assert not e.paused


def test_dashboard_check_shows_the_users_dashboard(tmp_path, monkeypatch):
    from sc_activity_agent.client import ScApp
    s, c = client(tmp_path)
    s.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c',?,NULL)", (s.enc("x"),))
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(1,1,'sub',?,'[]')", (s.enc("pw"),))
    s.db.commit()
    monkeypatch.setattr(ScApp, "call", lambda self, user, method, path, *a, **k:
                        {"UserProfile": {"DefaultScUserSetupId": 2752, "Dashboards": [{"SetupId": 2752, "Name": "PM Expert Dashboard"}]}}
                        if path.endswith("/profile") else {"Headers": [{"Id": 1, "DashboardId": 2752, "Name": "Mine.xlsx"}]})
    c.post("/dashboards/load", data={"subscriber_id": "5"})
    assert s.get("dashboard_info") == {"sub": {"user": "sub", "id": 2752, "name": "PM Expert Dashboard", "list": "Mine.xlsx", "error": ""}}
    assert "PM Expert Dashboard" in c.get("/connections").text and "Mine.xlsx" in c.get("/connections").text


def test_subscriber_user_without_a_dashboard_cannot_create_wos(tmp_path, monkeypatch):
    import json
    from sc_activity_agent.client import ScApp
    s, c = client(tmp_path)
    c.post("/connections/add", data={"side": "subscriber", "name": "S", "client_id": "a", "client_secret": "b"})
    has = {"yes": True}
    monkeypatch.setattr(ScApp, "token", lambda self, u, p: "t")
    monkeypatch.setattr(ScApp, "call", lambda self, user, method, path, *a, **k:
                        {"UserProfile": {"DefaultScUserSetupId": 2752 if user[0] == "yes" else 0, "Dashboards": [{"SetupId": 2752, "Name": "PM"}]}}
                        if path.endswith("/profile") else {"Headers": [{"Id": 1, "DashboardId": 2752, "Name": "L.xlsx"}]})
    c.post("/connections/1/users", data={"username": "no", "password": "p"})   # first user starts with every action ticked
    row = s.db.execute("SELECT can_do FROM users WHERE username='no'").fetchone()
    assert "create_wo" not in json.loads(row["can_do"]) and s.get("dashboard_info")["no"]["id"] is None
    r = c.post("/users/1/can-do", data={"can_do": ["create_wo", "review"]}, follow_redirects=False)
    assert "has%20no%20dashboard" in r.headers["location"]
    assert json.loads(s.db.execute("SELECT can_do FROM users WHERE id=1").fetchone()["can_do"]) == ["review"]
    c.post("/connections/1/users", data={"username": "yes", "password": "p"})
    assert s.get("dashboard_info")["yes"]["id"] == 2752
    c.post("/users/2/can-do", data={"can_do": ["create_wo"]})
    assert json.loads(s.db.execute("SELECT can_do FROM users WHERE id=2").fetchone()["can_do"]) == ["create_wo"]
    assert "No dashboard" in c.get("/connections").text and "<b>PM</b> (2752)" in c.get("/connections").text


def test_old_list_shaped_dashboard_info_does_not_break_pages(tmp_path):
    s, c = client(tmp_path)
    s.put("dashboard_info", [{"user": "sub", "id": 1, "name": "", "list": "", "error": ""}])
    assert c.get("/setup").status_code == 200 and c.get("/connections").status_code == 200


def test_settings_offers_the_issue_list_download(tmp_path):
    _, c = client(tmp_path)
    assert "/issue-list.xlsx" in c.get("/settings").text
    r = c.get("/issue-list.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]


def test_seed_button_approves_the_location_and_seeds_in_the_background(tmp_path, monkeypatch):
    import time
    from sc_activity_agent import assets
    s, c = client(tmp_path)
    s.db.execute("INSERT INTO locations(store_id, db_id, subscriber_id, name) VALUES('HQ-NYC', 1, 2, 'HQ')")
    s.put("rank1", {"HQ-NYC": {"at": 0, "trades": ["HVAC"], "owners": {}}})
    s.db.commit()
    monkeypatch.setattr(assets, "seed_location", lambda store, rt, sid: 12)
    assert "/assets/seed/HQ-NYC" in c.get("/dashboard").text
    c.post("/assets/seed/HQ-NYC", headers={"referer": "/dashboard"})
    for _ in range(50):
        if s.get("assets_seed", {}).get("HQ-NYC", {}).get("state") == "done":
            break
        time.sleep(0.1)
    assert s.get("assets_seed")["HQ-NYC"]["created"] == 12
    assert s.get("assets")["approved_locations"] == ["HQ-NYC"]
    c.post("/assets/seed/NOPE")   # unknown location: nothing approved
    assert s.get("assets")["approved_locations"] == ["HQ-NYC"]
