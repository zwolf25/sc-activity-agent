"""Situation-aware note text. Templates only, no LLM: slots come from the WO context, phrasing varies by seeded rng."""
import re

GREET = ["", "", "Hi, ", "Hello, ", "Team, "]
CLOSE = ["", "", " Thanks.", " Thank you.", " Let us know if anything changes."]

# What a store says is still wrong, by trade. Reads after "the {equipment}", so each starts with a verb.
COMPLAINTS = {
    "HVAC": ["is still not cooling", "is blowing warm air again", "is making a loud noise again", "shut off again after the visit", "is not holding the set temperature"],
    "PLUMBING": ["is leaking again", "still has low pressure", "is still backing up", "still has no hot water", "is dripping again"],
    "ELECTRICAL": ["tripped the breaker again", "is still flickering", "still has no power", "is buzzing again", "is still not working"],
    "DOORS": ["still sticks and will not latch", "is still not closing properly", "still will not lock", "is still catching on the frame", "is still not opening"],
    "GENERAL MAINTENANCE": ["is still loose and unsafe", "has the same problem as before", "is still not repaired", "is still damaged"],
    "JANITORIAL": ["was missed again", "still was not cleaned properly", "still needs a proper clean"],
    "KITCHEN EQUIPMENT": ["is still not holding temperature", "is still not working", "is still leaking", "is still making noise"],
    "FREIGHT EQUIPMENT": ["is still not operating", "is still jammed", "still stops mid-cycle"],
    "*": ["is still not working", "has the same problem as before", "is not fixed"],
}
GENERIC_ISSUES = {"other issues", "other", "reported issue", ""}   # issue labels that name no problem; a template quoting {issue} reads badly


def complaint(ctx, rng):
    """One 'still wrong' phrase for this WO's trade."""
    return rng.choice(COMPLAINTS.get(str(ctx.get("trade", "")).upper(), COMPLAINTS["*"]))


