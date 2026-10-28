"""Update path: check GitHub Releases, show a banner, and apply on request. Never auto-applies."""
import json
import os
import shutil
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
    """Returns {"tag", "notes"} when a newer release exists, else None. Cached for a day. Network errors return None."""
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
    except Exception:  # offline, rate-limited or no release yet: try again tomorrow
        return pending(store)
    store.put("update_check", {"at": clock(), "found": found})
    return found


def backup(store):
    """Copy agent.db before an update. Returns the copy's path."""
    store.db.commit()
    dest = store.dir / "backups"
    dest.mkdir(exist_ok=True)
    f = dest / f"agent-{__version__}-{int(time.time())}.db"
    shutil.copy2(store.dir / "agent.db", f)
    for old in sorted(dest.glob("agent-*.db"), key=lambda p: p.stat().st_mtime)[:-KEEP]:
        old.unlink()
    return f


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
    shutil.copy2(src, store.dir / "agent.db")
    return keep


def _pip(spec):
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", spec]
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode:
        cmd = ["uv", "pip", "install", "--python", sys.executable, "--upgrade", spec]
    return subprocess.run(cmd, capture_output=True, text=True)


def apply(store, tag, run=subprocess.run, pip=_pip):
    """Pause, back up, install the tag, let the new code migrate the DB and resume. Restores the DB copy if that fails.
    Returns (ok, message)."""
    r = repo(store)
    if not r:
        return False, "No update repository configured."
    was_paused = store.get("paused_at") is not None
    store.put("paused_at", store.get("paused_at") or time.time())
    saved = backup(store)
    res = pip(f"git+https://github.com/{r}@{tag}")
    if res.returncode:
        if not was_paused:
            store.put("paused_at", None)
        return False, f"Install failed, nothing changed: {res.stderr[-300:]}"
    # new code runs migrations when it opens the store; resume only if we paused it
    args = [sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(store.dir), "status"]
    if not was_paused:
        args[-1] = "resume"
    if run(args, capture_output=True).returncode:
        shutil.copy2(saved, store.dir / "agent.db")
        return False, f"New version failed to start. Database restored from {saved.name}. Run agent resume to continue."
    pid = store.dir / "agent.pid"
    if pid.exists():
        try:
            os.kill(int(pid.read_text()), signal.SIGTERM)  # Start at login restarts it on the new code
        except (OSError, ValueError):
            pass
    return True, f"Updated to {tag}. Restart the agent if it does not restart by itself."
