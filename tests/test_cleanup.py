import random

from fastapi.testclient import TestClient

from sc_activity_agent import cleanup
from sc_activity_agent.client import ScError
from sc_activity_agent.handlers import Runtime
from sc_activity_agent.store import Store
from sc_activity_agent.web.app import create_app

NOW = 1_761_566_400   # 2025-10-27
OLD, NEW = "2025-09-01T00:00:00Z", "2025-10-26T00:00:00Z"


def wo(i, upd=OLD, status="OPEN", labels=()):
    return {"Id": i, "Status": {"Primary": status}, "UpdatedDate": upd, "Trade": "HVAC", "Provider": {"Name": "ACME"},
            "Labels": [{"Id": n, "Label": lab} for n, lab in enumerate(labels)] or [{"Id": 0}]}


class FakeApp:
    def __init__(self, listing, protected=()):
        self.listing, self.protected, self.calls, self.fail = listing, protected, [], None
        self.paused = lambda: False

    def call(self, user, method, path, params=None, body=None, **kw):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/odata/workorders":
            return {"value": [{"Id": i} for i in self.protected]}
        if method == "GET" and path.startswith("/odata/locations"):
            return {"value": self.listing}
        if method == "GET":
            return next(w for w in self.listing if f"/{w['Id']}" == path[-len(str(w["Id"])) - 1:])
        if self.fail:
            raise self.fail
        return {}


def setup(tmp_path, listing, protected=()):
    s = Store(tmp_path)
    s.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c','x',NULL)")
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(1,1,'sub',?,'[\"subscriber_note\"]')", (s.enc("pw"),))
    s.db.execute("INSERT INTO locations(store_id,db_id,subscriber_id,name,lat,lon,tz) VALUES('HQ',10,5,'HQ',1,2,'America/New_York')")
    s.db.execute("INSERT INTO work_orders(id, sc_id, location, trade, state, created_at) VALUES(1, 7, 'HQ', 'HVAC', 'active', 0)")
    s.db.commit()
    app = FakeApp(listing, protected)
    return s, app, Runtime(s, {1: app}, random.Random(1))


def test_preview_skips_agent_wos_and_protect_label(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1), wo(7), wo(3)], protected=[3])
    r = cleanup.preview(s, rt, clock=lambda: NOW)
    assert [i["id"] for i in r["items"]] == [1] and r["protected"] == 1
    assert not [c for c in app.calls if c[0] == "PUT"]   # preview never writes


def test_run_cancels_as_subscriber_and_skips_wos_changed_since_preview(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1), wo(2)])
    cleanup.preview(s, rt, clock=lambda: NOW)
    app.listing = [wo(1), wo(2, upd=NEW)]   # WO 2 got activity after the preview
    st = cleanup.run(s, rt, clock=lambda: NOW)
    puts = [c for c in app.calls if c[0] == "PUT"]
    assert st["cancelled"] == 1 and st["skipped"] == 1 and len(puts) == 1
    assert puts[0][1] == "/workorders/1/status" and puts[0][2]["Status"] == {"Primary": "COMPLETED", "Extended": "CANCELED"}
    assert s.db.execute("SELECT state FROM work_orders").fetchone()[0] == "active"   # agent's own table untouched


def test_run_stops_when_paused_and_records_errors(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1), wo(2)])
    cleanup.preview(s, rt, clock=lambda: NOW)
    app.fail = ScError(0, "paused", "")
    st = cleanup.run(s, rt, clock=lambda: NOW)
    assert st["cancelled"] == 0 and len(st["errors"]) == 1 and not st["running"]


def test_console_flow_needs_preview_and_confirm(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1)])
    c = TestClient(create_app(s, rt=rt))
    assert "Tick the box" in c.post("/cleanup/run", data={"confirm": "1"}).text   # no preview yet
    c.post("/cleanup/preview", data={"days": "14", "protect": "do not touch"})
    assert "<b>1</b> work order(s) found" in c.get("/cleanup").text
    assert "Tick the box" in c.post("/cleanup/run", data={}).text                 # preview but no tick
    assert not [x for x in app.calls if x[0] == "PUT"]


def test_finish_gives_our_providers_wos_a_plan_and_cancels_the_rest(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1), wo(2)])
    s.db.execute("INSERT INTO connections VALUES(2,'provider','P','c','x',77)")
    s.db.commit()
    app.listing[0]["Provider"] = {"Id": 77, "Name": "ours"}
    app.listing[1]["Provider"] = {"Id": 99, "Name": "theirs"}
    cleanup.preview(s, rt, clock=lambda: NOW)
    st = cleanup.run(s, rt, clock=lambda: NOW, finish=True)
    assert st["finished"] == 1 and st["cancelled"] == 1
    kinds = [r[0] for r in s.db.execute("SELECT kind FROM steps WHERE wo_id=(SELECT id FROM work_orders WHERE sc_id=1) ORDER BY seq")]
    assert kinds == ["check_in", "check_out", "review", "invoice_submit", "invoice_decide"]
    assert [c[1] for c in app.calls if c[0] == "PUT"] == ["/workorders/2/status"]


