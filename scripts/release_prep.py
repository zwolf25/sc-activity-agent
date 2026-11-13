"""B-108: the mechanical half of a release. Usage: python scripts/release_prep.py 0.22.0 [--date 2026-11-13]
Renames CHANGELOG "Unreleased" to the version (a fresh Unreleased stays on top), bumps the version, runs the tests, then prints the
ARCHITECTURE.md hash and the doctor gate. The doctor digest stamp and the commit, push, tag and Release stay manual (the digest lives in the skill)."""
import datetime
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from bump_version import ROOT, bump  # noqa: E402


def rename_unreleased(version, date, root=ROOT):
    path = root / "CHANGELOG.md"
    text = path.read_text()
    m = re.search(r"^## Unreleased\n(.*?)(?=^## )", text, flags=re.M | re.S)
    if not m or not m[1].strip():
        raise SystemExit("CHANGELOG.md has nothing under Unreleased: write the release notes first")
    path.write_text(text.replace(m[0], f"## Unreleased\n\n## v{version} - {date}\n{m[1].lstrip(chr(10))}", 1))


def main(version, date):
    rename_unreleased(version, date)
    bump(version)
    if subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT).returncode:
        raise SystemExit("tests failed: fix them before the digest and the commit")
    print(subprocess.run(["shasum", "-a", "256", "docs/ARCHITECTURE.md"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    doctor = pathlib.Path.home() / ".claude/skills/sc-activity-agent-doctor/scripts/doctor.py"
    if doctor.exists():
        out = subprocess.run([sys.executable, "-I", str(doctor)], capture_output=True, text=True).stdout
        print("doctor_stale:", re.search(r'"doctor_stale": (\[.*?\])', out, flags=re.S)[1] if '"doctor_stale"' in out else "n/a")
    print("Next: update the doctor digest stamp (repo_version, architecture_sha256) and skill version, then commit and ask before push.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        raise SystemExit(__doc__)
    main(args[0], args[args.index("--date") + 1] if "--date" in args else datetime.date.today().isoformat())
