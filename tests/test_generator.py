import datetime as dt
import random

from sc_activity_agent import generator as g

IL = {"ProblemTypes": [
    {"Name": "Doors", "Items": [{"Name": "Automatic Door", "Problems": [
        {"Name": "Noisy", "Trade": "DOORS", "TradeId": 1, "Priority": "NORMAL", "Category": {"Default": "REPAIR"},
         "CategoryId": 9, "Nte": "500"}]}]},
    {"Name": "HVAC", "Items": [{"Name": "RTU", "Problems": [
        {"Name": "Coil", "Trade": "HVAC", "TradeId": 2, "Priority": "NORMAL", "Category": {"Default": "REPAIR"},
         "CategoryId": 9, "Nte": "50"}]}]},
    {"Name": "Fridge", "Items": [{"Name": "Case", "Problems": [
        {"Name": "Warm", "Trade": "REFRIGERATION", "TradeId": 3, "Priority": "NORMAL",
         "Category": {"Default": "REPAIR"}, "CategoryId": 9, "Nte": ""}]}]}]}


def test_only_trades_we_rank_one_for():
    pool = g.eligible(g.issues(IL), {"DOORS", "HVAC"})
    assert {i["trade"] for i in pool} == {"DOORS", "HVAC"}
    assert g.pick(random.Random(1), g.eligible(g.issues(IL), set())) is None


def test_trade_mix_weights():
    pool = g.eligible(g.issues(IL), {"DOORS", "HVAC"})
    r = random.Random(2)
    n = sum(g.pick(r, pool, {"HVAC": 9, "DOORS": 1})["trade"] == "HVAC" for _ in range(1000))
    assert 850 < n < 950


def test_payload_takes_nte_from_issue_and_omits_status():
    i = g.issues(IL)[1]
    now = dt.datetime(2026, 10, 23, 12)
    p = g.payload(i, {"subscriber_id": 5, "id": 6, "store_id": "HQ"}, 110058, 3, now + dt.timedelta(days=2), now)
    assert p["Nte"] == 50 and "Status" not in p and p["IssueListHeaderId"] == 110058
    assert p["ContractInfo"]["TradeId"] == 2 and p["IssueRequestInfo"]["AssetType"] == "RTU"


def test_daily_count_weekdays_only_and_mean():
    r = random.Random(3)
    sat = dt.date(2026, 10, 24)
    assert g.daily_count(r, 120, sat) == 0
    mon = dt.date(2026, 10, 26)
    avg = sum(g.daily_count(r, 120, mon) for _ in range(2000)) / 2000
    assert 5 < avg < 6.5


def test_rank_one_trades_uses_location_membership():
    data = {"/GetPrimaryRankedProviderTrades/5/9": [{"Trade": "HVAC", "TradeId": 1}, {"Trade": "ELECTRICAL", "TradeId": 2}],
            "/GetPrimaryRankedProviderLocations/5/9/1": [10, 11], "/GetPrimaryRankedProviderLocations/5/9/2": [12]}
    assert g.rank_one_trades(data.__getitem__, 5, 9, 10) == {"HVAC"}


def test_daily_count_follows_the_activity_days():
    r = random.Random(3)
    sat, mon = dt.date(2026, 10, 24), dt.date(2026, 10, 26)
    assert g.daily_count(r, 120, mon, (5, 6)) == 0
    avg = sum(g.daily_count(r, 120, sat, (5, 6)) for _ in range(2000)) / 2000
    assert 12 < avg < 15   # 120 a month over 2 days a week, 4.2 weeks
