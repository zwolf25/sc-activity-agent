"""B-51: give a plan to work orders people create by hand at our locations. Once an hour (setting pickup.on, on by default) it
lists recent active WOs, keeps those held by one of our providers in a trade where Rank 1 is ours, and plans them with
cleanup.finish_plan. The protect label and the age limit keep it off real customers' work."""
import time

from . import cleanup
from .client import ScError

EVERY, MAX_PER_PASS = 3600, 10   # shortcut: runs in the main loop, so a pass of ~12 calls at 15 calls/min holds the step loop about a minute an hour; move to a thread like the sweep if that shows
DEFAULTS = {"on": True, "days": 7}


def settings(store):
    return {**DEFAULTS, **store.get("pickup", {})}


def tick(store, rt, creator, clock=time.time):
    """Returns engine-style [(key, outcome)]."""
    cfg = settings(store)
    if not cfg["on"] or store.get("paused_at") is not None or clock() - store.get("pickup_at", 0) < EVERY:
        return []
    store.put("pickup_at", clock())
    protect = cleanup.settings(store)["protect"]
    mine = {r[0] for r in store.db.execute("SELECT sc_id FROM work_orders")}
    ours = {r[0] for r in store.db.execute("SELECT provider_id FROM connections WHERE side='provider' AND provider_id IS NOT NULL")}
    cutoff = cleanup._iso(clock() - cfg["days"] * 86400)
    status = " or ".join(f"Status/Primary eq '{s}'" for s in cleanup.ACTIVE)
    out = []
    for loc in store.db.execute("SELECT * FROM locations WHERE enabled=1").fetchall():
        try:
            trades = creator.our_trades(loc)
            app, user = rt.user_for(loc["store_id"], "sub_note")
            rows = cleanup._pages(app, user, f"/odata/locations({loc['db_id']})/workorders",
                                  {"$filter": f"CreatedDate gt {cutoff} and ({status})", "$orderby": "CreatedDate",
                                   "$select": "Id,Trade", "$expand": "Provider($select=Id)"}, cleanup.MAX)
            for w in rows:
                if len(out) >= MAX_PER_PASS:
                    return out
                if w["Id"] in mine or (w.get("Provider") or {}).get("Id") not in ours or w.get("Trade") not in trades:
                    continue
                wo = app.call(user, "GET", f"/workorders/{w['Id']}", action="pickup_check", wo=w["Id"])   # re-read: the list can be stale
                if wo["Status"]["Primary"] not in cleanup.ACTIVE or cleanup._protected(wo.get("Labels"), protect):
                    continue
                cleanup.finish_plan(store, rt, {**wo, "_location": loc["store_id"]}, clock(), accept=wo["Status"]["Primary"] == "OPEN")
                out.append((w["Id"], f"planned at {loc['store_id']}"))
        except ScError as e:
            out.append((loc["store_id"], f"{str(e)[:120]}"))
            if e.status == 0:   # paused
                break
    return out
