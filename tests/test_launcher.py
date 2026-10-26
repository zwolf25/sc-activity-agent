from sc_activity_agent import launcher


def test_macos_bundle_runs_open_command_with_data_dir(tmp_path):
    app = launcher.install(tmp_path / "data", "sb2", platform="darwin", home=tmp_path)
    assert app.name == "SC Activity Agent (SB2).app"
    script = (app / "Contents/MacOS/launch").read_text()
    assert "sc_activity_agent.cli" in script and "open" in script and str(tmp_path / "data") in script
    assert (app / "Contents/Resources/icon.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_windows_and_linux_launchers(tmp_path):
    w = launcher.install(tmp_path / "d", "prod", platform="win32", home=tmp_path)
    assert w.suffix == ".cmd" and "cli" in w.read_text()
    l = launcher.install(tmp_path / "d", "prod", platform="linux", home=tmp_path)
    assert "Exec=" in l.read_text() and l.with_suffix(".png").exists()
