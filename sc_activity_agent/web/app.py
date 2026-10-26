"""FastAPI console. Server-rendered Jinja pages and plain forms (post/redirect/get), localhost only."""
import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, autostart, planner, status, update
from .. import locations as locations_mod
from ..client import ScApp, ScError
from ..handlers import ACTION, cancel_wo

ACTIONS = sorted(set(ACTION.values()))

HERE = Path(__file__).parent
NAV = [("dashboard", "Dashboard"), ("behavior", "Behavior"), ("locations", "Locations"), ("connections", "Connections"),
       ("roles", "Roles"), ("audit", "Audit log"), ("errors", "Errors"), ("cleanup", "Cleanup"), ("settings", "Settings")]
# key, label, hint, min, max, step
SLIDERS = [("wo_per_month", "Work orders per month", "Per enabled location, weekdays only", 0, 600, 5),
           ("proposal_rate", "Proposal rate %", "Share of WOs that get a proposal", 0, 100, 1),
           ("proposal_approval", "Proposal approval %", "Rest are rejected", 0, 100, 1),
           ("invoice_approval", "Invoice approval %", "Rest are rejected and resubmitted", 0, 100, 1),
           ("sub_notes", "Subscriber notes per WO", "Average", 0, 8, 0.5),
           ("prov_notes", "Provider notes per WO", "Average", 0, 8, 0.5),
           ("late_checkin", "Late check-in %", "Provider arrives after the scheduled date", 0, 100, 1),
           ("late_days", "Average days late", "", 1, 7, 1),
           ("time_on_site", "Time on site factor", "Multiplier on check-in to check-out time", 0.5, 2, 0.1),
           ("first_time_fix", "First-time fix %", "Rest need 2 or 3 visits", 0, 100, 1),
           ("hours_start", "Activity starts (hour)", "Local time at the location", 0, 23, 1),
           ("hours_end", "Activity ends (hour)", "", 1, 24, 1)]


