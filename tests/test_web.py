from fastapi.testclient import TestClient

from sc_activity_agent.store import Store
from sc_activity_agent.web.app import create_app


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
    for p in ("/behavior", "/locations", "/roles", "/cleanup", "/settings"):
        assert c.get(p).status_code == 200
    c.post("/behavior", data={"wo_per_month": "60", "hours_start": "9"})
    assert s.get("behavior")["wo_per_month"] == 60 and s.get("hours_start") == 9
    s.put("locations_cache", [{"store_id": "HQ", "db_id": 1, "subscriber_id": 2, "name": "", "lat": 1, "lon": 2, "tz": "America/New_York", "city": "", "state": "", "status": ""}])
    c.post("/locations/add", data={"store_id": "HQ"})
    c.post("/connections/add", data={"side": "subscriber", "name": "m", "client_id": "a", "client_secret": "b"})
    c.post("/connections/1/users", data={"username": "u1", "password": "p"})
    c.post("/roles", data={"*|accept": "1", "HQ|accept": ""})
    assert s.db.execute("SELECT user_ids FROM roles WHERE location='*' AND action='accept'").fetchone()[0] == "[1]"
    assert "u1" in c.get("/roles").text and "HQ" in c.get("/locations").text


def test_wizard_points_to_next_step_and_dashboard_select(tmp_path):
    s, c = client(tmp_path)
    assert "Next: Subscriber connection with a user" in c.get("/setup").text
    c.post("/dashboards/select", data={"dashboard_id": "3498"})
    assert s.get("dashboard_id") == 3498 and s.get("dashboard_chosen")
    r = c.post("/dashboards/load", data={"subscriber_id": "5"}, follow_redirects=False)
    assert "Add%20a%20Subscriber%20user%20first" in r.headers["location"]
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
    p1, p2 = c.get("/dashboard").text, c.get("/dashboard?page=2").text
    assert "This week" in p1 and "Page 1 of 2" in p1 and p1.count("prov note") == 10 and p2.count("prov note") == 2
    hidden = c.get("/dashboard?hide_done=1").text
    assert hidden.count("prov note") == 9 and "Page 1 of" not in hidden and "done</span>" not in hidden
    assert "API calls in the last hour" not in p1
    s.db.execute("INSERT INTO steps(wo_id,seq,kind,due_at,state) VALUES(1,99,'sub_note',?, 'skipped')", (wed,))
    s.db.commit()
    assert "skipped</span>" not in c.get("/dashboard").text
    assert "skipped</span>" in c.get("/dashboard?f=1").text and "skipped</span>" not in c.get("/dashboard?f=1&hide_skipped=1").text


def test_activity_hours_are_one_row_of_selects_and_end_follows_start(tmp_path):
    s, c = client(tmp_path)
    page = c.get("/behavior").text
    assert 'name="hours_start"' in page and 'type="range" name="hours_start"' not in page
    c.post("/behavior", data={"hours_start": "10", "hours_end": "9"})
    assert s.get("hours_start") == 10 and s.get("hours_end") == 11


def test_roles_use_single_dropdowns(tmp_path):
    s, c = client(tmp_path)
    c.post("/connections/add", data={"side": "subscriber", "name": "m", "client_id": "a", "client_secret": "b"})
    c.post("/connections/1/users", data={"username": "u1", "password": "p"})
    assert "multiple" not in c.get("/roles").text


def test_step_context_text():
    from sc_activity_agent.status import detail
    assert detail("proposal_decide", {"approve": False}) == "Will reject"
    assert detail("check_in", {"visit": 1, "late": True}) == "Visit 1, late" and detail("check_in", {"visit": 2}) == "Visit 2"
    assert detail("prov_note", {"situation": "parts"}) == "Note: parts needed"
    assert detail("check_out", {"visit": 1, "final": False}).endswith("return visit") and detail("review", {}) == ""


def test_packaged_update_prepare_pauses_and_backs_up(tmp_path, monkeypatch):
    import sc_activity_agent.web.app as app_mod
    s, c = client(tmp_path)
    assert c.post("/update/prepare").status_code == 404 and "Start at login" in c.get("/settings").text
    monkeypatch.setattr(app_mod, "PACKAGED", True)
    assert c.post("/update/prepare").json() == {"ok": True}
    assert s.get("paused_at") and s.get("resume_after_update") is True and list((tmp_path / "backups").glob("agent-*.db"))
    assert "Start at login" not in c.get("/settings").text


def test_welcome_page_sets_environment_once(tmp_path):
    import threading
    import time
    import urllib.parse
    import urllib.request

    from sc_activity_agent.welcome import wait_for_env
    s = Store(tmp_path)
    port = 18999
    t = threading.Thread(target=wait_for_env, args=(s, port), daemon=True)
    t.start()
    for _ in range(40):
        try:
            assert b"Production" in urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
            break
        except OSError:
            time.sleep(0.25)
    urllib.request.urlopen(f"http://127.0.0.1:{port}/choose", urllib.parse.urlencode({"env": "sb2"}).encode())
    t.join(15)
    assert s.get("env") == "sb2" and s.get("port") == port


def test_setup_shows_checkin_permission_request_and_status(tmp_path):
    s, c = client(tmp_path)
    s.put("subscriber_id", 2014917582)
    c.post("/connections/add", data={"side": "provider", "name": "SydeTech", "client_id": "c", "client_secret": "x", "provider_id": "2000078685"})
    c.post("/connections/1/users", data={"username": "pu", "password": "pw"})
    t = c.get("/setup").text
    assert "Not confirmed yet" in t and "Subscriber ID 2014917582 with Provider ID 2000078685 (SydeTech)" in t and "SB2" in t
    s.log(ts=1, role="provider", user="pu", action="check_in", method="POST", path="/workorders/1/universalCheckIn", http=403)
    assert "Blocked (error 804)" in c.get("/setup").text and "Check-in is blocked for SydeTech" in c.get("/dashboard").text
    s.log(ts=2, role="provider", user="pu", action="check_in", method="POST", path="/workorders/2/universalCheckIn", http=200)
    t = c.get("/setup").text
    assert "Confirmed" in t and "Please link" not in t and "Check-in is blocked" not in c.get("/dashboard").text
