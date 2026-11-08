"""Update path: check GitHub Releases, show a banner, and apply on request. Never auto-applies."""
import json
import os
import shutil
import sqlite3
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import __version__
from .client import SSL_CONTEXT

KEEP = 10   # backups kept; older ones are deleted

REPO = "zwolf25/sc-activity-agent"
CHECK_EVERY = 3600   # hourly: a day-long cache hid a fresh release from the banner for up to a day


def _fetch(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sc-activity-agent"})
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as r:
        return json.load(r)


def _ver(tag):
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def pending(store):
    """The cached newer release, or None. Rechecked against the running version, because the cache outlives an update."""
    found = (store.get("update_check") or {}).get("found")
    return found if found and _ver(found["tag"]) > _ver(__version__) else None


def repo(store):
    return store.get("update_repo") or REPO


def check(store, fetch=_fetch, clock=time.time, force=False):
    """Returns {"tag", "notes"} when a newer release exists, else None. Cached for CHECK_EVERY (an hour). Network errors return None."""
    r = repo(store)
    if not r:
        return None
    cached = store.get("update_check")
    if cached and not force and clock() - cached["at"] < CHECK_EVERY:
        return pending(store)
    found = None
    try:
        rel = fetch(f"https://api.github.com/repos/{r}/releases/latest")
        if _ver(rel["tag_name"]) > _ver(__version__):
            found = {"tag": rel["tag_name"], "notes": rel.get("body") or ""}
    except Exception:  # offline, rate-limited or no release yet: try again at the next check
        return pending(store)
    store.put("update_check", {"at": clock(), "found": found})
    return found


def backup(store):
    """Copy agent.db before an update. Returns the copy's path."""
    store.db.commit()
    dest = store.dir / "backups"
    dest.mkdir(exist_ok=True)
    f = dest / f"agent-{__version__}-{int(time.time())}.db"
    n = 0
    while f.exists():   # two backups in one second (a restore saves the current database first) must not overwrite each other
        n += 1
        f = dest / f"agent-{__version__}-{int(time.time())}-{n}.db"
    dst = sqlite3.connect(f)
    store.db.backup(dst)   # a file copy would miss pages still in the WAL
    dst.close()
    for old in sorted(dest.glob("agent-*.db"), key=lambda p: p.stat().st_mtime)[:-KEEP]:
        old.unlink()
    return f


def put_db(store, src):
    """Replace agent.db with a backup file; stale WAL files from the old database must go with it."""
    c = getattr(store._tl, "c", None)
    if c is not None:   # close first: deleting WAL files under an open connection corrupts it
        c.close()
        store._tl.c = None
    for ext in ("-wal", "-shm"):
        (store.dir / f"agent.db{ext}").unlink(missing_ok=True)
    shutil.copy2(src, store.dir / "agent.db")


def backups(store):
    """Newest first: (name, size in bytes, mtime)."""
    fs = sorted((store.dir / "backups").glob("agent-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [(f.name, f.stat().st_size, f.stat().st_mtime) for f in fs]


def restore(store, name):
    """Replace agent.db with a backup. The agent must be stopped: a running agent keeps its own open connections. Returns the
    path of the safety copy of the database being replaced."""
    src = store.dir / "backups" / Path(name).name
    if not src.is_file():
        raise FileNotFoundError(name)
    pid = store.dir / "agent.pid"
    if pid.exists():
        try:
            os.kill(int(pid.read_text()), 0)
            raise RuntimeError("The agent is running. Quit it first, then restore.")
        except (OSError, ValueError):
            pass
    keep = backup(store)
    put_db(store, src)
    return keep


def _spec(repo, tag):
    """A tag archive installs without git on the machine."""
    return f"https://github.com/{repo}/archive/refs/tags/{tag}.zip"


def _pip(spec):
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", spec]
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode:
        cmd = ["uv", "pip", "install", "--python", sys.executable, "--upgrade", spec]
    return subprocess.run(cmd, capture_output=True, text=True)


def _restart(store, wait=10):
    """Source install: start the agent again once the old one has let go of its port. A Start at login unit
    restarts it itself, and a second copy would run every step twice."""
    from . import autostart, launcher
    port = store.get("port")
    if not port or autostart.enabled(store.dir, store.get("env")):
        return
    for _ in range(wait * 4):
        if not launcher.port_open(port):
            break
        time.sleep(0.25)
    launcher.ensure_running(store.dir, port)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _agent_pid(store):
    """The running agent's pid: the one in agent.pid when that process is alive, else whoever holds agent.lock. The pid file can go stale
    (2026-11-07 Prod: it named a dead process, so the update signalled nothing and the old agent kept running)."""
    try:
        pid = int((store.dir / "agent.pid").read_text())
        if _alive(pid):
            return pid
    except (OSError, ValueError):
        pass
    if shutil.which("lsof"):
        out = subprocess.run(["lsof", "-t", str(store.dir / "agent.lock")], capture_output=True, text=True).stdout.split()
        held = [int(p) for p in out if p.isdigit() and int(p) != os.getpid()]
        return held[0] if held else None
    return None


def _stop(store, wait=20):
    """Ask the running agent to exit and wait for it to go. False when there is none; RuntimeError when it will not exit."""
    pid = _agent_pid(store)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(wait * 4):
        if not _alive(pid):
            return True
        time.sleep(0.25)
    raise RuntimeError(f"the old agent (process {pid}) did not exit")


def in_progress(store):
    """The update that is still running on this version, or None. A status older than 15 minutes is a dead run, so a retry is allowed."""
    st = store.get("update_status") or {}
    if st.get("state") in ("installing", "restarting") and st.get("from") == __version__ and time.time() - st.get("at", 0) < 900:
        return st
    return None


def notes_blocks(notes):
    """Release notes (the CHANGELOG bullets) as [(kind, text)] with kind h, li or p, for the Updating page. Bold and code marks are dropped."""
    out = []
    for line in (notes or "").splitlines():
        t = line.strip().replace("**", "").replace("`", "")
        if not t:
            continue
        if t.startswith("#"):
            out.append(("h", t.lstrip("# ")))
        elif t[0] in "-*":
            out.append(("li", t[1:].strip()))
        else:
            out.append(("p", t))
    return out


def apply(store, tag, **kw):
    """Runs _apply and leaves its progress in store key update_status, which the console's progress page polls."""
    notes = (store.get("update_status") or {}).get("notes", "")   # the console saved them when Update was pressed; keep them for the progress page
    store.put("update_status", {"state": "installing", "tag": tag, "from": __version__, "at": time.time(), "notes": notes})
    ok, msg = _apply(store, tag, **kw)
    store.put("update_status", {"state": "restarting" if ok else "failed", "tag": tag, "from": __version__, "at": time.time(), "msg": msg, "notes": notes})
    return ok, msg


def _apply(store, tag, run=subprocess.run, pip=_pip, restart=_restart, stop=_stop):
    """Pause, back up, install the tag, let the new code migrate the DB and resume. If the new version does not start, put the
    old code and the old database back. Returns (ok, message)."""
    r = repo(store)
    if not r:
        return False, "No update repository configured."
    was_paused = store.get("paused_at") is not None
    store.put("paused_at", store.get("paused_at") or time.time())
    saved = backup(store)
    res = pip(_spec(r, tag))
    if res.returncode:
        if not was_paused:
            store.put("paused_at", None)
        return False, f"Install failed, nothing changed: {res.stderr[-300:]}"
    # new code runs migrations when it opens the store; resume only if we paused it
    args = [sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(store.dir), "status"]
    if not was_paused:
        args[-1] = "resume"
    if run(args, capture_output=True).returncode:
        put_db(store, saved)
        back = pip(_spec(r, f"v{__version__}"))
        what = "Previous version put back" if not back.returncode else f"Could not reinstall v{__version__}, run agent update"
        return False, f"New version failed to start. Database restored from {saved.name}. {what}. Run agent resume to continue."
    try:
        stopped = stop(store)
    except RuntimeError as e:   # the new code is installed but the old agent still runs: say so, or the page waits for a restart that never comes
        return False, f"Updated to {tag}, but {e}. Quit it and the new version starts."
    if not stopped:
        return True, f"Updated to {tag}. The agent was not running; start it to use the new version."
    restart(store)
    return True, f"Updated to {tag}. The agent restarts on the new version."
