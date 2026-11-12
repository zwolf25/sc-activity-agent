"""Subscriber review (plain confirm or a star rating) and the rework visit a bad rating plans."""
import datetime as dt
import json

from .. import content, planner
from ..client import Park
from .common import insert_steps


def build(rt, call, ctx_of):
    def review(engine, wo, step):
        """Subscriber verifies the work. Plain: COMPLETED/CONFIRMED with the review text as the status note. With the Behavior sliders (B-25) a share of
        reviews (star_rating) is a rating instead (POST /feedbacks). Of those, rework % get 1 or 2 stars and mark the WO Unsatisfactory (IN PROGRESS)
        so the provider returns for another visit; the rest get 3 to 5 stars and confirm it. Feedback is only accepted while the WO is COMPLETED / PENDING CONFIRMATION (verified on SB2)."""
        def confirm():
            again = json.loads(step["payload"]).get("round", 1) > 1   # the second review follows a return visit
            text = content.note("subscriber", "review_rework" if again else "review", ctx_of(wo), rt.rng)
            return call(wo, step, "PUT", f"/workorders/{wo['sc_id']}/status",
                        body={"Status": {"Primary": "COMPLETED", "Extended": "CONFIRMED"}, "Note": text})

        def rolled(key, fn):   # roll once and keep it in the payload: a retry must not turn a rating into a plain confirm or back
            p = json.loads(rt.store.db.execute("SELECT payload FROM steps WHERE id=?", (step["id"],)).fetchone()[0]) if "id" in step.keys() else {}
            if key not in p:
                p[key] = fn()
                if "id" in step.keys():
                    rt.store.db.execute("UPDATE steps SET payload=? WHERE id=?", (json.dumps(p), step["id"]))
                    rt.store.db.commit()
            return p[key]
        b = {**planner.DEFAULTS, **rt.store.get("behavior", {})}
        if not rolled("rated", lambda: rt.rng.random() * 100 < b["star_rating"]):
            return confirm()
        bad = rolled("bad", lambda: rt.rng.random() * 100 < b["rework"] and json.loads(step["payload"]).get("round", 1) < 2)   # one rework round at most, so a WO always finishes
        live = (call(wo, step, "GET", f"/workorders/{wo['sc_id']}") or {}).get("Status", {})   # feedback is refused (501) outside COMPLETED / PENDING CONFIRMATION
        if live.get("Extended") == "CONFIRMED":
            return   # a user already confirmed it; never overturn
        if live.get("Primary") != "COMPLETED":
            raise Park(f"WO status {live} is not one a rating can be posted in. Skip the step to carry on, or cancel the WO.")
        if live.get("Extended") in ("NO CHARGE", "CANCELED"):
            return   # a user closed it that way; never overturn
        if live.get("Extended") != "PENDING CONFIRMATION":
            return confirm()   # feedback gets 501 "Invalid WorkOrder status" here, the plain confirm still works
        loc = rt.location(wo["location"])
        stars = rt.rng.choice([1, 2]) if bad else rt.rng.choice([3, 4, 4, 5, 5])
        fb = {"Answer": "unsatisfactory" if bad else "satisfactory", "StarScore": stars, "LocationId": loc["db_id"], "SubscriberId": loc["subscriber_id"]}
        if bad or stars < 3:
            c = {**ctx_of(wo), "complaint": content.complaint(ctx_of(wo), rt.rng), "last_visit": last_visit(wo)}
            fb["Comment"] = content.note("subscriber", "low_stars" if stars < 2 else "unsatisfactory", c, rt.rng)
        call(wo, step, "POST", f"/feedbacks/workorders/{wo['sc_id']}", body=fb)
        if bad:
            rt.save_ctx(wo, complaint=c["complaint"])   # the provider's return note answers the same complaint
            rework(engine, wo, step)

    def last_visit(wo):
        """'Tuesday's visit' from the latest finished check-out, or None-safe fallback text."""
        r = rt.store.db.execute("SELECT done_at FROM steps WHERE wo_id=? AND kind='check_out' AND state='done' ORDER BY done_at DESC LIMIT 1", (wo["id"],)).fetchone()
        return f"{dt.datetime.fromtimestamp(r[0]):%A}'s visit" if r and r[0] else "the last visit"

    def rework(engine, wo, step):
        """Plan the return: a provider note, another visit, a final check-out and a second review. Every later step moves back by the
        length of the rework, so the invoice still follows the last review."""
        rows = rt.store.db.execute("SELECT payload FROM steps WHERE wo_id=? AND kind='check_in'", (wo["id"],)).fetchall()
        visit = max([json.loads(r["payload"]).get("visit", 1) for r in rows] + [1]) + 1
        t_in = engine.snap(step["due_at"] + 86400, wo["location"])
        t_out = t_in + int(rt.rng.uniform(1.5, 3) * 3600)
        t_rev = t_out + rt.rng.randint(3600, 86400)
        rt.store.db.execute("UPDATE steps SET payload=? WHERE wo_id=? AND seq=?", (json.dumps({**json.loads(step["payload"]), "unsatisfactory": True}), wo["id"], step["seq"]))
        rt.store.db.execute("UPDATE steps SET due_at=due_at+? WHERE wo_id=? AND seq>? AND state='pending'", (t_rev - step["due_at"], wo["id"], step["seq"]))
        insert_steps(rt.store, wo["id"], step["seq"], [
            ("prov_note", t_in - 3600, {"situation": "rework"}),
            ("check_in", t_in, {"visit": visit, "tech": 0, "situation": "return"}),
            ("check_out", t_out, {"visit": visit, "final": True, "situation": "complete"}),
            ("review", t_rev, {"situation": "review", "round": 2})])

    return {"review": review}
