import importlib.util
from pathlib import Path

import pytest

from sc_activity_agent.store import Store


def load():
    spec = importlib.util.spec_from_file_location("live_sb2", Path(__file__).parent.parent / "scripts/live_sb2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_live_script_refuses_production_and_missing_instances(tmp_path):
    live = load()
    with pytest.raises(SystemExit, match="No instance"):
        live.main(["--data-dir", str(tmp_path / "none")])
    s = Store(tmp_path)
    s.put("env", "prod")
    with pytest.raises(SystemExit, match="SB2 only"):
        live.main(["--data-dir", str(tmp_path)])
