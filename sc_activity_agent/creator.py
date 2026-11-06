"""Creates new WOs on schedule. Each day it rolls how many WOs each enabled location gets, spreads them over activity hours,
and at each slot creates one WO (Subscriber API) and persists its full plan for the engine."""
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from . import assets, generator, photos, planner
from .alerts import Alerts
from .client import ScError
from .engine import add_plan

DASH_TTL = 3600   # B-91: how long the user's dashboard is trusted before the profile is read again
DEFAULT_AREA = 3          # SALES FLOOR: accepts every item of DOORS, HVAC and GENERAL MAINTENANCE on dashboard 3151
RANK_TTL = 24 * 3600


def user_dashboard(store, app, user, now, force=False):
    """Read the user's default dashboard from GET /users/current/profile (api-notes 2026-11-05). Cached per user for DASH_TTL.
    Returns {"id", "name", "at"}; raises ScError(409) when the profile names none."""
    cache = store.get("user_dashboard") or {}
    hit = cache.get(user[0])
    if hit and not force and now - hit["at"] < DASH_TTL:
        return hit
    prof = (app.call(user, "GET", "/users/current/profile", None, action="dashboard") or {}).get("UserProfile") or {}
    did = prof.get("DefaultScUserSetupId")
    if not did:
        raise ScError(409, f"{user[0]} has no dashboard assigned in ServiceChannel", "/users/current/profile")
    name = next((d.get("Name", "") for d in prof.get("Dashboards") or [] if d.get("SetupId") == did), "")
    cache[user[0]] = {"id": did, "name": name, "at": now}
    store.put("user_dashboard", cache)
    return cache[user[0]]


def check_user(store, app, user, subscriber_id, now, force=True):
    """B-92: read one Subscriber user's own dashboard and, when the Subscriber ID is known, its issue list. Returns and stores
    {user, id, name, list, error} in settings key dashboard_info (username -> row). `id` is None when the user has no readable dashboard,
    and the console then refuses to tick Create WOs for that user."""
    row = {"user": user[0], "id": None, "name": "", "list": "", "error": ""}
    try:
        d = user_dashboard(store, app, user, now, force=force)
        row.update(id=d["id"], name=d["name"])
        if subscriber_id:
            heads = app.call(user, "GET", f"/api/subscribers/{subscriber_id}/issuelist/headers", action="dashboards")["Headers"]
            row["list"] = next((h["Name"] for h in heads if h["DashboardId"] == d["id"]), "")
    except (ScError, OSError) as e:
        row["error"] = f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)
    info = store.get("dashboard_info") or {}
    if not isinstance(info, dict):   # v0.20.0/1 stored a list
        info = {}
    info[user[0]] = row
    store.put("dashboard_info", info)
    return row


def check_users(store, subscriber_id, now, force=True):
    """check_user for every Subscriber user. Used by the Subscriber ID form and Check setup."""
    from .client import ScApp
    return [check_user(store, ScApp(store.get("env"), r["client_id"], store.dec(r["client_secret"]), store=store, role="subscriber"),
                       (r["username"], store.dec(r["password"])), subscriber_id, now, force)
            for r in store.db.execute("SELECT u.username, u.password, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id "
                                      "WHERE c.side='subscriber' ORDER BY u.id")]


FAIL_ALERT = 3   # B-86: failed creates in a row before an alert is sent


