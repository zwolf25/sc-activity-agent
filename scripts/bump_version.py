"""B-55: set the release version in every file that carries it, then check each one. Usage: python scripts/bump_version.py 0.11.3"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
# (file, pattern with the version in group 2, occurrences to change). Cargo.lock: only the desktop package's entry.
FILES = [
    ("sc_activity_agent/__init__.py", r'(__version__ = ")([^"]+)(")', 1),
    ("package.json", r'("version": ")([^"]+)(")', 1),
    ("package-lock.json", r'("name": "sc-activity-agent-desktop",\s+"version": ")([^"]+)(")', 2),
    ("src-tauri/tauri.conf.json", r'("version": ")([^"]+)(")', 1),
    ("src-tauri/Cargo.toml", r'(^version = ")([^"]+)(")', 1),
    ("src-tauri/Cargo.lock", r'(name = "sc-activity-agent-desktop"\nversion = ")([^"]+)(")', 1),
]


def bump(version, root=ROOT):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"not a version: {version}")
    for name, pattern, want in FILES:
        path = root / name
        text, n = re.subn(pattern, lambda m: m[1] + version + m[3], path.read_text(), flags=re.M)
        if n != want:
            raise SystemExit(f"{name}: expected {want} version string(s), found {n}; nothing written for this file")
        path.write_text(text)
        print(f"{name}: {version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    bump(sys.argv[1])
