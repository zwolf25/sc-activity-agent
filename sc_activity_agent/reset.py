"""Factory reset: back the database up, then clear everything the user entered or the agent learned, so the instance starts setup again.
Keeps what `agent init` chose (environment, port, twin port), the secret key and the backups folder. Work orders already created in
ServiceChannel are not touched; the agent only forgets them."""
import time
from contextlib import contextmanager
from pathlib import Path

from . import update

KEEP = ("env", "port", "twin_port")   # locked per data folder at init; the console could not start without them


def factory_reset(store, rt=None, engine=None):
    """Returns the path of the backup taken first. The caller must make sure nothing else is writing (see `busy`)."""
    path = update.backup(store)
    db = store.db
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        if t != "settings":
            db.execute(f'DELETE FROM "{t}"')
    db.execute(f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(KEEP))})", KEEP)
    db.commit()
    for pattern in ("issuelist-*.json", "assets-brands.json"):   # caches of the old Subscriber's data
        for f in store.dir.glob(pattern):
            f.unlink()
    if rt is not None:
        rt.apps.clear()   # connection ids restart at 1; a cached app would sign in with the old client secret
    if engine is not None:
        engine.paused_at = None
        engine.only_wo = None
    return path


def busy(store):
    """Why a reset must wait, or ''."""
    if (store.get("cleanup_run") or {}).get("running"):
        return "A clean-up is running. Wait for it to finish."
    if update.in_progress(store):
        return "An update is installing."
    return ""


class Busy(Exception):
    pass


@contextmanager
def quiesced(engine, wait=60):
    """Pause the step loop and wait for the pass in progress to end, so a reset or restore never overlaps a step. If the pass does not
    end within `wait` seconds, undo the pause and raise Busy. A pause that was already on stays on."""
    if engine is None:
        yield
        return
    was_paused = engine.paused
    if not was_paused:
        engine.pause()
    end = time.time() + wait
    while getattr(engine, "running", False) and time.time() < end:
        time.sleep(0.2)
    if getattr(engine, "running", False):
        if not was_paused:
            engine.resume("push")
        raise Busy("The agent is still working on a step. Try again in a minute.")
    try:
        yield
    except BaseException:
        if not was_paused:
            engine.resume("push")
        raise


def restore_live(store, name, rt=None, engine=None):
    """B-89: replace the database content with a backup while the agent runs: copy every table's rows from the backup into the live
    database in one transaction (a running agent keeps open connections, so the file cannot be swapped). The current database is backed
    up first. Columns the backup lacks get their defaults. The environment, port and twin port of this instance are kept, so a backup
    from another instance cannot flip the environment. Returns the path of the safety copy."""
    src = store.dir / "backups" / Path(name).name
    if not src.is_file():
        raise FileNotFoundError(name)
    keep = update.backup(store)
    kept = {k: store.get(k) for k in KEEP}
    db = store.db
    db.commit()
    db.execute("ATTACH DATABASE ? AS bk", (str(src),))
    try:
        main = [r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        have = {r[0] for r in db.execute("SELECT name FROM bk.sqlite_master WHERE type='table'")}
        copy = []
        for t in main:
            if t in have:
                cols = [r[1] for r in db.execute(f'PRAGMA main.table_info("{t}")')]
                theirs = {r[1] for r in db.execute(f'PRAGMA bk.table_info("{t}")')}
                copy.append((t, ",".join(f'"{c}"' for c in cols if c in theirs)))
        for t, _ in reversed(copy):
            db.execute(f'DELETE FROM main."{t}"')
        for t, cols in copy:
            db.execute(f'INSERT INTO main."{t}"({cols}) SELECT {cols} FROM bk."{t}"')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.execute("DETACH DATABASE bk")
    for k, v in kept.items():
        if v is not None:
            store.put(k, v)
    if rt is not None:
        rt.apps.clear()
    if engine is not None:
        engine.paused_at = store.get("paused_at")
        engine.only_wo = None
    return keep
