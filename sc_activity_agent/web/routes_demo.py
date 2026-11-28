"""B-119: Demo cleanup page, opened from the Cleanup page. Production only. The routes only change the job; the agent loop does the work."""
import csv
import io
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from .. import awake
from .. import cleanup as cleanup_mod
from .. import demo_cleanup as demo


def register(app, store, rt, db, page, stamp):
    def guard():
        if store.get("env") != "prod":
            raise HTTPException(404, "Demo cleanup runs on Production instances only.")

    def back(msg):
        return RedirectResponse("/demo-cleanup" + (f"?msg={quote(msg)}" if msg else ""), 303)

    @app.get("/demo-cleanup")
    def demo_page(request: Request, msg: str = ""):
        guard()
        j = demo.job(store)
        c = demo.counts(store)
        ctx = dict(msg=msg, j=j, c=c, live=demo.live(), subscriber_id=store.get("subscriber_id"),
                   protect=j.get("protect", cleanup_mod.settings(store)["protect"]), run_limit=demo.RUN_LIMIT,
                   expired=demo.expired(store), asleep_risk=awake.supported() and not store.get("keep_awake", True),
                   paused_by_user=store.get("paused_at") is not None and store.get("paused_at") != j.get("own_pause"),
                   blocked=bool((store.get("cleanup_run") or {}).get("running")))
        if c["total"] and j.get("state") != "previewing":
            start, end = j.get("start", "20:00"), j.get("end", "06:00")
            ctx.update(groups=demo.breakdown(store), start=start, end=end,
                       normal=demo.estimate(store, demo.RATE, start, end), quick=demo.estimate(store, demo.FAST_RATE, start, end),
                       problems=db.execute("SELECT * FROM demo_cleanup_items WHERE state='error' ORDER BY done_at DESC LIMIT 10").fetchall())
        if j.get("preview_at"):
            ctx["previewed"] = stamp(j["preview_at"], ZoneInfo(store.get("tz", "America/New_York")))
        return page(request, "demo_cleanup", here="cleanup", **ctx)

    @app.post("/demo-cleanup/preview")
    def demo_preview(months: int = Form(4), protect: str = Form("")):
        guard()
        if not rt:
            return back("The agent is not running")
        return back(demo.start_preview(store, months, protect))

    @app.post("/demo-cleanup/run")
    def demo_run(understood: str = Form(""), mode: str = Form("nightly"), start: str = Form("20:00"),
                 end: str = Form("06:00"), limit: str = Form(""), fast: str = Form("")):
        guard()
        if not rt:
            return back("The agent is not running")
        if limit.strip() and not limit.strip().isdigit():
            return back("The record limit must be a whole number, or blank.")
        n = int(limit) if limit.strip() else demo.RUN_LIMIT if mode == "now" else 0
        return back(demo.start_run(store, bool(understood), mode, start, end, n, bool(fast)))

    @app.post("/demo-cleanup/stop")
    def demo_stop():
        guard()
        demo.halt(store)
        return back("Stopped. A write already in progress finishes first.")

    @app.get("/demo-cleanup/items.csv", response_class=PlainTextResponse)
    def demo_csv():
        guard()
        cols = ["kind", "rid", "wo_id", "location", "status", "action", "created", "provider", "state", "reason"]
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["type", "record_id", "work_order_id", "location", "status_at_preview", "action", "created", "provider", "result", "reason"])
        for r in db.execute(f"SELECT {','.join(cols)} FROM demo_cleanup_items ORDER BY id"):
            # a leading = + - @ would run as a formula when the file is opened in a spreadsheet
            w.writerow([f"'{v}" if isinstance(v, str) and v[:1] in "=+-@" else v for v in r])
        return PlainTextResponse(out.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=demo-cleanup.csv"})
