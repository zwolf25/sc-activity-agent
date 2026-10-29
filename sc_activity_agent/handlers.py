"""Step executors: one per plan step kind. Each picks the mapped user, calls the API as that user, and stores ids it needs later in the WO ctx.

Verified on SB2: sub_note, accept, prov_note, check_in, check_out, review. invoice_submit, invoice_decide (approve and reject). Proposals: create (provider), assignWO then approve (subscriber) and reject verified on SB2."""
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from . import content, planner
from .client import ScError

ACTION = {"accept": "accept", "prov_note": "provider_note", "sub_note": "subscriber_note", "review": "review",
          "proposal_create": "proposal_create", "proposal_decide": "proposal_decide", "check_in": "check_in",
          "check_out": "check_out", "invoice_submit": "invoice_submit", "invoice_decide": "invoice_decide",
          "invoice_pay": "invoice_decide",   # the same Subscriber user decides and pays; no new role row for existing instances
          "decline": "accept", "reschedule": "accept", "reassign": "subscriber_note", "cancel": "subscriber_note",   # a provider who can accept can also decline and reschedule
          "create": "create_wo"}


class Skip(Exception):
    """Raised by Runtime.user_for when a step has nobody to run it (no second tech). The step ends as done without a call."""


class Runtime:
    """What handlers need: the store, one ScApp per connection id, and an rng for note text and picks."""

    def __init__(self, store, apps, rng):
        self.store, self.apps, self.rng = store, apps, rng

    def user_for(self, location, step_kind, wo=None, step=None):
        """Pick a user who can do this action (users.can_do). Provider-side actions are limited to users of the WO's provider
        (ctx provider_id; WOs without one fall back to every capable user). A check-out reuses the tech who checked in for that
        visit; a second tech on a visit never repeats one already used. Returns (app, (username, password))."""
        action = ACTION[step_kind]
        rows = self.store.db.execute(
            "SELECT u.*, c.side, c.provider_id AS pid FROM users u JOIN connections c ON c.id=u.conn_id "
            "WHERE EXISTS (SELECT 1 FROM json_each(u.can_do) WHERE value=?) ORDER BY u.id", (action,)).fetchall()
        ctx = json.loads(wo["ctx"]) if wo else {}
        pid = ctx.get("provider_id")
        if pid:
            rows = [u for u in rows if u["side"] == "subscriber" or u["pid"] == pid]
        if not rows:
            who = f" for provider {pid}" if pid else ""
            raise ScError(409, f"no user{who} is set to {action} at {location}. Tick it under Can do on Connections.", "")
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
        u = u or self.rng.choice(rows)
        return self.apps[u["conn_id"]], (u["username"], self.store.dec(u["password"]))

    def location(self, store_id):
        return self.store.db.execute("SELECT * FROM locations WHERE store_id=?", (store_id,)).fetchone()

    def save_ctx(self, wo, **kw):
        ctx = {**json.loads(wo["ctx"]), **kw}
        self.store.db.execute("UPDATE work_orders SET ctx=? WHERE id=?", (json.dumps(ctx), wo["id"]))
        self.store.db.commit()
        return ctx


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_steps(store, wo_id, after_seq, steps):
    """Add steps right after `after_seq` of a WO, shifting later steps down. steps: [(kind, due_at, payload)]."""
    store.db.execute("UPDATE steps SET seq=seq+? WHERE wo_id=? AND seq>?", (len(steps), wo_id, after_seq))
    for i, (kind, due, payload) in enumerate(steps, 1):
        store.db.execute("INSERT INTO steps(wo_id, seq, kind, due_at, payload) VALUES(?,?,?,?,?)",
                         (wo_id, after_seq + i, kind, due, json.dumps(payload)))
    store.db.commit()


