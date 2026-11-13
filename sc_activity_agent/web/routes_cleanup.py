"""Clean-up page routes, split out of app.py (B-77). `register` adds them to the app; the shared helpers come in as arguments."""
import time
from zoneinfo import ZoneInfo

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from .. import cleanup as cleanup_mod
from ..client import ScError
from ..handlers import cancel_wo


def register(app, store, rt, db, page, background, stamp):
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
