"""B-119: Demo cleanup."""
import datetime as dt
import random
import re

from fastapi.testclient import TestClient

from sc_activity_agent import caps, cleanup, demo_cleanup as demo
from sc_activity_agent.client import ScError
from sc_activity_agent.handlers import Runtime
from sc_activity_agent.store import Store
from sc_activity_agent.web.app import create_app

NOW = dt.datetime(2026, 11, 27, 16, tzinfo=dt.timezone.utc).timestamp()   # 11:00 in New York
NIGHT = dt.datetime(2026, 11, 28, 3, tzinfo=dt.timezone.utc).timestamp()   # 22:00 in New York
OLD, NEW = "2025-01-01T00:00:00Z", "2026-11-20T00:00:00Z"
LATER = "2026-12-30T00:00:00Z"
SUB = 5


def wo(i, status="OPEN", ext="", created=OLD, updated=OLD, scheduled=OLD, loc=10):
    return {"Id": i, "LocationId": loc, "CallDate": created, "UpdatedDate": updated, "ScheduledDate": scheduled,
            "Status": {"Primary": status, "Extended": ext}, "Provider": {"Name": "ACME"}}


def proposal(i, w, status="Open", created=OLD):
    return {"Id": i, "CreatedDate": created, "Status": {"Primary": status, "ModifiedDate": OLD}, "WorkOrder": w and {**w, "LocationId": 0}}


def invoice(i, wo_id, status="OPEN", posted=OLD):
    return {"Id": i, "WoTrackingNumber": wo_id, "PostedDate": posted, "UpdatedDate": OLD, "Status": status}


class FakeApp:
    """Answers the OData lists with the same Id keyset and Id-list filters the module sends."""

    def __init__(self, wos=(), proposals=(), invoices=(), protected=()):
        self.wos, self.proposals, self.invoices, self.protected = list(wos), list(proposals), list(invoices), set(protected)
        self.writes, self.fail = [], {}
        self.paused = lambda: False

    @staticmethod
    def _page(rows, flt):
        ids = {int(x) for x in re.findall(r"Id eq (\d+)", flt)}
        if ids:
            return [r for r in rows if r["Id"] in ids]
        after = int(re.search(r"Id gt (\d+)", flt).group(1))
        return sorted((r for r in rows if r["Id"] > after), key=lambda r: r["Id"])[:50]

    def call(self, user, method, path, params=None, body=None, **kw):
        flt = (params or {}).get("$filter", "")
        if method != "GET":
            if self.paused():
                raise ScError(0, "paused", path)
            for key, err in self.fail.items():
                if key in path:
                    raise err
            self.writes.append((method, path, params, body, kw.get("action")))
            return None
        if path == "/odata/locations":
            return {"value": [{"Id": 10, "StoreId": "HQ", "SubscriberId": SUB}]}
        if path == "/odata/workorders":
            if "Labels/any" in flt:
                return {"value": [{"Id": r["Id"]} for r in self._page([{"Id": i} for i in self.protected], flt)]}
            return {"value": self._page(self.wos, flt)}
        if path == "/odata/proposals":
            return {"value": self._page(self.proposals, flt)}
        if path == "/odata/invoices":
            return {"value": self._page(self.invoices, flt)}
        n = int(path.rsplit("/", 1)[1])
        if path.startswith("/invoices/"):
            return next(i for i in self.invoices if i["Id"] == n)
        return {**next(w for w in self.wos if w["Id"] == n), "LocationId": 0}


def setup(tmp_path, env="prod", **data):
    s = Store(tmp_path)
    s.put("env", env)
    s.put("tz", "America/New_York")
    s.put("subscriber_id", SUB)
    s.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c','x',NULL)")
    s.db.execute("INSERT INTO users(id,conn_id,username,password,can_do) VALUES(1,1,'sub',?,"
                 "'[\"subscriber_note\",\"proposal_decide\",\"invoice_decide\"]')", (s.enc("pw"),))
    s.db.execute("INSERT INTO locations(store_id,db_id,subscriber_id,name,lat,lon,tz) VALUES('HQ',10,?,'HQ',1,2,'America/New_York')", (SUB,))
    s.db.execute("INSERT INTO work_orders(id, sc_id, location, trade, state, created_at) VALUES(1, 7, 'HQ', 'HVAC', 'active', 0)")
    s.db.commit()
    app = FakeApp(**data)
    rt = Runtime(s, {1: app}, random.Random(1))
    return s, app, rt


