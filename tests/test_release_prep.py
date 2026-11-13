import importlib.util
import pathlib

import pytest

spec = importlib.util.spec_from_file_location("release_prep", pathlib.Path(__file__).parent.parent / "scripts" / "release_prep.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def test_unreleased_notes_become_the_version_and_a_fresh_unreleased_stays_on_top(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n- New: a thing.\n\n## v1.0.0 - 2026-01-01\n\n- Old.\n")
    rp.rename_unreleased("1.1.0", "2026-02-02", tmp_path)
    assert (tmp_path / "CHANGELOG.md").read_text() == "# Changelog\n\n## Unreleased\n\n## v1.1.0 - 2026-02-02\n- New: a thing.\n\n## v1.0.0 - 2026-01-01\n\n- Old.\n"


def test_an_empty_unreleased_section_stops_the_release(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n## v1.0.0 - 2026-01-01\n\n- Old.\n")
    with pytest.raises(SystemExit, match="nothing under Unreleased"):
        rp.rename_unreleased("1.1.0", "2026-02-02", tmp_path)
