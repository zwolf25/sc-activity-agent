"""B-87: Check setup. Runs every setup test against ServiceChannel and records each result with its fix, so a new instance shows all
its problems at once instead of one error at a time. Reads only; creates nothing. Locations are capped to keep the run short under the
rate limit."""
import time

from .client import ScApp, ScError
from .creator import Creator, user_dashboard
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
    sub = store.db.execute("SELECT u.username, u.password, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id "
                           "WHERE c.side='subscriber' ORDER BY u.id LIMIT 1").fetchone()
    sid = store.get("subscriber_id")
    if sub and sid:
        try:
            sa = ScApp(env, sub["client_id"], store.dec(sub["client_secret"]), store=store, role="subscriber")
            user = (sub["username"], store.dec(sub["password"]))
            d = user_dashboard(store, sa, user, time.time(), force=True)
            heads = sa.call(user, "GET", f"/api/subscribers/{sid}/issuelist/headers", action="dashboards")["Headers"]
            lst = next((h["Name"] for h in heads if h["DashboardId"] == d["id"]), "")
            add("Issue list dashboards readable", bool(lst), f"{d['name'] or d['id']}: {lst}" if lst else
                f"Dashboard {d['id']} of {sub['username']} has no issue list for this Subscriber ID. Check the Subscriber ID on Connections, or assign a dashboard with an issue list to the user in ServiceChannel.")
        except (ScError, OSError) as e:
            why = _why(e)
            add("Issue list dashboards readable", False, f"{why}. Check the Subscriber ID on Connections. {hint(why)}".strip())
    elif sub:
        add("Issue list dashboards readable", False, "Enter the Subscriber ID on Connections and press Check dashboard.")
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
