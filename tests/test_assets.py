import datetime as dt
import sqlite3

from sc_activity_agent import assets
from sc_activity_agent.client import ScError
from sc_activity_agent.store import Store

TODAY = dt.date(2026, 11, 2)
CAT = assets.load_catalog()


def bp(trade="PLUMBING", store="HQ-NYC"):
    return assets.blueprint(CAT, store, trade, TODAY)


def test_blueprint_deterministic_and_within_rules():
    assert bp() == bp()
    assert bp() != bp(store="ZW123")
    for t, (lo, hi) in CAT["targets"].items():
        items = bp(t)
        assert len(items) <= hi and len({i["tag"] for i in items}) == len(items)
        for i in items:
            assert i["serial"] and i["purchase"] < i["install"] and 5 <= i["condition"] <= 100
            assert dt.date.fromisoformat(i["install"][:10]) <= TODAY


def test_plan_counts_existing_toward_target():
    full = bp()
    assert assets.plan(CAT, "HQ-NYC", ["PLUMBING"], [], TODAY) == full
    have = [{"Tag": "OTHER-1", "Trade": "Plumbing"}]
    assert len(assets.plan(CAT, "HQ-NYC", ["PLUMBING"], have, TODAY)) == len(full) - 1
    have = [{"Tag": full[0]["tag"], "Trade": "PLUMBING"}]
    assert full[0]["tag"] not in {i["tag"] for i in assets.plan(CAT, "HQ-NYC", ["PLUMBING"], have, TODAY)}


def test_serial_formats():
    d = dt.date(2019, 9, 5)
    assert assets.SERIALS["bradford"](d, 55976, "A") == "TJ00055976"   # 2019 = T, September = J
    assert assets.SERIALS["lennox"](d, 1234, "A") == "5619J01234"
    assert assets.SERIALS["york"](d, 123456, "A") == "N1K9123456"


def test_migration_from_v1_db(tmp_path):
    c = sqlite3.connect(tmp_path / "agent.db")
    c.executescript(__import__("sc_activity_agent.store", fromlist=["x"]).SCHEMA)
    c.execute("ALTER TABLE users ADD COLUMN can_do TEXT NOT NULL DEFAULT '[]'")
    c.execute("CREATE TABLE contracts(location TEXT)")   # shipped before B-63 dropped it
    c.execute("PRAGMA user_version=1")
    c.commit()
    c.close()
    s = Store(tmp_path)
    assert s.db.execute("PRAGMA user_version").fetchone()[0] == 3
    s.db.execute("SELECT * FROM assets")
    assert not s.db.execute("SELECT 1 FROM sqlite_master WHERE name='contracts'").fetchone()


class FakeApp:
    def __init__(self, fail=()):
        self.fail, self.posts, self.n = set(fail), [], 100

    def call(self, user, method, path, params=None, body=None, **kw):
        if method == "GET" and path == "/assettypes":
            return [{"Id": 1, "Name": n, "PrimaryTrade": t, "TradeId": 9} for n, t in
                    {(e["type"], e["trade"]) for e in CAT["entries"]}]
        if method == "GET" and path == "/assets":
            self.lists = getattr(self, "lists", 0) + 1
            return {"Assets": getattr(self, "listed", [])}
        if method == "GET" and path.startswith("/assets/"):
            self.gets = getattr(self, "gets", 0) + 1
            return {"Id": int(path.split("/")[-1]), "Tag": "ONE-OFF", "ModelNo": "x"}
        if method == "POST":
            if body["Tag"] in self.fail:
                raise ScError(400, "bad asset", path)
            self.posts.append(body)
            self.n += 1
            return {"Id": self.n}


def seeder(tmp_path, app):
    s = Store(tmp_path)
    (tmp_path / "assets-brands.json").write_text(
        '[' + ",".join(f'{{"Name":"{n}","Id":{i}}}' for n, i in CAT["brands"].items()) + ']')
    rt = type("RT", (), {"user_for": lambda self, st, a: (app, "u")})()
    sd = assets.Seeder(s, rt, None, today=TODAY, sleep=lambda x: None)
    return s, sd


def test_seed_logs_bad_asset_and_continues_and_rerun_creates_nothing(tmp_path):
    first = bp()[0]["tag"]
    app = FakeApp(fail={first})
    s, sd = seeder(tmp_path, app)
    loc = {"store_id": "HQ-NYC", "db_id": 5}
    items = assets.plan(CAT, "HQ-NYC", ["PLUMBING"], [], TODAY)
    made = sd.seed(loc, items, [], 600)
    assert made == len(items) - 1 and first not in {p["Tag"] for p in app.posts}
    assert s.db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == made
    have = [{"Tag": p["Tag"], "Trade": "PLUMBING"} for p in app.posts]
    again = assets.plan(CAT, "HQ-NYC", ["PLUMBING"], have, TODAY)
    assert [i["tag"] for i in again] == [first]   # only the one that failed is retried


def test_value_follows_model_and_batch():
    for t in ("HVAC", "ELECTRICAL"):
        for store in ("HQ-NYC", "ZW123", "ST-9"):
            for i in assets.blueprint(CAT, store, t, TODAY):
                m = next(m for e in CAT["entries"] if e["code"] == i["code"] for m in e["models"] if m["model"] == i["model"])
                lo, hi = m.get("value", next(e["value"] for e in CAT["entries"] if e["code"] == i["code"]))
                assert lo * 0.94 <= i["value"] <= hi * 1.06 + 50


def test_missing_reads_the_list_once_and_gets_only_unlisted_ids(tmp_path):
    first = bp()[0]
    app = FakeApp()
    app.listed = [{"Id": 11, "Tag": first["tag"], "ModelNo": "", "SerialNo": "S", "InstallDate": "d", "PurchaseDate": "d",
                   "OriginalValue": 5, "Condition": 50, "Area": "Roof", "Description": "d"}]
    s, sd = seeder(tmp_path, app)
    s.db.execute("INSERT INTO assets(id, location, tag, trade, type, created_at) VALUES(11,'HQ-NYC',?,'PLUMBING','t',0)", (first["tag"],))
    rows = sd.missing({"store_id": "HQ-NYC", "db_id": 5}, ids=[99])
    assert app.lists == 1 and app.gets == 1   # only the id the list does not hold
    assert [a["Id"] for a, _ in rows] == [11, 99]
    assert list(rows[0][1]) == ["ModelNo"]
