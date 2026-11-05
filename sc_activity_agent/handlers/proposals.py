"""Proposals: the Provider creates one above the NTE, the Subscriber links it and approves or rejects."""
import json

from .. import content
from ..client import ScError
from .common import insert_steps


def build(rt, call, ctx_of):
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

    return {"proposal_create": proposal_create, "proposal_decide": proposal_decide}