def make_handlers(rt):
    def call(wo, step, method, path, **kw):
        app, user = rt.user_for(wo["location"], step["kind"], wo, step)
        return app.call(user, method, path, action=step["kind"], wo=wo["sc_id"], write=method != "GET", **kw)

    def ctx_of(wo):
        return json.loads(wo["ctx"])

    def note(role):
        def run(engine, wo, step):
            situation = json.loads(step["payload"])["situation"]
            text = content.note(role, situation, ctx_of(wo), rt.rng)
            call(wo, step, "POST", f"/workorders/{wo['sc_id']}/notes",
                 body={"Note": text, "NotifyFollowers": False, "DoNotSendEmail": True})
        return run

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

    def cancel(engine, wo, step):
        cancel_wo(rt, wo, content.note("subscriber", json.loads(step["payload"])["situation"], ctx_of(wo), rt.rng))

    def checkio(path, body, wo, step):
        try:
            call(wo, step, "POST", path, body=body)
        except Skip:
            return
        except ScError as e:
            if e.status == 403 and "804" in str(e):
                raise ScError(403, "No check-in/out permission for this Subscriber and Provider pair. ServiceChannel must enable XML "
                                   "or GPS check-in/out for the pair (see README, Prerequisites).", path) from e
            raise

    def check_in(engine, wo, step):
        loc = rt.location(wo["location"])
        checkio(f"/workorders/{wo['sc_id']}/universalCheckIn",
                {"Latitude": loc["lat"], "Longitude": loc["lon"], "TechsCount": 1, "CheckInTime": _iso(step["due_at"])}, wo, step)

    def check_out(engine, wo, step):
        p = json.loads(step["payload"])
        loc = rt.location(wo["location"])
        text = content.note("provider", p["situation"], ctx_of(wo), rt.rng)
        # the first tech out of a crew visit must not complete the WO, but only if the second tech really checked in
        partial = bool(p.get("partial")) and f"{p['visit']}.1" in ctx_of(wo).get("techs", {})
        checkio(f"/workorders/{wo['sc_id']}/universalCheckOut",
                {"Latitude": loc["lat"], "Longitude": loc["lon"], "CheckOutTime": _iso(step["due_at"]),
                 "PrimaryStatus": "Completed" if p["final"] and not partial else "PartsOnOrder",   # Completed closes the WO and blocks the second tech's check-out (921)
                  "ActionStatus": "Complete",
                 "Resolution": text, "TechsCount": 1}, wo, step)

    def review(engine, wo, step):
        """Subscriber verifies the work: COMPLETED/CONFIRMED with the review text as the status note (verified on SB2)."""
        text = content.note("subscriber", "review", ctx_of(wo), rt.rng)
        call(wo, step, "PUT", f"/workorders/{wo['sc_id']}/status",
             body={"Status": {"Primary": "COMPLETED", "Extended": "CONFIRMED"}, "Note": text})

    def invoice_submit(engine, wo, step):
        c = ctx_of(wo)
        total = round(float(c.get("nte") or 0) * rt.rng.uniform(0.6, 1.0), 2)
        labor = round(total * 0.7, 2)
        n = (c.get("invoice_count") or (1 if c.get("invoice_id") else 0)) + 1   # a resubmission after a reject must not reuse the first invoice's number
        body = {"InvoiceNumber": f"INV-{wo['sc_id']}-{n}", "WoIdentifier": str(wo["sc_id"]),
                "InvoiceDate": _iso(step["due_at"]), "InvoiceTotal": total,
                "InvoiceAmountsDetails": {"LaborAmount": labor, "MaterialAmount": round(total - labor, 2)}}
        r = call(wo, step, "POST", "/invoices", body=body)
        rt.save_ctx(wo, invoice_id=(r or {}).get("Id"), amount=f"${total:,.2f}", invoice_count=n)

    def invoice_decide(engine, wo, step):
        p = json.loads(step["payload"])
        c = ctx_of(wo)
        inv = call(wo, step, "GET", f"/invoices/{c['invoice_id']}")
        if (inv or {}).get("Status") in ("APPROVED", "PAID", "REJECTED"):
            return   # the user already decided; never overturn it
        text = content.note("subscriber", "invoice_ok" if p["approve"] else "invoice_no", c, rt.rng)
        if p["approve"]:
            call(wo, step, "PUT", f"/invoices/{c['invoice_id']}/approve",
                 params={"approvalCode": c.get("approval_code", ""), "comments": text, "category": c.get("category", "REPAIR")})
        else:
            call(wo, step, "PUT", f"/invoices/{c['invoice_id']}/reject", params={"comments": text, "isNotifyProvider": "true"})

    def invoice_pay(engine, wo, step):
        """Subscriber records a payment for the approved invoice (verified on SB2: 204, invoice Status becomes PAID)."""
        c = ctx_of(wo)
        inv = call(wo, step, "GET", f"/invoices/{c['invoice_id']}") or {}
        if inv.get("Status") != "APPROVED":
            return   # already paid, or the user rejected it: nothing to pay
        body = {"PaymentDate": _iso(max(step["due_at"], engine.clock())), "PaymentNumber": f"PAY-{wo['sc_id']}",
                "PaymentAmount": inv.get("InvoiceTotal")}
        try:
            call(wo, step, "POST", f"/invoices/{c['invoice_id']}/Payment", body=body)
        except ScError as e:
            if e.status != 400 or "Pay not allowed" not in str(e):
                raise
            # ponytail: this Subscriber cannot record payments; skip quietly. Add a visible setting if it shows up on Prod.

    LABOR = ["Regular Hours", "Overtime Hours", "Double Time / Holiday Hours", "Helper Regular Hours",
             "Helper Overtime Hours", "Helper Double Time / Holiday Hours", "Subcontractor Labor"]   # CreateProposal requires all seven labor lines (error 503 otherwise)

    def proposal_create(engine, wo, step):
        """Provider creates a proposal above the NTE. The create call has no WO field; the Subscriber links it before deciding."""
        c = ctx_of(wo)
        w = call(wo, step, "GET", f"/workorders/{wo['sc_id']}")
        loc = rt.location(wo["location"])
        total = round(float(c.get("nte") or 500) * rt.rng.uniform(1.3, 2.5), 2)
        labor, travel = round(total * 0.4, 2), 45.0
        hours = max(1, round(labor / 95))
        part = round(total - hours * 95 - travel, 2)
        lines = [{"description": n, "tech": 1 if i == 0 else 0, "hours": float(hours) if i == 0 else 0.0,
                  "rate": 95.0 if i == 0 else 0.0} for i, n in enumerate(LABOR)]
        body = {"version": "1.0.0", "subscriberId": loc["subscriber_id"], "providerId": w["Provider"]["Id"], "locationId": loc["db_id"],
                "tradeId": w["TradeId"], "currency": "USD", "proposalNumber": f"PR-{wo['sc_id']}-{step['seq']}-{step['attempts'] + 1}",
                "description": f"{c.get('issue', 'Repair')} - parts and labor", "notificationEmails": "", "costsIncurredToDate": [],
                "materials": [{"description": "Replacement parts", "unit": "each", "qty": 1, "price": part}], "materialsAnswer": "New",
                "installationLabor": lines, "installationLaborFlatFeeLabor": 0,
                "nonInstallationExpenses": {"travel": {"ofTrips": 1, "charge": travel}, "fees": 0, "nonInstallationLabor": 0},
                "nonInstallationExpensesOther": [], "freight": 0, "freightOther": [],
                "tax": {"materialSalesTax": 0, "installationLaborSalesTax": 0, "nonInstallationExpensesSalesTax": 0, "freightTax": 0}}
        pid = call(wo, step, "POST", "/proposals/CreateProposal", body=body)
        c = rt.save_ctx(wo, proposal_id=pid, amount=f"${hours * 95 + part + travel:,.2f}")
        text = content.note("provider", "proposal", c, rt.rng)
        call(wo, step, "POST", f"/workorders/{wo['sc_id']}/notes", body={"Note": text, "NotifyFollowers": False, "DoNotSendEmail": True})

    def proposal_decide(engine, wo, step):
        """Subscriber links the proposal to the WO (subscriber-only call), then approves or rejects it.
        The live status comes first: the user may already have decided, and the API lets an approve overturn a rejection."""
        p = json.loads(step["payload"])
        c = ctx_of(wo)
        pid = c["proposal_id"]
        r = call(wo, step, "GET", "/odata/proposals", params={"$filter": f"Id eq {pid}", "$top": 1})
        status = r["value"][0]["Status"]["Primary"] if r and r.get("value") else None
        if status == "Approved" or (status == "Rejected" and not p["approve"]):
            return   # the user already did what the plan wanted (or something it can live with): carry on
        if status == "Rejected":   # the user rejected a proposal the plan meant to approve: take the plan's rejection branch
            n = c.get("revisions", 0) + 1
            if n > 3:
                raise ScError(409, f"proposal {pid} was rejected {n} times by the user; the plan needs attention", "/proposals")
            rt.save_ctx(wo, revisions=n)
            gap = rt.rng.randint(3600, 4 * 3600)
            insert_steps(rt.store, wo["id"], step["seq"], [
                ("proposal_create", step["due_at"] + gap, {"situation": "proposal"}),
                ("proposal_decide", step["due_at"] + gap + rt.rng.randint(1800, 4 * 3600), {"approve": True})])
            return
        call(wo, step, "PUT", f"/proposals/{pid}/assignWO", body=int(wo["sc_id"]))
        text = content.note("subscriber", "proposal_ok" if p["approve"] else "proposal_no", c, rt.rng)
        if p["approve"]:
            call(wo, step, "PUT", f"/proposals/{pid}/approve",
                 body={"Comment": text, "ActionSource": "Standard", "ReasonString": "Best fit for the job and scope",
                       "PinNote": True, "AttachmentstoWO": True})
        else:
            call(wo, step, "PUT", f"/proposals/{pid}/reject",
                 body={"Comment": text, "ActionSource": "Standard", "RejectReasonCodeId": rt.rng.choice([2, 3, 4, 5])})

    def guarded(kind, fn):
        """If a write is refused, read the live WO. The user may have moved it on: a cancelled WO ends the plan, a completed
        WO makes the field steps moot, and a check-in/out the user already did is done. Anything else is a real failure."""
        def run(engine, wo, step):
            try:
                if preflight(rt, call, wo, step, kind):
                    return
                return fn(engine, wo, step)
            except ScError as e:
                if e.status not in (400, 403, 409):
                    raise
                try:
                    w = call(wo, step, "GET", f"/workorders/{wo['sc_id']}")
                except ScError:
                    raise e from None
                st = w.get("Status", {})
                if st.get("Extended") == "CANCELED":
                    end_plan(rt, wo)
                elif st.get("Primary") == "COMPLETED" and kind in FIELD:
                    return
                elif kind == "check_in" and st.get("Extended") == "ON SITE":
                    return
                else:
                    raise
        return run

    handlers = {"accept": accept, "prov_note": note("provider"), "sub_note": note("subscriber"), "check_in": check_in,
                "check_out": check_out, "review": review, "invoice_submit": invoice_submit,
                "invoice_decide": invoice_decide, "invoice_pay": invoice_pay, "decline": decline, "reassign": reassign, "reschedule": reschedule, "cancel": cancel, "proposal_create": proposal_create, "proposal_decide": proposal_decide}
    return {k: guarded(k, f) for k, f in handlers.items()}