def previewed(s, rt, app, at=NOW):
    assert demo.start_preview(s, 4, "do not touch", clock=lambda: at) == ""
    demo.preview(s, rt, clock=lambda: at, api=demo.Api(s, rt, demo.FAST_RATE))
    return s.db.execute("SELECT * FROM demo_cleanup_items ORDER BY id").fetchall()


def work(s, rt, at=NOW, engine=None):
    demo.session(s, rt, engine, clock=lambda: at, api=demo.Api(s, rt, demo.FAST_RATE))


def go(s, rt, app, mode="now", **kw):
    """preview, then confirm"""
    previewed(s, rt, app)
    assert demo.start_run(s, True, mode, clock=lambda: NOW, **kw) == ""


def states(s):
    return {(r["kind"], r["rid"]): r["state"] for r in s.db.execute("SELECT * FROM demo_cleanup_items")}


def test_preview_applies_every_skip_rule_and_never_writes(tmp_path):
    wos = [wo(1), wo(2, created=NEW), wo(7), wo(3), wo(4, scheduled=LATER), wo(5, updated=NEW), wo(6, loc=99),
           wo(8, "COMPLETED", "CONFIRMED"), wo(9, "COMPLETED", "PENDING CONFIRMATION")]
    s, app, rt = setup(tmp_path, wos=wos, protected=[3],
                       proposals=[proposal(101, wo(1)), proposal(102, wo(7)), proposal(103, wo(3)), proposal(104, None)],
                       invoices=[invoice(201, 1), invoice(202, 7), invoice(203, 3)])
    items = previewed(s, rt, app)
    assert {(i["kind"], i["rid"], i["action"]) for i in items} == {
        ("proposal", 101, "reject"), ("invoice", 201, "reject"), ("wo", 1, "cancel"), ("wo", 9, "confirm")}
    assert demo.job(s)["skips"] == {"created or picked up by the agent": 3, "has the protect label": 3, "scheduled in the future": 1,
                                    "updated in the last 30 days": 1, "not this Subscriber, or no linked work order": 2}
    assert not app.writes


def test_each_action_writes_the_right_call_in_order(tmp_path):
    wos = [wo(1), wo(2, "IN PROGRESS", "ON SITE"), wo(3, "COMPLETED", "PENDING CONFIRMATION"), wo(4, "COMPLETED", "PENDING REFRIGERANT USE"),
           wo(5, "COMPLETED", ""), wo(6, "COMPLETED", "PENDING COMPLIANCE DETAILS")]
    s, app, rt = setup(tmp_path, wos=wos, proposals=[proposal(101, wo(1))], invoices=[invoice(201, 2)])
    go(s, rt, app)
    work(s, rt)
    assert demo.job(s)["state"] == "done" and set(states(s).values()) == {"done"}
    paths = [p for _, p, *_ in app.writes]
    assert paths.index("/proposals/101/reject") < paths.index("/invoices/201/reject") < paths.index("/workorders/1/status")
    assert paths.index("/workorders/4/UpdateWorkOrderLeakInspectionInfo") < paths.index("/workorders/4/status")
    sent = {p: (params, body) for _, p, params, body, _ in app.writes}
    assert sent["/proposals/101/reject"][0] == {"useProposalAlertEmails": "false"} and sent["/proposals/101/reject"][1]["RejectReasonCodeId"] == 7
    assert sent["/invoices/201/reject"][0] == {"comments": demo.NOTE, "isNotifyProvider": "false"}
    status = lambda i: sent[f"/workorders/{i}/status"][1]["Status"]["Extended"]
    assert [status(i) for i in range(1, 7)] == ["CANCELED", "CANCELED", "CONFIRMED", "CONFIRMED", "CONFIRMED", "CONFIRMED"]
    assert len(paths) == len(set(paths))
    assert all(a.startswith("demo_") for *_, a in app.writes)


def test_changes_after_the_preview_are_skipped(tmp_path):
    wos = [wo(i) for i in range(1, 15)]
    s, app, rt = setup(tmp_path, wos=wos)
    previewed(s, rt, app)
    app.wos[0] = wo(1, "COMPLETED", "CONFIRMED")
    app.protected = {2}
    app.wos[2] = wo(3, scheduled=LATER)
    app.wos[3] = wo(4, "OPEN", "", updated=NEW)   # our own rejects move UpdatedDate, so this must not skip
    assert demo.start_run(s, True, "now", clock=lambda: NOW) == ""
    work(s, rt)
    got = states(s)
    assert [got[("wo", i)] for i in (1, 2, 3, 4)] == ["skipped", "skipped", "skipped", "done"]


