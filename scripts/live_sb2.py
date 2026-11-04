"""B-56: live check on an SB2 instance. Creates one work order and runs its whole plan to the end with every step due now,
then prints each step's outcome and the audit calls. Exit 0 only when no step failed and every step finished or was skipped.
Refuses to run against Production. Usage: python scripts/live_sb2.py [--data-dir DIR] [--store HQ-NYC] [--trade DOOR] [--photos] [--checklists] [--rework]
--photos sets both photo sliders to 100, --checklists turns checklist answering on, and --rework rates every review and makes the first one unsatisfactory
(a return visit and a second, rated review), for this run only (the settings are restored). The logic lives in sc_activity_agent/smoke.py
(B-78), which an SB2 instance can also run on a schedule."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from sc_activity_agent import smoke  # noqa: E402
from sc_activity_agent.cli import build_engine  # noqa: E402
from sc_activity_agent.store import Store  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=str(pathlib.Path.home() / "sc-activity-agent-sb2"))
    ap.add_argument("--store", default="HQ-NYC")
    ap.add_argument("--trade", default="DOOR", help="part of the trade name to prefer (needs a contract at the location)")
    ap.add_argument("--photos", action="store_true")
    ap.add_argument("--checklists", action="store_true")
    ap.add_argument("--rework", action="store_true")
    a = ap.parse_args(argv)
    if not (pathlib.Path(a.data_dir) / "agent.db").exists():
        sys.exit(f"No instance in {a.data_dir}")
    st = Store(pathlib.Path(a.data_dir))
    if st.get("env") != "sb2":
        sys.exit(f"Refusing to run: {a.data_dir} is a {st.get('env')} instance. This script is for SB2 only.")
    engine, rt = build_engine(st, with_rt=True)
    r = smoke.run(st, engine, rt, a.store, a.trade, a.photos, a.checklists, a.rework, log=print)
    for seq, kind, state, err in r["steps"]:
        print(f"  {seq:>2} {kind:<16} {state}" + (f"  {err[:120]}" if err else ""))
    for http, method, path, action in r["calls"]:
        print(f"  {http} {method} {path}  [{action}]")
    print("PASS" if r["ok"] else f"FAIL: {r['error'] or 'step(s) not finished'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
