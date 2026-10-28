"""B-41: on-demand clean-up of old WOs at the agent's locations that the agent did not create. Preview first, then cancel.
Cancel sets Completed / Canceled (the API cannot set VOID). A WO with the protect label is never touched."""
import datetime as dt
import json
import random
import time
from zoneinfo import ZoneInfo

from . import planner, update
from .client import ScError
from .engine import add_plan

ACTIVE = ("OPEN", "IN PROGRESS", "ON HOLD")
DEFAULTS = {"days": 14, "protect": "do not touch", "sweep": "off"}   # sweep: off | cancel | finish
SWEEP_MAX = 100
PAGE, MAX = 50, 500   # ponytail: one preview lists at most MAX WOs; run it again after cancelling to see the rest
NOTE = "Cancelled by SC Activity Agent clean-up (no activity for {days} days)"


def settings(store):
    return {**DEFAULTS, **store.get("cleanup", {})}


def _iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _protected(labels, protect):
    return any((lab.get("Label") or "").strip().lower() == protect.strip().lower() for lab in labels or [])


def _pages(app, user, path, params, limit):
    out, skip = [], 0
    while len(out) < limit:
        rows = app.call(user, "GET", path, {**params, "$top": PAGE, "$skip": skip}, action="cleanup_list")["value"]
        out += rows
        if len(rows) < PAGE:
            break
        skip += PAGE
    return out[:limit]


def preview(store, rt, clock=time.time):
    """List old active WOs at the enabled locations. Skips the agent's own WOs and anything with the protect label."""
    cfg = settings(store)
    cutoff = _iso(clock() - cfg["days"] * 86400)
    mine = {r[0] for r in store.db.execute("SELECT sc_id FROM work_orders")}
    status = " or ".join(f"Status/Primary eq '{s}'" for s in ACTIVE)
    items, protected = [], 0
    for loc in store.db.execute("SELECT * FROM locations WHERE enabled=1").fetchall():
        app, user = rt.user_for(loc["store_id"], "sub_note")
        shielded = {w["Id"] for w in _pages(app, user, "/odata/workorders", {
            "$filter": f"Labels/any(l: l/Label eq '{cfg['protect']}')", "$select": "Id"}, MAX)} if cfg["protect"] else set()
        rows = _pages(app, user, f"/odata/locations({loc['db_id']})/workorders",
                      {"$filter": f"UpdatedDate lt {cutoff} and ({status})", "$orderby": "UpdatedDate",
                       "$expand": "Provider($select=Id,Name)"}, MAX - len(items))
        for w in rows:
            if w["Id"] in mine:
                continue
            if w["Id"] in shielded:
                protected += 1
                continue
            items.append({"id": w["Id"], "location": loc["store_id"], "trade": w.get("Trade", ""), "status": w["Status"]["Primary"],
                          "updated": w.get("UpdatedDate", ""), "provider": (w.get("Provider") or {}).get("Name", "")})
    result = {"at": clock(), "days": cfg["days"], "protect": cfg["protect"], "protected": protected, "items": items}
    store.put("cleanup_preview", result)
    return result


def finish_plan(store, rt, w, now):
    """Give a WO held by one of our providers a short plan: accept, one visit, review, invoice, approve. Times fit the activity window."""
    loc = store.db.execute("SELECT * FROM locations WHERE store_id=?", (w["_location"],)).fetchone()
    c, rng, tz = {**planner.DEFAULTS, **store.get("behavior", {})}, rt.rng, loc["tz"] or "America/New_York"
    t, steps = now, []
    # no accept step: idle WOs are mostly past acceptance and the API refuses it with 904 (seen live on Prod, 2026-10-27)
    for kind, lo, hi, payload in (("check_in", 600, 3600, {"visit": 1, "situation": "onsite"}),
                                  ("check_out", 5400, 10800, {"visit": 1, "final": True, "situation": "complete"}),
                                  ("review", 3600, 28800, {"situation": "review"}), ("invoice_submit", 7200, 21600, {"situation": "invoice"}),
                                  ("invoice_decide", 3600, 21600, {"approve": True})):
        t = planner._fit(t + rng.randint(lo, hi), t, c, tz, rng)
        steps.append({"kind": kind, "due_at": t, "payload": payload})
    trade = w.get("Trade") or "General"
    issue = w.get("Problem") or w.get("ProblemDescription") or "reported issue"
    ctx = dict(trade=trade, issue=issue, location=loc["name"] or loc["store_id"], sched_day="", eta="", eta_end="", area="sales floor",
               equipment=w.get("AssetType") or "equipment", amount="", nte=w.get("Nte") or 500, category="REPAIR")
    if (w.get("Provider") or {}).get("Id"):
        ctx["provider_id"] = w["Provider"]["Id"]
    add_plan(store, loc["store_id"], trade, w["Id"], steps, ctx, now)


