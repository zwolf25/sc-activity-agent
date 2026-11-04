from sc_activity_agent.store import Store




def test_get_null_uses_default(tmp_path):
    s = Store(tmp_path)
    s.put("checklists", None)
    assert s.get("checklists", {}) == {}
