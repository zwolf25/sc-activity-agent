"""Factory reset: back the database up, then clear everything the user entered or the agent learned, so the instance starts setup again.
Keeps what `agent init` chose (environment, port, twin port), the secret key and the backups folder. Work orders already created in
ServiceChannel are not touched; the agent only forgets them."""
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
