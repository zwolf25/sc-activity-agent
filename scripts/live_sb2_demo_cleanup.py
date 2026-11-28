"""B-119: live check of Demo cleanup on an SB2 instance. Refuses to run against Production.
  preview  reads only: the module's real preview over all of SB2, then its counts and skip reasons
  setup    creates throwaway records (open WO, held WOs, proposal, invoice) and remembers their ids
  run      replaces the work list with those throwaway records ONLY, runs one confirmed job, and prints each live status
No other SB2 record is written: `run` builds the list from the ids `setup` saved. Wait 5 minutes after `setup` so no visit is
still in the future. Usage: python scripts/live_sb2_demo_cleanup.py preview|setup|run [--data-dir DIR] [--months 4]"""
import argparse
import datetime as dt
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from sc_activity_agent import demo_cleanup as demo  # noqa: E402
from sc_activity_agent.cli import build_engine  # noqa: E402
from sc_activity_agent.store import Store  # noqa: E402

TEMPLATE_WO = 370471185   # an SB2 test WO, read only: supplies category and priority


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["preview", "setup", "run"])
    ap.add_argument("--data-dir", default=str(pathlib.Path.home() / "sc-activity-agent-sb2"))
    ap.add_argument("--months", type=int, default=4)
    a = ap.parse_args(argv)
    if not (pathlib.Path(a.data_dir) / "agent.db").exists():
        sys.exit(f"No instance in {a.data_dir}")
    st = Store(pathlib.Path(a.data_dir))
    if st.get("env") != "sb2":
        sys.exit(f"Refusing to run: {a.data_dir} is a {st.get('env')} instance. This script is for SB2 only.")
    engine, rt = build_engine(st, with_rt=True)
    return {"preview": preview, "setup": setup, "run": run}[a.step](st, rt, a)


def preview(st, rt, a):
    error = demo.start_preview(st, a.months, "do not touch", any_env=True)
    if error:
        sys.exit(error)
    t = time.time()
    demo.preview(st, rt)
    j = demo.job(st)
    print(f"state {j['state']}, {(time.time() - t) / 60:.1f} min, {j['locations']} locations")
    print("counts", demo.counts(st))
    for title, rows in demo.breakdown(st)[:3]:
        print(title, rows)
    print("skips", j["skips"])
    print("estimate (calls, hours, nights)", demo.estimate(st))
    return 0


def setup(st, rt, a):
    loc = st.db.execute("SELECT * FROM locations WHERE store_id='HQ-NYC'").fetchone()
    users = {}
    for u in st.db.execute("SELECT u.*, c.provider_id AS pid, c.side FROM users u JOIN connections c ON c.id=u.conn_id").fetchall():
        users.setdefault(u["pid"] if u["side"] == "provider" else "sub", (u["conn_id"], (u["username"], st.dec(u["password"]))))

    def call(who, method, path, **kw):
        cid, user = users[who]
        return rt.apps[cid].call(user, method, path, action="demo_spike", **kw)

    def stamp(minutes, z=""):
        return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S") + z

    t = call("sub", "GET", f"/workorders/{TEMPLATE_WO}")

    def create(label):
        r = call("sub", "POST", "/workorders", body={
            "ContractInfo": {"SubscriberId": loc["subscriber_id"], "LocationId": loc["db_id"], "StoreId": loc["store_id"],
                             "TradeName": "GENERAL MAINTENANCE", "TradeId": 112193},
            "Category": t["Category"], "Priority": t["Priority"], "Nte": 500, "CallDate": stamp(0), "ScheduledDate": stamp(2),
            "Description": f"SB2 throwaway, demo cleanup live check: {label}",
            "DispatchSettingsInfo": {"IsTest": False, "NotificationDisabled": True}, "ApiRequest": True})
        print("created", r["id"], label)
        return r["id"]

    def provider(wid):
        return call("sub", "GET", f"/workorders/{wid}")["Provider"]["Id"]

    def set_status(wid, extended):
        call("sub", "PUT", f"/workorders/{wid}/status", body={"Status": {"Primary": "COMPLETED", "Extended": extended}, "Note": demo.NOTE})

    made = []
    made.append(("wo", create("open"), "cancel"))
    blank = create("blank sub-status")
    set_status(blank, "")
    made.append(("wo", blank, "confirm"))
    held = create("compliance details")
    set_status(held, "PENDING COMPLIANCE DETAILS")
    made.append(("wo", held, "confirm"))

    quoted = create("open proposal")
    pid = provider(quoted)
    call(pid, "PUT", f"/workorders/{quoted}/accept", body={"Note": "Accepted."})
    labor = ["Regular Hours", "Overtime Hours", "Double Time / Holiday Hours", "Helper Regular Hours",
             "Helper Overtime Hours", "Helper Double Time / Holiday Hours", "Subcontractor Labor"]
    proposal = call(pid, "POST", "/proposals/CreateProposal", body={
        "version": "1.0.0", "subscriberId": loc["subscriber_id"], "providerId": pid, "locationId": loc["db_id"], "tradeId": 112193,
        "currency": "USD", "proposalNumber": f"PR-{quoted}-{random.randint(100, 999)}", "description": "SB2 throwaway proposal",
        "notificationEmails": "", "costsIncurredToDate": [],
        "materials": [{"description": "Replacement parts", "unit": "each", "qty": 1, "price": 600.0}], "materialsAnswer": "New",
        "installationLabor": [{"description": n, "tech": int(i == 0), "hours": 1.0 if i == 0 else 0.0, "rate": 95.0 if i == 0 else 0.0}
                              for i, n in enumerate(labor)],
        "installationLaborFlatFeeLabor": 0, "nonInstallationExpenses": {"travel": {"ofTrips": 1, "charge": 45.0}, "fees": 0, "nonInstallationLabor": 0},
        "nonInstallationExpensesOther": [], "freight": 0, "freightOther": [],
        "tax": {"materialSalesTax": 0, "installationLaborSalesTax": 0, "nonInstallationExpensesSalesTax": 0, "freightTax": 0}})
    call("sub", "PUT", f"/proposals/{proposal}/assignWO", body=int(quoted))
    made += [("proposal", int(proposal), "reject"), ("wo", quoted, "cancel")]

    billed = create("open invoice")
    set_status(billed, "CONFIRMED")
    inv = call(provider(billed), "POST", "/invoices", body={
        "InvoiceNumber": f"INV-{billed}-{random.randint(100, 999)}", "WoIdentifier": str(billed), "InvoiceDate": stamp(0, "Z"),
        "InvoiceTotal": 50.0, "InvoiceAmountsDetails": {"LaborAmount": 0, "MaterialAmount": 50.0}, "Labors": [],
        "Materials": [{"Description": "Hardware kit", "PartNum": "P-1000", "UnitType": "7", "UnitPrice": 50.0, "Quantity": 1, "Amount": 50.0}]})
    made.append(("invoice", inv["Id"], "reject"))
    wo_of = {proposal: quoted, inv["Id"]: billed}
    st.put("demo_live_records", [[k, int(rid), int(wo_of.get(rid, rid)), act] for k, rid, act in made])
    st.put("demo_live_made_at", time.time())
    print("saved", st.get("demo_live_records"))
    return 0