class Creator:
    def __init__(self, store, rt, rng, clock=time.time):
        self.store, self.rt, self.rng, self.clock = store, rt, rng, clock
        self._pinned = None
        self.resolves = {}   # (location db id, problem type, item, problem) -> bool

    # --- API reads (Subscriber) ---
    def _sub(self, loc):
        if self._pinned:   # B-92: one user for the whole create, so the pool, issuechoice and POST all see the same dashboard
            return self._pinned
        return self.rt.user_for(loc["store_id"], "create")

    def _get(self, loc, path, params=None):
        app, user = self._sub(loc)
        return app.call(user, "GET", path, params, action="create_lookup")

    def dashboard(self, loc):
        """B-91: the dashboard of the Subscriber user that creates WOs. POST /workorders resolves issues on that user's own dashboard, so the
        agent draws from it instead of a dashboard chosen here. Falls back to the last known value when the profile cannot be read."""
        app, user = self._sub(loc)
        try:
            return user_dashboard(self.store, app, user, self.clock())["id"]
        except (ScError, OSError):
            hit = (self.store.get("user_dashboard") or {}).get(user[0])
            if hit:
                return hit["id"]
            raise

    def _header_id(self, loc, dashboard):
        known = self.store.get("header_ids", {})
        if str(dashboard) not in known:
            for h in self._get(loc, f"/api/subscribers/{loc['subscriber_id']}/issuelist/headers")["Headers"]:
                known[str(h["DashboardId"])] = h["Id"]
            self.store.put("header_ids", known)
        return known[str(dashboard)]

    def _issues(self, loc, dashboard):
        f = self.store.dir / f"issuelist-{dashboard}.json"
        if not f.exists() or self.clock() - f.stat().st_mtime > 7 * 86400:
            f.write_text(json.dumps(self._get(loc, f"/api/subscribers/{loc['subscriber_id']}/storedashboards/{dashboard}/issuelist")))
        return generator.issues(json.loads(f.read_text()))

    def our_trades(self, loc, force=False):
        """Trades where Rank 1 at this location is one of our provider connections. Cached for RANK_TTL; force re-reads now."""
        cache = self.store.get("rank1", {})
        hit = cache.get(loc["store_id"])
        if hit and "owners" in hit and not force and self.clock() - hit["at"] < RANK_TTL:   # no owners = an older cache entry: re-read
            return set(hit["trades"])
        owners = {}   # trade -> provider id, so a WO's provider-side steps run as that provider's users
        get = lambda p: self._get(loc, p)
        for c in self.store.db.execute("SELECT provider_id FROM connections WHERE side='provider' AND provider_id IS NOT NULL"):
            for t in generator.rank_one_trades(get, loc["subscriber_id"], c["provider_id"], loc["db_id"]):
                owners.setdefault(t, c["provider_id"])
        trades = set(owners)
        if trades:   # never cache an empty answer: a transient API blip would block creation for a day
            cache[loc["store_id"]] = {"at": self.clock(), "trades": sorted(trades), "owners": owners}
            self.store.put("rank1", cache)
        return trades

    def resync(self, loc):
        """Re-read Rank 1 now and record which trades on the location's issue list are skipped because another provider is Rank 1."""
        ours = self.our_trades(loc, force=True)
        listed = {i["trade"] for i in self._issues(loc, self.dashboard(loc))}
        cache = self.store.get("rank1", {})
        if loc["store_id"] in cache:
            cache[loc["store_id"]]["skipped"] = sorted(listed - ours)
            self.store.put("rank1", cache)
        return ours

    def _resolves(self, loc, issue):
        """True if POST /workorders can resolve this issue. The POST looks the issue up on the location's own dashboard, not the
        IssueListHeaderId we send, and issuechoice without setupId does the same lookup read-only. A 400 here is the 502 a create would
        hit, which would leave a VOID shell."""
        key = (self._sub(loc)[1][0], loc["db_id"], issue["problem_type"], issue["item"], issue["problem"])
        if key not in self.resolves:
            try:
                self._get(loc, "/issuelist/issuechoice", {"problemType": issue["problem_type"], "equipmentType": issue["item"],
                                                          "problemCode": issue["problem"], "locationId": loc["db_id"]})
                self.resolves[key] = True
            except ScError as e:
                if e.status != 400:
                    raise
                self.resolves[key] = False
        return self.resolves[key]

    # --- daily slots ---
    def _roll_day(self, loc):
        b = {**planner.DEFAULTS, **self.store.get("behavior", {})}
        tz = ZoneInfo(loc["tz"] or "America/New_York")
        today = dt.datetime.fromtimestamp(self.clock(), tz).date()
        slots = self.store.get("create_slots", {"day": {}, "due": []})
        if slots["day"].get(loc["store_id"]) == today.isoformat():
            return slots
        slots["day"][loc["store_id"]] = today.isoformat()
        n = generator.daily_count(self.rng, b["wo_per_month"], today, b["days"])
        lo = dt.datetime.combine(today, dt.time(int(b["hours_start"])), tz).timestamp()
        hi = dt.datetime.combine(today, dt.time(min(int(b["hours_end"]), 23)), tz).timestamp() - 1800
        slots["due"] += [{"loc": loc["store_id"], "at": self.rng.uniform(lo, max(lo, hi))} for _ in range(n)]
        self.store.put("create_slots", slots)
        return slots

    def tick(self):
        """Create at most one WO per call. Returns [(store_id, sc_id or error)]."""
        if self.store.get("paused_at") is not None:
            return []
        out = []
        for loc in self.store.db.execute("SELECT * FROM locations WHERE enabled=1"):
            slots = self._roll_day(loc)
            due = [s for s in slots["due"] if s["loc"] == loc["store_id"] and s["at"] <= self.clock()]
            if not due or out:
                continue
            slots["due"].remove(due[0])   # drop first: a failed create is never retried blindly (it leaves a VOID shell)
            self.store.put("create_slots", slots)
            try:
                out.append((loc["store_id"], self.create(loc)))
                self.store.put("create_streak", 0)
            except ScError as e:
                streak = (self.store.get("create_streak") or 0) + 1
                self.store.put("create_streak", streak)
                if streak >= FAIL_ALERT:
                    Alerts(self.store).create_failed(streak, loc["store_id"], e)
                errs = self.store.get("create_errors", [])[-19:]
                errs.append({"at": self.clock(), "location": loc["store_id"], "error": str(e)})
                self.store.put("create_errors", errs)
                out.append((loc["store_id"], str(e)))
        return out

    def create(self, loc):
        self._pinned = self.rt.user_for(loc["store_id"], "create")
        try:
            return self._create(loc)
        finally:
            self._pinned = None

    def _create(self, loc):
        now = self.clock()
        dashboard = self.dashboard(loc)
        area = self.store.get("area_id", DEFAULT_AREA)
        ours = self.our_trades(loc)
        pool = generator.eligible(self._issues(loc, dashboard), ours)
        if not pool:
            raise ScError(409, f"no eligible trade at {loc['store_id']} (no Rank 1 provider connection)", "create")
        issue = None
        for _ in range(8):   # redraw until one resolves on the location's dashboard; bounded to stay under the rate limit
            cand = generator.pick(self.rng, pool, self.store.get("trade_mix"))
            if self._resolves(loc, cand):
                issue = cand
                break
            pool = [i for i in pool if (i["problem_type"], i["item"], i["problem"]) != (cand["problem_type"], cand["item"], cand["problem"])]
        if not issue:
            raise ScError(409, f"no issue resolves on the dashboard of {loc['store_id']}", "create")
        b = {**planner.DEFAULTS, **self.store.get("behavior", {})}
        tz = loc["tz"] or "America/New_York"
        # an EMERGENCY issue is the one case where we pick a same-day ETA; every behavior then keys off that ETA, not the label
        hrs = b["emergency_hours"]
        eta = now + self.rng.randint(1800, max(1800, int(hrs * 3600 * 0.9))) if issue["priority"] == "EMERGENCY" and hrs else None
        plan = planner.build_plan(self.rng, now, b, tz, eta=eta)
        first_in = next((s["payload"]["from_ts"] for s in plan if s["kind"] == "reschedule"), None) \
            or next((s["due_at"] for s in plan if s["kind"] == "check_in"), now + 2 * 86400)   # a rescheduled WO is created with its original date; a declined one has no visit
        sched = dt.datetime.fromtimestamp(first_in, ZoneInfo(tz))
        locd = {"subscriber_id": loc["subscriber_id"], "id": loc["db_id"], "store_id": loc["store_id"]}
        body = generator.payload(issue, locd, self._header_id(loc, dashboard), area, sched.replace(tzinfo=None),
                                 dt.datetime.fromtimestamp(now, ZoneInfo(tz)).replace(tzinfo=None), test=bool(self.store.get("test_flag", False)))
        asset = assets.pick(self.store, self.rng, loc["store_id"], issue["item"]) if b["asset_on_create"] and self.rng.random() * 100 < b["asset_on_create"] else None
        if asset:
            body["AssetId"] = asset
        app, user = self._sub(loc)
        r = app.call(user, "POST", "/workorders", body=body, action="create_wo", write=True)
        ctx = dict(trade=issue["trade"], issue=issue["problem"], location=loc["name"] or loc["store_id"],
                   sched_day=sched.strftime("%A"), eta=sched.strftime("%I:%M %p").lstrip("0"),
                   eta_end=(sched + dt.timedelta(hours=2)).strftime("%I:%M %p").lstrip("0"), area="sales floor",
                   equipment=issue["item"], amount="", nte=issue["nte"], category=issue["category"])
        if asset:
            ctx["asset_id"] = asset
        pid = self.store.get("rank1", {}).get(loc["store_id"], {}).get("owners", {}).get(issue["trade"])
        if pid:
            ctx["provider_id"] = pid
        if self.rng.random() * 100 < b["photo_before"]:
            self._attach_before(app, user, r["id"], issue["trade"], ctx, loc["store_id"])
        add_plan(self.store, loc["store_id"], issue["trade"], r["id"], plan, ctx, now)
        return r["id"]

    def _attach_before(self, app, user, wo_id, trade, ctx, location):
        """B-52: a before photo on the new WO. The WO already exists, so any refusal (even a pause) is skipped rather than lose its plan."""
        pic = photos.pick(trade, "before", self.rng, issue=f"{ctx.get('equipment', '')} {ctx.get('issue', '')}",
                          avoid=photos.recent(self.store, location))
        if not pic:
            return
        try:
            app.call(user, "POST", f"/workorders/{wo_id}/attachments", action="attach_before", wo=wo_id, write=True,
                     parts=photos.attach_parts(pic, "Photo of the issue", as_list=False))
            ctx["photo_set"] = pic[0]
        except ScError:
            pass
