"""Asset seeding (B-67): builds realistic assets per location from assets_catalog.json and creates them through the Subscriber API.
Commands: `agent assets plan | seed | audit | enrich`. The plan is deterministic per (store id, trade), so a rerun plans the same assets
and only the gap is created. Design and sources: docs/asset-seeding-design.md, docs/asset-seeding-research.md."""
import datetime as dt
import functools
import json
import random
import sys
import time
from pathlib import Path

from .client import ScError

CATALOG = Path(__file__).with_name("assets_catalog.json")
DEFAULT_TRADES = ["HVAC", "ELECTRICAL", "PLUMBING"]
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"   # no I, O or Q
MONTH = "ABCDEFGHJKLM"   # Lennox and Bradford White: I is skipped
YORK_MONTH = "ABCDEFGHKLMN"   # York: I and J are skipped
BRADFORD_YEAR = "ABCDEFGHJKLMNPSTWXYZ"   # A = 2004 or 2024; skips I, O, Q, R, U, V
EMPTY_FIELDS = {"ModelNo": "model", "SerialNo": "serial", "InstallDate": "install", "PurchaseDate": "purchase",
                "OriginalValue": "value", "Condition": "condition", "Area": "area", "Description": "description"}


# Issue-list equipment (Equipment column) -> asset type name, for B-23/B-24. Items not listed have no matching asset type.
ISSUE_ASSET = {"HVAC RTU": "RTU", "Electrical Panel": "Electrical Panel", "Generator": "Generator", "Exit Signs, Emergency Lights": "Exit Sign / Emergency Light",
               "Lighting": "LED Light Fixture", "Water Heater": "Water Heater", "Backflow Preventer": "Backflow Preventer",
               "Flushometer Valve": "Flushometer Valve"}


def pick(store, rng, store_id, item, trade=None):
    """The id of a seeded asset at the location for this issue's equipment, or of any seeded asset in `trade` when `trade` is given and the
    equipment has no match. None when there is none. Only assets the agent created are used (the `assets` table)."""
    skip = _refrigerant_types()
    rows = [r for r in store.db.execute("SELECT id, type, trade FROM assets WHERE location=?", (store_id,)).fetchall() if r["type"] not in skip]
    own = [r["id"] for r in rows if r["type"] == ISSUE_ASSET.get(item.strip())]
    return rng.choice(own) if own else rng.choice([r["id"] for r in rows if trade and r["trade"] == trade.upper()] or [None])


def _refrigerant_types():
    """A WO that checks out with a refrigerant asset stops at COMPLETED / PENDING REFRIGERANT USE, which blocks the review and the invoice,
    and no API call to answer it is known (seen on Prod 2026-11-06 and SB2). Those assets are not attached until one is found."""
    return {e["type"] for e in load_catalog()["entries"] if e.get("refrigerant")}


def load_catalog():
    return json.loads(CATALOG.read_text())


@functools.cache
def _targets():
    return set(load_catalog()["targets"])


def unseeded(store):
    """B-67 prompt: [(store id, [trade, ...])] for enabled locations where we hold Rank 1 in a trade that carries assets, the trade is
    switched on for seeding, and the agent has seeded none there yet. Reads only local state (the `rank1` cache and the `assets` table),
    so it is cheap enough for every page. Pairs listed in `assets.dismissed` ("STORE:TRADE") are left out."""
    cfg = store.get("assets", {})
    on = {t.upper() for t in cfg.get("trades", DEFAULT_TRADES)} & _targets()
    skip, rank1 = set(cfg.get("dismissed", [])), store.get("rank1", {})
    have = {(r["location"], (r["trade"] or "").upper()) for r in store.db.execute("SELECT DISTINCT location, trade FROM assets")}
    out = []
    for loc in store.db.execute("SELECT store_id FROM locations WHERE enabled=1 ORDER BY store_id"):
        sid = loc["store_id"]
        todo = sorted(t for t in {x.upper() for x in rank1.get(sid, {}).get("trades", [])} & on if (sid, t) not in have and f"{sid}:{t}" not in skip)
        if todo:
            out.append((sid, todo))
    return out


