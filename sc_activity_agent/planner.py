"""Builds the full lifecycle plan for one WO up front: ordered, timed steps. Outcomes (approve/reject, visits) are rolled once here."""
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

DEFAULTS = {
    "wo_per_month": 120,
    "proposal_rate": 10, "proposal_approval": 90, "invoice_approval": 95,
    "sub_notes": 2.0, "prov_notes": 3.0,
    "late_checkin": 15, "late_days": 2,
    "time_on_site_hrs": 2.0, "pay_days": 30, "multi_tech": 5, "first_time_fix": 80,
    "hours_start": 8, "hours_end": 17,
    "resume_policy": "catch_up",
}


def _biz_day(d, n):
    """The date n business days after d."""
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _at(day, hour_float, tz):
    h = int(hour_float)
    return datetime.combine(day, dtime(h, int((hour_float - h) * 60)), tzinfo=ZoneInfo(tz)).timestamp()


def _fit(ts, prev, c, tz, rng):
    """Moves ts inside activity hours on a business day, keeping it after prev. A step outside the window moves to the start of the
    next one, and the order rule spreads consecutive moved steps a few minutes apart."""
    z = ZoneInfo(tz)
    d = datetime.fromtimestamp(ts, z)
    h0, h1 = c["hours_start"], c["hours_end"]
    new = ts
    if not (d.weekday() < 5 and _at(d.date(), h0, tz) <= ts <= _at(d.date(), h1, tz)):
        day = d.date() if d.weekday() < 5 and ts < _at(d.date(), h0, tz) else _biz_day(d.date(), 1)
        new = _at(day, h0, tz)
    if new <= prev:
        new = prev + rng.randint(60, 600)
        if new > _at(datetime.fromtimestamp(new, z).date(), h1, tz):
            return _fit(new, prev, c, tz, rng)
    return new


def build_plan(rng, now, cfg, tz="America/New_York"):
    """now: epoch seconds when the WO is created. Returns list of dicts {kind, due_at, payload}, sorted by due_at.
    Times are epoch seconds. Kinds: accept, prov_note, sub_note, proposal_create, proposal_decide, check_in, check_out,
    review, invoice_submit, invoice_decide, invoice_pay."""
    c = {**DEFAULTS, **cfg}
    steps = []

    def add(kind, due, **payload):
        steps.append({"kind": kind, "due_at": due, "payload": payload})

    created = datetime.fromtimestamp(now, ZoneInfo(tz))
    sched_day = _biz_day(created.date(), rng.randint(1, 5))
    add("accept", now + rng.randint(300, 2400), situation="ack")
    add("prov_note", now + rng.randint(2700, 5400), situation="eta")

    # first-time-fix decides how many visits; each visit is a check-in/out pair on its own business day
    visits = 1 if rng.random() * 100 < c["first_time_fix"] else rng.choice([2, 2, 3])
    late = rng.random() * 100 < c["late_checkin"]
    day = _biz_day(sched_day, rng.randint(1, max(1, int(c["late_days"]) * 2 - 1))) if late else sched_day
    span = c["hours_end"] - c["hours_start"]
    has_proposal = rng.random() * 100 < c["proposal_rate"]
    t = _at(day, c["hours_start"] + rng.random() * span * 0.4, tz)

    if has_proposal:
        # check-in is blocked until the proposal is approved, so the proposal precedes the first visit
        p_at = now + rng.randint(3600, 4 * 3600)
        add("proposal_create", p_at, situation="proposal")
        if rng.random() * 100 < c["proposal_approval"]:
            add("proposal_decide", p_at + rng.randint(1800, 4 * 3600), approve=True)
        else:
            add("proposal_decide", p_at + rng.randint(1800, 4 * 3600), approve=False)
            add("proposal_create", p_at + 86400, situation="proposal")  # revised proposal
            add("proposal_decide", p_at + 86400 + rng.randint(1800, 4 * 3600), approve=True)
        t = max(t, steps[-1]["due_at"] + 3600)
        day = datetime.fromtimestamp(t, ZoneInfo(tz)).date()
        if day.weekday() >= 5:
            day = _biz_day(day, 1)
            t = _at(day, c["hours_start"] + rng.random() * span * 0.4, tz)

    for v in range(visits):
        if v:
            day = _biz_day(day, 1)
            t = _at(day, c["hours_start"] + rng.random() * span * 0.4, tz)
        if t > _at(day, c["hours_end"] - 1, tz):   # a late proposal decision can leave no room today: start the next business day
            day = _biz_day(day, 1)
            t = _at(day, c["hours_start"] + rng.random() * span * 0.4, tz)
        hours = max(0.5, rng.gauss(c["time_on_site_hrs"], c["time_on_site_hrs"] * 0.35))
        end_cap = _at(day, c["hours_end"], tz)
        out = min(t + hours * 3600, end_cap)
        add("check_in", t, visit=v + 1, situation="onsite" if v == 0 else "return", **({"late": late} if v == 0 else {}))
        crew = rng.random() * 100 < c["multi_tech"] and out - t > 2400   # a second tech works the same visit, a little behind the first
        if crew:
            in2 = t + rng.randint(300, min(1200, int(out - t) - 1800))
            add("check_in", in2, visit=v + 1, tech=1, situation="onsite")
        if rng.random() < 0.7:
            add("prov_note", t + 600, situation="onsite" if v == 0 else "return")
        last = v == visits - 1
        add("check_out", out, visit=v + 1, final=last, situation="complete" if last else "parts", **({"partial": True} if crew else {}))   # partial: the other tech still on site
        if crew:
            add("check_out", min(out + rng.randint(60, 600), end_cap), visit=v + 1, tech=1, final=last, situation="complete" if last else "parts")
        if not last:
            add("prov_note", out + 60, situation="parts")

    final_out = max(s["due_at"] for s in steps if s["kind"] == "check_out")
    review_at = final_out + rng.randint(3600, 86400)
    add("review", review_at, situation="review")
    inv_at = review_at + rng.randint(7200, 2 * 86400)  # invoices follow the review
    add("invoice_submit", inv_at, situation="invoice")
    if rng.random() * 100 < c["invoice_approval"]:
        dec_at = inv_at + rng.randint(3600, 2 * 86400)
        add("invoice_decide", dec_at, approve=True)
    else:
        add("invoice_decide", inv_at + rng.randint(3600, 86400), approve=False)
        add("invoice_submit", inv_at + 2 * 86400, situation="invoice_fix")
        dec_at = inv_at + 3 * 86400
        add("invoice_decide", dec_at, approve=True)

    # notes sprinkled between creation and the final invoice decision
    lo, hi = now + 600, steps[-1]["due_at"]
    for _ in range(_poisson(rng, c["sub_notes"])):
        add("sub_note", rng.uniform(lo, hi), situation=rng.choice(["created", "access", "followup"]))
    for _ in range(max(0, _poisson(rng, c["prov_notes"]) - 2)):  # ack/eta/onsite notes already count
        add("prov_note", rng.uniform(lo, hi), situation=rng.choice(["access", "eta"]))
    add("invoice_pay", dec_at + max(2, rng.gauss(c["pay_days"], c["pay_days"] * 0.25)) * 86400)   # after the notes block so notes still end at the decision
    steps.sort(key=lambda s: s["due_at"])
    prev = 0
    for st in steps:   # planned times can fall at night or on a weekend: fit them to the activity window, order unchanged
        prev = st["due_at"] = _fit(st["due_at"], prev, c, tz, rng)
    return steps


def _poisson(rng, lam):
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1
