"""Update path: check GitHub Releases, show a banner, and apply on request. Never auto-applies."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

from . import __version__
from .client import SSL_CONTEXT

REPO = "zwolf25/sc-activity-agent"
CHECK_EVERY = 24 * 3600


def _fetch(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sc-activity-agent"})
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as r:
        return json.load(r)


def _ver(tag):
    return tuple(int(x) for x in tag.lstrip("v").split("."))


def repo(store):
    return store.get("update_repo") or REPO


def check(store, fetch=_fetch, clock=time.time, force=False):
    """Returns {"tag", "notes"} when a newer release exists, else None. Cached for a day. Network errors return None."""
    r = repo(store)
    if not r:
        return None
    cached = store.get("update_check")
    if cached and not force and clock() - cached["at"] < CHECK_EVERY:
        return cached.get("found")
    found = None
    try:
        rel = fetch(f"https://api.github.com/repos/{r}/releases/latest")
        if _ver(rel["tag_name"]) > _ver(__version__):
            found = {"tag": rel["tag_name"], "notes": rel.get("body") or ""}
    except Exception:  # offline, rate-limited or no release yet: try again tomorrow
        return cached.get("found") if cached else None
    store.put("update_check", {"at": clock(), "found": found})
    return found


def backup(store):
    """Copy agent.db before an update. Returns the copy's path."""
    store.db.commit()
    dest = store.dir / "backups"
    dest.mkdir(exist_ok=True)
    f = dest / f"agent-{__version__}-{int(time.time())}.db"
    shutil.copy2(store.dir / "agent.db", f)
    return f


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