def test_guards_environment_subscriber_confirmation_and_expiry(tmp_path):
    s, app, rt = setup(tmp_path, env="sb2", wos=[wo(1)])
    assert "Production" in demo.start_preview(s, 4, "x")
    s.put("env", "prod")
    assert demo.start_preview(s, 61, "x")
    s.put("subscriber_id", None)
    assert "Connections" in demo.start_preview(s, 4, "x")
    s.put("subscriber_id", SUB)
    assert demo.start_run(s, True, clock=lambda: NOW) == "Run a preview first."
    previewed(s, rt, app)
    assert demo.start_run(s, False, clock=lambda: NOW) == "Tick the box to confirm."
    assert "24 hours" in demo.start_run(s, True, clock=lambda: NOW + demo.EXPIRES + 1)
    s.put("subscriber_id", 999)
    assert "changed" in demo.start_run(s, True, clock=lambda: NOW)
    s.put("subscriber_id", SUB)
    assert demo.start_run(s, True, clock=lambda: NOW) == ""
    demo.halt(s)
    assert demo.start_run(s, True, clock=lambda: NOW + 9 * demo.EXPIRES) == ""   # a started job can always resume


def test_nightly_job_waits_for_the_window_keeps_its_limit_and_finishes_by_itself(tmp_path):
    s, app, rt = setup(tmp_path, wos=[wo(i) for i in range(100, 125)])
    go(s, rt, app, "nightly", limit=10)
    assert demo.due(s, lambda: NOW) is None
    work(s, rt)   # outside the window: nothing happens
    assert not app.writes and demo.due(s, lambda: NIGHT) == "session"
    work(s, rt, NIGHT)
    assert len(app.writes) == 10 and demo.job(s)["state"] == "scheduled"
    assert demo.due(s, lambda: NIGHT + 600) is None   # this night is used up
    assert demo.due(s, lambda: NIGHT + 86400) == "session"
    work(s, rt, NIGHT + 86400)
    work(s, rt, NIGHT + 2 * 86400)
    assert len(app.writes) == 25 and demo.job(s)["state"] == "done"
    assert len({p for _, p, *_ in app.writes}) == 25
    assert demo.due(s, lambda: NIGHT + 3 * 86400) is None


def test_night_window_may_cross_midnight(tmp_path):
    s, _, _ = setup(tmp_path)
    j = {"start": "20:00", "end": "06:00"}
    at = lambda h, d=27: dt.datetime(2026, 11, d, h + 5, tzinfo=dt.timezone.utc).timestamp()
    assert demo.night_of(s, j, at(18)) is None
    assert demo.night_of(s, j, at(2)) == "2026-11-26"
    assert demo.night_of(s, j, at(6)) is None
    assert demo.minutes("20:00", "06:00") == 600


def test_stop_and_pause_leave_items_pending_and_resume_does_not_repeat(tmp_path):
    s, app, rt = setup(tmp_path, wos=[wo(i) for i in range(100, 130)])
    go(s, rt, app)
    s.put("paused_at", NOW)
    work(s, rt)
    assert not app.writes and demo.due(s, lambda: NOW) is None
    s.put("paused_at", None)
    demo.halt(s)
    assert demo.due(s, lambda: NOW) is None
    assert demo.start_run(s, True, "now", limit=5, clock=lambda: NOW) == ""
    work(s, rt)
    assert len(app.writes) == 5 and demo.job(s)["state"] == "stopped"
    assert demo.start_run(s, True, "now", clock=lambda: NOW) == ""
    work(s, rt)
    assert len(app.writes) == len({p for _, p, *_ in app.writes}) == 30 and demo.job(s)["state"] == "done"


