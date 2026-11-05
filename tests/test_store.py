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


def test_settle_commits_a_leaked_transaction(tmp_path, capsys):
    s = Store(tmp_path)
    s.db.execute("INSERT INTO settings VALUES('k','1')")
    assert s.db.in_transaction
    s.settle("piece")
    assert not s.db.in_transaction and "piece left a database transaction open" in capsys.readouterr().out
    s.settle("piece")   # nothing open: silent
    assert capsys.readouterr().out == ""


def test_lock_error_names_the_thread_holding_a_transaction(tmp_path, monkeypatch, capsys):
    import sqlite3
    import threading

    import pytest

    from sc_activity_agent import store as store_mod
    monkeypatch.setattr(store_mod, "TIMEOUT", 0.2)
    s = Store(tmp_path)
    held, release = threading.Event(), threading.Event()

    def hold():
        s.db.execute("UPDATE settings SET value='x' WHERE key='nope'")
        s.db.execute("INSERT INTO settings VALUES('h','1')")
        held.set()
        release.wait(5)
        s.db.rollback()
    t = threading.Thread(target=hold, name="holder")
    t.start()
    held.wait(5)
    with pytest.raises(sqlite3.OperationalError):
        s.put("other", 2)
    release.set()
    t.join()
    out = capsys.readouterr().out
    assert "database is locked" in out and "holder:" in out and "hold" in out


def test_drop_removes_a_setting_instead_of_storing_null(tmp_path):
    s = Store(tmp_path)
    s.put("checklists", {"on": True})
    s.drop("checklists")
    assert s.db.execute("SELECT 1 FROM settings WHERE key='checklists'").fetchone() is None


def test_settle_idle_commits_only_threads_with_the_prefix(tmp_path, capsys):
    import threading
    s = Store(tmp_path)
    ready, go = threading.Event(), threading.Event()

    def leak():
        s.db.execute("INSERT INTO settings VALUES('w','1')")
        ready.set()
        go.wait(5)

    web = threading.Thread(target=leak, name="AnyIO worker thread")
    web.start()
    ready.wait(5)
    s.settle_idle("other")
    assert s._conns[web.ident].in_transaction   # wrong prefix: left alone
    s.settle_idle("AnyIO worker thread", "web request")
    assert not s._conns[web.ident].in_transaction and "web request left a database transaction open" in capsys.readouterr().out
    go.set()
    web.join()
