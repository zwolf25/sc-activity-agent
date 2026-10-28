import json

from sc_activity_agent.cli import main
from sc_activity_agent.engine import add_plan
from sc_activity_agent.store import Store


def test_set_get_plan_and_step(tmp_path, capsys):
    d = str(tmp_path)
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