T = {  # (role, situation) -> templates; {slots} filled from ctx
    ("provider", "ack"): [
        "Received the {trade} request for {issue}. We will get a tech scheduled.",
        "Work order accepted. {issue} at {location}, scheduling now.",
        "We have this one. Planning a visit for {sched_day}."],
    ("provider", "reschedule"): [
        "We need to move the visit to {sched_day}. The tech's earlier schedule ran over, sorry for the change.",
        "Rescheduling the {issue} repair. New date is in the work order and the tech will arrive around the same time of day.",
        "Pushing the visit out a few days so we can bring the right parts for the {equipment}."],
    ("subscriber", "noshow"): [
        "Your tech did not arrive for the {sched_day} visit and we have not heard from anyone. Escalating this work order.",
        "No check-in for the {issue} repair on {sched_day} and no update. We need to find another provider for this."],
    ("subscriber", "noshow_cancel"): [
        "Provider never showed and nobody else can take it right now. Cancelling this request; we will log a new one.",
        "No other provider is available after the missed visit. Cancelling this work order."],
    ("subscriber", "declined"): [
        "No provider coverage after the decline, cancelling this request. We will log a new one.",
        "Provider declined and nobody else can take it right now. Cancelling this work order."],
    ("provider", "eta"): [
        "Tech is scheduled for {sched_day}, expected arrival {eta}.",
        "Confirming {sched_day} between {eta} and {eta_end} for the {issue} repair.",
        "Dispatching a {trade} tech {sched_day}, ETA {eta}."],
    ("provider", "access"): [
        "Please confirm the tech can access the {area} area on arrival.",
        "Need the best contact on site to get into the {area}. Who should the tech ask for?"],
    ("provider", "onsite"): [
        "Tech is on site and starting on the {issue}.",
        "Arrived at {location}. Assessing the {issue} now.",
        "Checked in. Looking at the {equipment} first."],
    ("provider", "parts"): [
        "Diagnosed the problem. A part is needed for the {equipment}. Ordering now, will return when it arrives.",
        "Found the cause on the {equipment}. Waiting on a replacement part before we can finish."],
    ("provider", "return"): [
        "Back on site to finish the {issue} repair.",
        "Returning today to complete the work on the {equipment}."],
    ("provider", "complete"): [
        "Work complete. {issue} resolved and the area is clean.",
        "Repair finished on the {equipment}. Tested and working.",
        "All done. {issue} is fixed and we left the {area} tidy."],
    ("provider", "proposal"): [
        "Sent a proposal of {amount} for the repair. The work is beyond the NTE of {nte}.",
        "Proposal submitted for {amount}. Please review so we can proceed.",
        "Sent a proposal of {amount} for the {equipment} repair in the {area} area. The work is beyond the NTE of {nte}.",
        "Proposal for {amount} submitted for the {issue} at {location}. It is over the {nte} NTE, please review."],
    ("provider", "invoice"): [
        "Invoice submitted for {amount}.",
        "Invoice {amount} submitted for this work order.",
        "Invoice {amount} submitted for the {equipment} work at {location}.",
        "Work on the {equipment} is complete. Invoice for {amount} submitted."],
    ("provider", "invoice_fix"): [
        "Corrected the invoice as requested and resubmitted for {amount}.",
        "Updated the invoice per your comments. Resubmitted at {amount}.",
        "Corrected the invoice for the {equipment} work and resubmitted at {amount}.",
        "Updated the {location} invoice per your comments. Resubmitted at {amount}."],
    ("subscriber", "created"): [
        "Please prioritize. {issue} is affecting the {area}.",
        "Store reports {issue}. Please schedule soon."],
    ("subscriber", "access"): [
        "Front desk will let the tech in. Check in with the manager on arrival.",
        "Manager on site will meet your tech at the {area}."],
    ("subscriber", "followup"): [
        "Checking in on the {issue}. Any update on timing?",
        "Can you confirm the repair is still on track for {sched_day}?"],
    ("subscriber", "proposal_ok"): [
        "Proposal approved. Please proceed.",
        "Approved. Go ahead with the {equipment} repair."],
    ("subscriber", "proposal_no"): [
        "Proposal rejected. The amount is higher than expected. Please revise.",
        "Not approving at this price. Please send a lower option.",
        "Not approving the {equipment} repair at this price. Please send a lower option.",
        "The proposal for the {area} area is higher than expected. Please revise."],
    ("subscriber", "review"): [
        "Reviewed. Work looks good.",
        "Confirmed with the store, the {issue} is resolved."],
    ("subscriber", "unsatisfactory"): [
        "After {last_visit}, the {equipment} {complaint}. Please send the technician back to finish the repair.",
        "{location} reports the {equipment} {complaint}, same as before. Please return and complete the work.",
        "The {equipment} in the {area} area {complaint}, so the {issue} repair was not completed. Please schedule a return visit.",
        "Store contact says the {equipment} {complaint} in the {area} area. We need the provider back on site.",
        "The {trade_text} repair did not hold. The {equipment} {complaint}. Please come back and fix it properly.",
        "Checked with {location} after {last_visit}: the {equipment} {complaint}. Please return to finish."],
    ("subscriber", "low_stars"): [
        "Not satisfied with the {trade_text} work at {location}. The {equipment} {complaint}. Please come back and finish the job.",
        "Work was incomplete. The {equipment} in the {area} area {complaint}, and the {issue} is still open.",
        "Poor result after {last_visit}. The {equipment} {complaint}. This needs another visit.",
        "The store is not happy with this repair. The {equipment} {complaint} and the {area} area is still affected.",
        "Not up to standard. The {equipment} {complaint}, so the {issue} was not resolved."],
    ("provider", "rework"): [
        "Sorry about that. Understood that the {equipment} {complaint}. Scheduling a return visit to {location}.",
        "Thanks for the feedback. We will send a {trade_text} tech back to look at the {equipment} in the {area} area.",
        "Acknowledged. Planning a return visit to find out why the {equipment} {complaint}.",
        "We hear you. Our tech will return to {location} and recheck the {equipment} before leaving."],
    ("subscriber", "review_rework"): [
        "The return visit fixed it. The {equipment} in the {area} area is working as expected.",
        "Store confirms the {equipment} is fixed after the second visit. Thank you for coming back.",
        "Verified at {location}. The {trade_text} problem is resolved this time."],
    ("subscriber", "invoice_ok"): [
        "Invoice approved.",
        "Approved. Thank you for the quick turnaround.",
        "Invoice approved for the {equipment} work at {location}.",
        "Approved. The {equipment} repair is done, thank you."],
    ("subscriber", "invoice_no_rate"): [
        "Invoice rejected. The labor rate does not match the agreed rate. Please correct and resubmit.",
        "Rejecting: the hourly rate billed is above our agreed rate. Resubmit at the contract rate.",
        "Invoice rejected. The labor rate on the {equipment} work does not match the agreed rate. Please correct and resubmit."],
    ("subscriber", "invoice_no_hours"): [
        "Invoice rejected. The labor hours are more than the time on site. Please correct and resubmit.",
        "Rejecting: hours billed do not match the check-in and check-out times. Resubmit with the hours on site.",
        "Invoice rejected. Labor hours on the {equipment} work at {location} are more than the time on site. Please correct and resubmit."],
    ("subscriber", "invoice_no"): [
        "Invoice rejected. The labor hours do not match the time on site. Please correct and resubmit.",
        "Rejecting for now. Please attach the missing detail and resubmit.",
        "Invoice rejected for now. Please add the missing detail for the {equipment} work and resubmit."],
}


def note(role, situation, ctx, rng):
    """Return note text. Raises KeyError for an unknown situation, ValueError if a slot is missing from ctx."""
    pool = T[(role, situation)]
    if str(ctx.get("issue", "")).strip().lower() in GENERIC_ISSUES:
        pool = [t for t in pool if "{issue}" not in t] or pool
    text = rng.choice(pool)
    if "{complaint}" in text and "complaint" not in ctx:
        ctx = {**ctx, "complaint": complaint(ctx, rng)}
    if "{trade_text}" in text:   # "plumbing work", "HVAC work": short names stay as they are
        t = str(ctx.get("trade", ""))
        ctx = {**ctx, "trade_text": t if len(t) <= 4 else t.lower()}
    if "{last_visit}" in text and "last_visit" not in ctx:
        ctx = {**ctx, "last_visit": "the last visit"}
    greet = rng.choice(GREET)
    if greet and not text.startswith(("We ", "I ", "{")):   # a leading slot may be a place name; keep its capitals
        text = text[0].lower() + text[1:]
    text = greet + text + rng.choice(CLOSE)
    missing = [s for s in re.findall(r"{(\w+)}", text) if s not in ctx]
    if missing:
        raise ValueError(f"note {role}/{situation} missing slots {missing}")
    return text.format(**ctx).strip()
