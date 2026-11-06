"""B-90: save one real ServiceChannel response per endpoint the agent reads into tests/fixtures/, with personal data removed.
Read-only GETs against the instance in --data-dir (a Production or SB2 instance). Usage:
  python scripts/record_fixtures.py DATA_DIR SUBSCRIBER_USER_ID PROVIDER_USER_ID WO_ID INVOICE_ID LOCATION_STORE_ID"""
import json
import re
import sys
from pathlib import Path

from sc_activity_agent.store import Store

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DROP = re.compile(r"(?i)phone|e-?mail|fax|address|street|city|zip|postal|contact|firstname|lastname|fullname|technician|mechanic|username|caller|by$|assignee|requester|approver|approvedby|reviewer|user$")


def scrub(o, key=""):
    if isinstance(o, dict):
        return {k: ("redacted" if isinstance(v, str) and DROP.search(k) else scrub(v, k)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v, key) for v in o]
    if isinstance(o, str):
        return re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "user@example.com", re.sub(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", "555-0100", o))
    return o


def save(name, data, cap=None):
    if cap and isinstance(data, list):
        data = data[:cap]
    (OUT / f"{name}.json").write_text(json.dumps(scrub(data), indent=1, sort_keys=True) + "\n")
    print("saved", name)


def main(d, sub_id, prov_id, wo, inv, store_id):
    from sc_activity_agent.client import ScApp
    s = Store(Path(d))
    def who(uid):
        u = s.db.execute("select * from users where id=?", (uid,)).fetchone()
        c = s.db.execute("select * from connections where id=?", (u["conn_id"],)).fetchone()
        return ScApp(s.get("env"), c["client_id"], s.dec(c["client_secret"]), store=None, role=c["side"]), (u["username"], s.dec(u["password"])), c
    app, user, _ = who(sub_id)
    papp, puser, pconn = who(prov_id)
    loc = s.db.execute("select * from locations where store_id=?", (store_id,)).fetchone()
    get = lambda a, u, path, **p: a.call(u, "GET", path, p or None, action="fixture", write=False)
    sid = loc["subscriber_id"]
    OUT.mkdir(parents=True, exist_ok=True)
    save("work_order", get(app, user, f"/workorders/{wo}"))
    save("profile", get(app, user, "/users/current/profile"))
    heads = get(app, user, f"/api/subscribers/{sid}/issuelist/headers")
    save("issuelist_headers", heads)
    dash = (get(app, user, "/users/current/profile").get("UserProfile") or {}).get("DefaultScUserSetupId")
    il = get(app, user, f"/api/subscribers/{sid}/storedashboards/{dash}/issuelist")
    il["ProblemTypes"] = il["ProblemTypes"][:3]
    save("issuelist", il)
    trades = get(app, user, f"/GetPrimaryRankedProviderTrades/{sid}/{pconn['provider_id']}")
    save("rank_trades", trades)
    save("rank_locations", get(app, user, f"/GetPrimaryRankedProviderLocations/{sid}/{pconn['provider_id']}/{trades[0]['TradeId']}"))
    save("contracts", get(app, user, "/contracts", locationDbId=loc["db_id"], providerId=pconn["provider_id"], trade="HVAC"))
    save("invoice", get(app, user, f"/invoices/{inv}"))
    save("assets", get(app, user, "/assets", locationId=loc["db_id"]).get("Assets", [])[:3])
    save("odata_workorders", get(app, user, f"/odata/locations({loc['db_id']})/workorders", **{"$top": 2}))
    save("checklist_detail", get(papp, puser, "/checklists/detail", tradeName="GENERAL MAINTENANCE", storeId=store_id, subscriberId=sid))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), *sys.argv[4:])
