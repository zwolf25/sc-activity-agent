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


def today(db, tz="America/New_York", now=None):
    """({kind: done today}, {kind: still to do today}) for pending/done steps in the local calendar day."""
    z = ZoneInfo(tz)
    d = dt.datetime.fromtimestamp(now, z) if now else dt.datetime.now(z)
    lo = d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    hi = lo + 86400
    q = lambda sql: {r[0]: r[1] for r in db.execute(sql, (lo, hi))}
    done = q("SELECT kind, COUNT(*) FROM steps WHERE state='done' AND done_at>=? AND done_at<? GROUP BY kind")
    todo = q("SELECT kind, COUNT(*) FROM steps WHERE state='pending' AND due_at>=? AND due_at<? GROUP BY kind")
    return done, todo
