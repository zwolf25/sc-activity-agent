"""Derives a WO's current stage and today's action counts from saved plan steps."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

STAGES = ["Scheduled", "Proposal pending", "On site", "Awaiting return", "Awaiting review", "Invoice due",
          "Invoice pending", "Invoice rejected", "Closed"]


def stage(done):
    """done: list of (kind, payload dict) in plan order. Returns one of STAGES."""
    st = "Scheduled"
    for kind, p in done:
        if kind == "proposal_create":
            st = "Proposal pending"
        elif kind == "proposal_decide":
            st = "Scheduled"
        elif kind == "check_in":
            st = "On site"
        elif kind == "check_out":
            st = "Awaiting review" if p.get("final") else "Awaiting return"
        elif kind == "review":
            st = "Invoice due"
        elif kind == "invoice_submit":
            st = "Invoice pending"
        elif kind == "invoice_decide":
            st = "Closed" if p.get("approve") else "Invoice rejected"
    return st


def by_stage(db):
    counts = dict.fromkeys(STAGES, 0)
    for w in db.execute("SELECT id FROM work_orders WHERE state='active'"):
        rows = db.execute("SELECT kind,payload FROM steps WHERE wo_id=? AND state='done' ORDER BY seq", (w["id"],)).fetchall()
        counts[stage([(r["kind"], json.loads(r["payload"])) for r in rows])] += 1
    return counts


NOTE = {"ack": "acknowledge", "eta": "ETA update", "onsite": "on site", "return": "return visit", "parts": "parts needed",
        "access": "access", "followup": "follow-up", "created": "WO created"}


def detail(kind, p):
    """One-line context for a step, from its saved payload. Empty when there is nothing useful to add."""
    if kind in ("prov_note", "sub_note"):
        return "Note: " + NOTE.get(p.get("situation"), p.get("situation", ""))
    if kind in ("proposal_decide", "invoice_decide"):
        return "Will approve" if p.get("approve") else "Will reject"
    if kind == "check_in":
        late = {True: ", late", False: ", on time"}.get(p.get("late"), "")
        return f"Visit {p.get('visit', 1)}{late}"
    if kind == "check_out":
        return f"Visit {p.get('visit', 1)}, " + ("work complete" if p.get("final") else "parts on order, return visit")
    if kind == "invoice_submit":
        return "Resubmission after reject" if p.get("situation") == "invoice_fix" else ""
    return ""


def week(db, tz="America/New_York", now=None, hide_done=False, hide_skipped=True, page=1, size=10):
    """Steps planned for the local calendar week (Monday to Sunday), oldest first; skipped steps (their WO was cancelled or ended) can be hidden: (rows, total, pages, page)."""
    z = ZoneInfo(tz)
    d = dt.datetime.fromtimestamp(now, z) if now else dt.datetime.now(z)
    mon = (d - dt.timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    lo, hi = mon.timestamp(), (mon + dt.timedelta(days=7)).timestamp()
    where = "s.due_at>=? AND s.due_at<?" + (" AND s.state!='skipped'" if hide_skipped else "") + (" AND s.state!='done'" if hide_done else "")
    total = db.execute(f"SELECT COUNT(*) FROM steps s WHERE {where}", (lo, hi)).fetchone()[0]
    pages = max(1, -(-total // size))
    page = min(max(1, page), pages)
    rows = db.execute(f"SELECT s.kind, s.state, s.due_at, s.payload, w.sc_id, w.location FROM steps s JOIN work_orders w ON w.id=s.wo_id "
                      f"WHERE {where} ORDER BY s.due_at, s.id LIMIT ? OFFSET ?", (lo, hi, size, (page - 1) * size)).fetchall()
    return rows, total, pages, page