def _live(api, kind, rid):
    """(status as the preview stores it, the row)"""
    bound = demo._iso(time.time() + 86400)
    if kind == "proposal":
        rows = api.call("GET", "/odata/proposals", {"$filter": f"Id eq {rid} and CreatedDate lt {bound}", "$top": 1})["value"]
        return rows[0]["Status"]["Primary"], rows[0]
    if kind == "invoice":
        row = api.call("GET", f"/invoices/{rid}")
        return row.get("Status"), row
    row = api.call("GET", f"/workorders/{rid}")
    primary, ext = row["Status"]["Primary"], row["Status"].get("Extended") or ""
    return primary if primary in demo.ACTIVE else f"{primary}/{ext}", row


def run(st, rt, a):
    made = st.get("demo_live_records")
    if not made:
        sys.exit("Run the setup step first.")
    api = demo.Api(st, rt, demo.FAST_RATE)
    st.db.execute("DELETE FROM demo_cleanup_items")
    for kind, rid, wo, action in made:
        # an invoice is listed as Open, as the preview would: SB2 auto-approves in about 5 minutes, and the re-read must then skip it
        status = "Open" if kind == "invoice" else _live(api, kind, rid)[0]
        st.db.execute("INSERT INTO demo_cleanup_items(kind, rid, wo_id, location, status, action) VALUES(?,?,?,'HQ-NYC',?,?)",
                      (kind, rid, wo, status, action))
        print("listed", kind, rid, status, action)
    st.db.commit()
    assert demo.counts(st)["total"] == len(made)
    st.put("demo_job", {"state": "ready", "preview_at": time.time(), "subscriber_id": st.get("subscriber_id"), "protect": "do not touch"})
    error = demo.start_run(st, True, "now", limit=len(made))
    if error:
        sys.exit(error)
    demo.session(st, rt, api=api)
    print("job", demo.job(st).get("state"), demo.job(st).get("message"), demo.counts(st))
    for r in st.db.execute("SELECT kind, rid, action, state, reason FROM demo_cleanup_items ORDER BY id").fetchall():
        print(f"  {r['kind']:<8} {r['rid']} {r['action']:<8} {r['state']:<7} now {_live(api, r['kind'], r['rid'])[0]}  {r['reason']}")
    ok = demo.counts(st)["done"] == len(made)
    st.put("demo_job", {})   # leave nothing for an agent to pick up
    print("PASS" if ok else "CHECK the rows above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
