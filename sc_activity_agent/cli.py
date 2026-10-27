"""agent init|status|tick|run|pause|resume. The environment is chosen once at init and then locked."""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

from . import PACKAGED, __version__
from .store import Store

DEFAULT_PORT = {"prod": 8080, "sb2": 8081}


def data_dir(args):
    return Path(args.data_dir or os.environ.get("SC_AGENT_DATA") or Path.home() / ".sc-activity-agent")


def cmd_init(args, store):
    cur = store.get("env")
    if cur and cur != args.env:
        sys.exit(f"This data dir is locked to {cur}. Use a new --data-dir for {args.env}.")
    store.put("env", args.env)
    store.put("port", args.port or DEFAULT_PORT[args.env])
    print(f"Initialized {args.env} instance in {store.dir}\nNext: agent run, then open http://127.0.0.1:{store.get('port')} to finish setup.")


def cmd_status(args, store):
    now = time.time()
    q = lambda sql, *a: store.db.execute(sql, a).fetchone()[0]
    print(f"agent {__version__}  env={store.get('env')}  paused={store.get('paused_at') is not None}")
    print(f"WOs active={q('SELECT COUNT(*) FROM work_orders WHERE state=?', 'active')}  "
          f"steps pending={q('SELECT COUNT(*) FROM steps WHERE state=?', 'pending')}  "
          f"failed={q('SELECT COUNT(*) FROM steps WHERE state=?', 'failed')}  "
          f"calls last hour={store.count_calls_since(now - 3600)}")


def build_engine(store, with_rt=False):
    import random

    from .client import ScApp
    from .engine import Engine
    from .handlers import Runtime, make_handlers
    env = store.get("env") or sys.exit("Run `agent init --env prod|sb2` first.")

    class Apps(dict):
        """One ScApp per connection id, built on first use so connections added in the console work without a restart."""
        def __missing__(self, cid):
            c = store.db.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
            if not c:
                raise KeyError(cid)
            app = ScApp(env, c["client_id"], store.dec(c["client_secret"]), store=store, role=c["side"])
            app.paused = lambda: store.get("paused_at") is not None
            self[cid] = app
            return app
    apps = Apps()
    rt = Runtime(store, apps, random.Random())
    engine = Engine(store, make_handlers(rt))
    return (engine, rt) if with_rt else engine


def cmd_tick(args, store):
    print(build_engine(store).tick())


def free_port(start=8080):
    import socket
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)):
                return p
    sys.exit("No free port found.")