def test_ten_errors_stop_the_job_but_refused_records_do_not(tmp_path):
    s, app, rt = setup(tmp_path, wos=[wo(i) for i in range(100, 140)])
    go(s, rt, app)
    app.fail = {"/status": ScError(400, '{"ErrorCodes":[921],"ErrorCode":921,"ErrorMessage":"Cannot update invoiced work order."}')}
    s.put("demo_job", {**demo.job(s), "limit": 0})
    work(s, rt)
    assert demo.counts(s)["skipped"] == 40 and demo.job(s)["state"] == "done"
    app.fail = {"/status": ScError(500, "boom")}
    s.db.execute("UPDATE demo_cleanup_items SET state='pending' WHERE state='skipped'")
    s.put("demo_job", {**demo.job(s), "state": "running"})
    work(s, rt)
    assert demo.job(s)["state"] == "error" and demo.counts(s) == {"pending": 30, "done": 0, "skipped": 0, "error": 10, "total": 40}


def test_rejected_sign_in_stops_at_once_and_network_loss_keeps_items(tmp_path):
    s, app, rt = setup(tmp_path, wos=[wo(i) for i in range(100, 120)])
    go(s, rt, app, "nightly")
    app.fail = {"/status": TimeoutError("slow")}
    work(s, rt, NIGHT)
    assert demo.counts(s)["pending"] == 20 and demo.job(s)["state"] == "scheduled" and demo.due(s, lambda: NIGHT + 60) is None
    app.fail = {"/status": ScError(400, "Username or password rejected", "token")}
    work(s, rt, NIGHT + 86400)
    assert demo.job(s)["state"] == "error" and demo.counts(s)["pending"] == 20 and demo.counts(s)["error"] == 0


def test_fast_mode_pauses_the_agent_only_while_working(tmp_path):
    s, app, rt = setup(tmp_path, wos=[wo(i) for i in range(100, 120)])
    go(s, rt, app, "nightly", fast=True)
    seen = []

    class Engine:
        def pause(self):
            s.put("paused_at", 123.0)

        def resume(self, policy):
            seen.append(policy)
            s.put("paused_at", None)
    real = app.call

    def call(user, method, path, *a, **k):
        if method == "PUT":
            seen.append(s.get("paused_at"))
        return real(user, method, path, *a, **k)
    app.call = call
    work(s, rt, NIGHT, Engine())
    assert demo.job(s)["state"] == "done" and seen[0] == 123.0 and seen[-1] == "catch_up" and s.get("paused_at") is None


def test_demo_calls_do_not_count_toward_the_daily_limit(tmp_path):
    s, _, _ = setup(tmp_path)
    for action in ("demo_cancel", "demo_list", "cancel", None):
        s.log(action=action, method="GET", path="/x", http=200, ts=NOW)
    assert caps.used(s, NOW)["calls_per_day"] == 2


def test_daily_sweep_waits_while_demo_cleanup_works(tmp_path, monkeypatch):
    s, _, rt = setup(tmp_path)
    s.put("cleanup", {"sweep": "cancel"})
    monkeypatch.setattr(demo, "live", lambda: True)
    assert cleanup.sweep(s, rt, clock=lambda: NOW) == [] and s.get("last_sweep") is None


def test_web_page_is_production_only_and_drives_the_job(tmp_path):
    s, app, rt = setup(tmp_path, env="sb2", wos=[wo(i) for i in range(1, 16)])
    web = TestClient(create_app(s, rt=rt))
    assert web.get("/demo-cleanup").status_code == 404
    assert web.post("/demo-cleanup/preview", data={"months": 4}).status_code == 404
    assert "/demo-cleanup" not in web.get("/cleanup").text
    s.put("env", "prod")
    assert "/demo-cleanup" in web.get("/cleanup").text
    assert "1. Preview (reads only" in web.get("/demo-cleanup").text
    web.post("/demo-cleanup/preview", data={"months": 4, "protect": ""})
    assert "Building the preview" in web.get("/demo-cleanup").text
    demo.preview(s, rt, clock=__import__("time").time, api=demo.Api(s, rt, demo.FAST_RATE))
    page = web.get("/demo-cleanup").text
    assert "Run the cleanup" in page and 'name="subscriber_id"' not in page and "ilot" not in page
    s.db.execute("UPDATE demo_cleanup_items SET location='=1+1'")
    s.db.commit()
    assert "Every night until done" in web.get("/demo-cleanup").text
    assert "'=1+1" in web.get("/demo-cleanup/items.csv").text
    web.post("/demo-cleanup/run", data={"understood": "1", "mode": "nightly"})
    assert demo.job(s)["state"] == "scheduled" and demo.job(s)["limit"] == 0
    assert "Scheduled every night" in web.get("/demo-cleanup").text
    web.post("/demo-cleanup/stop")
    assert demo.job(s)["state"] == "stopped"
