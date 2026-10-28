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


def test_backup_keeps_last_ten_and_restore_swaps_the_database(tmp_path):
    import os
    from sc_activity_agent import update
    from sc_activity_agent.store import Store
    s = Store(tmp_path)
    (tmp_path / "backups").mkdir()
    for i in range(12):
        f = tmp_path / "backups" / f"agent-0.0.0-{i}.db"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))
    s.put("marker", 1)
    first = update.backup(s).rename(tmp_path / "backups" / "agent-keep.db")   # two backups in one second share a name
    s.put("marker", 2)
    update.backup(s)
    assert len(update.backups(s)) == update.KEEP
    update.restore(Store(tmp_path), first.name)
    assert Store(tmp_path).get("marker") == 1


def test_roles_convert_to_user_capabilities_on_open(tmp_path):
    import sqlite3
    from sc_activity_agent.store import SCHEMA, Store
    db = sqlite3.connect(tmp_path / "agent.db")
    db.executescript(SCHEMA)   # the pre-0.6.0 shape: no users.can_do
    db.execute("INSERT INTO connections VALUES(1,'provider','P','c','x',7)")
    db.execute("INSERT INTO users(id,conn_id,username,password) VALUES(1,1,'a','x'),(2,1,'b','x')")
    db.execute("INSERT INTO roles VALUES('*','check_in','[1,2]','random'),('*','accept','[1]','single'),('HQ','accept','[2]','single')")
    db.commit()
    db.close()
    s = Store(tmp_path)
    can = {r["id"]: sorted(__import__("json").loads(r["can_do"])) for r in s.db.execute("SELECT id, can_do FROM users")}
    assert can == {1: ["accept", "check_in"], 2: ["check_in"]}   # the per-location HQ override is dropped