ALREADY_DONE_WHEN_COMPLETED = {"accept", "decline", "reassign", "reschedule", "check_in", "check_out", "proposal_create", "proposal_decide"}


def preflight(rt, call, wo, step, kind):
    """B-39: read the live WO before a write. A cancelled WO ends the plan; a WO a user already completed makes the field steps
    moot. Returns True when the step must not run. A failed read changes nothing: the step runs and its own guard handles it."""
    try:
        st = (call(wo, step, "GET", f"/workorders/{wo['sc_id']}") or {}).get("Status", {})
    except ScError:
        return False
    if st.get("Extended") == "CANCELED":
        end_plan(rt, wo)
        return True
    return st.get("Primary") == "COMPLETED" and kind in ALREADY_DONE_WHEN_COMPLETED


FIELD = {"accept", "decline", "reassign", "reschedule", "prov_note", "sub_note", "check_in", "check_out", "proposal_create", "proposal_decide", "review"}


def end_plan(rt, wo):
    """Stop a WO's plan because the WO itself was cancelled outside the agent."""
    rt.store.db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?", (wo["id"],))
    rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],))
    rt.store.db.commit()


WATCH_EVERY, WATCH_MAX = 3600, 1   # on by default (setting status_check, Settings page); the preflight read alone only catches changes before a write


