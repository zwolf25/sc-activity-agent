"""FastAPI console. Server-rendered Jinja pages and plain forms (post/redirect/get), localhost only."""
import json
import re
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import assets, caps, smoke
from .. import reset as reset_mod
from .. import cleanup as cleanup_mod
from .. import pickup as pickup_mod
from .. import __version__, autostart, awake, planner, status, update
from .. import locations as locations_mod
from ..alerts import EVENTS, Alerts, AlertError
from ..client import ScApp, ScError
from ..hints import ERROR_HINTS, hint
from .. import setupcheck
from ..handlers import ACTION, cancel_wo

# what a user can be set to do, by connection side: key, label (users.can_do stores the keys; they match handlers.ACTION values)
CAN_DO = {"subscriber": [("create_wo", "Create WOs"), ("subscriber_note", "Add notes"), ("review", "Review WOs"),
                         ("proposal_decide", "Decide proposals"), ("invoice_decide", "Decide and pay invoices")],
          "provider": [("accept", "Accept WOs"), ("provider_note", "Add notes"), ("check_in", "Check in"), ("check_out", "Check out"),
                       ("proposal_create", "Create proposals"), ("invoice_submit", "Submit invoices")]}

HERE = Path(__file__).parent
NAV = [("dashboard", "Dashboard"), ("behavior", "Behavior"), ("locations", "Locations"), ("connections", "Connections"),
       ("audit", "Audit log"), ("errors", "Errors"), ("cleanup", "Cleanup"), ("settings", "Settings")]
# key, label, hint, min, max, step
# Order = where the behavior first shows up in the WO flow, earliest first (create, accept, proposal, visits, review, invoice, payment), global settings last.
# A new slider goes in at its place in that flow, not at the end.
SLIDERS = [("wo_per_month", "Work orders per month", "Per enabled location, spread over the activity days", 0, 600, 5),
           ("photo_before", "Before photo on new WOs %", "Share of new work orders created with a photo of the problem, from the library for the trade", 0, 100, 1),
           ("asset_on_create", "WOs created with an asset %", "Share of new work orders created with a seeded asset on them, when the location has one for the issue's equipment (HVAC RTU, Generator, Electrical Panel, Exit Signs, Lighting, Water Heater, Backflow Preventer, Flushometer Valve)", 0, 100, 1),
           ("emergency_hours", "Treat as emergency up to (hours)", "A WO whose original ETA is at most this many hours after its call date gets the fast emergency plan; 0 = never", 0, 72, 1),
           ("sub_notes", "Subscriber notes per WO", "Average", 0, 8, 0.5),
           ("prov_notes", "Provider notes per WO", "Average", 0, 8, 0.5),
           ("decline", "Provider declines %", "The provider declines instead of accepting; the WO is cancelled 1 to 3 days later. Turn off auto-reassign for the trade (SC admin) or the WO moves to another provider", 0, 100, 1),
           ("reassign", "Reassign after a decline %", "Of the declines, the share the Subscriber moves to another provider with a contract for the trade at the location; the rest, and any with no such provider, are cancelled", 0, 100, 1),
           ("no_show", "Provider no-shows %", "The provider accepts but never arrives. The Subscriber notes it and moves the WO to another provider with a contract for the trade, or cancels it if none can take it", 0, 100, 1),
           ("reschedule", "Reschedules %", "The provider moves the scheduled date 1 to 3 business days later than the original date", 0, 100, 1),
           ("proposal_rate", "Proposal rate %", "Share of WOs that get a proposal", 0, 100, 1),
           ("proposal_approval", "Proposal approval %", "Rest are rejected", 0, 100, 1),
           ("late_checkin", "Late check-in %", "Provider arrives after the scheduled date", 0, 100, 1),
           ("asset_on_site", "Provider attaches an asset on site %", "Of the work orders created without an asset, the share where the provider attaches one between check-in and check-out: the asset for the issue's equipment, or any seeded asset in the WO's trade at the location", 0, 100, 1),
           ("late_days", "Average days late", "", 1, 7, 1),
           ("first_time_fix", "First-time fix %", "Rest need 2 or 3 visits", 0, 100, 1),
           ("time_on_site_hrs", "Average time on site (hours)", "Check-in to check-out per visit", 0.5, 8, 0.5),
           ("multi_tech", "Two-technician visits %", "Share of visits worked by 2 technicians (needs 2 check-in techs on the provider)", 0, 100, 1),
           ("photo_after", "After photo on closing note %", "Share of finished work orders where the provider posts a work-complete note with a photo of the finished work, from the same scene as the before photo", 0, 100, 1),
           ("star_rating", "Star rating on review %", "Share of reviews that carry a star rating. The rest are a plain confirm with a note. Unsatisfactory work % below splits the rated ones", 0, 100, 1),
           ("rework", "Unsatisfactory work % of rated reviews", "Share of rated reviews that get 1 or 2 stars and a comment (the rest get 3 to 5). The WO is marked Unsatisfactory; the WO goes back to In Progress, the provider returns onsite to finish, and the Subscriber reviews again", 0, 100, 1),
           ("invoice_rate_flaw", "Invoices with a wrong rate %", "The provider bills labor above the agreed rate. The Subscriber sees the rate flag, rejects, and the provider resubmits at the agreed rate", 0, 100, 1),
           ("invoice_hours_flaw", "Invoices billing extra hours %", "The provider bills more labor hours than the time on site. The Subscriber rejects, and the provider resubmits with the hours on site", 0, 100, 1),
           ("invoice_approval", "Invoice approval %", "Rest are rejected and resubmitted", 0, 100, 1),
           ("pay_days", "Average days to pay", "After the invoice is approved (30 = Net 30 terms)", 1, 90, 1),
           ("hours_start", "Activity starts (hour)", "Local time at the location", 0, 23, 1),
           ("hours_end", "Activity ends (hour)", "", 1, 24, 1)]


