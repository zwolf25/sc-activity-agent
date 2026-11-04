"""B-71: daily limits on WOs created and API calls. Counts come from the audit log, per local day in the instance time zone.
0 turns a limit off. Reaching a limit pauses the agent (the same pause as the Pause button) and sends an alert."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .alerts import Alerts

# About 3.5x the load of the default 120 WOs a month at two locations; a wrong slider or a plan bug stops here.
DEFAULTS = {"wo_per_day": 40, "calls_per_day": 3000}
LABELS = {"wo_per_day": "work orders created today", "calls_per_day": "API calls today"}


def limits(store):
    return {**DEFAULTS, **store.get("caps", {})}


def used(store, now=None):
    now = now or time.time()
    day = datetime.fromtimestamp(now, ZoneInfo(store.get("tz", "America/New_York"))).replace(hour=0, minute=0, second=0, microsecond=0)
    r = store.db.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(action='create_wo' AND http<400), 0) AS wos FROM api_log WHERE ts>=?",
                         (day.timestamp(),)).fetchone()
    return {"wo_per_day": r["wos"], "calls_per_day": r["calls"]}


def reached(store, now=None):
    """The first limit that is used up, as text, or None."""
    lim, use = limits(store), used(store, now)
    for k, label in LABELS.items():
        if lim[k] and use[k] >= lim[k]:
            return f"{use[k]} {label} (limit {lim[k]})"


def check(store, clock=time.time):
    """One agent loop step: pause when a limit is reached. Returns log lines for the loop."""
    if store.get("paused_at") is not None:
        return []
    now = clock()
    why = reached(store, now)
    if not why:
        if store.get("cap_hit"):
            store.put("cap_hit", None)
        return []
    store.put("paused_at", now)
    store.put("cap_hit", {"at": now, "why": why})
    Alerts(store).send("cap", f"Paused by a daily limit: {why}. Raise the limit on the Settings page or wait for tomorrow, then Resume.", event="cap_hit")
    return [("limit", f"paused: {why}")]
