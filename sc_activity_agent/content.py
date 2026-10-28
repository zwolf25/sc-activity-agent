"""Situation-aware note text. Templates only, no LLM: slots come from the WO context, phrasing varies by seeded rng."""
import re

GREET = ["", "", "Hi, ", "Hello, ", "Team, "]
CLOSE = ["", "", " Thanks.", " Thank you.", " Let us know if anything changes."]

T = {  # (role, situation) -> templates; {slots} filled from ctx
    ("provider", "ack"): [
        "Received the {trade} request for {issue}. We will get a tech scheduled.",
        "Work order accepted. {issue} at {location}, scheduling now.",
        "We have this one. Planning a visit for {sched_day}."],
    ("provider", "reschedule"): [
        "We need to move the visit to {sched_day}. The tech's earlier schedule ran over, sorry for the change.",
        "Rescheduling the {issue} repair. New date is in the work order and the tech will arrive around the same time of day.",
        "Pushing the visit out a few days so we can bring the right parts for the {equipment}."],
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
        "Proposal submitted for {amount}. Please review so we can proceed."],
    ("provider", "invoice"): [
        "Invoice submitted for {amount}.",
        "Invoice {amount} submitted for this work order."],
    ("provider", "invoice_fix"): [
        "Corrected the invoice as requested and resubmitted for {amount}.",
        "Updated the invoice per your comments. Resubmitted at {amount}."],
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
        "Not approving at this price. Please send a lower option."],
    ("subscriber", "review"): [
        "Reviewed. Work looks good.",
        "Confirmed with the store, the {issue} is resolved."],
    ("subscriber", "invoice_ok"): [
        "Invoice approved.",
        "Approved. Thank you for the quick turnaround."],
    ("subscriber", "invoice_no"): [
        "Invoice rejected. The labor hours do not match the time on site. Please correct and resubmit.",
        "Rejecting for now. Please attach the missing detail and resubmit."],
}


def note(role, situation, ctx, rng):
    """Return note text. Raises KeyError for an unknown situation, ValueError if a slot is missing from ctx."""
    text = rng.choice(T[(role, situation)])
    greet = rng.choice(GREET)
    if greet and not text.startswith(("We ", "I ")):
        text = text[0].lower() + text[1:]
    text = greet + text + rng.choice(CLOSE)
    missing = [s for s in re.findall(r"{(\w+)}", text) if s not in ctx]
    if missing:
        raise ValueError(f"note {role}/{situation} missing slots {missing}")
    return text.format(**ctx).strip()
