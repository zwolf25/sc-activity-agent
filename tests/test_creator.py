import random

from sc_activity_agent.client import ScError
from sc_activity_agent.creator import Creator
from sc_activity_agent.store import Store

NOW = 1_761_566_400  # Mon 2025-10-27 12:00 UTC (08:00 New York)
IL = {"ProblemTypes": [{"Name": "Doors", "Items": [{"Name": "Automatic Door", "Problems": [
    {"Name": "Noisy", "Trade": "DOORS", "TradeId": 1, "Priority": "NORMAL", "Category": {"Default": "REPAIR"}, "CategoryId": 9, "Nte": "500"}]}]},
    {"Name": "Elec", "Items": [{"Name": "Panel", "Problems": [
        {"Name": "Breaker", "Trade": "ELECTRICAL", "TradeId": 2, "Priority": "NORMAL", "Category": {"Default": "REPAIR"}, "CategoryId": 9, "Nte": "100"}]}]}]}


class FakeApp:
    def __init__(self):
        self.calls = []

    def call(self, user, method, path, params=None, body=None, **kw):
        self.calls.append((method, path, body))
        if path.endswith("/headers"):
            return {"Headers": [{"Id": 110058, "DashboardId": 3151}]}
        if path.endswith("/issuelist"):
            return IL
        if path == "/issuelist/issuechoice":
            if params["equipmentType"] == "Panel":
                raise ScError(400, "Cannot find issue choice", path)
            return {}
        if path.startswith("/GetPrimaryRankedProviderTrades"):
            return [{"Trade": "DOORS", "TradeId": 1}]
        if path.startswith("/GetPrimaryRankedProviderLocations"):
            return [10]
        if method == "POST":
            return {"id": 9001}


def setup(tmp_path, per_month=2000):
    s = Store(tmp_path)
    s.db.execute("INSERT INTO connections VALUES(1,'subscriber','S','c','x',NULL)")
    s.db.execute("INSERT INTO connections VALUES(2,'provider','P','c','x',77)")
    s.db.execute("INSERT INTO users VALUES(1,1,'sub',?, '',NULL)", (s.enc("pw"),))
    s.db.execute("INSERT INTO roles VALUES('*','create_wo','[1]','single')")
    s.db.execute("INSERT INTO locations(store_id,db_id,subscriber_id,name,lat,lon,tz) VALUES('HQ',10,5,'HQ',1,2,'America/New_York')")
    s.db.commit()
    s.put("behavior", {"wo_per_month": per_month})
    app = FakeApp()
    from sc_activity_agent.handlers import Runtime
    return s, app, Creator(s, Runtime(s, {1: app}, random.Random(1)), random.Random(2), clock=lambda: NOW + 9 * 3600)


def test_creates_only_rank_one_trade_and_persists_plan(tmp_path):
    s, app, c = setup(tmp_path)
    out = c.tick()
    assert out == [("HQ", 9001)]
    post = next(b for m, p, b in app.calls if m == "POST")
    assert post["ContractInfo"]["TradeName"] == "DOORS" and post["IssueListHeaderId"] == 110058 and "Status" not in post
    assert s.db.execute("SELECT COUNT(*) FROM steps").fetchone()[0] > 5


def test_failed_create_is_not_retried_and_is_logged(tmp_path):
    s, app, c = setup(tmp_path)
    s.db.execute("DELETE FROM connections WHERE side='provider'")
    s.db.commit()
    first = c.tick()
    assert "no eligible trade" in first[0][1]
    assert s.get("create_errors")
    assert not [1 for m, p, b in app.calls if m == "POST"]


def test_paused_and_weekend_create_nothing(tmp_path):
    s, app, c = setup(tmp_path)
    s.put("paused_at", NOW)
    assert c.tick() == []
    s.put("paused_at", None)
    c.clock = lambda: NOW + 5 * 86400 + 9 * 3600  # Saturday
    assert c.tick() == []


def test_unresolvable_issue_is_redrawn_not_posted(tmp_path):
    s, app, c = setup(tmp_path)
    orig = app.call

    def both_trades(user, method, path, params=None, body=None, **kw):
        if path.startswith("/GetPrimaryRankedProviderTrades"):
            return [{"Trade": "DOORS", "TradeId": 1}, {"Trade": "ELECTRICAL", "TradeId": 2}]
        return orig(user, method, path, params, body, **kw)
    app.call = both_trades
    s.put("trade_mix", {"ELECTRICAL": 1000, "DOORS": 1})   # Panel is drawn first almost always, and it does not resolve
    assert c.tick() == [("HQ", 9001)]
    posts = [b for m, p, b in app.calls if m == "POST"]
    assert len(posts) == 1 and posts[0]["IssueRequestInfo"]["AssetType"] == "Automatic Door"


def test_resync_rereads_rank_one_and_records_skipped_trades(tmp_path):
    s, app, c = setup(tmp_path)
    loc = s.db.execute("SELECT * FROM locations").fetchone()
    s.put("rank1", {"HQ": {"at": NOW + 9 * 3600, "trades": ["STALE"]}})   # fresh cache: normal reads would trust it
    assert c.our_trades(loc) == {"STALE"}
    assert c.resync(loc) == {"DOORS"}
    hit = s.get("rank1")["HQ"]
    assert hit["trades"] == ["DOORS"] and hit["skipped"] == ["ELECTRICAL"]
