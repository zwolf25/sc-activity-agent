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
    s.db.execute("INSERT INTO users VALUES(1,1,'sub',?, '',NULL)", (s.enc("pw"),))
    s.db.execute("INSERT INTO roles VALUES('*','subscriber_note','[1]','single')")
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
