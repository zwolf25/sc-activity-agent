"""B-41: on-demand clean-up of old WOs at the agent's locations that the agent did not create. Preview first, then cancel.
Cancel sets Completed / Canceled (the API cannot set VOID). A WO with the protect label is never touched."""
import datetime as dt
import time

from .client import ScError

ACTIVE = ("OPEN", "IN PROGRESS", "ON HOLD")
DEFAULTS = {"days": 14, "protect": "do not touch"}
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
                      {"$filter": f"UpdatedDate lt {cutoff} and ({status})", "$orderby": "UpdatedDate"}, MAX - len(items))
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


def run(store, rt, clock=time.time):
    """Cancel every WO in the saved preview. Each one is re-read first: a WO that was updated, finished or labelled since the
    preview is skipped. Progress is saved after each WO so the page can show it."""
    prev = store.get("cleanup_preview") or {"items": []}
    cfg = settings(store)
    cutoff = _iso(clock() - prev.get("days", cfg["days"]) * 86400)
    state = {"running": True, "total": len(prev["items"]), "cancelled": 0, "skipped": 0, "errors": [], "started": clock()}
    store.put("cleanup_run", state)
    for it in prev["items"]:
        try:
            app, user = rt.user_for(it["location"], "sub_note")
            wo = app.call(user, "GET", f"/workorders/{it['id']}", action="cleanup_check", wo=it["id"])
            if (wo["Status"]["Primary"] not in ACTIVE or wo["UpdatedDate"] >= cutoff or _protected(wo.get("Labels"), cfg["protect"])):
                state["skipped"] += 1
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
    log.append({"at": clock(), "what": f"cleanup: cancelled {state['cancelled']}, skipped {state['skipped']}, errors {len(state['errors'])}"})
    store.put("changes", log)
    return state