# --- serial formatters: (manufacture date, sequence, batch letter) -> serial. Formats: docs/asset-seeding-research.md ---
def _week(d):
    return min(52, d.timetuple().tm_yday // 7 + 1)


SERIALS = {
    "carrier": lambda d, n, k: f"{_week(d):02d}{d.year % 100:02d}{k}{n:05d}",
    "trane": lambda d, n, k: f"{d.year % 100:02d}{_week(d):02d}{n:05d}{k}",   # shortcut: sequence and factory layout inferred, confirm with a nameplate
    "lennox": lambda d, n, k: f"56{d.year % 100:02d}{MONTH[d.month - 1]}{n:05d}",
    "york": lambda d, n, k: f"{'NWAS'[LETTERS.index(k) % 4]}{d.year % 100 // 10}{YORK_MONTH[d.month - 1]}{d.year % 10}{n:06d}",
    "bradford": lambda d, n, k: f"{BRADFORD_YEAR[(d.year - 2004) % 20]}{MONTH[d.month - 1]}{n:08d}",
    "generic": lambda d, n, k: f"{k}{n:08d}",
}


def _install(rng, life, today):
    """Age in years: middle-weighted over the service life, with a 5% chance of an asset past its life."""
    years = life * rng.uniform(1.05, 1.3) if rng.random() < 0.05 else (rng.uniform(0, life) + rng.uniform(0, life)) / 2
    return today - dt.timedelta(days=int(years * 365.25))


def _describe(e, m):
    extra = next((f"{m[k]:g} {u}" if isinstance(m[k], (int, float)) else f"{m[k]} {u}".strip()
                  for k, u in (("tons", "ton"), ("kw", "kW"), ("amps", "A"), ("gallons", "gal"), ("size", "")) if k in m), "")
    return f"{m['brand']} {m['model']} {e['describe']}" + (f", {extra}" if extra else "")


def blueprint(cat, store_id, trade, today):
    """The full list of assets a location should have in one trade. Same inputs always give the same list."""
    rng = random.Random(f"{store_id}|{trade}")
    lo, hi = cat["targets"][trade]
    n = rng.randint(lo, hi)
    entries = [e for e in cat["entries"] if e["trade"] == trade]
    used, out, prefix = {}, [], store_id.replace("-", "")
    while len(out) < n:
        open_ = [e for e in entries if used.get(e["code"], 0) < e["max"]]
        if not open_:
            break
        e = rng.choices(open_, [x["weight"] for x in open_])[0]
        install = models = None
        for _ in range(8):   # a model may not exist yet (or any more) for the drawn year
            install = _install(rng, e["life_years"], today)
            models = [m for m in e["models"] if m.get("from_year", 0) <= install.year <= m.get("until_year", 9999)]
            if models:
                break
        if not models:
            used[e["code"]] = e["max"]
            continue
        size = min(rng.randint(2, 4) if e["max"] > 1 else 1, e["max"] - used.get(e["code"], 0), n - len(out))
        m, letter = rng.choice(models), rng.choice(LETTERS)
        made = install - dt.timedelta(days=rng.randint(30, 180))
        seq = rng.randint(10000, 89999)
        base = rng.uniform(*m.get("value", e["value"]))   # one price per batch; units bought together cost about the same
        for i in range(size):
            used[e["code"]] = used.get(e["code"], 0) + 1
            when = min(today, install + dt.timedelta(days=rng.randint(0, 25) if i else 0))
            frac = (today - when).days / 365.25 / e["life_years"]
            cond = max(5, min(100, round(100 - 60 * frac + rng.uniform(-8, 8))))
            out.append(dict(
                trade=trade, type=e["type"], code=e["code"], create_type=e.get("create_type", False), refrigerant=int(e.get("refrigerant", False)),
                tag=f"{prefix}-{e['code']}-{used[e['code']]:02d}", brand=m["brand"], model=m["model"], source=m["source"],
                serial=SERIALS[m["serial"]](made, seq + i, letter), install=when.isoformat() + "T08:00:00",
                purchase=(when - dt.timedelta(days=rng.randint(3, 30))).isoformat() + "T00:00:00",
                value=int(round(base * rng.uniform(0.95, 1.05) / 50) * 50), condition=min(cond, 39) if frac > 1 else cond,
                area=rng.choice(e["areas"]), description=_describe(e, m)))
    return out


def plan(cat, store_id, trades, existing, today):
    """Blueprint items still missing at the location. Existing assets (any origin) count toward each trade's target."""
    have_tags = {a["Tag"] for a in existing}
    out = []
    for t in trades:
        bp = blueprint(cat, store_id, t, today)
        have = sum(1 for a in existing if (a.get("Trade") or "").upper() == t)
        out += [b for b in bp if b["tag"] not in have_tags][:max(0, len(bp) - have)]
    return out


class Seeder:
    def __init__(self, store, rt, creator, today=None, sleep=time.sleep):
        self.store, self.rt, self.creator, self.sleep = store, rt, creator, sleep
        self.today, self.cat = today or dt.date.today(), load_catalog()

    def who(self, loc):
        return self.rt.user_for(loc["store_id"], "create")

    def trades(self, loc, only):
        enabled = {t.upper() for t in self.store.get("assets", {}).get("trades", DEFAULT_TRADES)}
        if only:
            return [t for t in only if t in enabled and t in self.cat["targets"]]
        return sorted(enabled & set(self.cat["targets"]) & {t.upper() for t in self.creator.our_trades(loc)})

    def existing(self, loc):
        app, user = self.who(loc)
        return (app.call(user, "GET", "/assets", {"locationId": loc["db_id"]}, write=False) or {}).get("Assets") or []

    def brands(self, loc):
        """name (lower case) -> id from GET /assets/brands, cached a week. Every catalog brand must match its pinned id."""
        f = self.store.dir / "assets-brands.json"
        if not f.exists() or time.time() - f.stat().st_mtime > 7 * 86400:
            app, user = self.who(loc)
            f.write_text(json.dumps(app.call(user, "GET", "/assets/brands", write=False)))
        raw = json.loads(f.read_text())
        by = {b["Name"].lower(): b["Id"] for b in (raw if isinstance(raw, list) else next(v for v in raw.values() if isinstance(v, list)))}
        for name, want in self.cat["brands"].items():
            if by.get(name.lower(), want) != want:
                sys.exit(f"Brand {name!r} is id {by[name.lower()]} here but the catalog pins {want}. Stopping.")
        return {n.lower(): i for n, i in self.cat["brands"].items() if n.lower() in by}

    def types(self, loc):
        app, user = self.who(loc)
        r = app.call(user, "GET", "/assettypes", write=False)
        return r if isinstance(r, list) else r.get("AssetTypes", r)

    def build(self, loc, only=None):
        """Returns (items, types to create, warnings). Items whose brand or type cannot be resolved are dropped with a warning."""
        trades, warns = self.trades(loc, only), []
        if not trades:
            return [], [], [f"{loc['store_id']}: no trade to seed (not Rank 1 for any enabled trade; use --trade to override)"]
        items = plan(self.cat, loc["store_id"], trades, self.existing(loc), self.today)
        brands, types = self.brands(loc), {(t["Name"].lower(), t["PrimaryTrade"].upper()): t for t in self.types(loc)}
        keep, make = [], {}
        for it in items:
            if it["brand"].lower() not in brands:
                warns.append(f"{it['tag']}: brand {it['brand']!r} not in the brand list, skipped")
            elif (it["type"].lower(), it["trade"]) not in types and not it["create_type"]:
                warns.append(f"{it['tag']}: asset type {it['type']!r} does not exist and the catalog does not create it, skipped")
            else:
                keep.append(it)
                if (it["type"].lower(), it["trade"]) not in types:
                    make[(it["type"], it["trade"])] = None
        return keep, sorted(make), warns

    def approved(self, loc):
        return self.store.get("env") != "prod" or loc["store_id"] in self.store.get("assets", {}).get("approved_locations", [])

    def seed(self, loc, items, new_types, rate):
        app, user = self.who(loc)
        brands, trade_ids = self.brands(loc), {}
        for t in self.types(loc):
            trade_ids.setdefault(t["PrimaryTrade"].upper(), t["TradeId"])
        for name, trade in new_types:
            r = app.call(user, "POST", "/assettypes", body={"Name": name, "PrimaryTrade": trade, "TradeId": trade_ids[trade], "IsActive": True, "IsCircuit": False},
                         action="create_asset_type", write=True)
            tid = r.get("Id") if isinstance(r, dict) else None
            for _ in range(5):   # the list can lag a create by a moment on Production
                if tid:
                    break
                tid = next((t["Id"] for t in self.types(loc) if t["Name"] == name and t["PrimaryTrade"].upper() == trade), None)
                if not tid:
                    self.sleep(3)
            self.store.db.execute("INSERT OR IGNORE INTO asset_types(id, name, trade, created_at) VALUES(?,?,?,?)", (tid, name, trade, time.time()))
            self.store.db.commit()
            print(f"created asset type {name} ({trade})")
        types = {(t["Name"].lower(), t["PrimaryTrade"].upper()): t["Id"] for t in self.types(loc)}
        made = 0
        for it in items:
            body = {"LocationId": loc["db_id"], "StoreId": loc["store_id"], "Tag": it["tag"], "AssetTag": it["tag"], "Active": True,
                    "AssetTypeId": types[(it["type"].lower(), it["trade"])], "BrandId": brands[it["brand"].lower()], "Manufacturer": it["brand"],
                    "UsesRefrigerant": it["refrigerant"], **{f: it[k] for f, k in EMPTY_FIELDS.items()}}
            try:
                r = app.call(user, "POST", "/assets", body=body, action="create_asset", write=True)
            except ScError as e:
                if e.status != 400:
                    raise   # anything but a per-asset validation error stops the run
                print(f"skipped {it['tag']}: {e.body[:120]}")
                continue
            self.store.db.execute("INSERT OR IGNORE INTO assets(id, location, tag, trade, type, created_at) VALUES(?,?,?,?,?,?)",
                                  (r["Id"], loc["store_id"], it["tag"], it["trade"], it["type"], time.time()))
            self.store.db.commit()
            made += 1
            print(f"created {it['tag']} id {r['Id']}")
            self.sleep(60 / rate)
        return made

    def missing(self, loc, ids=None):
        """(asset id, tag, {field: value to fill}) for agent-created assets (plus `ids`) that have empty fields."""
        app, user = self.who(loc)
        ids = {r["id"] for r in self.store.db.execute("SELECT id FROM assets WHERE location=?", (loc["store_id"],))} | set(ids or ())
        bp = {b["tag"]: b for t in self.cat["targets"] for b in blueprint(self.cat, loc["store_id"], t, self.today)}
        listed = {a["Id"]: a for a in self.existing(loc)}   # one call: list items carry every field enrich needs (checked on SB2, 2026-11-03)
        out = []
        for i in sorted(ids):
            a = listed.get(i) or app.call(user, "GET", f"/assets/{i}", write=False)
            empty = {f: bp[a["Tag"]][k] for f, k in EMPTY_FIELDS.items() if a.get(f) in (None, "", 0) and f != "Condition" or a.get(f) is None and f == "Condition"
                     if a["Tag"] in bp}
            out.append((a, empty))
        return out

    def enrich(self, loc, rows):
        app, user = self.who(loc)
        for a, fill in rows:
            if not fill:
                continue
            body = {"Id": a["Id"], **{k: a[k] for k in ("LocationId", "AssetTypeId", "BrandId", "Tag", "UsesRefrigerant")}, **fill}
            app.call(user, "PUT", "/assets", body=body, action="enrich_asset", write=True)
            print(f"filled {a['Tag']}: {', '.join(fill)}")


def _locs(store, args):
    rows = store.db.execute("SELECT * FROM locations WHERE enabled=1" + ("" if args.all else " AND store_id=?"), () if args.all else (args.location,)).fetchall()
    return rows or sys.exit("No such enabled location. Give --location <store id> or --all.")


def cmd(args, store):
    from .cli import build_engine
    from .creator import Creator
    _, rt = build_engine(store, with_rt=True)
    s = Seeder(store, rt, Creator(store, rt, rt.rng))
    only = [t.upper() for t in args.trade or []]
    for loc in _locs(store, args):
        print(f"== {loc['store_id']}")
        if args.action == "audit":
            have = {}
            for a in s.existing(loc):
                have[a.get("Trade")] = have.get(a.get("Trade"), 0) + 1
            for t in s.cat["targets"]:
                print(f"  {t:<11} have {have.get(t, 0):>3}  target {len(blueprint(s.cat, loc['store_id'], t, s.today))}")
            for a, fill in s.missing(loc):
                if fill:
                    print(f"  {a['Tag']}: empty {', '.join(fill)}")
            continue
        if args.action == "enrich":
            rows = s.missing(loc, args.include)
            for a, fill in rows:
                print(f"  {a['Tag']}: " + (", ".join(f"{f}={v!r}" for f, v in fill.items()) or "nothing to fill"))
            if args.yes and s.approved(loc):
                s.enrich(loc, rows)
            elif not args.yes:
                print("Not applied. Add --yes to write.")
            else:
                print("Production: add this location to assets.approved_locations first (agent set).")
            continue
        items, new_types, warns = s.build(loc, only)
        for w in warns:
            print("  warning:", w)
        for n, t in new_types:
            print(f"  would create asset type {n} ({t})")
        for it in items:
            print(f"  {it['tag']:<16} {it['type']:<26} {it['brand']} {it['model']}  sn {it['serial']}  inst {it['install'][:10]}  "
                  f"${it['value']} cond {it['condition']} {it['area']}  [{it['source']}]")
        print(f"  {len(items)} assets, {len(new_types)} asset types to create")
        if args.action == "seed" and items:
            if not args.yes:
                print("Not written. Add --yes to create these.")
            elif not s.approved(loc):
                print("Production: add this location to assets.approved_locations first (agent set).")
            else:
                print(f"Created {s.seed(loc, items, new_types, args.rate)} assets.")


def add_parser(sub):
    p = sub.add_parser("assets", help="seed realistic assets: plan (dry run), seed, audit, enrich")
    p.add_argument("action", choices=["plan", "seed", "audit", "enrich"])
    p.add_argument("--location")
    p.add_argument("--all", action="store_true")
    p.add_argument("--trade", action="append", help="limit to this trade; also overrides the Rank 1 filter (repeatable)")
    p.add_argument("--yes", action="store_true", help="seed and enrich write only with this")
    p.add_argument("--rate", type=float, default=5, help="asset creates per minute (default 5, leaves room for a running agent)")
    p.add_argument("--include", type=int, action="append", help="enrich: also this asset id the agent did not create")
    return p
