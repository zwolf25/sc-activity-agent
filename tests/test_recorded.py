"""B-90: the code that reads ServiceChannel runs against real responses saved by scripts/record_fixtures.py (personal data removed).
Hand-written fakes only prove the code matches our belief about the API; these prove it matches the API."""
import datetime as dt
import json
from pathlib import Path

from sc_activity_agent import generator
from sc_activity_agent.creator import Creator, user_dashboard
from sc_activity_agent.store import Store

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FX / f"{name}.json").read_text())


class Replay:
    """Answers GETs with the recorded response for the path."""
    def __init__(self, by_path):
        self.by_path = by_path

    def call(self, user, method, path, *a, **kw):
        return self.by_path[path]


def test_issue_list_flattens_into_problems_with_trade_and_category():
    out = generator.issues(fx("issuelist"))
    assert out and all(i["trade"] and i["category_id"] and i["problem"] for i in out)


def test_rank_one_trades_read_the_recorded_rank_endpoints():
    trades, locs = fx("rank_trades"), fx("rank_locations")
    get = lambda p: trades if "Trades" in p else locs
    assert generator.rank_one_trades(get, 1, 2, locs[0]) == {t["Trade"] for t in trades}   # same location list for every trade here
    assert generator.rank_one_trades(get, 1, 2, -1) == set()


def test_user_dashboard_reads_the_default_dashboard_from_the_profile(tmp_path):
    prof = fx("profile")
    hit = user_dashboard(Store(tmp_path), Replay({"/users/current/profile": prof}), ("u", "p"), 1000)
    assert hit["id"] == prof["UserProfile"]["DefaultScUserSetupId"] and hit["name"]
    assert isinstance(prof["UserProfile"]["AuthUserId"], int)   # checklist answers send it


def test_assigned_provider_comes_from_the_work_order(tmp_path):
    wo = fx("work_order")
    c = Creator.__new__(Creator)
    assert c._assigned_provider(Replay({f"/workorders/{wo['Id']}": wo}), ("u", "p"), wo["Id"]) == wo["Provider"]["Id"]


def test_work_order_fields_the_handlers_read():
    wo = fx("work_order")
    assert wo["Status"]["Primary"] and "Extended" in wo["Status"] and isinstance(wo["Provider"]["Id"], int)
    assert wo.get("Nte") is None or float(wo["Nte"]) >= 0


def test_invoice_fields_the_handlers_read():
    inv = fx("invoice")
    assert isinstance(inv["Status"], str) and isinstance(inv["Labors"], list) and inv["InvoiceTotal"] is not None
    dt.datetime.fromisoformat(inv["InvoiceDate"])   # the payment step parses it
    assert all("Hours" in l for l in inv["Labors"])


def test_odata_work_order_list_rows_carry_what_cleanup_and_pickup_use():
    rows = fx("odata_workorders")["value"]
    assert rows and all(isinstance(r["Id"], int) and "Status" in r for r in rows)


def test_contracts_assets_checklists_and_dashboard_headers_have_their_shapes():
    assert fx("contracts")["Contracts"] and "Id" in fx("contracts")["Contracts"][0]
    assert all("Id" in a for a in fx("assets"))
    assert isinstance(fx("checklist_detail")["CheckListDetails"], list)
    assert all("Id" in h and "DashboardId" in h for h in fx("issuelist_headers")["Headers"])
