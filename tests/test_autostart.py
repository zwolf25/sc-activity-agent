import plistlib
from pathlib import Path

from sc_activity_agent import autostart as a


def test_labels_differ_per_data_dir_and_env(tmp_path):
    assert a.label(tmp_path / "a", "prod") != a.label(tmp_path / "b", "prod")
    assert a.label(tmp_path, "sb2").startswith("com.sc-activity-agent.sb2.")


def test_macos_plan_runs_this_instance_at_load_and_keeps_alive(tmp_path):
    path, data, cmds = a.plan(tmp_path, "prod", "darwin")
    pl = plistlib.loads(data)
    assert pl["RunAtLoad"] and pl["KeepAlive"] and str(tmp_path.resolve()) in pl["ProgramArguments"]
    assert path.name.endswith(".plist") and cmds[0][:2] == ["launchctl", "bootstrap"]


def test_windows_and_linux_plans(tmp_path):
    _, _, cmds = a.plan(tmp_path, "sb2", "win32")
    assert cmds[0][0] == "schtasks" and "ONLOGON" in cmds[0]
    path, data, cmds = a.plan(tmp_path, "sb2", "linux")
    assert b"Restart=always" in data and cmds[0][:3] == ["systemctl", "--user", "enable"]
