"""B-22: answering the location's checklists before the primary tech checks out."""
import json

from .. import content, photos
from ..client import ScError


class NoChecklist(Exception):
    """The WO has no active checklist for the question just answered."""


def build(rt, call, ctx_of):
    def answer_checklists(wo, step):
        """B-22: before the primary tech checks out, answer every checklist the location has for the WO's trade (Settings toggle, off by
        default). One answer per question per visit (Attempt = visit). A picture question gets the WO's photo set, side by side. Fail-soft:
        any API refusal is audited and skipped, so the check-out still goes through. Questions per asset (B-23/B-24) are skipped."""
        c, p = ctx_of(wo), json.loads(step["payload"])
        visit = p.get("visit", 1)
        if not rt.store.get("checklists", {}).get("on") or p.get("tech", 0) or visit in c.get("checklists", []) or not c.get("provider_id"):
            return
        loc = rt.location(wo["location"])
        try:
            app, user = rt.user_for(wo["location"], "check_out", wo, step)
            found = app.call(user, "GET", "/checklists/detail", action="checklist_read", wo=wo["sc_id"], write=False,
                             params={"tradeName": wo["trade"], "storeId": loc["store_id"], "subscriberId": loc["subscriber_id"]}) or {}
            qs = [q for lst in found.get("CheckListDetails", []) for q in lst.get("Questions", [])]
            uid = sc_user_id(app, user, wo) if qs else None
            left = []
            for q in qs:
                if not answer_question(app, user, wo, c, visit, q, uid) and q.get("AnswerRequired"):
                    left.append(q["Id"])
            if left:   # ServiceChannel will not submit the checklist while a required question is open: leave a trace instead of a silent gap
                rt.store.log(role="provider", user=user[0], sc_wo=wo["sc_id"], action="checklist_required_open", method=None, path="/checklists",
                             http=0, ms=0, detail=f"required questions not answered: {left}")
        except NoChecklist:
            pass
        except ScError as e:
            if e.status == 0:
                raise   # paused: leave the visit unmarked so the step answers once it resumes
        rt.save_ctx(wo, checklists=[*c.get("checklists", []), visit])

    def sc_user_id(app, user, wo):
        """The ServiceChannel id of the user answering (AuthUserId on the response), read once from /users/current/profile and kept in
        users.sc_user_id. None when the profile has no `AuthUserId`: the answers then fall back to TechnicianID 1."""
        row = rt.store.db.execute("SELECT id, sc_user_id FROM users WHERE username=?", (user[0],)).fetchone()
        if row and row["sc_user_id"]:
            return row["sc_user_id"]
        try:
            prof = app.call(user, "GET", "/users/current/profile", action="user_lookup", wo=wo["sc_id"], write=False)
        except ScError as e:
            if e.status == 0:
                raise
            return None
        prof = prof.get("UserProfile") if isinstance(prof, dict) else None   # verified on SB2: {"UserProfile": {"UserId", "AuthUserId", ...}}
        uid = prof.get("AuthUserId") if isinstance(prof, dict) else None
        uid = uid if isinstance(uid, int) and uid > 0 else None
        if uid and row:
            rt.store.db.execute("UPDATE users SET sc_user_id=? WHERE id=?", (uid, row["id"]))
            rt.store.db.commit()
        return uid

    def answer_question(app, user, wo, c, visit, q, uid=None):
        """True when an answer was sent (or refused by the API, which the audit log shows); False when the agent cannot answer this question."""
        if q.get("DisplayForEachAsset"):
            return False
        # shortcut: without a known user id send TechnicianID 1 (any nonzero id is accepted on SB2); numbers are a small random count
        req = {"CheckListQuestionID": q["Id"], "ProviderID": c["provider_id"], "EntityID": wo["sc_id"], "Attempt": visit,
               **({"AuthUserID": uid} if uid else {"TechnicianID": 1})}
        kind = q["QuestionType"]
        if kind == 0:
            req["Answer"] = "on"   # "yes" returns a misleading "checklist not found"
        elif kind == 1:
            opts = [o for o in q["CheckListQuestionOptions"] if not o.get("IsConditionalFollowUp")]
            if not opts:
                return False
            req["CheckListQuestionOptionID"] = rt.rng.choice(opts)["Id"]
        elif kind == 2:
            req["Answer"] = content.note("provider", "complete", c, rt.rng)
        elif kind == 4:
            req["Answer"] = str(rt.rng.randint(1, 4))
        else:
            return False
        parts = [("CheckListResponseRequest", None, "application/json", json.dumps(req).encode())]
        if q.get("PictureFlag"):
            pic = photos.pick(wo["trade"], "both", rt.rng, c.get("photo_set"), f'{c.get("equipment", "")} {c.get("issue", "")}', photos.recent(rt.store, wo["location"]))
            if pic:
                c["photo_set"] = pic[0]
                rt.save_ctx(wo, photo_set=pic[0])
                parts.append(("file", pic[1], "image/jpeg", pic[2]))
        try:
            app.call(user, "POST", "/checklists/CheckListResponse", action="checklist_answer", wo=wo["sc_id"], write=True, parts=parts)
        except ScError as e:
            if e.status == 0:
                raise   # paused: stop answering
            if '"ErrorCode":503' in str(getattr(e, "body", "")):
                raise NoChecklist   # the checklist is not active on this WO: every other question gets the same 503 (11 audit rows on Prod, 2026-11-06)
        return True

    return answer_checklists
