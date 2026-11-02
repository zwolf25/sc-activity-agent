"""B-56: live check on an SB2 instance. Creates one work order and runs its whole plan to the end with every step due now,
then prints each step's outcome and the audit calls. Exit 0 only when no step failed and every step finished or was skipped.
Refuses to run against Production. Usage: python scripts/live_sb2.py [--data-dir DIR] [--store HQ-NYC] [--trade DOOR] [--photos] [--checklists]
--photos sets both photo sliders to 100 and --checklists turns checklist answering on, for this run only (the settings are restored)."""
import argparse
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from sc_activity_agent import generator  # noqa: E402
from sc_activity_agent.cli import build_engine  # noqa: E402
from sc_activity_agent.creator import Creator  # noqa: E402
from sc_activity_agent.store import Store  # noqa: E402

MAX_TICKS = 60   # the 15 calls/min limit makes a full run take a few minutes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=str(pathlib.Path.home() / "sc-activity-agent-sb2"))
    ap.add_argument("--store", default="HQ-NYC")
    ap.add_argument("--trade", default="DOOR", help="part of the trade name to prefer (needs a contract at the location)")
    ap.add_argument("--photos", action="store_true")
    ap.add_argument("--checklists", action="store_true")
    a = ap.parse_args(argv)
    if not (pathlib.Path(a.data_dir) / "agent.db").exists():
        sys.exit(f"No instance in {a.data_dir}")
    st = Store(pathlib.Path(a.data_dir))
    if st.get("env") != "sb2":
        sys.exit(f"Refusing to run: {a.data_dir} is a {st.get('env')} instance. This script is for SB2 only.")
    engine, rt = build_engine(st, with_rt=True)
    loc = st.db.execute("SELECT * FROM locations WHERE store_id=?", (a.store,)).fetchone() or sys.exit(f"No location {a.store}")
    saved = {k: st.get(k) for k in ("behavior", "checklists")}
    if a.photos:
        st.put("behavior", {**(saved["behavior"] or {}), "photo_before": 100, "photo_after": 100})
    if a.checklists:
        st.put("checklists", {**(saved["checklists"] or {}), "on": True})
    pick = generator.pick
    generator.pick = lambda rng, pool, mix: next((i for i in pool if a.trade.upper() in i["trade"].upper()), None) or pick(rng, pool, mix)
    try:
        sc_id = Creator(st, rt, random.Random()).create(loc)
        if not sc_id:
            sys.exit("No work order was created (see the audit log).")
        wo = st.db.execute("SELECT * FROM work_orders WHERE sc_id=?", (sc_id,)).fetchone()
        print(f"created WO {sc_id} ({wo['trade']}) at {a.store}")
        for _ in range(MAX_TICKS):
            st.db.execute("UPDATE steps SET due_at=? WHERE wo_id=? AND state='pending'", (time.time(), wo["id"]))
            st.db.commit()
            engine.tick()
            if not st.db.execute("SELECT 1 FROM steps WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],)).fetchone():
                break
    finally:
        generator.pick = pick
        for k, v in saved.items():
            st.put(k, v)
    steps = st.db.execute("SELECT seq,kind,state,error FROM steps WHERE wo_id=? ORDER BY seq", (wo["id"],)).fetchall()
    for s in steps:
        print(f"  {s['seq']:>2} {s['kind']:<16} {s['state']}" + (f"  {s['error'][:120]}" if s["error"] else ""))
    for r in st.db.execute("SELECT action,method,path,http FROM api_log WHERE sc_wo=? ORDER BY id", (sc_id,)).fetchall():
        print(f"  {r['http']} {r['method']} {r['path']}  [{r['action']}]")
    bad = [s for s in steps if s["state"] not in ("done", "skipped")]
    print("PASS" if not bad else f"FAIL: {len(bad)} step(s) not finished")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
