"""Invoices: the Provider submits (line items, or a No Charge close without an NTE), the Subscriber decides and pays."""
import datetime as dt
import json

from .. import content
from ..client import ScError
from .common import _iso, insert_steps


def build(rt, call, ctx_of):
    def onsite_hours(wo):
        """Time on site from the WO's check-in and check-out steps (done time when it ran, else the planned time), per visit, in hours."""
        rows = rt.store.db.execute("SELECT kind, payload, due_at, done_at FROM steps WHERE wo_id=? AND kind IN ('check_in','check_out') "
                                   "AND state!='skipped' ORDER BY seq", (wo["id"],)).fetchall()
        visits = {}
        for r in rows:
            v = visits.setdefault(json.loads(r["payload"]).get("visit", 1), {})
            t = r["done_at"] or r["due_at"]
            k = r["kind"]
            v[k] = min(t, v[k]) if k in v else t
        return sum(max(0, v["check_out"] - v["check_in"]) for v in visits.values() if len(v) == 2) / 3600

    def no_charge(wo, step):
        """A WO with no NTE cannot be invoiced: the Subscriber closes it as COMPLETED/NO CHARGE (verified on SB2) and the plan ends."""
        app, user = rt.user_for(wo["location"], "sub_note", wo, step)
        app.call(user, "PUT", f"/workorders/{wo['sc_id']}/status", action="no_charge", wo=wo["sc_id"], write=True,
                 body={"Status": {"Primary": "COMPLETED", "Extended": "NO CHARGE"}, "Note": "No NTE on this work order, closing with no charge."})
        rt.store.db.execute("UPDATE work_orders SET state='closed' WHERE id=?", (wo["id"],))
        rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND state IN ('pending','failed')", (wo["id"],))
        rt.store.db.commit()

    def invoice_submit(engine, wo, step):
        """Line-item invoice (B-12): labor at the agreed rate for the hours on site, plus materials up to a share of the NTE. A flawed
        first invoice (payload flaw) bills the wrong rate or extra hours. The API refuses a total above the NTE (1104)."""
        c = ctx_of(wo)
        flaw = json.loads(step["payload"]).get("flaw")
        live = call(wo, step, "GET", f"/workorders/{wo['sc_id']}") or {}
        if live.get("Nte") is not None and float(live["Nte"]) <= 0:
            return no_charge(wo, step)   # the API refuses any invoice above an NTE of 0 (1104), so the WO closes as No Charge
        nte = float(c.get("nte") or 0)
        rates = rt.store.get("agreed_rates", {})
        key = f"{c.get('provider_id')}:2"
        rate = float(c.get("agreed_rate") or rates.get(key) or rt.rng.choice([65, 75, 85, 95]))
        hours = max(0.5, round(onsite_hours(wo) * 2) / 2)
        if flaw == "hours":
            hours = round((hours * rt.rng.uniform(1.6, 2.6) + 1) * 2) / 2
        if flaw == "rate":
            rate = round(rate * rt.rng.uniform(1.3, 1.8), 2)
        if nte and hours * rate > nte * 0.9:
            rate = round(nte * 0.9 / hours, 2)   # keep the total under the NTE; the API refuses more
        labor = round(hours * rate, 2)
        target = nte * rt.rng.uniform(0.6, 1.0) if nte else labor
        mats = []
        left = round(target - labor, 2)
        for i in range(rt.rng.randint(1, 2) if left >= 20 else 0):
            amt = round(left / 2, 2) if i == 0 and left >= 40 else round(left, 2)
            mats.append({"Description": rt.rng.choice(["Replacement part", "Hardware kit", "Fasteners and sealant", "Control module"]),
                         "PartNum": f"P-{rt.rng.randint(1000, 9999)}", "UnitType": "7", "UnitPrice": amt, "Quantity": 1, "Amount": amt})
            left = round(left - amt, 2)
        material = round(sum(m["Amount"] for m in mats), 2)
        total = round(labor + material, 2)
        n = (c.get("invoice_count") or (1 if c.get("invoice_id") else 0)) + 1   # a resubmission after a reject must not reuse the first invoice's number
        body = {"InvoiceNumber": f"INV-{wo['sc_id']}-{n}", "WoIdentifier": str(wo["sc_id"]),
                "InvoiceDate": _iso(step["due_at"]), "InvoiceTotal": total,
                "InvoiceAmountsDetails": {"LaborAmount": labor, "MaterialAmount": material},
                "Labors": [{"SkillLevel": "2", "LaborType": "1", "NumOfTech": "1", "HourlyRate": rate, "Hours": hours, "Amount": labor}],
                "Materials": mats}
        try:
            r = call(wo, step, "POST", "/invoices", body=body)
        except ScError as e:
            if json.loads(step["payload"]).get("situation") == "invoice_fix" and e.status == 400 and "1105" in str(e):
                return   # someone approved the invoice before this resubmit: nothing to resubmit
            raise
        agreed = None
        try:   # learn the contract rate the API compares against, so the next invoice (or the resubmission) bills it
            inv = call(wo, step, "GET", f"/invoices/{(r or {}).get('Id')}") or {}
            agreed = next((l["AgreedRate"] for l in inv.get("Labors", []) if l.get("AgreedRate")), None)
        except ScError:
            pass
        if agreed:
            rt.store.put("agreed_rates", {**rates, key: agreed})
        rt.save_ctx(wo, invoice_id=(r or {}).get("Id"), amount=f"${total:,.2f}", invoice_count=n, agreed_rate=agreed or c.get("agreed_rate"))

    def invoice_flag(wo, inv):
        """What the Subscriber sees on an invoice: the API's rate flag, or more labor hours than the time on site (the API has no hours check)."""
        if inv.get("WithMismatchedRates"):
            return "rate"
        billed = sum(l.get("Hours") or 0 for l in inv.get("Labors", []))
        return "hours" if billed > onsite_hours(wo) * 1.25 + 0.5 else None

    def invoice_decide(engine, wo, step):
        p = json.loads(step["payload"])
        c = ctx_of(wo)
        inv = call(wo, step, "GET", f"/invoices/{c['invoice_id']}")
        if (inv or {}).get("Status") in ("APPROVED", "PAID", "REJECTED"):
            if inv["Status"] != "REJECTED":   # approved by someone else: the planned resubmit would hit 1105 "Invoice exists"
                rt.store.db.execute("UPDATE steps SET state='skipped' WHERE wo_id=? AND seq>? AND state='pending' AND kind IN ('invoice_submit','invoice_decide')",
                                    (wo["id"], step["seq"]))
                rt.store.db.commit()
            return   # the user already decided; never overturn it
        flag = invoice_flag(wo, inv or {})
        if p["approve"] and flag and (c.get("invoice_count") or 1) < 3:   # the plan meant to approve, but the invoice carries a flag: reject, and the provider resubmits
            p = {**p, "approve": False, "flaw": flag}
            gap = rt.rng.randint(86400, 2 * 86400)
            insert_steps(rt.store, wo["id"], step["seq"], [
                ("invoice_submit", step["due_at"] + gap, {"situation": "invoice_fix"}),
                ("invoice_decide", step["due_at"] + gap + rt.rng.randint(3600, 86400), {"approve": True})])
        situation = "invoice_ok" if p["approve"] else f"invoice_no_{p['flaw']}" if p.get("flaw") else "invoice_no"
        text = content.note("subscriber", situation, c, rt.rng)
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
        paid_at = max(step["due_at"], engine.clock())
        if inv.get("InvoiceDate"):
            # An invoice posted late in the US evening is dated the next UTC day, and ServiceChannel refuses a payment dated before it (error 1178).
            paid_at = max(paid_at, dt.datetime.fromisoformat(inv["InvoiceDate"]).timestamp())
        body = {"PaymentDate": _iso(paid_at), "PaymentNumber": f"PAY-{wo['sc_id']}",
                "PaymentAmount": inv.get("InvoiceTotal")}
        try:
            call(wo, step, "POST", f"/invoices/{c['invoice_id']}/Payment", body=body)
        except ScError as e:
            if e.status != 400 or "Pay not allowed" not in str(e):
                raise
            # ponytail: this Subscriber cannot record payments; skip quietly. Add a visible setting if it shows up on Prod.

    return {"invoice_submit": invoice_submit, "invoice_decide": invoice_decide, "invoice_pay": invoice_pay}
