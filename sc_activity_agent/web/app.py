"""FastAPI console. Server-rendered Jinja pages and plain forms (post/redirect/get), localhost only."""
import json
import re
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import cleanup as cleanup_mod
from .. import PACKAGED, __version__, autostart, planner, status, update
from .. import locations as locations_mod
from ..alerts import EVENTS, Alerts, AlertError
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


def gap_text(g, z):
    """Readable offline notice: local times, how long, and what the agent did about it."""
    a, b = (datetime.fromtimestamp(g[k], z) for k in ("start", "end"))
    mins = max(1, round((g["end"] - g["start"]) / 60))
    span = f"{mins} min" if mins < 120 else f"{mins / 60:.0f} h"
    fmt = "%a %b %d, %H:%M"
    moved = f"{g['steps']} scheduled steps were moved forward to make up for it." if g["steps"] else "No scheduled steps were affected."
    return f"The agent was not running from {a.strftime(fmt)} to {b.strftime(fmt)} ({span}), for example while the computer slept or the app was updated. {moved}"


def create_app(store, engine=None, rt=None):
    app = FastAPI(title="SC Activity Agent")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    db = store.db

    def page(request, name, **ctx):
        failed = db.execute("SELECT COUNT(*) FROM steps WHERE state='failed'").fetchone()[0]
        base = dict(request=request, nav=NAV, here=name, env=store.get("env"), version=__version__, packaged=PACKAGED,
                    paused=store.get("paused_at") is not None, failed=failed,
                    port=store.get("port"), twin_port=store.get("twin_port"), setup=setup_checks(), update=update.pending(store))
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

    def pair_status():
        """Check-in permission per Provider: ok after a successful check-in, blocked after a 403 (error 804), else not tried yet."""
        sub, env = store.get("subscriber_id") or "<Subscriber ID>", "Production" if store.get("env") == "prod" else "SB2"
        out = []
        for c in db.execute("SELECT id,name,provider_id FROM connections WHERE side='provider' ORDER BY id"):
            last = db.execute("SELECT http FROM api_log WHERE role='provider' AND path LIKE '%universalCheckIn' AND user IN "
                              "(SELECT username FROM users WHERE conn_id=?) ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
            state = "pending" if not last else "ok" if 200 <= (last[0] or 0) < 300 else "blocked" if last[0] == 403 else "pending"
            pid = c["provider_id"] or "<Provider ID>"
            out.append(dict(name=c["name"], state=state, request=(
                f"Please link Subscriber ID {sub} with Provider ID {pid} ({c['name']}) for API work in {env} and enable XML check-in/out "
                "(and GPS check-in/out if a radius is wanted) for this pair.")))
        return out

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
        return page(request, "setup", pairs=pair_status())

    @app.get("/dashboard")
    def dashboard(request: Request, page_no: int = Query(1, alias="page"), hide_done: str = "", hide_skipped: str = "", f: str = ""):
        hide_skipped = hide_skipped or ("" if f else "1")  # f marks a submitted filter form, so unchecked means off
        tz = store.get("tz", "America/New_York")
        rows, total, pages, cur = status.week(db, tz, hide_done=bool(hide_done), hide_skipped=bool(hide_skipped), page=page_no)
        z = ZoneInfo(tz)
        week = [dict(r, when=datetime.fromtimestamp(r["due_at"], z).strftime("%a %b %d, %H:%M"), detail=status.detail(r["kind"], json.loads(r["payload"]))) for r in rows]
        return page(request, "dashboard", stages=status.by_stage(db), week=week, total=total, pages=pages, cur=cur, hide_done=bool(hide_done), hide_skipped=bool(hide_skipped),
                    gaps=[dict(g, i=i, text=gap_text(g, z)) for i, g in enumerate(store.get("gaps", [])) if not g["acked"]],
                    blocked=[p["name"] for p in pair_status() if p["state"] == "blocked"])

    @app.post("/gap/dismiss-all")
    def dismiss_all_gaps():
        store.put("gaps", [dict(g, acked=True) for g in store.get("gaps", [])])
        return RedirectResponse("/dashboard", 303)

    @app.post("/gap/{i}/dismiss")
    def dismiss_gap(i: int):
        gaps = store.get("gaps", [])
        if 0 <= i < len(gaps):
            gaps[i]["acked"] = True   # the shift already happened; dismissing only hides the notice
            store.put("gaps", gaps)
        return RedirectResponse("/dashboard", 303)

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

    def to_peer(path):
        """Desktop app: one app update or quit covers both instances, so pass the call on to the other one if it is running."""
        from ..launcher import port_open, twin_dir
        peer = twin_dir(store.dir) if store.get("env") != "sb2" else store.dir.parent
        try:
            port = int((peer / "port").read_text())
        except (OSError, ValueError):
            return
        if port_open(port):
            try:
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}?cascade=0", method="POST"), timeout=10).read()
            except OSError:
                pass   # a peer that does not answer must not hold up this one

    @app.post("/update/prepare")
    def prepare_update(cascade: str = "1"):
        """Desktop app only: pause and back up the database right before the shell installs a new version."""
        if not PACKAGED:
            return JSONResponse({"ok": False}, 404)
        if cascade != "0":
            to_peer("/update/prepare")
        was_paused = store.get("paused_at") is not None
        store.put("resume_after_update", not was_paused)
        if not was_paused:
            store.put("paused_at", time.time())
        update.backup(store)
        return {"ok": True}

    @app.post("/shutdown")
    def shutdown(cascade: str = "1"):
        """Desktop app only: the shell asks the agent to stop when the app quits or restarts for an update."""
        if not PACKAGED:
            return JSONResponse({"ok": False}, 404)
        if cascade != "0":
            to_peer("/shutdown")
        threading.Timer(0.3, os._exit, args=(0,)).start()
        return {"ok": True}

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
        from ..cli import free_port
        from ..launcher import ensure_running, twin_dir
        from ..store import Store
        d = twin_dir(store.dir)
        twin = Store(d)
        if not twin.get("env"):
            twin.put("env", "sb2")
            twin.put("port", free_port(8081) if PACKAGED else 8081)
            twin.put("twin_port", store.get("port"))
        if not ensure_running(d, twin.get("port")):
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
        if "hours_start" in vals and "hours_end" in vals:
            vals["hours_end"] = max(vals["hours_end"], vals["hours_start"] + 1)
        store.put("behavior", vals)
        for k in ("hours_start", "hours_end"):
            if k in vals:
                store.put(k, int(vals[k]))
        return RedirectResponse("/behavior", 303)

    @app.get("/locations")
    def locations(request: Request, q: str = "", msg: str = ""):
        locs = db.execute("SELECT * FROM locations ORDER BY store_id").fetchall()
        r1 = store.get("rank1", {})
        con = [{"location": k, "trade": t} for k, v in sorted(r1.items()) for t in v["trades"]]
        skipped = [{"location": k, "trades": v["skipped"]} for k, v in sorted(r1.items()) if v.get("skipped")]
        checked = max((v["at"] for v in r1.values()), default=None)
        have = {l["store_id"] for l in locs}
        pool = [c for c in store.get("locations_cache", []) if c["store_id"] not in have]
        ql = q.strip().lower()
        if ql:
            pool = [c for c in pool if ql in f"{c['store_id']} {c['name']} {c['city']} {c['state']}".lower()]
        return page(request, "locations", locs=locs, contracts=con, pool=pool[:50], pool_n=len(pool), q=q, msg=msg, skipped=skipped,
                    checked=datetime.fromtimestamp(checked, ZoneInfo(store.get('tz', 'America/New_York'))).strftime('%b %d %H:%M') if checked else None,
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

    @app.post("/locations/resync")
    def resync_locations():
        from ..creator import Creator
        n = 0
        try:
            for loc in db.execute("SELECT * FROM locations WHERE enabled=1").fetchall():
                Creator(store, rt, rt.rng).resync(loc)
                n += 1
        except ScError as e:
            return RedirectResponse(f"/locations?msg=Could not read contracts: {e.body or e}", 303)
        return RedirectResponse(f"/locations?msg=Contracts re-read for {n} location(s)", 303)

    def add_loc(store_id):
        c = next((c for c in store.get("locations_cache", []) if c["store_id"] == store_id), None)
        if not c or c["lat"] is None or c["lon"] is None:
            return False
        if db.execute("SELECT 1 FROM locations WHERE store_id=?", (store_id,)).fetchone():
            return True   # already added: keep its enabled flag
        db.execute("INSERT INTO locations(store_id,db_id,subscriber_id,name,lat,lon,tz) VALUES(?,?,?,?,?,?,?)",
                   (c["store_id"], c["db_id"], c["subscriber_id"], c["name"], c["lat"], c["lon"], c["tz"]))
        db.commit()
        return True

    @app.post("/locations/add")
    def add_location(store_id: str = Form(...)):
        if not add_loc(store_id):
            return RedirectResponse("/locations?msg=Location not found or has no coordinates. Reload the list", 303)
        return RedirectResponse("/locations", 303)

    @app.post("/locations/add-many")
    def add_locations(store_ids: list[str] = Form(default=[]), pasted: str = Form("")):
        """Ticked rows plus any store IDs pasted as a list or CSV (commas, spaces or lines)."""
        ids = list(dict.fromkeys([s for s in store_ids] + [s for s in re.split(r"[,;\s]+", pasted) if s]))
        bad = [s for s in ids if not add_loc(s)]
        msg = f"Added {len(ids) - len(bad)} location(s)." + (f" Not found or no coordinates: {', '.join(bad[:10])}{'...' if len(bad) > 10 else ''}." if bad else "")
        return RedirectResponse(f"/locations?msg={msg}", 303)

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
                ids = [int(v) for v in form.getlist(key)[:1] if v]
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
        prev = store.get("cleanup_preview")
        if prev:
            prev = {**prev, "when": datetime.fromtimestamp(prev["at"], ZoneInfo(store.get("tz", "America/New_York"))).strftime("%b %d %H:%M")}
        return page(request, "cleanup", rows=rows, msg=msg, cfg=cleanup_mod.settings(store), prev=prev, runstate=store.get("cleanup_run"))

    @app.post("/cleanup/preview")
    def cleanup_preview(days: int = Form(14), protect: str = Form("do not touch"), sweep: str = Form("off")):
        if not rt:
            return RedirectResponse("/cleanup?msg=The agent is not running", 303)
        store.put("cleanup", {"days": max(1, min(days, 3650)), "protect": protect.strip(), "sweep": sweep if sweep in ("off", "cancel", "finish") else "off"})
        try:
            r = cleanup_mod.preview(store, rt)
        except ScError as e:
            return RedirectResponse(f"/cleanup?msg=Could not read work orders: {e.body or e}", 303)
        return RedirectResponse(f"/cleanup?msg=Found {len(r['items'])} work order(s) to cancel", 303)

    @app.post("/cleanup/now")
    def cleanup_now(confirm: str = Form("")):
        if not (rt and confirm) or (store.get("cleanup_run") or {}).get("running"):
            return RedirectResponse("/cleanup?msg=Tick the box to confirm (or a clean-up is already running)", 303)
        threading.Thread(target=cleanup_mod.now, args=(store, rt), daemon=True).start()
        return RedirectResponse("/cleanup?msg=Clean-up started. Refresh this page for progress", 303)

    @app.post("/cleanup/run")
    def cleanup_run(confirm: str = Form("")):
        run = store.get("cleanup_run") or {}
        if not (rt and confirm and (store.get("cleanup_preview") or {}).get("items")):
            return RedirectResponse("/cleanup?msg=Tick the box to confirm, after a preview that found work orders", 303)
        if run.get("running"):
            return RedirectResponse("/cleanup?msg=A clean-up is already running", 303)
        threading.Thread(target=cleanup_mod.run, args=(store, rt), daemon=True).start()
        return RedirectResponse("/cleanup?msg=Clean-up started. Refresh this page for progress", 303)

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
    def settings(request: Request, msg: str = ""):
        al = Alerts(store)
        return page(request, "settings", login=autostart.enabled(store.dir, store.get("env")),
                    policy=store.get("resume_policy", "catch_up"), msg=msg, al=al.cfg, token_set=bool(store.get("alerts_token")),
                    events=EVENTS, alert_error=store.get("alert_error"), other_env="SB2" if store.get("env") == "prod" else "Production")

    @app.post("/alerts/token")
    def alerts_token(token: str = Form(...)):
        al = Alerts(store)
        try:
            bot = al.call(token.strip(), "getMe")
        except AlertError as e:
            return RedirectResponse(f"/settings?msg=Telegram did not accept that token: {e}", 303)
        store.put("alerts_token", store.enc(token.strip()))
        al.save(bot=bot.get("username", ""), chat_id=None, chat_name="", enabled=False)
        return RedirectResponse(f"/settings?msg=Bot @{bot.get('username')} found. Now open it in Telegram, press Start, then click Find my chat.", 303)

    @app.post("/alerts/find-chat")
    def alerts_find_chat():
        al = Alerts(store)
        if not al.token():
            return RedirectResponse("/settings?msg=Paste the bot token first.", 303)
        try:
            ups = al.call(al.token(), "getUpdates", timeout=0, allowed_updates=["message"])
        except AlertError as e:
            return RedirectResponse(f"/settings?msg={e}", 303)
        msgs = [u["message"] for u in ups if u.get("message")]
        if not msgs:
            return RedirectResponse("/settings?msg=No message found yet. Open your bot in Telegram, press Start, then click Find my chat again.", 303)
        chat = msgs[-1]["chat"]
        name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or str(chat["id"])
        al.save(chat_id=chat["id"], chat_name=name)
        return RedirectResponse(f"/settings?msg=Found chat with {name}. Send a test message to confirm.", 303)

    @app.post("/alerts/test")
    def alerts_test():
        al = Alerts(store)
        try:
            al.raw("Test message from SC Activity Agent. Alerts are working.", [[("Dismiss", "d")]])
            store.put("alert_error", None)
            return RedirectResponse("/settings?msg=Test message sent. Check Telegram.", 303)
        except (AlertError, TypeError) as e:
            return RedirectResponse(f"/settings?msg=Could not send: {e}", 303)

    @app.post("/alerts/save")
    async def alerts_save(request: Request):
        f = await request.form()
        Alerts(store).save(enabled=f.get("enabled") == "on", buttons=f.get("buttons") == "on",
                           events={k: f.get(f"ev_{k}") == "on" for k in EVENTS})
        return RedirectResponse("/settings?msg=Alert settings saved.", 303)

    @app.post("/alerts/remove")
    def alerts_remove():
        store.db.execute("DELETE FROM settings WHERE key IN ('alerts','alerts_token','alerts_offset','alert_sent','alert_times')")
        store.db.commit()
        return RedirectResponse("/settings?msg=Telegram alerts removed.", 303)

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
