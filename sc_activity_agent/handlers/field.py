"""Provider field work: accept, decline, reassign, reschedule, check-in (with asset attach) and check-out (with checklists and the after photo)."""
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from .. import assets, content, photos, planner
from ..client import ScError
from .common import _iso, insert_steps


def build(rt, call, ctx_of, answer_checklists):
    def accept(engine, wo, step):
        text = content.note("provider", "ack", ctx_of(wo), rt.rng)
        call(wo, step, "PUT", f"/workorders/{wo['sc_id']}/accept", body={"Note": text})

    def decline(engine, wo, step):
        # no Note: a note on a decline fails with 501 even though the decline goes through (SB2, 2026-10-28)
        call(wo, step, "PUT", f"/workorders/{wo['sc_id']}/decline", body={"DeclineReasonId": json.loads(step["payload"])["reason"]})

    def reassign(engine, wo, step):
        """B-20: after a decline or a no-show, move the WO to another provider connection that holds a contract for its trade at the location
        (the API refuses the move otherwise), then plan the new provider's work. With no such provider, cancel as a plain decline does."""
        p = json.loads(step["payload"])
        loc, ctx = rt.location(wo["location"]), ctx_of(wo)
        app, user = rt.user_for(wo["location"], "reassign", wo, step)
        rows = rt.store.db.execute(
            "SELECT DISTINCT c.provider_id FROM connections c JOIN users u ON u.conn_id=c.id WHERE c.side='provider' AND c.provider_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM json_each(u.can_do) WHERE value='accept')").fetchall()
        # ctx may not carry the provider (a WO is routed by contract rank), so read the live one
        current = (call(wo, step, "GET", f"/workorders/{wo['sc_id']}").get("Provider") or {}).get("Id") or ctx.get("provider_id")
        targets = []
        for r in rows:
            if r["provider_id"] == current:
                continue
            try:
                found = app.call(user, "GET", "/contracts", params={"locationDbId": loc["db_id"], "providerId": r["provider_id"], "trade": wo["trade"]},
                                 action="reassign_lookup", wo=wo["sc_id"], write=False)
            except ScError as e:
                if e.status >= 500:
                    raise   # a server fault is not "no contract": let the engine retry the step instead of cancelling the WO
                continue
            if (found or {}).get("Contracts"):
                targets.append(r["provider_id"])
        new = rt.rng.choice(targets) if targets else None
        if new is not None:
            try:
                app.call(user, "PUT", f"/workorders/{wo['sc_id']}/reassign", action="reassign", wo=wo["sc_id"], write=True,
                         body={"ProviderId": new, "ReasonId": p["reason"]})
            except ScError as e:
                if e.status != 400:
                    raise
                new = None   # refused (for example the contract changed): fall back to the cancel
        now = time.time()
        # the rest of the old plan belonged to the old provider (a no-show or a mid-job move leaves steps such as check-out pending)
        rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND seq>? AND state='pending'", (wo["id"], step["seq"]))
        if new is None:
            insert_steps(rt.store, wo["id"], step["seq"], [("cancel", now + rt.rng.randint(1, 3) * 86400, {"situation": p.get("cancel", "declined")})])
            return
        rt.save_ctx(wo, provider_id=new, techs={})
        cfg = {**planner.DEFAULTS, **rt.store.get("behavior", {}), "decline": 0, "reschedule": 0, "reassign": 0, "no_show": 0}
        plan = planner.build_plan(rt.rng, now, cfg, loc["tz"] or "America/New_York")
        insert_steps(rt.store, wo["id"], step["seq"], [(s["kind"], s["due_at"], s["payload"]) for s in plan])

    def reschedule(engine, wo, step):
        p = json.loads(step["payload"])
        tz = (rt.location(wo["location"])["tz"] or "America/New_York")
        app, user = rt.user_for(wo["location"], "reschedule", wo, step)
        app.call(user, "PUT", f"/workorders/{wo['sc_id']}/scheduledate", params={"rescheduleReasonCode": p["reason"]}, action="reschedule", wo=wo["sc_id"],
                 write=True, body={"Value": dt.datetime.fromtimestamp(p["to"], ZoneInfo(tz)).strftime("%Y-%m-%dT%H:%M:%S"), "Actor": user[0]})
        rt.save_ctx(wo, sched=None)   # our own move: the next preflight reads the new date as the baseline

    def checkio(path, body, wo, step):
        try:
            call(wo, step, "POST", path, body=body)
        except ScError as e:
            if e.status == 403 and "804" in str(e):
                raise ScError(403, "No check-in/out permission for this Subscriber and Provider pair. ServiceChannel must enable XML "
                                   "or GPS check-in/out for the pair (see README, Prerequisites).", path) from e
            raise

    def check_in(engine, wo, step):
        loc = rt.location(wo["location"])
        checkio(f"/workorders/{wo['sc_id']}/universalCheckIn",
                {"Latitude": loc["lat"], "Longitude": loc["lon"], "TechsCount": 1, "CheckInTime": _iso(step["due_at"])}, wo, step)
        attach_asset(wo, step)

    def attach_asset(wo, step):
        """B-24: once per WO, on its first check-in, the provider attaches a seeded asset (Behavior slider, default 0) when the WO was created
        without one. The call needs a user of the WO's own provider and an asset of the WO's trade at its location. Fail-soft: a refusal or a
        pause only skips the attach (shortcut: a paused attach is not retried), the visit goes on."""
        c = ctx_of(wo)
        pct = {**planner.DEFAULTS, **rt.store.get("behavior", {})}["asset_on_site"]
        if not pct or c.get("asset_id") or c.get("asset_tried") or json.loads(step["payload"]).get("tech", 0):
            return
        rt.save_ctx(wo, asset_tried=True)
        if rt.rng.random() * 100 >= pct:
            return
        asset = assets.pick(rt.store, rt.rng, wo["location"], c.get("equipment", ""), wo["trade"])
        if not asset:
            return
        try:
            app, user = rt.user_for(wo["location"], "check_in", wo, step)
            app.call(user, "PUT", f"/assets/workorders/{wo['sc_id']}/attach", action="asset_attach", wo=wo["sc_id"], write=True, body={"AssetId": asset})
            rt.save_ctx(wo, asset_id=asset)
        except ScError:
            pass

    def check_out(engine, wo, step):
        p = json.loads(step["payload"])
        answer_checklists(wo, step)
        loc = rt.location(wo["location"])
        text = content.note("provider", p["situation"], ctx_of(wo), rt.rng)
        # the first tech out of a crew visit must not complete the WO, but only if the second tech really checked in
        partial = bool(p.get("partial")) and f"{p['visit']}.1" in ctx_of(wo).get("techs", {})
        checkio(f"/workorders/{wo['sc_id']}/universalCheckOut",
                {"Latitude": loc["lat"], "Longitude": loc["lon"], "CheckOutTime": _iso(step["due_at"]),
                 "PrimaryStatus": "Completed" if p["final"] and not partial else "PartsOnOrder",   # Completed closes the WO and blocks the second tech's check-out (921)
                  "ActionStatus": "Complete",
                 "Resolution": text, "TechsCount": 1}, wo, step)
        if p["final"] and not partial and not p.get("tech", 0):
            attach_after(wo, step)

    def attach_after(wo, step):
        """B-53: the provider's closing note carries the after photo, at the Behavior "after photo" rate (0 by default). The check-out already
        went through, so any refusal, even a pause, is skipped; a retry would only fail the check-out."""
        if rt.rng.random() * 100 >= {**planner.DEFAULTS, **rt.store.get("behavior", {})}["photo_after"]:
            return
        c = ctx_of(wo)
        pic = photos.pick(wo["trade"], "after", rt.rng, c.get("photo_set"), f'{c.get("equipment", "")} {c.get("issue", "")}', photos.recent(rt.store, wo["location"]))
        if not pic:
            return
        try:
            n = call(wo, step, "POST", f"/workorders/{wo['sc_id']}/notes",
                     body={"Note": content.note("provider", "complete", c, rt.rng), "NotifyFollowers": False, "DoNotSendEmail": True}) or {}
            if n.get("id"):
                call(wo, step, "POST", f"/workorders/{wo['sc_id']}/notes/{n['id']}/attachments", parts=photos.attach_parts(pic, "Photo after the work", as_list=True))
                rt.save_ctx(wo, photo_set=pic[0])
        except ScError:
            pass

    return {"accept": accept, "decline": decline, "reassign": reassign, "reschedule": reschedule, "check_in": check_in, "check_out": check_out}