STAMP = "%a %b %d, %H:%M"   # the one date-time format every page uses, in the instance's time zone


def stamp(t, z):
    """Format an epoch or an ISO-8601 string (as ServiceChannel sends it, UTC with a Z) as STAMP in zone z."""
    d = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(z) if isinstance(t, str) else datetime.fromtimestamp(t, z)
    return d.strftime(STAMP)


def gap_text(g, z):
    """Readable offline notice: local times, how long, and what the agent did about it."""
    a, b = (datetime.fromtimestamp(g[k], z) for k in ("start", "end"))
    mins = max(1, round((g["end"] - g["start"]) / 60))
    span = f"{mins} min" if mins < 120 else f"{mins / 60:.0f} h"
    fmt = STAMP
    moved = f"{g['steps']} scheduled steps were moved forward to make up for it." if g["steps"] else "No scheduled steps were affected."
    return f"The agent was not running from {a.strftime(fmt)} to {b.strftime(fmt)} ({span}), for example while the computer slept or the app was updated. {moved}"


def error_groups(rows, tz):
    """B-79: failed steps with the same kind and the same error text (digits blurred) become one row with a count, the
    first and last due time, the WO ids and a hint for known causes."""
    groups = {}
    for r in rows:
        err = r["error"] or ""
        g = groups.setdefault((r["kind"], re.sub(r"\d{4,}", "#", err)), dict(kind=r["kind"], error=err, rows=[]))
        g["rows"].append(r)
    out = []
    for g in groups.values():
        rs = g["rows"]
        out.append(dict(kind=g["kind"], error=g["error"], count=len(rs), ids=[r["id"] for r in rs], wos=[r["sc_id"] for r in rs],
                        first=stamp(rs[0]["due_at"], tz), last=stamp(rs[-1]["due_at"], tz),
                        hint=hint(g["error"])))
    return sorted(out, key=lambda g: -g["count"])