def watch(store, rt, clock=time.time):
    """B-39: read the live status of the WOs that still have pending steps, least recently read first. A WO the user cancelled
    ends its plan here instead of failing a step later. Returns [(sc_id, outcome)]."""
    if not store.get("status_check", True) or store.get("paused_at") is not None or clock() - store.get("watch_at", 0) < WATCH_EVERY:
        return []
    store.put("watch_at", clock())
    out = []
    for wo in store.db.execute(
            "SELECT w.* FROM work_orders w WHERE w.state='active' AND EXISTS (SELECT 1 FROM steps s WHERE s.wo_id=w.id AND s.state='pending') "
            "ORDER BY COALESCE(json_extract(w.ctx,'$.watched'),0) LIMIT ?", (WATCH_MAX,)).fetchall():
        try:
            app, user = rt.user_for(wo["location"], "sub_note", wo)
            st = (app.call(user, "GET", f"/workorders/{wo['sc_id']}", action="watch", wo=wo["sc_id"]) or {}).get("Status", {})
        except ScError:
            continue   # a failed read changes nothing; the next pass tries again
        rt.save_ctx(wo, watched=clock())
        if st.get("Extended") == "CANCELED":
            end_plan(rt, wo)
            out.append((wo["sc_id"], "cancelled by a user: plan ended"))
    return out


def cancel_wo(rt, wo, note="Cancelled by SC Activity Agent cleanup"):
    """Cancel a WO as the Subscriber and stop its plan. SC has no API path to VOID, so use COMPLETED/CANCELED."""
    app, user = rt.user_for(wo["location"], "sub_note")
    app.call(user, "PUT", f"/workorders/{wo['sc_id']}/status", action="cancel", wo=wo["sc_id"], write=True,
             body={"Status": {"Primary": "COMPLETED", "Extended": "CANCELED"}, "Note": note})
    rt.store.db.execute("UPDATE work_orders SET state='cancelled' WHERE id=?", (wo["id"],))
    rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],))
    rt.store.db.commit()