def test_sweep_runs_once_a_day_on_weekdays_only_when_on(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1)])
    assert cleanup.sweep(s, rt, clock=lambda: NOW) == []                      # off by default
    s.put("cleanup", {"sweep": "cancel"})
    assert cleanup.sweep(s, rt, clock=lambda: NOW + 5 * 86400) == []          # Saturday
    assert "cancelled 1" in cleanup.sweep(s, rt, clock=lambda: NOW)[0][1]
    assert cleanup.sweep(s, rt, clock=lambda: NOW + 3600) == []               # already ran today


def test_now_selects_every_idle_wo_without_review(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1), wo(2), wo(3, upd=NEW)])
    st = cleanup.now(s, rt, clock=lambda: NOW)
    assert st["cancelled"] == 2 and [c[1] for c in app.calls if c[0] == "PUT"] == ["/workorders/1/status", "/workorders/2/status"]


def test_finish_is_never_automatic_on_prod_and_saving_does_not_start_a_sweep(tmp_path):
    s, app, rt = setup(tmp_path, [wo(1)])
    s.put("env", "prod")
    s.put("cleanup", {"sweep": "finish"})
    assert cleanup.sweep(s, rt, clock=lambda: NOW) == []   # finish on prod acts as off
    c = TestClient(create_app(s, rt=rt))
    c.post("/cleanup/auto", data={"sweep": "cancel", "confirm": "1"})
    assert s.get("cleanup")["sweep"] == "cancel" and cleanup.sweep(s, rt, clock=lambda: s.get("last_sweep") + 60) == []
    c.post("/cleanup/auto", data={"sweep": "finish", "confirm": "1"})
    assert s.get("cleanup")["sweep"] == "cancel"            # refused on prod


def test_finish_plan_adds_the_availability_exchange_only_when_the_eta_is_inside_the_emergency_hours(tmp_path):
    s, app, rt = setup(tmp_path, [])
    s.db.execute("INSERT INTO connections VALUES(2,'provider','P','c','x',77)")
    s.db.commit()
    iso = lambda h: __import__("datetime").datetime.fromtimestamp(NOW + h * 3600, __import__("datetime").timezone.utc).isoformat()
    for i, h in ((11, 3), (12, 30), (13, -5)):
        cleanup.finish_plan(s, rt, {**wo(i), "ScheduledDate": iso(h), "CallDate": iso(-1), "_location": "HQ"}, NOW)
    s.put("behavior", {"emergency_hours": 2})   # call date to ETA is 4 hours: over this threshold
    cleanup.finish_plan(s, rt, {**wo(14), "ScheduledDate": iso(3), "CallDate": iso(-1), "_location": "HQ"}, NOW)
    kinds = lambda i: [r[0] for r in s.db.execute("SELECT kind FROM steps WHERE wo_id=(SELECT id FROM work_orders WHERE sc_id=?) ORDER BY seq", (i,))]
    assert kinds(11)[:3] == ["sub_note", "prov_note", "check_in"]
    assert kinds(12)[0] == kinds(13)[0] == kinds(14)[0] == "check_in"


def test_pickup_plans_only_recent_wos_of_ours_in_our_trades_and_can_be_turned_off(tmp_path):
    from sc_activity_agent import pickup
    s, app, rt = setup(tmp_path, [wo(i, upd=NEW, status=st) for i, st in ((1, "OPEN"), (2, "OPEN"), (3, "OPEN"), (4, "IN PROGRESS"), (5, "OPEN"), (7, "OPEN"))])
    s.db.execute("INSERT INTO connections VALUES(2,'provider','P','c','x',77)")
    s.db.commit()
    for w in app.listing:
        w["Provider"] = {"Id": 99 if w["Id"] == 2 else 77}
    app.listing[2]["Labels"] = [{"Id": 1, "Label": "Do Not Touch"}]   # protect label, any case
    app.listing[4]["Trade"] = "PLUMBING"
    creator = type("C", (), {"our_trades": lambda self, loc: {"HVAC"}})()
    s.put("pickup", {"on": False})
    assert pickup.tick(s, rt, creator, clock=lambda: NOW) == []
    s.put("pickup", {"on": True})
    out = pickup.tick(s, rt, creator, clock=lambda: NOW)
    assert sorted(i for i, _ in out) == [1, 4]   # not 2 (foreign provider), 3 (protected), 5 (trade), 7 (the agent's own)
    kinds = lambda sc: [r[0] for r in s.db.execute("SELECT kind FROM steps WHERE wo_id=(SELECT id FROM work_orders WHERE sc_id=?) ORDER BY seq", (sc,))]
    assert kinds(1)[:2] == ["accept", "check_in"] and kinds(4)[0] == "check_in"
    assert not [c for c in app.calls if c[0] == "PUT"]   # planning writes nothing itself
    assert pickup.tick(s, rt, creator, clock=lambda: NOW + 60) == []   # once an hour
