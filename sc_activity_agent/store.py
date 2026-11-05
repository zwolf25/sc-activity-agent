"""SQLite state for one instance: settings, encrypted secrets, connections/users/roles, WOs, plan steps, audit log."""
import json
import sqlite3
import sys
import threading
import time
import traceback
from pathlib import Path

from cryptography.fernet import Fernet

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connections(
  id INTEGER PRIMARY KEY, side TEXT NOT NULL CHECK(side IN ('subscriber','provider')),
  name TEXT NOT NULL, client_id TEXT NOT NULL, client_secret TEXT NOT NULL, provider_id INTEGER);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, conn_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  username TEXT NOT NULL, password TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', sc_user_id INTEGER);
CREATE TABLE IF NOT EXISTS locations(
  store_id TEXT PRIMARY KEY, db_id INTEGER, subscriber_id INTEGER, name TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  lat REAL, lon REAL, tz TEXT, overrides TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS work_orders(
  id INTEGER PRIMARY KEY, sc_id INTEGER UNIQUE, location TEXT NOT NULL, trade TEXT, state TEXT NOT NULL,
  created_at REAL NOT NULL, ctx TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS steps(
  id INTEGER PRIMARY KEY, wo_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, kind TEXT NOT NULL, due_at REAL NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','done','failed','skipped')),
  attempts INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}', error TEXT, done_at REAL);
CREATE INDEX IF NOT EXISTS steps_due ON steps(state, due_at);
CREATE TABLE IF NOT EXISTS api_log(
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, role TEXT, user TEXT, sc_wo INTEGER, action TEXT,
  method TEXT, path TEXT, http INTEGER, ms INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS api_log_ts ON api_log(ts);
"""


# Each entry upgrades the schema by one version (PRAGMA user_version). Append only; never edit a shipped entry.
MIGRATIONS = [
    # 1 (v0.6.0): roles move onto the user. Only the '*' default rows convert; per-location overrides are dropped.
    # The roles table is created here, not in SCHEMA, so migration 4 can drop it for good.
    """
    CREATE TABLE IF NOT EXISTS roles(
      location TEXT NOT NULL, action TEXT NOT NULL, user_ids TEXT NOT NULL, pick TEXT NOT NULL DEFAULT 'single',
      PRIMARY KEY(location, action));
    ALTER TABLE users ADD COLUMN can_do TEXT NOT NULL DEFAULT '[]';
    UPDATE users SET can_do=(SELECT json_group_array(r.action) FROM roles r
                             WHERE r.location='*' AND EXISTS (SELECT 1 FROM json_each(r.user_ids) j WHERE j.value=users.id));
    """,
    # 2 (B-67): assets and asset types the agent created, so reruns and `enrich` know which are ours.
    """
    CREATE TABLE IF NOT EXISTS assets(
      id INTEGER PRIMARY KEY, location TEXT NOT NULL, tag TEXT NOT NULL, trade TEXT, type TEXT, created_at REAL NOT NULL,
      UNIQUE(location, tag));
    CREATE TABLE IF NOT EXISTS asset_types(id INTEGER PRIMARY KEY, name TEXT NOT NULL, trade TEXT, created_at REAL NOT NULL);
    """,
    # 3 (B-63): the contracts table was never read; Rank 1 trades live in the `rank1` setting. An older build that
    # runs on this database again only ever created it with IF NOT EXISTS, so a downgrade is safe.
    "DROP TABLE IF EXISTS contracts;",
    # 4 (B-76): roles was only read by migration 1. An older build that runs on this database again would create it empty
    # and, since roles live on the user since 0.6.0, ignore it, so a downgrade is safe.
    "DROP TABLE IF EXISTS roles;",
]


TIMEOUT = 30   # seconds a statement waits on another connection's lock


class _Conn(sqlite3.Connection):
    """Reports who holds the lock when a statement gives up on `database is locked`, then re-raises."""
    report = None

    def execute(self, *a, **k):
        try:
            return super().execute(*a, **k)
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and self.report:
                self.report()
            raise

    def commit(self):
        try:
            return super().commit()
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and self.report:
                self.report()
            raise


class Store:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        key_file = self.dir / "secret.key"
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
            key_file.chmod(0o600)
        self.fernet = Fernet(key_file.read_bytes())
        self._tl = threading.local()
        self._conns = {}   # thread id -> its connection, only so a lock error can name the thread holding a transaction open
        self._reported = 0
        self.db.executescript(SCHEMA)
        v = self.db.execute("PRAGMA user_version").fetchone()[0]
        for n in range(v, len(MIGRATIONS)):
            self.db.executescript(MIGRATIONS[n])
            self.db.execute(f"PRAGMA user_version={n + 1}")
        self.db.commit()

    @property
    def db(self):
        """One connection per thread: the engine, web and sweep threads must not share one (sqlite3 raises InterfaceError on overlap)."""
        c = getattr(self._tl, "c", None)
        if c is None:
            c = self._tl.c = sqlite3.connect(self.dir / "agent.db", timeout=TIMEOUT, factory=_Conn, check_same_thread=False)
            c.report = self.report_lock
            self._conns[threading.get_ident()] = c
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA journal_mode=WAL")   # readers (web, sweep, alerts threads) never wait on the step loop's write lock
        return c

    def settle(self, where=""):
        """Commit a transaction the calling thread left open, and say so: an open write transaction blocks every other writer.
        Call it when a loop piece or background thread finishes."""
        c = getattr(self._tl, "c", None)
        if c is not None and c.in_transaction:
            c.commit()
            if where:
                print(time.strftime("%H:%M:%S"), f"{where} left a database transaction open; committed it")

    def settle_idle(self, prefix, where=""):
        """Commit open transactions on the connections of threads named `prefix...`. Only call it when none of those threads is
        working (the web middleware calls it with no request in flight), because it commits from another thread."""
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, c in list(self._conns.items()):
            try:
                if c.in_transaction and names.get(ident, "").startswith(prefix):
                    c.commit()
                    if where:
                        print(time.strftime("%H:%M:%S"), f"{where} left a database transaction open; committed it")
            except sqlite3.ProgrammingError:
                self._conns.pop(ident, None)   # that thread's connection is closed

    def report_lock(self):
        """Log which threads hold a transaction open and where they are, at most once a minute."""
        if time.time() - self._reported < 60:
            return
        self._reported = time.time()
        frames, names = sys._current_frames(), {t.ident: t.name for t in threading.enumerate()}
        print(time.strftime("%H:%M:%S"), "database is locked. Threads with a transaction open:")
        for ident, c in list(self._conns.items()):
            try:
                if c.in_transaction and ident in frames:
                    where = " <- ".join(f.strip().splitlines()[0] for f in reversed(traceback.format_stack(frames[ident])[-4:]))
                    print(f"  {names.get(ident, ident)}: {where}")
            except sqlite3.ProgrammingError:
                self._conns.pop(ident, None)   # that thread's connection is closed

    # secrets are encrypted at rest and only decrypted when used
    def enc(self, plain):
        return self.fernet.encrypt(plain.encode()).decode()

    def dec(self, token):
        return self.fernet.decrypt(token.encode()).decode()

    def get(self, key, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        v = json.loads(r["value"]) if r else None
        return default if v is None else v   # a stored null (cleared setting) means "use the default", not None

    def put(self, key, value):
        self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))
        self.db.commit()

    def drop(self, key):
        self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()

    def log(self, **kw):
        kw.setdefault("ts", time.time())
        cols = ",".join(kw)
        self.db.execute(f"INSERT INTO api_log({cols}) VALUES({','.join('?' * len(kw))})", tuple(kw.values()))
        self.db.commit()

    def count_calls_since(self, since):
        return self.db.execute("SELECT COUNT(*) FROM api_log WHERE ts>=? AND method IS NOT NULL", (since,)).fetchone()[0]
