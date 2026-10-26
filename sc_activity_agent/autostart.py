"""Start at login for one instance: macOS LaunchAgent, Windows Task Scheduler, Linux systemd --user. One unit per data dir."""
import hashlib
import os
import plistlib
import subprocess
import sys
from pathlib import Path


def label(data_dir, env):
    return f"com.sc-activity-agent.{env}.{hashlib.sha1(str(Path(data_dir).resolve()).encode()).hexdigest()[:6]}"


def command(data_dir):
    return [sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(Path(data_dir).resolve()), "run"]


def plist(data_dir, env):
    log = Path(data_dir).resolve() / "agent.log"
    return {"Label": label(data_dir, env), "ProgramArguments": command(data_dir), "RunAtLoad": True,
            "KeepAlive": True, "StandardOutPath": str(log), "StandardErrorPath": str(log)}


def systemd_unit(data_dir):
    return f"[Unit]\nDescription=SC Activity Agent\n\n[Service]\nExecStart={' '.join(command(data_dir))}\nRestart=always\n\n[Install]\nWantedBy=default.target\n"


def plan(data_dir, env, platform=sys.platform):
    """Return (file_path or None, file_bytes or None, [shell commands]) for enabling; pure so it can be tested."""
    lab = label(data_dir, env)
    if platform == "darwin":
        path = Path.home() / "Library/LaunchAgents" / f"{lab}.plist"
        return path, plistlib.dumps(plist(data_dir, env)), [["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)]]
    if platform == "win32":
        return None, None, [["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", lab, "/TR", subprocess.list2cmdline(command(data_dir))]]
    path = Path.home() / ".config/systemd/user" / f"{lab}.service"
    return path, systemd_unit(data_dir).encode(), [["systemctl", "--user", "enable", "--now", f"{lab}.service"]]


def enable(data_dir, env):
    path, data, cmds = plan(data_dir, env)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for c in cmds:
        subprocess.run(c, check=False)
    return path or label(data_dir, env)


def disable(data_dir, env):
    lab = label(data_dir, env)
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{lab}"], check=False)
        (Path.home() / "Library/LaunchAgents" / f"{lab}.plist").unlink(missing_ok=True)
    elif sys.platform == "win32":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", lab], check=False)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{lab}.service"], check=False)
        (Path.home() / ".config/systemd/user" / f"{lab}.service").unlink(missing_ok=True)


def enabled(data_dir, env):
    lab = label(data_dir, env)
    if sys.platform == "darwin":
        return (Path.home() / "Library/LaunchAgents" / f"{lab}.plist").exists()
    if sys.platform == "win32":
        return subprocess.run(["schtasks", "/Query", "/TN", lab], capture_output=True).returncode == 0
    return (Path.home() / ".config/systemd/user" / f"{lab}.service").exists()