def create_app(store, engine=None, rt=None):
    app = FastAPI(title="SC Activity Agent")
    busy = [0]   # requests in flight; only touched on the event loop thread

    @app.middleware("http")
    async def settle_after(request, call_next):
        """B-82: a request thread that leaves a transaction open blocks every writer. Commit it once no request is running."""
        busy[0] += 1
        try:
            return await call_next(request)
        finally:
            busy[0] -= 1
            if not busy[0]:
                store.settle_idle("AnyIO worker thread", "web request")

    def background(fn, *a):
        def go():
            try:
                fn(*a)
            finally:
                store.settle("clean-up thread")
        threading.Thread(target=go, daemon=True).start()
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    class _Db:   # request threads differ; resolve the calling thread's connection on every use
        def __getattr__(self, name):
            return getattr(store.db, name)
    db = _Db()

    def page(request, name, **ctx):
        failed = db.execute("SELECT COUNT(*) FROM steps WHERE state='failed'").fetchone()[0]
        base = dict(request=request, nav=NAV, here=name, env=store.get("env"), version=__version__,
                    paused=store.get("paused_at") is not None, failed=failed,
                    port=store.get("port"), twin_port=store.get("twin_port"), setup=setup_checks(), update=update.pending(store), update_busy=bool(update.in_progress(store)), dash_warn=(store.get("dash_check") or {}) if (store.get("dash_check") or {}).get("warn") else None, asset_todo=assets.unseeded(store), cap_hit=store.get("cap_hit") if store.get("paused_at") is not None else None)
        return tpl.TemplateResponse(request, f"{name}.html", {**base, **ctx})

    def missing_actions():
        """Actions nobody can do yet: the agent would stop on them."""
        have = {a for (cd,) in db.execute("SELECT can_do FROM users") for a in json.loads(cd)}
        sides = {r[0] for r in db.execute("SELECT DISTINCT side FROM connections")}
        return [a for side in sides for a, _ in CAN_DO[side] if a not in have]

    def no_tech():
        """Provider connections with no user who can check in."""
        return [c["name"] for c in db.execute("SELECT id,name FROM connections WHERE side='provider'")
                if not db.execute("SELECT 1 FROM users WHERE conn_id=? AND EXISTS (SELECT 1 FROM json_each(can_do) WHERE value='check_in')", (c["id"],)).fetchone()]

    def setup_checks():
        """(label, done, link, help, required). help says what to do when the step is open. A step that is not required
        (it can only be confirmed by the first creation pass) shows on the checklist but does not hold back the Dashboard."""
        n = lambda sql: db.execute(sql).fetchone()[0]
        has = lambda side: n(f"SELECT COUNT(*) FROM connections c WHERE side='{side}' AND EXISTS(SELECT 1 FROM users u WHERE u.conn_id=c.id)") > 0
        no_pid = [r[0] for r in db.execute("SELECT name FROM connections WHERE side='provider' AND provider_id IS NULL")]
        r1 = store.get("rank1", {})
        ranked = any(r1.get(r[0], {}).get("trades") for r in db.execute("SELECT store_id FROM locations WHERE enabled=1"))
        return [("Subscriber connection with a user", has("subscriber"), "/connections",
                 "Add the Subscriber integration app (Client ID and secret) and a Subscriber user. Both come from ServiceChannel; the app must be registered in this environment.", True),
                ("Subscriber ID and issue list dashboard chosen", bool(store.get("subscriber_id")) and bool(store.get("dashboard_chosen")), "/connections",
                 "On Connections, enter the numeric Subscriber ID and load the dashboards, then pick the issue list dashboard the agent draws problems from.", True),
                ("Provider connection with a user", has("provider"), "/connections",
                 "Add a Provider integration app and a Provider user. A Provider that is Rank 1 for a trade at your location receives the Work Orders.", True),
                ("Every Provider has its numeric Provider ID", not no_pid, "/connections",
                 "Delete and re-add " + ", ".join(no_pid) + " with its Provider ID. Without it the agent cannot read the Provider's Rank 1 trades, so it creates nothing." if no_pid else "", True),
                ("At least one enabled location", n("SELECT COUNT(*) FROM locations WHERE enabled=1") > 0, "/locations",
                 "On Locations, add a store ID and keep it enabled.", True),
                ("Every action has a user", not missing_actions(), "/connections",
                 "On Connections, tick every action on at least one user: " + ", ".join(missing_actions()) + "." if missing_actions() else "", True),
                ("Every Provider has a check-in tech", not no_tech(), "/connections",
                 "On Connections, give a user of " + ", ".join(no_tech()) + " the check-in action." if no_tech() else "", True),
                ("Behavior reviewed", bool(store.get("behavior")), "/behavior",
                 "Open Behavior, review the rates and press Save.", True),
                ("A Provider you control is Rank 1 at an enabled location", ranked, "/locations",
                 "Confirmed by the first creation pass. If it stays open: in ServiceChannel Contracts, rank one of your Providers 1 for a trade at the location, or add a location where it is Rank 1, then press 'Re-read contracts' on Locations. Until then every create fails with 'no eligible trade'.", False)]

    def pair_status():
        """Check-in permission per Provider: ok after a successful check-in, blocked after a 403 with error 804 (no pair permission),
        failed after any other refusal (its reason is shown, the pair may be fine), else not tried yet."""
        sub, env = store.get("subscriber_id") or "<Subscriber ID>", "Production" if store.get("env") == "prod" else "SB2"
        out = []
        for c in db.execute("SELECT id,name,provider_id FROM connections WHERE side='provider' ORDER BY id"):
            last = db.execute("SELECT http, detail FROM api_log WHERE role='provider' AND path LIKE '%universalCheckIn' AND user IN "
                              "(SELECT username FROM users WHERE conn_id=?) ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
            http, why = (last[0] or 0, last[1] or "") if last else (0, "")
            state = "ok" if 200 <= http < 300 else "blocked" if http == 403 and "804" in why else "failed" if http >= 400 else "pending"
            pid = c["provider_id"] or "<Provider ID>"
            out.append(dict(name=c["name"], state=state, why=why[:200], request=(
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
        if not all(c[1] for c in setup_checks() if c[4]):
            return RedirectResponse("/setup", 303)
        return RedirectResponse("/dashboard", 303)

    @app.get("/setup")
    def setup(request: Request):
        chk = store.get("setup_check") or {}
        return page(request, "setup", pairs=pair_status(), check=dict(chk, when=stamp(chk["at"], ZoneInfo(store.get("tz", "America/New_York")))) if chk.get("at") else chk)

    @app.get("/dashboard")
    def dashboard(request: Request, page_no: int = Query(1, alias="page"), hide_done: str = "", hide_skipped: str = "", f: str = "", w: str = ""):
        # f marks a submitted filter form, so unchecked means off; a plain visit uses the last choice (both hidden at first)
        if f:
            store.put("dashboard_hide", {"done": bool(hide_done), "skipped": bool(hide_skipped)})
        else:
            saved_hide = store.get("dashboard_hide") or {}
            hide_done, hide_skipped = saved_hide.get("done", True), saved_hide.get("skipped", True)
        tz = store.get("tz", "America/New_York")
        # the choice is remembered, but only for the week it was made in: a new week starts on "this week" again
        mon = status.week_start(tz)
        saved = store.get("dashboard_week") or {}
        if w in ("this", "next"):
            store.put("dashboard_week", {"w": w, "monday": mon.date().isoformat()})
        else:
            w = saved.get("w", "this") if saved.get("monday") == mon.date().isoformat() else "this"
        shown = mon + timedelta(days=7 if w == "next" else 0)
        rows, total, pages, cur = status.week(db, tz, hide_done=bool(hide_done), hide_skipped=bool(hide_skipped), page=page_no, weeks_ahead=int(w == "next"))
        z = ZoneInfo(tz)
        week = [dict(r, when=stamp(r["due_at"], z), detail=status.detail(r["kind"], json.loads(r["payload"]))) for r in rows]
        return page(request, "dashboard", stages=status.by_stage(db), week=week, total=total, pages=pages, cur=cur, w=w, span=f"{shown:%b %d} to {shown + timedelta(days=6):%b %d}", hide_done=bool(hide_done), hide_skipped=bool(hide_skipped),
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
        conns = [dict(c, users=[dict(u) for u in db.execute("SELECT id,username,label,can_do FROM users WHERE conn_id=?", (c["id"],))])
                 for c in db.execute("SELECT id,side,name,client_id,provider_id FROM connections ORDER BY side DESC, id")]
        for c in conns:
            for u in c["users"]:
                u["can_do"] = json.loads(u["can_do"])
            c["actions"] = CAN_DO[c["side"]]
        return page(request, "connections", conns=conns, idle=[a for a in missing_actions()], techless=no_tech(), msg=msg, dashboards=store.get("dashboards_cache", []),
                    dashboard=store.get("dashboard_id", 3151), subscriber_id=store.get("subscriber_id", ""))

    @app.post("/dashboards/load")
    def load_dashboards(subscriber_id: int = Form(...)):
        store.put("subscriber_id", subscriber_id)
        sa = sub_app()
        if not sa:
            return RedirectResponse("/connections?msg=Add a Subscriber user first", 303)
        try:
            heads = sa[0].call(sa[1], "GET", f"/api/subscribers/{subscriber_id}/issuelist/headers", action="dashboards")["Headers"]
        except (ScError, OSError) as e:
            why = "Could not reach ServiceChannel: " + str(e) if isinstance(e, OSError) else str(e.body or e)
            return RedirectResponse("/connections?msg=" + quote(f"Could not load dashboards: {why}. Check the Subscriber ID and that the Subscriber user can see issue lists. {hint(why)}".strip()), 303)
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
        pid = provider_id.strip()
        if side == "provider" and not pid.isdigit():
            return RedirectResponse("/connections?msg=" + quote("Enter the Provider ID as a number (find it in ServiceChannel under the Provider's profile). The agent needs it to read which trades this Provider is Rank 1 for."), 303)
        if pid and not pid.isdigit():
            return RedirectResponse("/connections?msg=" + quote("The Provider ID must be a number."), 303)
        db.execute("INSERT INTO connections(side,name,client_id,client_secret,provider_id) VALUES(?,?,?,?,?)",
                   (side, name, client_id.strip(), store.enc(client_secret.strip()), int(pid) if pid else None))
        db.commit()
        store.put("rank1", {})   # a new provider can be Rank 1 somewhere; re-read at the next creation pass
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/users")
    def add_user(cid: int, username: str = Form(...), password: str = Form(...), label: str = Form("")):
        c = db.execute("SELECT client_id, client_secret FROM connections WHERE id=?", (cid,)).fetchone()
        try:   # log in first: a user that cannot sign in is not saved
            ScApp(store.get("env"), c["client_id"], store.dec(c["client_secret"])).token(username.strip(), password)
        except (ScError, OSError) as e:
            why = f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)
            return RedirectResponse("/connections?msg=" + quote(f"{username.strip()} was not added: {why}. {hint(why)}".strip()), 303)
        side = db.execute("SELECT side FROM connections WHERE id=?", (cid,)).fetchone()["side"]
        first = not db.execute("SELECT 1 FROM users WHERE conn_id=?", (cid,)).fetchone()   # the first user on a connection can do everything
        db.execute("INSERT INTO users(conn_id,username,password,label,can_do) VALUES(?,?,?,?,?)",
                   (cid, username.strip(), store.enc(password), label, json.dumps([a for a, _ in CAN_DO[side]] if first else [])))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/can-do")
    async def set_can_do(uid: int, request: Request):
        side = db.execute("SELECT c.side FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()["side"]
        ok = {a for a, _ in CAN_DO[side]}
        picked = [a for a in (await request.form()).getlist("can_do") if a in ok]
        db.execute("UPDATE users SET can_do=? WHERE id=?", (json.dumps(picked), uid))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/label")
    def set_label(uid: int, label: str = Form("")):
        db.execute("UPDATE users SET label=? WHERE id=?", (label.strip(), uid))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/delete")
    def del_connection(cid: int):
        db.execute("DELETE FROM connections WHERE id=?", (cid,))
        db.commit()
        if rt is not None:
            rt.apps.pop(cid, None)
        store.put("rank1", {})
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/test")
    def test_user(uid: int):
        u = db.execute("SELECT u.*, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()
        try:
            ScApp(store.get("env"), u["client_id"], store.dec(u["client_secret"])).token(u["username"], store.dec(u["password"]))
            msg = f"{u['username']}: connection OK"
        except (ScError, OSError) as e:
            why = f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)
            msg = f"{u['username']}: {why}. {hint(why)}".strip()
        return RedirectResponse("/connections?msg=" + quote(msg), 303)

    @app.post("/users/{uid}/delete")
    def del_user(uid: int):
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.get("/audit")
    def audit(request: Request, q: str = "", failed: str = ""):
        like = f"%{q}%"
        rows = db.execute("SELECT l.*, (SELECT label FROM users u WHERE u.username=l.user LIMIT 1) AS label FROM api_log l "
                          "WHERE (?='' OR user LIKE ? OR path LIKE ? OR action LIKE ? OR CAST(sc_wo AS TEXT) LIKE ?) "
                          "AND (?='' OR http>=400 OR http IS NULL OR http=0) ORDER BY id DESC LIMIT 200",
                          (q, like, like, like, like, failed)).fetchall()
        z = ZoneInfo(store.get("tz", "America/New_York"))
        return page(request, "audit", rows=[dict(r, when=stamp(r["ts"], z)) for r in rows], q=q, failed=failed)

    @app.get("/stage")
    def stage_list(request: Request, s: str = ""):
        z = ZoneInfo(store.get("tz", "America/New_York"))
        rows = [dict(r, when=stamp(r["next_due"], z) if r["next_due"] else "") for r in status.in_stage(db, s)] if s in status.STAGES else []
        return page(request, "stage", title=s, rows=rows, known=s in status.STAGES)

    @app.get("/errors")
    def errors(request: Request):
        rows = db.execute("SELECT s.*, w.sc_id FROM steps s JOIN work_orders w ON w.id=s.wo_id WHERE s.state='failed' ORDER BY s.due_at").fetchall()
        tz = ZoneInfo(store.get("tz", "America/New_York"))
        return page(request, "errors", groups=error_groups(rows, tz), create_errors=[dict(e, hint=hint(e["error"]), when=stamp(e["at"], tz))
                                                    for e in store.get("create_errors", [])[::-1]])

    @app.post("/smoke")
    def save_smoke(on: str = Form("off"), now: str = Form("")):
        if store.get("env") == "sb2":   # the run creates a real WO: never on Production
            store.put("smoke", {**smoke.settings(store), "on": on == "on" or bool(now), "run_now": bool(now)})
        return RedirectResponse("/settings", 303)

    @app.post("/steps/group/{action}")
    async def group_action(action: str, request: Request):
        ids = [int(i) for i in (await request.form()).getlist("id")]
        if action in ("retry", "skip") and ids:
            marks = ",".join("?" * len(ids))
            if action == "retry":
                db.execute(f"UPDATE steps SET state='pending', attempts=0, due_at=? WHERE state='failed' AND id IN ({marks})", (time.time(), *ids))
            else:
                db.execute(f"UPDATE steps SET state='skipped' WHERE state='failed' AND id IN ({marks})", ids)
            db.commit()
        return RedirectResponse("/errors", 303)

    @app.post("/steps/{sid}/{action}")
    def step_action(sid: int, action: str):
        if action == "retry":
            db.execute("UPDATE steps SET state='pending', attempts=0, due_at=? WHERE id=?", (time.time(), sid))
        elif action == "skip":
            db.execute("UPDATE steps SET state='skipped' WHERE id=?", (sid,))
        db.commit()
        return RedirectResponse("/errors", 303)

    @app.post("/assets/dismiss")
    def assets_dismiss(request: Request):
        cfg = store.get("assets", {})
        cfg["dismissed"] = sorted({*cfg.get("dismissed", []), *(f"{sid}:{t}" for sid, ts in assets.unseeded(store) for t in ts)})
        store.put("assets", cfg)
        return RedirectResponse(request.headers.get("referer") or "/dashboard", 303)

    @app.post("/update")
    def run_update():
        if update.in_progress(store):   # a second click must not start a second installer
            return RedirectResponse("/updating", 303)
        found = update.check(store, force=True)
        if not found:
            return RedirectResponse("/dashboard", 303)
        store.put("update_status", {"state": "installing", "tag": found["tag"], "from": __version__, "at": time.time()})
        subprocess.Popen([sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(store.dir), "update", "--yes"],
                         start_new_session=True)
        return RedirectResponse("/updating", 303)

    @app.get("/updating")
    def updating(request: Request):
        return page(request, "updating", st=store.get("update_status") or {})

    @app.get("/api/update-status")
    def update_status():
        return {"version": __version__, **(store.get("update_status") or {})}

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
            twin.put("port", 8081)
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

    @app.post("/caps")
    async def save_caps(request: Request):
        form = await request.form()
        store.put("caps", {k: max(0, int(float(form.get(k) or 0))) for k in caps.DEFAULTS})
        return RedirectResponse("/settings", 303)

    @app.post("/behavior")
    async def save_behavior(request: Request):
        form = await request.form()
        vals = {k: float(form[k]) for k, *_ in SLIDERS if k in form}
        if "hours_start" in vals and "hours_end" in vals:
            vals["hours_end"] = max(vals["hours_end"], vals["hours_start"] + 1)
        days = sorted({int(d) for d in form.getlist("days") if d in list("0123456")}) or [0, 1, 2, 3, 4]   # at least one day, or nothing would ever run
        store.put("behavior", {**vals, "days": days})
        store.put("days", days)
        for k in ("hours_start", "hours_end"):
            if k in vals:
                store.put(k, int(vals[k]))
        return RedirectResponse("/behavior", 303)

    @app.get("/locations")
    def locations(request: Request, q: str = "", msg: str = ""):
        locs = db.execute("SELECT * FROM locations ORDER BY store_id").fetchall()
        r1 = store.get("rank1", {})
        seeded = {(r["location"], (r["trade"] or "").upper()): r["n"] for r in db.execute("SELECT location, trade, COUNT(*) n FROM assets GROUP BY location, trade")}
        con = [{"location": k, "trade": t, "assets": seeded.get((k, t.upper()), 0)} for k, v in sorted(r1.items()) for t in v["trades"]]
        skipped = [{"location": k, "trades": v["skipped"]} for k, v in sorted(r1.items()) if v.get("skipped")]
        checked = max((v["at"] for v in r1.values()), default=None)
        have = {l["store_id"] for l in locs}
        pool = [c for c in store.get("locations_cache", []) if c["store_id"] not in have]
        ql = q.strip().lower()
        if ql:
            pool = [c for c in pool if ql in f"{c['store_id']} {c['name']} {c['city']} {c['state']}".lower()]
        return page(request, "locations", locs=locs, contracts=con, pool=pool[:1000], pool_n=len(pool), q=q, msg=msg, skipped=skipped,
                    checked=stamp(checked, ZoneInfo(store.get('tz', 'America/New_York'))) if checked else None,
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
            return RedirectResponse("/locations?msg=" + quote(f"Could not load locations: {e.body or e}. Check the Subscriber ID on Connections."), 303)
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

    @app.get("/cleanup")
    def cleanup(request: Request, msg: str = ""):
        z = ZoneInfo(store.get("tz", "America/New_York"))
        rows = [dict(r, when=stamp(r["created_at"], z))
                for r in db.execute("SELECT * FROM work_orders ORDER BY created_at DESC LIMIT 500")]
        prev = store.get("cleanup_preview")
        if prev:
            prev = {**prev, "when": stamp(prev["at"], z), "items": [dict(i, when=stamp(i["updated"], z)) for i in prev["items"]]}
        return page(request, "cleanup", rows=rows, msg=msg, cfg=cleanup_mod.settings(store), env=store.get("env"), prev=prev, runstate=store.get("cleanup_run"))

    @app.post("/cleanup/preview")
    def cleanup_preview(days: int = Form(14), protect: str = Form("do not touch")):
        if not rt:
            return RedirectResponse("/cleanup?msg=The agent is not running", 303)
        store.put("cleanup", {**cleanup_mod.settings(store), "days": max(1, min(days, 3650)), "protect": protect.strip()})
        try:
            r = cleanup_mod.preview(store, rt)
        except ScError as e:
            return RedirectResponse(f"/cleanup?msg=Could not read work orders: {e.body or e}", 303)
        return RedirectResponse(f"/cleanup?msg=Found {len(r['items'])} work order(s) to cancel", 303)

    @app.post("/cleanup/auto")
    def cleanup_auto(sweep: str = Form("off"), confirm: str = Form("")):
        if sweep not in ("off", "cancel", "finish") or (sweep == "finish" and store.get("env") == "prod"):
            return RedirectResponse("/cleanup?msg=That choice is not allowed here", 303)
        if sweep != "off" and not confirm:
            return RedirectResponse("/cleanup?msg=Tick the box to confirm the daily choice", 303)
        store.put("cleanup", {**cleanup_mod.settings(store), "sweep": sweep})
        store.put("last_sweep", time.time())   # the first run is a day away, never minutes after saving
        return RedirectResponse(f"/cleanup?msg=Daily choice saved: {sweep}. First run in about a day", 303)

    @app.post("/cleanup/now")
    def cleanup_now(confirm: str = Form("")):
        if not (rt and confirm) or (store.get("cleanup_run") or {}).get("running"):
            return RedirectResponse("/cleanup?msg=Tick the box to confirm (or a clean-up is already running)", 303)
        background(cleanup_mod.now, store, rt)
        return RedirectResponse("/cleanup?msg=Clean-up started. Refresh this page for progress", 303)

    @app.post("/cleanup/run")
    def cleanup_run(confirm: str = Form("")):
        run = store.get("cleanup_run") or {}
        if not (rt and confirm and (store.get("cleanup_preview") or {}).get("items")):
            return RedirectResponse("/cleanup?msg=Tick the box to confirm, after a preview that found work orders", 303)
        if run.get("running"):
            return RedirectResponse("/cleanup?msg=A clean-up is already running", 303)
        background(cleanup_mod.run, store, rt)
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
        cur = {**planner.DEFAULTS, **store.get("behavior", {})}
        n = store.db.execute("SELECT COUNT(*) FROM locations WHERE enabled=1").fetchone()[0]
        expected = cur["wo_per_month"] * n / (30 * len(cur["days"]) / 7)   # WOs on an activity day, all enabled locations
        return page(request, "settings", caps=caps.limits(store), used=caps.used(store), expected=expected, locs=n,
                    smoke_ui=store.get("env") == "sb2", smoke=smoke.settings(store), smoke_last=store.get("smoke_last"), login=autostart.enabled(store.dir, store.get("env")),
                    awake_ui=awake.supported(), awake_on=store.get("keep_awake", True), check_on=store.get("status_check", True), pickup_on=pickup_mod.settings(store)["on"], checklist_on=store.get("checklists", {}).get("on", False),
                    policy=store.get("resume_policy", "catch_up"), msg=msg, al=al.cfg, token_set=bool(store.get("alerts_token")),
                    backups=[(n, s // 1024, stamp(t, ZoneInfo(store.get("tz", "America/New_York")))) for n, s, t in update.backups(store)],
                    events=EVENTS, alert_error=store.get("alert_error"), other_env="SB2" if store.get("env") == "prod" else "Production")

    @app.post("/check-update")
    def check_update():
        found = update.check(store, force=True)
        return RedirectResponse("/settings?msg=" + quote(f"Version {found['tag']} is available." if found else f"You are on the latest version ({__version__})."), 303)

    @app.get("/diagnostics", response_class=PlainTextResponse)
    def diagnostics():
        """What to paste into a support message: versions, state and the end of the log (no credentials are ever logged)."""
        log = store.dir / "agent.log"
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-60:]) if log.exists() else "(no agent.log)"
        return (f"agent {__version__}  env={store.get('env')}  paused={store.get('paused_at') is not None}\n"
                f"python {sys.version.split()[0]}  {platform.platform()}  port={store.get('port')}\n--- agent.log (last 60 lines)\n{tail}")

    @app.post("/backup")
    def backup_now():
        update.backup(store)
        return RedirectResponse("/settings?msg=Backed+up+the+database.", 303)

    @app.get("/reset")
    def reset_page(request: Request):
        n = lambda t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        counts = dict(connections=n("connections"), users=n("users"), locations=n("locations"), wos=n("work_orders"), steps=n("steps"), log=n("api_log"))
        return page(request, "reset", counts=counts, busy=reset_mod.busy(store))

    @app.post("/reset")
    def reset_do(confirm: str = Form(""), understood: str = Form("")):
        """Factory reset. Needs the typed word and the tick box, so a stray click or a replayed request does nothing."""
        if confirm.strip() != "RESET" or not understood:
            return RedirectResponse("/reset?msg=" + quote("Nothing was reset. Type RESET and tick the box to confirm."), 303)
        why = reset_mod.busy(store)
        if why:
            return RedirectResponse("/reset?msg=" + quote("Nothing was reset. " + why), 303)
        path = reset_mod.factory_reset(store, rt, engine)
        return RedirectResponse("/setup?msg=" + quote(f"Factory reset done. The old database is saved at {path}. Set up again below."), 303)

    @app.post("/setup/check")
    def setup_check():
        """B-87: run every setup test in the background; Setup shows the rows when it finishes."""
        if rt is None:
            return RedirectResponse("/setup?msg=The agent is not running, so nothing can be checked.", 303)
        if not (store.get("setup_check") or {}).get("running"):
            store.put("setup_check", {**(store.get("setup_check") or {}), "running": True})
            background(setupcheck.run, store, rt)
        return RedirectResponse("/setup", 303)

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
    def save_settings(resume_policy: str = Form(...), login: str = Form("off"), awake_on: str = Form("off"), check_on: str = Form("off"), pickup_on: str = Form("off"), checklist_on: str = Form("off")):
        store.put("resume_policy", resume_policy)
        store.put("checklists", {"on": checklist_on == "on"})
        store.put("pickup", {**pickup_mod.settings(store), "on": pickup_on == "on"})
        store.put("status_check", check_on == "on")
        if awake.supported():
            store.put("keep_awake", awake_on == "on")
        env = store.get("env")
        if login == "on" and not autostart.enabled(store.dir, env):
            autostart.enable(store.dir, env)
        elif login != "on" and autostart.enabled(store.dir, env):
            autostart.disable(store.dir, env)
        return RedirectResponse("/settings", 303)

    return app
