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
