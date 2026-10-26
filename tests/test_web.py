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