def cmd_run(args, store):
    if PACKAGED and not args.no_ui:
        # the desktop shell reads this file to learn where the console is; a busy port moves to the next free one
        port = store.get("port") or free_port(DEFAULT_PORT["prod"])
        store.put("port", port)
        (store.dir / "port").write_text(str(port))
        if not store.get("env"):
            from .welcome import wait_for_env
            wait_for_env(store, port)
    engine, rt = build_engine(store, with_rt=True)
    if not args.no_ui:
        import threading

        import uvicorn

        from .web.app import create_app
        port = store.get("port")
        threading.Thread(target=uvicorn.run, args=(create_app(store, engine, rt),),
                         kwargs={"host": "127.0.0.1", "port": port, "log_level": "warning"}, daemon=True).start()
        print(f"Console: http://127.0.0.1:{port}")
    from . import update
    from .creator import Creator
    creator = Creator(store, rt, rt.rng)
    (store.dir / "agent.pid").write_text(str(os.getpid()))
    if store.get("resume_after_update"):   # the desktop app paused the agent for an update; carry on on the new version
        store.put("resume_after_update", False)
        engine.paused_at = store.get("paused_at")
        engine.resume(store.get("resume_policy", "catch_up"))
    if PACKAGED and store.get("env") == "prod":
        from .launcher import ensure_running, twin_dir
        d = twin_dir(store.dir)
        if (d / "agent.db").exists():   # an update stopped the SB2 copy too; bring it back if it was running
            twin = Store(d)
            if twin.get("resume_after_update"):
                threading.Thread(target=ensure_running, args=(d, twin.get("port")), daemon=True).start()
    print(f"agent {__version__} running ({store.get('env')}). Ctrl+C to stop.")
    try:
        while True:
            engine.paused_at = store.get("paused_at")
            # one failing piece must not stop the others, or the whole agent
            for name, fn in (("step", engine.tick), ("update", lambda: (update.check(store), [])[1]),
                             ("create", creator.tick)):
                try:
                    for key, outcome in fn():
                        print(time.strftime("%H:%M:%S"), f"{name} {key}: {outcome}")
                except Exception as e:  # noqa: BLE001
                    print(time.strftime("%H:%M:%S"), f"{name} loop error: {type(e).__name__}: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


def cmd_pause(args, store):
    build_engine(store).pause()
    print("Paused. Writes are blocked until `agent resume`.")


def cmd_resume(args, store):
    build_engine(store).resume(store.get("resume_policy", "catch_up"))
    print("Resumed.")


def cmd_update(args, store):
    from . import update
    found = update.check(store, force=True)
    if not found:
        return print(f"Up to date ({__version__}).")
    print(f"Update available: {found['tag']}\n{found['notes']}")
    if not args.yes and input("Install now? Work orders are paused during the update. [y/N] ").lower() != "y":
        return
    ok, msg = update.apply(store, found["tag"])
    print(msg)
    sys.exit(0 if ok else 1)


def cmd_open(args, store):
    """Start the agent if its port is closed, then open the console in the browser."""
    import webbrowser

    from .launcher import ensure_running
    port = store.get("port") or sys.exit("Run `agent init --env prod|sb2` first.")
    ensure_running(store.dir, port)
    webbrowser.open(f"http://127.0.0.1:{port}")


def cmd_install_app(args, store):
    from .launcher import install
    print("Launcher created:", install(store.dir, store.get("env") or sys.exit("Run `agent init` first.")))


def cmd_login(args, store):
    from . import autostart
    env = store.get("env") or sys.exit("Run `agent init --env prod|sb2` first.")
    if args.state == "off":
        autostart.disable(store.dir, env)
        print("Start at login: off.")
    elif args.state == "on":
        print("Start at login: on ->", autostart.enable(store.dir, env))
    else:
        print("Start at login:", "on" if autostart.enabled(store.dir, env) else "off")


def _change(store, what):
    """Keep the last 50 changes made through the command line (by the user or by the assistant on their behalf)."""
    log = store.get("changes", [])[-49:]
    log.append({"at": time.time(), "what": what})
    store.put("changes", log)


def cmd_get(args, store):
    """agent get [key[.path]]: show settings."""
    import json
    if not args.key:
        rows = {r["key"]: json.loads(r["value"]) for r in store.db.execute("SELECT * FROM settings ORDER BY key")}
        rows = {k: v for k, v in rows.items() if k not in ("create_slots", "gaps", "header_ids", "changes", "rank1")}
        return print(json.dumps(rows, indent=1))
    top, *path = args.key.split(".")
    v = store.get(top)
    for k in path:
        v = v[k]
    print(json.dumps(v, indent=1))


def cmd_set(args, store):
    """agent set behavior.proposal_rate 10: change one setting. The value is JSON (10, 0.5, true, "text"). Running agents pick it up on the next tick."""
    import json
    top, *path = args.key.split(".")
    cur = store.get(top, {} if path else None)
    new = json.loads(args.value)
    if path:
        node = cur
        for k in path[:-1]:
            node = node.setdefault(k, {})
        old = node.get(path[-1])
        node[path[-1]] = new
    else:
        old, cur = cur, new
    store.put(top, cur)
    _change(store, f"set {args.key}: {old!r} -> {new!r}")
    print(f"{args.key}: {old!r} -> {new!r}")


def cmd_plan(args, store):
    """agent plan <WO id>: list a work order's steps."""
    import datetime as dt
    wo = store.db.execute("SELECT * FROM work_orders WHERE sc_id=?", (args.wo,)).fetchone() or sys.exit("No such work order.")
    print(f"WO {wo['sc_id']} {wo['location']} {wo['trade']} state={wo['state']}")
    for st in store.db.execute("SELECT * FROM steps WHERE wo_id=? ORDER BY seq", (wo["id"],)):
        due = dt.datetime.fromtimestamp(st["due_at"]).strftime("%a %m-%d %H:%M")
        print(f"  step {st['id']:>4}  {st['seq']:>2} {st['kind']:<16} {st['state']:<8} due {due}" + (f"  {st['error'][:80]}" if st["error"] else ""))


def cmd_step(args, store):
    """agent step <step id> retry | skip | due <+30m|+2h|+1d|epoch>."""
    st = store.db.execute("SELECT * FROM steps WHERE id=?", (args.step,)).fetchone() or sys.exit("No such step.")
    if args.action == "skip":
        store.db.execute("UPDATE steps SET state='skipped' WHERE id=?", (st["id"],))
    elif args.action == "retry":
        store.db.execute("UPDATE steps SET state='pending', attempts=0, error=NULL, due_at=? WHERE id=?", (time.time(), st["id"]))
    else:
        v = args.value or sys.exit("due needs a value like +30m, +2h, +1d or an epoch time.")
        due = time.time() + int(v[1:-1]) * {"m": 60, "h": 3600, "d": 86400}[v[-1]] if v.startswith("+") else float(v)
        store.db.execute("UPDATE steps SET due_at=?, state='pending' WHERE id=?", (due, st["id"]))
    store.db.commit()
    _change(store, f"step {st['id']} ({st['kind']}): {args.action} {args.value or ''}".strip())
    print("OK")


def main(argv=None):
    p = argparse.ArgumentParser(prog="agent")
    p.add_argument("--data-dir")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--env", choices=["prod", "sb2"], required=True)
    i.add_argument("--port", type=int)
    r = sub.add_parser("run")
    r.add_argument("--interval", type=int, default=30)
    r.add_argument("--no-ui", action="store_true")
    u = sub.add_parser("update", help="check GitHub Releases and install the latest version")
    u.add_argument("--yes", action="store_true")
    sub.add_parser("open", help="start the agent if needed and open the console")
    sub.add_parser("install-app", help="create a double-clickable launcher with an icon")
    lg = sub.add_parser("login", help="start at login: on | off | status")
    lg.add_argument("state", choices=["on", "off", "status"], nargs="?", default="status")
    g = sub.add_parser("get", help="show settings")
    g.add_argument("key", nargs="?")
    st = sub.add_parser("set", help="change a setting, for example: set behavior.proposal_rate 10")
    st.add_argument("key")
    st.add_argument("value")
    pl = sub.add_parser("plan", help="list a work order's steps")
    pl.add_argument("wo", type=int)
    sp = sub.add_parser("step", help="retry, skip or reschedule one step")
    sp.add_argument("step", type=int)
    sp.add_argument("action", choices=["retry", "skip", "due"])
    sp.add_argument("value", nargs="?")
    for n in ("status", "tick", "pause", "resume"):
        sub.add_parser(n)
    args = p.parse_args(argv)
    cmd_fn = {"init": cmd_init, "status": cmd_status, "tick": cmd_tick, "run": cmd_run,
              "pause": cmd_pause, "resume": cmd_resume, "login": cmd_login, "update": cmd_update, "open": cmd_open, "install-app": cmd_install_app,
              "get": cmd_get, "set": cmd_set, "plan": cmd_plan, "step": cmd_step}[args.cmd]
    cmd_fn(args, Store(data_dir(args)))


if __name__ == "__main__":
    main()
