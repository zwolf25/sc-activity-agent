"""Locations page routes, split out of app.py (B-77). `register` adds them to the app; the shared helpers come in as arguments."""
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from .. import locations as locations_mod
from ..client import ScError


def register(app, store, rt, db, page, sub_app, stamp):
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