def create_app(store, engine=None, rt=None):
    app = FastAPI(title="SC Activity Agent")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    db = store.db

    def page(request, name, **ctx):
        failed = db.execute("SELECT COUNT(*) FROM steps WHERE state='failed'").fetchone()[0]
        base = dict(request=request, nav=NAV, here=name, env=store.get("env"), version=__version__,
                    paused=store.get("paused_at") is not None, failed=failed,
                    port=store.get("port"), twin_port=store.get("twin_port"), setup=setup_checks(), update=(store.get("update_check") or {}).get("found"))
        return tpl.TemplateResponse(request, f"{name}.html", {**base, **ctx})

    def setup_checks():
        n = lambda sql: db.execute(sql).fetchone()[0]
        has = lambda side: n(f"SELECT COUNT(*) FROM connections c WHERE side='{side}' AND EXISTS(SELECT 1 FROM users u WHERE u.conn_id=c.id)") > 0
        return [("Subscriber connection with a user", has("subscriber"), "/connections"),
                ("Subscriber ID and issue list dashboard chosen", bool(store.get("subscriber_id")) and bool(store.get("dashboard_chosen")), "/connections"),
                ("Provider connection with a user", has("provider"), "/connections"),
                ("At least one location", n("SELECT COUNT(*) FROM locations") > 0, "/locations"),
                ("Roles mapped", n("SELECT COUNT(*) FROM roles") > 0, "/roles"),
                ("Behavior reviewed", bool(store.get("behavior")), "/behavior")]

    def sub_app(uid=None):
        """(ScApp, (username, password)) for a Subscriber user, or None when no Subscriber user exists."""
        r = db.execute("SELECT u.*, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id "
                       "WHERE c.side='subscriber' ORDER BY u.id LIMIT 1").fetchone()
        if not r:
            return None
        return ScApp(store.get("env"), r["client_id"], store.dec(r["client_secret"]), store=store, role="subscriber"), \
            (r["username"], store.dec(r["password"]))

    @app.get("/")
    def home(request: Request):
        if not all(c[1] for c in setup_checks()):
            return RedirectResponse("/setup", 303)
        return RedirectResponse("/dashboard", 303)

    @app.get("/setup")
    def setup(request: Request):
        return page(request, "setup")

    @app.get("/dashboard")
    def dashboard(request: Request):
        done, todo = status.today(db, store.get("tz", "America/New_York"))
        kinds = sorted(set(done) | set(todo))
        return page(request, "dashboard", stages=status.by_stage(db), done=done, todo=todo, kinds=kinds,
                    calls_hour=store.count_calls_since(time.time() - 3600), gaps=[g for g in store.get("gaps", []) if not g["acked"]])

    @app.get("/connections")
    def connections(request: Request, msg: str = ""):
        conns = [dict(c, users=[dict(u) for u in db.execute("SELECT id,username,label FROM users WHERE conn_id=?", (c["id"],))])
                 for c in db.execute("SELECT id,side,name,client_id,provider_id FROM connections ORDER BY side DESC, id")]
        return page(request, "connections", conns=conns, msg=msg, dashboards=store.get("dashboards_cache", []),
                    dashboard=store.get("dashboard_id", 3151), subscriber_id=store.get("subscriber_id", ""))

    @app.post("/dashboards/load")
    def load_dashboards(subscriber_id: int = Form(...)):
        store.put("subscriber_id", subscriber_id)
        sa = sub_app()
        if not sa:
            return RedirectResponse("/connections?msg=Add a Subscriber user first", 303)
        try:
            heads = sa[0].call(sa[1], "GET", f"/api/subscribers/{subscriber_id}/issuelist/headers", action="dashboards")["Headers"]
        except ScError as e:
            return RedirectResponse(f"/connections?msg={e.body or e}", 303)
        store.put("dashboards_cache", [{"id": h["DashboardId"], "name": h["Name"]} for h in heads])
        return RedirectResponse("/connections?msg=Dashboards loaded", 303)

    @app.post("/dashboards/select")
    def select_dashboard(dashboard_id: int = Form(...)):
        store.put("dashboard_id", dashboard_id)
        store.put("dashboard_chosen", True)
        return RedirectResponse("/connections?msg=Dashboard saved", 303)

    @app.post("/connections/add")
    def add_connection(side: str = Form(...), name: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...),
                       provider_id: str = Form("")):
        if side == "subscriber" and db.execute("SELECT 1 FROM connections WHERE side='subscriber'").fetchone():
            return RedirectResponse("/connections?msg=Only one Subscriber connection is allowed", 303)
        db.execute("INSERT INTO connections(side,name,client_id,client_secret,provider_id) VALUES(?,?,?,?,?)",
                   (side, name, client_id.strip(), store.enc(client_secret.strip()), int(provider_id) if provider_id.strip() else None))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/users")
    def add_user(cid: int, username: str = Form(...), password: str = Form(...), label: str = Form("")):
        db.execute("INSERT INTO users(conn_id,username,password,label) VALUES(?,?,?,?)", (cid, username.strip(), store.enc(password), label))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/delete")
    def del_connection(cid: int):
        db.execute("DELETE FROM connections WHERE id=?", (cid,))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/test")
    def test_user(uid: int):
        u = db.execute("SELECT u.*, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()
        try:
            ScApp(store.get("env"), u["client_id"], store.dec(u["client_secret"])).token(u["username"], store.dec(u["password"]))
            msg = f"{u['username']}: connection OK"
        except ScError as e:
            msg = f"{u['username']}: {e.body if e.body else e}"
        return RedirectResponse(f"/connections?msg={msg}", 303)

    @app.post("/users/{uid}/delete")
    def del_user(uid: int):
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.get("/audit")
    def audit(request: Request, q: str = "", failed: str = ""):
        like = f"%{q}%"
        rows = db.execute("SELECT * FROM api_log WHERE (?='' OR user LIKE ? OR path LIKE ? OR action LIKE ? OR CAST(sc_wo AS TEXT) LIKE ?) "
                          "AND (?='' OR http>=400 OR http IS NULL OR http=0) ORDER BY id DESC LIMIT 200",
                          (q, like, like, like, like, failed)).fetchall()
        return page(request, "audit", rows=rows, q=q, failed=failed)

    @app.get("/errors")
    def errors(request: Request):
        rows = db.execute("SELECT s.*, w.sc_id FROM steps s JOIN work_orders w ON w.id=s.wo_id WHERE s.state='failed' ORDER BY s.due_at").fetchall()
        return page(request, "errors", rows=rows, create_errors=store.get("create_errors", [])[::-1])

    @app.post("/steps/{sid}/{action}")
    def step_action(sid: int, action: str):
        if action == "retry":
            db.execute("UPDATE steps SET state='pending', attempts=0, due_at=? WHERE id=?", (time.time(), sid))
        elif action == "skip":
            db.execute("UPDATE steps SET state='skipped' WHERE id=?", (sid,))
        db.commit()
        return RedirectResponse("/errors", 303)

    @app.post("/update")
    def run_update():
        found = update.check(store, force=True)
        if found:
            subprocess.Popen([sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(store.dir), "update", "--yes"],
                             start_new_session=True)
        return RedirectResponse("/dashboard", 303)

    @app.post("/test-instance")
    def test_instance():
        """Production instance only: create (first time) and start the SB2 twin in <data dir>-sb2, then go to it."""
        from ..launcher import ensure_running
        from ..store import Store
        twin_dir = store.dir.with_name(store.dir.name + "-sb2")
        twin = Store(twin_dir)
        if not twin.get("env"):
            twin.put("env", "sb2")
            twin.put("port", 8081)
            twin.put("twin_port", store.get("port"))
        if not ensure_running(twin_dir, twin.get("port")):
            return RedirectResponse("/connections?msg=The SB2 instance did not start. See agent.log in its data folder.", 303)
        return RedirectResponse(f"http://127.0.0.1:{twin.get('port')}/dashboard", 303)

    @app.post("/pause")
    def pause():
        engine.pause() if engine else store.put("paused_at", time.time())
        return RedirectResponse("/dashboard", 303)

    @app.post("/resume")
    def resume():
        engine.resume(store.get("resume_policy", "catch_up")) if engine else store.put("paused_at", None)
        return RedirectResponse("/dashboard", 303)

    @app.get("/behavior")
    def behavior(request: Request):
        cur = {**planner.DEFAULTS, **store.get("behavior", {})}
        return page(request, "behavior", sliders=SLIDERS, cur=cur)

    @app.post("/behavior")
    async def save_behavior(request: Request):
        form = await request.form()
        vals = {k: float(form[k]) for k, *_ in SLIDERS if k in form}
        store.put("behavior", vals)
        for k in ("hours_start", "hours_end"):
            if k in vals:
                store.put(k, int(vals[k]))
        return RedirectResponse("/behavior", 303)

    @app.get("/locations")
    def locations(request: Request, q: str = "", msg: str = ""):
        locs = db.execute("SELECT * FROM locations ORDER BY store_id").fetchall()
        con = [{"location": k, "trade": t} for k, v in sorted(store.get("rank1", {}).items()) for t in v["trades"]]
        have = {l["store_id"] for l in locs}
        pool = [c for c in store.get("locations_cache", []) if c["store_id"] not in have]
        ql = q.strip().lower()
        if ql:
            pool = [c for c in pool if ql in f"{c['store_id']} {c['name']} {c['city']} {c['state']}".lower()]
        return page(request, "locations", locs=locs, contracts=con, pool=pool[:50], pool_n=len(pool), q=q, msg=msg,
                    loaded=store.get("locations_cache") is not None)

    @app.post("/locations/load")
    def load_locations():
        sa = sub_app()
        if not sa:
            return RedirectResponse("/locations?msg=Add a Subscriber user first on Connections", 303)
        try:
            rows = locations_mod.fetch(lambda path, params: sa[0].call(sa[1], "GET", path, params, action="locations"),
                                       store.get("subscriber_id"))
        except ScError as e:
            return RedirectResponse(f"/locations?msg=Could not load locations: {e.body or e}", 303)
        store.put("locations_cache", rows)
        return RedirectResponse(f"/locations?msg=Loaded {len(rows)} locations", 303)

    @app.post("/locations/add")
    def add_location(store_id: str = Form(...)):
        c = next((c for c in store.get("locations_cache", []) if c["store_id"] == store_id), None)
        if not c or c["lat"] is None or c["lon"] is None:
            return RedirectResponse("/locations?msg=Location not found or has no coordinates. Reload the list", 303)
        db.execute("INSERT OR REPLACE INTO locations(store_id,db_id,subscriber_id,name,lat,lon,tz) VALUES(?,?,?,?,?,?,?)",
                   (c["store_id"], c["db_id"], c["subscriber_id"], c["name"], c["lat"], c["lon"], c["tz"]))
        db.commit()
        return RedirectResponse("/locations", 303)

    @app.post("/locations/{sid}/toggle")
    def toggle_location(sid: str):
        db.execute("UPDATE locations SET enabled=1-enabled WHERE store_id=?", (sid,))
        db.commit()
        return RedirectResponse("/locations", 303)

    @app.post("/locations/{sid}/delete")
    def del_location(sid: str):
        db.execute("DELETE FROM locations WHERE store_id=?", (sid,))
        db.commit()
        return RedirectResponse("/locations", 303)

    @app.get("/roles")
    def roles(request: Request):
        users = [dict(u) for u in db.execute("SELECT u.id, u.username, c.side, c.name cname FROM users u JOIN connections c ON c.id=u.conn_id ORDER BY c.side DESC, u.id")]
        scopes = ["*"] + [r["store_id"] for r in db.execute("SELECT store_id FROM locations ORDER BY store_id")]
        cur = {(r["location"], r["action"]): json.loads(r["user_ids"]) for r in db.execute("SELECT * FROM roles")}
        return page(request, "roles", users=users, scopes=scopes, actions=ACTIONS, cur=cur)

    @app.post("/roles")
    async def save_roles(request: Request):
        form = await request.form()
        for key in form:
            if key.count("|") == 1:
                loc, action = key.split("|")
                ids = [int(v) for v in form.getlist(key) if v]
                if ids:
                    db.execute("INSERT INTO roles(location,action,user_ids) VALUES(?,?,?) ON CONFLICT(location,action) DO UPDATE SET user_ids=excluded.user_ids",
                               (loc, action, json.dumps(ids)))
                elif loc != "*":
                    db.execute("DELETE FROM roles WHERE location=? AND action=?", (loc, action))
        db.commit()
        return RedirectResponse("/roles", 303)

    @app.get("/cleanup")
    def cleanup(request: Request, msg: str = ""):
        rows = db.execute("SELECT * FROM work_orders ORDER BY created_at DESC LIMIT 500").fetchall()
        return page(request, "cleanup", rows=rows, msg=msg)

    @app.post("/cleanup/{wid}/cancel")
    def cancel(wid: int):
        wo = db.execute("SELECT * FROM work_orders WHERE id=?", (wid,)).fetchone()
        if wo and rt and wo["state"] != "cancelled":
            try:
                cancel_wo(rt, wo)
            except ScError as e:
                return RedirectResponse(f"/cleanup?msg={e.body or e}", 303)
        return RedirectResponse("/cleanup", 303)

    @app.get("/settings")
    def settings(request: Request):
        return page(request, "settings", login=autostart.enabled(store.dir, store.get("env")),
                    policy=store.get("resume_policy", "catch_up"))

    @app.post("/settings")
    def save_settings(resume_policy: str = Form(...), login: str = Form("off")):
        store.put("resume_policy", resume_policy)
        env = store.get("env")
        if login == "on" and not autostart.enabled(store.dir, env):
            autostart.enable(store.dir, env)
        elif login != "on" and autostart.enabled(store.dir, env):
            autostart.disable(store.dir, env)
        return RedirectResponse("/settings", 303)

    return app
