"""SQLite state for one instance: settings, encrypted secrets, connections/users/roles, WOs, plan steps, audit log."""
import json
import sqlite3
import time
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
CREATE TABLE IF NOT EXISTS roles(
  location TEXT NOT NULL, action TEXT NOT NULL, user_ids TEXT NOT NULL, pick TEXT NOT NULL DEFAULT 'single',
  PRIMARY KEY(location, action));
CREATE TABLE IF NOT EXISTS locations(
  store_id TEXT PRIMARY KEY, db_id INTEGER, subscriber_id INTEGER, name TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  lat REAL, lon REAL, tz TEXT, overrides TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS contracts(
  location TEXT NOT NULL, trade_id INTEGER NOT NULL, trade TEXT, provider_id INTEGER, rank INTEGER, synced_at REAL,
  PRIMARY KEY(location, trade_id));
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
MIGRATIONS = []


class Store:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        key_file = self.dir / "secret.key"
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
            key_file.chmod(0o600)
        self.fernet = Fernet(key_file.read_bytes())
        self.db = sqlite3.connect(self.dir / "agent.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        v = self.db.execute("PRAGMA user_version").fetchone()[0]
        for n in range(v, len(MIGRATIONS)):
            self.db.executescript(MIGRATIONS[n])
            self.db.execute(f"PRAGMA user_version={n + 1}")
        self.db.commit()

    # secrets are encrypted at rest and only decrypted when used
    def enc(self, plain):
        return self.fernet.encrypt(plain.encode()).decode()

    def dec(self, token):
        return self.fernet.decrypt(token.encode()).decode()

    def get(self, key, default=None):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def put(self, key, value):
        self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))
        self.db.commit()

    def log(self, **kw):
        kw.setdefault("ts", time.time())
        cols = ",".join(kw)
        self.db.execute(f"INSERT INTO api_log({cols}) VALUES({','.join('?' * len(kw))})", tuple(kw.values()))
        self.db.commit()

    def count_calls_since(self, since):
        return self.db.execute("SELECT COUNT(*) FROM api_log WHERE ts>=? AND method IS NOT NULL", (since,)).fetchone()[0]
