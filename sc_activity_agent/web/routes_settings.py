"""Settings, backup, reset, restore and alert routes, split out of app.py (B-77)."""
from .. import __version__
from .. import autostart
from .. import awake
from .. import caps
from .. import pickup as pickup_mod
from .. import planner
from .. import reset as reset_mod
from .. import setupcheck
from .. import smoke
from .. import update
from ..alerts import AlertError
from ..alerts import Alerts
from ..alerts import EVENTS
from fastapi import Form
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import platform
import sys
from .app import stamp


def register(app, background, db, engine, page, rt, store):
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

    @app.get("/issue-list.xlsx")
    def issue_list_file():
        return FileResponse(Path(__file__).parent.parent / "SCActivityAgentIssueList.xlsx", filename="SCActivityAgentIssueList.xlsx")

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
        try:
            with reset_mod.quiesced(engine):
                path = reset_mod.factory_reset(store, rt, engine)
        except reset_mod.Busy as e:
            return RedirectResponse("/reset?msg=" + quote("Nothing was reset. " + str(e)), 303)
        return RedirectResponse("/setup?msg=" + quote(f"Factory reset done. The old database is saved at {path}. Set up again below."), 303)

    @app.get("/restore/{name}")
    def restore_page(request: Request, name: str):
        known = {n: (s_, t) for n, s_, t in update.backups(store)}
        if name not in known:
            return RedirectResponse("/settings?msg=" + quote("That backup no longer exists."), 303)
        return page(request, "restore", file=name, when=stamp(known[name][1], ZoneInfo(store.get("tz", "America/New_York"))),
                    busy=reset_mod.busy(store))

    @app.post("/restore/{name}")
    def restore_do(name: str, confirm: str = Form(""), understood: str = Form("")):
        """B-89: restore a backup while the agent runs. Same guard as the factory reset: typed word and tick box."""
        back = f"/restore/{quote(name)}?msg="
        if confirm.strip() != "RESTORE" or not understood:
            return RedirectResponse(back + quote("Nothing was restored. Type RESTORE and tick the box to confirm."), 303)
        why = reset_mod.busy(store)
        if why:
            return RedirectResponse(back + quote("Nothing was restored. " + why), 303)
        try:
            with reset_mod.quiesced(engine):
                keep = reset_mod.restore_live(store, name, rt, engine)
        except reset_mod.Busy as e:
            return RedirectResponse(back + quote("Nothing was restored. " + str(e)), 303)
        except FileNotFoundError:
            return RedirectResponse("/settings?msg=" + quote("That backup no longer exists."), 303)
        return RedirectResponse("/settings?msg=" + quote(f"Restored {name}. The database it replaced is saved at {keep}. Check the Dashboard, then resume the agent if it is paused."), 303)

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
