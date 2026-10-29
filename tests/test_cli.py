import json

from sc_activity_agent.cli import main
from sc_activity_agent.engine import add_plan
from sc_activity_agent.store import Store


def test_inspect_commands_do_not_create_an_instance(tmp_path):
    """A mistyped --data-dir once made an empty instance, and `plan` then said the WO did not exist."""
    import pytest
    missing = tmp_path / "typo"
    for cmd in (["status"], ["get"], ["plan", "1"], ["pause"], ["backup"]):
        with pytest.raises(SystemExit) as e:
            main(["--data-dir", str(missing)] + cmd)
        assert "no agent instance" in str(e.value)
    assert not missing.exists()


def test_set_get_plan_and_step(tmp_path, capsys):
    d = str(tmp_path)
    Store(tmp_path)
    main(["--data-dir", d, "set", "behavior.proposal_rate", "25"])
    main(["--data-dir", d, "get", "behavior.proposal_rate"])
    assert "25" in capsys.readouterr().out
    s = Store(tmp_path)
    assert s.get("behavior")["proposal_rate"] == 25 and "proposal_rate" in s.get("changes")[-1]["what"]
    add_plan(s, "HQ-NYC", "HVAC", 5001, [{"kind": "accept", "due_at": 1.0, "payload": {}}], {}, 1.0)
    main(["--data-dir", d, "plan", "5001"])
    assert "accept" in capsys.readouterr().out
    main(["--data-dir", d, "step", "1", "due", "+2h"])
    assert Store(tmp_path).db.execute("SELECT due_at FROM steps").fetchone()[0] > 7000
    main(["--data-dir", d, "step", "1", "skip"])
    assert Store(tmp_path).db.execute("SELECT state FROM steps").fetchone()[0] == "skipped"


def test_run_loop_uses_only_names_it_defines():
    """The status watch once went dead because its import landed in the wrong function; nothing exercised the loop."""
    import ast
    import builtins
    import inspect
    from sc_activity_agent import cli
    tree = ast.parse(inspect.getsource(cli.cmd_run))
    defined = set(dir(builtins)) | set(vars(cli))
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            defined.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            defined |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert used <= defined, used - defined


def test_keep_awake_follows_the_setting(tmp_path, monkeypatch):
    from sc_activity_agent import awake
    started = []

    class P:
        def __init__(self, cmd): started.append(cmd); self.dead = False
        def poll(self): return 1 if self.dead else None
        def terminate(self): self.dead = True
    monkeypatch.setattr(awake.subprocess, "Popen", P)
    monkeypatch.setattr(awake.sys, "platform", "darwin")
    s = Store(tmp_path)
    p = awake.sync(s, None)
    assert started[0][:2] == ["caffeinate", "-i"] and awake.sync(s, p) is p and len(started) == 1   # on by default, not restarted
    s.put("keep_awake", False)
    assert awake.sync(s, p) is None and p.dead
    monkeypatch.setattr(awake.sys, "platform", "win32")
    s.put("keep_awake", True)
    assert awake.sync(s, None) is None and len(started) == 1


def test_second_agent_on_the_same_data_folder_is_refused(tmp_path):
    from sc_activity_agent.launcher import lock_data_dir
    first = lock_data_dir(tmp_path)
    assert first is not None
    assert lock_data_dir(tmp_path) is None   # a second agent (launcher plus login job) must not run
    first.close()
    assert lock_data_dir(tmp_path) is not None
