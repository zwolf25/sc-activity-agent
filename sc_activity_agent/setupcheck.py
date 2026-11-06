"""B-87: Check setup. Runs every setup test against ServiceChannel and records each result with its fix, so a new instance shows all
its problems at once instead of one error at a time. Reads only; creates nothing. Locations are capped to keep the run short under the
rate limit."""
import time

from .client import ScApp, ScError
from .creator import Creator, check_users
from .hints import hint

MAX_LOCATIONS = 5


def _why(e):
    return f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)


def run(store, rt):
    """Returns [{label, ok, detail}] and saves it (with the time) in store key `setup_check`."""
    rows = []
    add = lambda label, ok, detail="": rows.append(dict(label=label, ok=ok, detail=detail))
    env = store.get("env")
    for u in store.db.execute("SELECT u.username, u.password, c.name, c.side, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id ORDER BY c.id, u.id"):
        label = f"Sign in: {u['username']} ({u['side']}, {u['name']})"
        try:
            ScApp(env, u["client_id"], store.dec(u["client_secret"])).token(u["username"], store.dec(u["password"]))
            add(label, True)
        except (ScError, OSError) as e:
            why = _why(e)
            add(label, False, f"{why}. {hint(why)}".strip())
    sid = store.get("subscriber_id")
    users = check_users(store, sid, time.time()) if sid else []
    for r in users:
        label = f"Issue list dashboard: {r['user']}"
        if r["error"]:
            add(label, False, f"{r['error']}. Check the Subscriber ID on Connections. {hint(r['error'])}".strip())
        else:
            add(label, bool(r["list"]), f"{r['name'] or r['id']}: {r['list']}" if r["list"] else
                f"Dashboard {r['id']} has no issue list for this Subscriber ID. Check the Subscriber ID on Connections, or assign a dashboard with an issue list to {r['user']} in ServiceChannel.")
    if not sid and store.db.execute("SELECT 1 FROM connections WHERE side='subscriber'").fetchone():
        add("Issue list dashboard", False, "Enter the Subscriber ID on Connections and press Check dashboard.")
    for p in store.db.execute("SELECT name FROM connections WHERE side='provider' AND provider_id IS NULL"):
        add(f"Provider ID: {p['name']}", False, "Delete this connection and add it again with its numeric Provider ID.")
    locs = store.db.execute("SELECT * FROM locations WHERE enabled=1 ORDER BY store_id").fetchall()
    for loc in locs[:MAX_LOCATIONS]:
        label = f"Rank 1 trades at {loc['store_id']}"
        try:
            ours = Creator(store, rt, rt.rng).resync(loc)
            add(label, bool(ours), (f"{len(ours)} trade(s): " + ", ".join(sorted(ours))) if ours else
                hint("no eligible trade at"))
        except (ScError, OSError) as e:
            why = _why(e)
            add(label, False, f"{why}. {hint(why)}".strip())
    if len(locs) > MAX_LOCATIONS:
        add("Locations checked", True, f"The first {MAX_LOCATIONS} of {len(locs)} enabled locations were checked.")
    if not locs:
        add("Locations", False, "Enable at least one location on Locations.")
    result = dict(at=time.time(), running=False, rows=rows)
    store.put("setup_check", result)
    return result
