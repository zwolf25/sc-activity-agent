from sc_activity_agent.store import Store




def test_get_null_uses_default(tmp_path):
    s = Store(tmp_path)
    s.put("checklists", None)
    assert s.get("checklists", {}) == {}


def test_reader_is_not_blocked_by_an_open_write(tmp_path):
    import threading
    s = Store(tmp_path)
    s.put("x", 1)
    s.db.execute("UPDATE settings SET value='2' WHERE key='x'")   # write transaction left open on this thread
    out = []
    t = threading.Thread(target=lambda: out.append(s.get("x")))
    t.start()
    t.join(5)
    assert out == [1]