def run(store, rt, clock=time.time, finish=False):
    """Cancel every WO in the saved preview. Each one is re-read first: a WO that was updated, finished or labelled since the
    preview is skipped. Progress is saved after each WO so the page can show it."""
    prev = store.get("cleanup_preview") or {"items": []}
    cfg = settings(store)
    if prev["items"]:
        update.backup(store)   # a restore point before a bulk cancel
    cutoff = _iso(clock() - prev.get("days", cfg["days"]) * 86400)
    state = {"running": True, "total": len(prev["items"]), "cancelled": 0, "skipped": 0, "errors": [], "started": clock()}
    store.put("cleanup_run", state)
    for it in prev["items"]:
        try:
            app, user = rt.user_for(it["location"], "sub_note")
            wo = app.call(user, "GET", f"/workorders/{it['id']}", action="cleanup_check", wo=it["id"])
            if (wo["Status"]["Primary"] not in ACTIVE or wo["UpdatedDate"] >= cutoff or _protected(wo.get("Labels"), cfg["protect"])):
                state["skipped"] += 1
            elif finish and (wo.get("Provider") or {}).get("Id") in {r[0] for r in store.db.execute(
                    "SELECT provider_id FROM connections WHERE side='provider' AND provider_id IS NOT NULL")}:
                finish_plan(store, rt, {**wo, "_location": it["location"]}, clock())
                state["finished"] = state.get("finished", 0) + 1
            else:
                app.call(user, "PUT", f"/workorders/{it['id']}/status", action="cleanup_cancel", wo=it["id"], write=True,
                         body={"Status": {"Primary": "COMPLETED", "Extended": "CANCELED"}, "Note": NOTE.format(days=prev["days"])})
                state["cancelled"] += 1
        except ScError as e:
            state["errors"].append(f"{it['id']}: {str(e)[:120]}")
            if e.status == 0:   # paused: stop here instead of listing every WO as an error
                break
        store.put("cleanup_run", state)
    state["running"] = False
    store.put("cleanup_run", state)
    log = store.get("changes", [])[-49:]
    log.append({"at": clock(), "what": f"cleanup: cancelled {state['cancelled']}, finishing {state.get('finished', 0)}, skipped {state['skipped']}, errors {len(state['errors'])}"})
    store.put("changes", log)
    return state


def now(store, rt, clock=time.time):
    """Select every idle WO and act on it right away, no review. Uses the daily-sweep choice for finish vs cancel."""
    preview(store, rt, clock)
    return run(store, rt, clock, finish=settings(store)["sweep"] == "finish" and store.get("env") != "prod")


def sweep(store, rt, clock=time.time):
    """B-40: once a day on a weekday, when the setting is on, preview and run without a click. Cancels, or (finish) gives WOs held
    by our providers a short plan. Returns engine-style [(key, outcome)]."""
    mode = settings(store)["sweep"]
    if mode == "finish" and store.get("env") == "prod":
        mode = "off"   # finishing plans act as the Provider on real work orders: never automatic on Prod
    now = clock()
    day = dt.datetime.fromtimestamp(now, ZoneInfo(store.get("tz", "America/New_York")))
    if mode == "off" or store.get("paused_at") is not None or day.weekday() >= 5 or now - store.get("last_sweep", 0) < 20 * 3600 \
            or (store.get("cleanup_run") or {}).get("running"):
        return []
    store.put("last_sweep", now)
    prev = preview(store, rt, clock)
    if not prev["items"]:
        return [("sweep", "nothing idle")]
    prev["items"] = prev["items"][:SWEEP_MAX]   # ponytail: the API allows ~15 calls/min and the sweep shares it; the rest wait for tomorrow
    store.put("cleanup_preview", prev)
    s = run(store, rt, clock, finish=mode == "finish")
    return [("sweep", f"cancelled {s['cancelled']}, finishing {s.get('finished', 0)}, skipped {s['skipped']}, errors {len(s['errors'])}")]
