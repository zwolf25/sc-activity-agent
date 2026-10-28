"""`agent install-app`: a double-clickable launcher that starts the agent if it is not running, then opens the console.
macOS: ~/Applications/SC Activity Agent.app. Windows: Start Menu .cmd. Linux: .desktop entry."""
import plistlib
import shutil
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

from . import PACKAGED, autostart


def name(env):
    return "SC Activity Agent" + (" (SB2)" if env == "sb2" else "")


def open_cmd(data_dir):
    return [sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(Path(data_dir).resolve()), "open"]


def twin_dir(data_dir):
    """Where the SB2 copy lives: inside the desktop app's data folder, or beside the data folder in a source install."""
    d = Path(data_dir)
    return d / "sb2" if PACKAGED else d.with_name(d.name + "-sb2")


def run_cmd(data_dir):
    """The frozen desktop program is the agent itself; a source install runs the module."""
    if PACKAGED:
        return [sys.executable, "--data-dir", str(Path(data_dir).resolve()), "run"]
    return [sys.executable, "-m", "sc_activity_agent.cli", "--data-dir", str(Path(data_dir).resolve()), "run"]


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_running(data_dir, port):
    """Start `agent run` for this data dir if its port is closed and wait (up to 15 s) for the console. Returns True if up."""
    if not port_open(port):
        data_dir = Path(data_dir)
        log = open(data_dir / "agent.log", "a")
        subprocess.Popen(run_cmd(data_dir), stdout=log, stderr=log, start_new_session=True)
        for _ in range(60):
            if port_open(port):
                break
            time.sleep(0.25)
    return port_open(port)


def alert(msg):
    """The launcher has no window, so a failure to start must be shown some other way."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display alert "SC Activity Agent" message "{msg}"'], capture_output=True)
    elif sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "SC Activity Agent", 0x10)
    print(msg, file=sys.stderr)


def png(size=512):
    """Blue rounded square with a white activity pulse line. Plain-Python PNG so no image library is needed."""
    r, bg, fg = size // 5, (31, 95, 214), (255, 255, 255)
    pts = [(.14, .55), (.34, .55), (.43, .30), (.55, .74), (.64, .55), (.86, .55)]
    segs = [((a[0] * size, a[1] * size), (b[0] * size, b[1] * size)) for a, b in zip(pts, pts[1:])]
    w = size * 0.035

    def near(x, y):
        for (x1, y1), (x2, y2) in segs:
            dx, dy = x2 - x1, y2 - y1
            t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
            if (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= w * w:
                return True
        return False

    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cx, cy = min(x, size - 1 - x), min(y, size - 1 - y)
            inside = cx >= r or cy >= r or (cx - r) ** 2 + (cy - r) ** 2 <= r * r
            row += bytes(fg + (255,) if inside and near(x, y) else bg + (255,) if inside else (0, 0, 0, 0))
        rows.append(bytes(row))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def _icns(png_path, out):
    """macOS only: build an .icns from one PNG with sips + iconutil."""
    if not (shutil.which("sips") and shutil.which("iconutil")):
        return
    iconset = out.parent / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for s in (16, 32, 64, 128, 256, 512):
        subprocess.run(["sips", "-z", str(s), str(s), str(png_path), "--out", str(iconset / f"icon_{s}x{s}.png")], capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], capture_output=True)
    shutil.rmtree(iconset, ignore_errors=True)


def install(data_dir, env, platform=sys.platform, home=None):
    """Writes the launcher and returns its path."""
    home = Path(home or Path.home())
    label, cmd = name(env), open_cmd(data_dir)
    quoted = subprocess.list2cmdline(cmd) if platform == "win32" else " ".join(f"'{c}'" for c in cmd)
    if platform == "darwin":
        app = home / "Applications" / f"{label}.app"
        (app / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
        (app / "Contents/Resources").mkdir(parents=True, exist_ok=True)
        sh = app / "Contents/MacOS/launch"
        sh.write_text(f"#!/bin/sh\nexec {quoted}\n")
        sh.chmod(0o755)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleName": label, "CFBundleDisplayName": label, "CFBundleExecutable": "launch", "CFBundleIconFile": "icon",
            "CFBundleIdentifier": "com.sc-activity-agent.launcher." + env, "CFBundlePackageType": "APPL", "LSUIElement": True}))
        p = app / "Contents/Resources/icon.png"
        p.write_bytes(png())
        _icns(p, app / "Contents/Resources/icon.icns")
        return app
    if platform == "win32":
        f = home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs" / f"{label}.cmd"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"@echo off\r\nstart \"\" /min {quoted}\r\n")
        return f
    f = home / ".local/share/applications" / f"{label.replace(' ', '-').lower()}.desktop"
    f.parent.mkdir(parents=True, exist_ok=True)
    icon = f.with_suffix(".png")
    icon.write_bytes(png())
    f.write_text(f"[Desktop Entry]\nType=Application\nName={label}\nExec={quoted}\nIcon={icon}\nTerminal=false\n")
    return f
