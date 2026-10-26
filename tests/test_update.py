import subprocess

from sc_activity_agent import update
from sc_activity_agent.store import Store


def rel(tag):
    return lambda url: {"tag_name": tag, "body": "notes"}


def test_check_needs_repo_and_newer_version_and_caches(tmp_path):
    s = Store(tmp_path)
    s.put("update_repo", "o/r")
    assert update.check(s, rel("v0.1.0")) is None             # same version
    assert update.check(s, rel("v9.0.0"), force=True) == {"tag": "v9.0.0", "notes": "notes"}
    boom = lambda url: 1 / 0
    assert update.check(s, boom)["tag"] == "v9.0.0"            # cached, no network
    assert update.check(s, boom, clock=lambda: 10 ** 12) == {"tag": "v9.0.0", "notes": "notes"}  # offline keeps last answer


def test_apply_success_backs_up_and_resumes(tmp_path):
    s = Store(tmp_path)
    s.put("update_repo", "o/r")
    ran = []
    ok, msg = update.apply(s, "v9.0.0", run=lambda a, **k: ran.append(a[-1]) or subprocess.CompletedProcess(a, 0),
                           pip=lambda spec: subprocess.CompletedProcess([], 0))
    assert ok and ran == ["resume"] and list((tmp_path / "backups").glob("*.db"))


def test_apply_failed_install_changes_nothing_and_failed_start_restores_db(tmp_path):
    s = Store(tmp_path)
    s.put("update_repo", "o/r")
    ok, _ = update.apply(s, "v9.0.0", pip=lambda spec: subprocess.CompletedProcess([], 1, stderr="no"))
    assert not ok and s.get("paused_at") is None
    ok, msg = update.apply(s, "v9.0.0", run=lambda a, **k: subprocess.CompletedProcess(a, 1),
                           pip=lambda spec: subprocess.CompletedProcess([], 0))
    assert not ok and "restored" in msg
