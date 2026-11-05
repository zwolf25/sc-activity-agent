"""B-56, B-78: a live check on an SB2 instance. Creates one work order, runs its whole plan with every step due now, and
reports each step. `scripts/live_sb2.py` and `agent smoke` run it by hand; an SB2 instance with the Settings toggle on runs it
every `days` days from the agent loop and sends the result as a Telegram alert. Never runs on Production."""
import random
import time

from . import generator
from .alerts import Alerts
from .creator import Creator

MAX_TICKS = 60   # the 15 calls/min limit makes a full run take a few minutes


def settings(store):
    return {"on": False, "days": 7, **store.get("smoke", {})}


def run(store, engine, rt, store_id=None, trade="DOOR", photos=True, checklists=True, rework=True, log=None):
    """Run one work order through its plan. The Behavior and checklist settings it changes are restored. Returns
    {ok, wo, steps: [(seq, kind, state, error)], calls: [(http, method, path, action)], error}."""
    if store.get("env") != "sb2":
        raise RuntimeError(f"Refusing to run: this is a {store.get('env')} instance. The smoke run is for SB2 only.")
    q, args = "SELECT * FROM locations WHERE enabled=1" + (" AND store_id=?" if store_id else "") + " ORDER BY store_id", ((store_id,) if store_id else ())
    loc = store.db.execute(q, args).fetchone()
    if not loc:
        return dict(ok=False, wo=None, steps=[], calls=[], error=f"No enabled location {store_id or ''}".strip())
    saved = {k: store.get(k) for k in ("behavior", "checklists")}
    if photos:
        store.put("behavior", {**(saved["behavior"] or {}), "photo_before": 100, "photo_after": 100})
    if rework:
        store.put("behavior", {**(store.get("behavior") or {}), "star_rating": 100, "rework": 100})
    if checklists:
        store.put("checklists", {**(saved["checklists"] or {}), "on": True})
    pick = generator.pick
    generator.pick = lambda rng, pool, mix: next((i for i in pool if trade.upper() in i["trade"].upper()), None) or pick(rng, pool, mix)
    try:
        sc_id = Creator(store, rt, random.Random()).create(loc)
        if not sc_id:
            return dict(ok=False, wo=None, steps=[], calls=[], error="No work order was created (see the audit log).")
        wo = store.db.execute("SELECT * FROM work_orders WHERE sc_id=?", (sc_id,)).fetchone()
        if log:
            log(f"created WO {sc_id} ({wo['trade']}) at {loc['store_id']}")
        engine.only_wo = wo["id"]   # old overdue steps on a busy test instance must not take this WO's slots
        for _ in range(MAX_TICKS):
            store.db.execute("UPDATE steps SET due_at=? WHERE wo_id=? AND state='pending'", (time.time(), wo["id"]))
            store.db.commit()
            engine.tick()
            if not store.db.execute("SELECT 1 FROM steps WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],)).fetchone():
                break
    finally:
        engine.only_wo = None
        generator.pick = pick
        for k, v in saved.items():
            store.drop(k) if v is None else store.put(k, v)   # B-84: a key that did not exist is deleted, never stored as null
    steps = [tuple(r) for r in store.db.execute("SELECT seq,kind,state,error FROM steps WHERE wo_id=? ORDER BY seq", (wo["id"],))]
    calls = [tuple(r) for r in store.db.execute("SELECT http,method,path,action FROM api_log WHERE sc_wo=? ORDER BY id", (sc_id,))]
    return dict(ok=all(s[2] in ("done", "skipped") for s in steps), wo=sc_id, steps=steps, calls=calls, error="")


def summary(r):
    if r["ok"]:
        return f"SB2 smoke run passed: WO {r['wo']}, {len(r['steps'])} steps."
    bad = [s for s in r["steps"] if s[2] not in ("done", "skipped")]
    first = f"{bad[0][1]} {bad[0][2]}: {(bad[0][3] or '')[:150]}" if bad else r["error"]
    on = f" on WO {r['wo']}" if r["wo"] else ""
    return f"SB2 smoke run FAILED{on}: {first}"


def tick(store, engine, rt, clock=time.time):
    """Loop piece: on an SB2 instance with the toggle on, run once every `days` days (or at once after Run now)."""
    cfg = settings(store)
    last = (store.get("smoke_last") or {}).get("at", 0)
    if store.get("env") != "sb2" or not cfg["on"] or store.get("paused_at") is not None:
        return []
    if not cfg.get("run_now") and clock() - last < cfg["days"] * 86400:
        return []
    store.put("smoke", {**cfg, "run_now": False})
    try:
        r = run(store, engine, rt)
    except Exception as e:  # noqa: BLE001
        r = dict(ok=False, wo=None, steps=[], calls=[], error=f"{type(e).__name__}: {e}")
    text = summary(r)
    store.put("smoke_last", {"at": clock(), "ok": r["ok"], "text": text})
    Alerts(store).send("smoke", text, event="smoke")
    return [("smoke", text)]
