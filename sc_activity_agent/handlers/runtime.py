"""The Runtime the executors share: store, one app per connection, an rng, and user selection."""
import json

from ..client import ScError
from .common import ACTION, Skip


class Runtime:
    """What handlers need: the store, one ScApp per connection id, and an rng for note text and picks."""

    def __init__(self, store, apps, rng):
        self.store, self.apps, self.rng = store, apps, rng

    def candidates(self, location, step_kind, ctx):
        """Users who can do this step kind (users.can_do); provider-side ones limited to the WO's provider (ctx provider_id)."""
        action = ACTION[step_kind]
        rows = self.store.db.execute(
            "SELECT u.*, c.side, c.provider_id AS pid FROM users u JOIN connections c ON c.id=u.conn_id "
            "WHERE EXISTS (SELECT 1 FROM json_each(u.can_do) WHERE value=?) ORDER BY u.id", (action,)).fetchall()
        pid = ctx.get("provider_id")
        if pid:
            rows = [u for u in rows if u["side"] == "subscriber" or u["pid"] == pid]
        if not rows:
            who = f" for provider {pid}" if pid else ""
            raise ScError(409, f"no user{who} is set to {action} at {location}. Tick it under Can do on Connections.", "")
        return rows

    def rotate_user(self, wo, step):
        """After a user-bound failure: drop the step's pinned user into payload `tried` so the next run picks another. False when nobody is left
        (or the kind keeps its tech), and the step then fails for good."""
        if step["kind"] in ("check_in", "check_out"):
            return False
        p = json.loads(self.store.db.execute("SELECT payload FROM steps WHERE id=?", (step["id"],)).fetchone()[0])
        tried = p.get("tried", []) + ([p["user"]] if p.get("user") else [])
        if not p.get("user") or not [r for r in self.candidates(wo["location"], step["kind"], json.loads(wo["ctx"])) if r["id"] not in tried]:
            return False
        self.store.db.execute("UPDATE steps SET payload=? WHERE id=?", (json.dumps({**{k: v for k, v in p.items() if k != "user"}, "tried": tried}), step["id"]))
        return True

    def user_for(self, location, step_kind, wo=None, step=None):
        """Pick a user who can do this action (users.can_do). Provider-side actions are limited to users of the WO's provider
        (ctx provider_id; WOs without one fall back to every capable user). A check-out reuses the tech who checked in for that
        visit; a second tech on a visit never repeats one already used. Returns (app, (username, password))."""
        ctx = json.loads(wo["ctx"]) if wo else {}
        rows = self.candidates(location, step_kind, ctx)
        u = None
        if step_kind in ("check_in", "check_out"):
            p = json.loads(step["payload"])
            visit, tech = p.get("visit", 1), p.get("tech", 0)
            techs = ctx.get("techs", {})
            if step_kind == "check_out" and f"{visit}.{tech}" in techs:
                u = next((r for r in rows if r["id"] == techs[f"{visit}.{tech}"]), None)
            elif step_kind == "check_out" and tech:
                raise Skip   # the second tech never checked in, so there is nobody to check out
            if u is None and step_kind == "check_in":
                busy = {v for k, v in techs.items() if k.split(".")[0] == str(visit) and k != f"{visit}.{tech}"}   # a retry may re-pick its own slot
                free = [r for r in rows if r["id"] not in busy]
                if not free and tech:
                    raise Skip   # one check-in tech only: this visit stays single-tech
                u = self.rng.choice(free or rows)
                if wo:
                    self.save_ctx(wo, techs={**techs, f"{visit}.{tech}": u["id"]})
        if u is None and step is not None and "id" in step.keys():
            # one user owns a step: pinned on first pick (payload "user"), reused by every call in it and by each retry. Read the DB, the row may be stale
            p = json.loads(self.store.db.execute("SELECT payload FROM steps WHERE id=?", (step["id"],)).fetchone()[0])
            u = next((r for r in rows if r["id"] == p.get("user")), None)
            if u is None:
                u = self.rng.choice([r for r in rows if r["id"] not in p.get("tried", [])] or rows)
                self.store.db.execute("UPDATE steps SET payload=? WHERE id=?", (json.dumps({**p, "user": u["id"]}), step["id"]))
                self.store.db.commit()
        u = u or self.rng.choice(rows)
        return self.apps[u["conn_id"]], (u["username"], self.store.dec(u["password"]))

    def location(self, store_id):
        return self.store.db.execute("SELECT * FROM locations WHERE store_id=?", (store_id,)).fetchone()

    def save_ctx(self, wo, **kw):
        # merge into the stored context, not the row the caller holds: preflight may have saved newer values this step
        ctx = {**json.loads(self.store.db.execute("SELECT ctx FROM work_orders WHERE id=?", (wo["id"],)).fetchone()[0]), **kw}
        self.store.db.execute("UPDATE work_orders SET ctx=? WHERE id=?", (json.dumps(ctx), wo["id"]))
        self.store.db.commit()
        return ctx

