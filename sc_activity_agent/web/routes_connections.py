"""Connections page and user routes, split out of app.py (B-77)."""
from ..client import ScApp
from ..client import ScError
from ..creator import check_user
from ..creator import check_users
from ..hints import hint
from fastapi import Form
from fastapi import Request
from fastapi.responses import RedirectResponse
from urllib.parse import quote
import json
import time
from .app import CAN_DO


def register(app, db, missing_actions, no_tech, page, rt, store):
    @app.get("/connections")
    def connections(request: Request, msg: str = ""):
        conns = [dict(c, users=[dict(u) for u in db.execute("SELECT id,username,label,can_do FROM users WHERE conn_id=?", (c["id"],))])
                 for c in db.execute("SELECT id,side,name,client_id,provider_id FROM connections ORDER BY side DESC, id")]
        for c in conns:
            for u in c["users"]:
                u["can_do"] = json.loads(u["can_do"])
            c["actions"] = CAN_DO[c["side"]]
        return page(request, "connections", conns=conns, idle=[a for a in missing_actions()], techless=no_tech(), msg=msg, dashboard=info if isinstance(info := store.get("dashboard_info"), dict) else {},
                    subscriber_id=store.get("subscriber_id", ""))

    @app.post("/dashboards/load")
    def load_dashboards(subscriber_id: int = Form(...)):
        store.put("subscriber_id", subscriber_id)
        rows = check_users(store, subscriber_id, time.time())
        if not rows:
            return RedirectResponse("/connections?msg=Subscriber ID saved. Add a Subscriber user next", 303)
        return RedirectResponse("/connections?msg=" + quote(_dash_msg(rows, drop_create=True)), 303)

    def _dash_msg(rows, drop_create=False):
        """Message for dashboard rows. A user without a dashboard loses Create WOs, since a create would fail for them."""
        out = []
        for r in rows:
            if r["id"] is None:
                why = r["error"] or "no dashboard"
                out.append(f"{r['user']}: {why}. {hint(why)}".strip())
                if drop_create:
                    _no_create(r["user"])
            elif not r["list"] and store.get("subscriber_id"):
                out.append(f"{r['user']}: dashboard {r['id']} has no issue list for this Subscriber ID.")
        return " ".join(out) or "Dashboards checked"

    def _no_create(username):
        u = db.execute("SELECT id, can_do FROM users WHERE username=?", (username,)).fetchone()
        if u and "create_wo" in json.loads(u["can_do"]):
            db.execute("UPDATE users SET can_do=? WHERE id=?", (json.dumps([a for a in json.loads(u["can_do"]) if a != "create_wo"]), u["id"]))
            db.commit()

    @app.post("/users/{uid}/check-dashboard")
    def check_dashboard(uid: int):
        u = db.execute("SELECT u.*, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()
        r = check_user(store, ScApp(store.get("env"), u["client_id"], store.dec(u["client_secret"]), store=store, role="subscriber"),
                       (u["username"], store.dec(u["password"])), store.get("subscriber_id"), time.time())
        msg = _dash_msg([r], drop_create=True)
        if r["id"] is not None and msg == "Dashboards checked":
            msg = f"{u['username']}: dashboard {r['name'] or r['id']}, issue list {r['list'] or 'not checked (enter the Subscriber ID)'}"
        return RedirectResponse("/connections?msg=" + quote(msg), 303)

    @app.post("/connections/add")
    def add_connection(side: str = Form(...), name: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...),
                       provider_id: str = Form("")):
        if side == "subscriber" and db.execute("SELECT 1 FROM connections WHERE side='subscriber'").fetchone():
            return RedirectResponse("/connections?msg=Only one Subscriber connection is allowed", 303)
        pid = provider_id.strip()
        if side == "provider" and not pid.isdigit():
            return RedirectResponse("/connections?msg=" + quote("Enter the Provider ID as a number (find it in ServiceChannel under the Provider's profile). The agent needs it to read which trades this Provider is Rank 1 for."), 303)
        if pid and not pid.isdigit():
            return RedirectResponse("/connections?msg=" + quote("The Provider ID must be a number."), 303)
        db.execute("INSERT INTO connections(side,name,client_id,client_secret,provider_id) VALUES(?,?,?,?,?)",
                   (side, name, client_id.strip(), store.enc(client_secret.strip()), int(pid) if pid else None))
        db.commit()
        store.put("rank1", {})   # a new provider can be Rank 1 somewhere; re-read at the next creation pass
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/users")
    def add_user(cid: int, username: str = Form(...), password: str = Form(...), label: str = Form("")):
        c = db.execute("SELECT client_id, client_secret FROM connections WHERE id=?", (cid,)).fetchone()
        try:   # log in first: a user that cannot sign in is not saved
            ScApp(store.get("env"), c["client_id"], store.dec(c["client_secret"])).token(username.strip(), password)
        except (ScError, OSError) as e:
            why = f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)
            return RedirectResponse("/connections?msg=" + quote(f"{username.strip()} was not added: {why}. {hint(why)}".strip()), 303)
        side = db.execute("SELECT side FROM connections WHERE id=?", (cid,)).fetchone()["side"]
        first = not db.execute("SELECT 1 FROM users WHERE conn_id=?", (cid,)).fetchone()   # the first user on a connection can do everything
        db.execute("INSERT INTO users(conn_id,username,password,label,can_do) VALUES(?,?,?,?,?)",
                   (cid, username.strip(), store.enc(password), label, json.dumps([a for a, _ in CAN_DO[side]] if first else [])))
        db.commit()
        if side == "subscriber":   # B-92: read the user's dashboard now; without one the user cannot create WOs
            r = check_user(store, ScApp(store.get("env"), c["client_id"], store.dec(c["client_secret"]), store=store, role="subscriber"),
                           (username.strip(), password), store.get("subscriber_id"), time.time())
            msg = _dash_msg([r], drop_create=True)
            return RedirectResponse("/connections" + ("" if msg == "Dashboards checked" else "?msg=" + quote(msg)), 303)
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/can-do")
    async def set_can_do(uid: int, request: Request):
        side = db.execute("SELECT c.side FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()["side"]
        ok = {a for a, _ in CAN_DO[side]}
        picked = [a for a in (await request.form()).getlist("can_do") if a in ok]
        msg = ""
        if side == "subscriber" and "create_wo" in picked:   # B-92: a user with no dashboard cannot create WOs
            u = db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
            row = (store.get("dashboard_info") or {}).get(u["username"]) if isinstance(store.get("dashboard_info"), dict) else None
            if not row or row["id"] is None:
                picked.remove("create_wo")
                msg = f"?msg={quote(u['username'] + ' has no dashboard, so Create WOs was not ticked. Press Check dashboard on that user, or assign a dashboard to the user in ServiceChannel.')}"
        db.execute("UPDATE users SET can_do=? WHERE id=?", (json.dumps(picked), uid))
        db.commit()
        return RedirectResponse("/connections" + msg, 303)

    @app.post("/users/{uid}/label")
    def set_label(uid: int, label: str = Form("")):
        db.execute("UPDATE users SET label=? WHERE id=?", (label.strip(), uid))
        db.commit()
        return RedirectResponse("/connections", 303)

    @app.post("/connections/{cid}/delete")
    def del_connection(cid: int):
        db.execute("DELETE FROM connections WHERE id=?", (cid,))
        db.commit()
        if rt is not None:
            rt.apps.pop(cid, None)
        store.put("rank1", {})
        return RedirectResponse("/connections", 303)

    @app.post("/users/{uid}/test")
    def test_user(uid: int):
        u = db.execute("SELECT u.*, c.client_id, c.client_secret FROM users u JOIN connections c ON c.id=u.conn_id WHERE u.id=?", (uid,)).fetchone()
        try:
            ScApp(store.get("env"), u["client_id"], store.dec(u["client_secret"])).token(u["username"], store.dec(u["password"]))
            msg = f"{u['username']}: connection OK"
        except (ScError, OSError) as e:
            why = f"Could not reach ServiceChannel: {e}" if isinstance(e, OSError) else str(getattr(e, "body", None) or e)
            msg = f"{u['username']}: {why}. {hint(why)}".strip()
        return RedirectResponse("/connections?msg=" + quote(msg), 303)

    @app.post("/users/{uid}/delete")
    def del_user(uid: int):
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
        return RedirectResponse("/connections", 303)
