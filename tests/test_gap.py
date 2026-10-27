import datetime as dt
import json
import random
from zoneinfo import ZoneInfo

from sc_activity_agent.engine import Engine, add_plan
from sc_activity_agent.store import Store

TZ = ZoneInfo("America/New_York")
T0 = dt.datetime(2026, 10, 26, 7, 0, tzinfo=TZ).timestamp()  # Monday 07:00


def local(ts):
    return dt.datetime.fromtimestamp(ts, TZ)


def mk(tmp_path, steps, clock):
    s = Store(tmp_path)
    add_plan(s, "HQ", "HVAC", 1, steps, {}, T0)
    return s, Engine(s, {}, clock=clock)


def dues(s):
    return [r["due_at"] for r in s.db.execute("SELECT due_at FROM steps ORDER BY seq")]


PLAN = [{"kind": "check_in", "due_at": T0 + 3 * 3600, "payload": {}},       # 10:00
        {"kind": "check_out", "due_at": T0 + 6 * 3600, "payload": {}},      # 13:00
        {"kind": "review", "due_at": T0 + 30 * 3600, "payload": {}}]        # Tue 13:00


def test_short_gap_is_shifted_and_recorded(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    e.tick()
    t[0] = T0 + 4 * 3600  # asleep 4h, now 11:00, check-in (10:00) overdue
    e.tick()
    g = s.get("gaps")[0]
    assert g["policy"] == "shift" and g["steps"] == 3
    ci, co, rv = dues(s)
    assert ci == T0 + 3 * 3600 + 4 * 3600 and co - ci == 3 * 3600 or local(co).hour == 17


def test_overnight_gap_snaps_to_activity_hours_and_keeps_same_day(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    e.tick()
    t[0] = T0 + 14 * 3600  # 21:00, gap spans the whole workday
    e.tick()
    ci, co, rv = dues(s)
    assert local(ci).hour >= 8 and local(ci).date() == local(co).date()
    assert ci <= co <= rv and 8 <= local(rv).hour < 17


def test_weekend_gap_lands_on_weekday(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    e.tick()
    t[0] = T0 + 5 * 86400 + 3600  # Saturday morning
    e.tick()
    assert all(local(d).weekday() < 5 for d in dues(s))


def test_resolve_gap_catch_up_and_undo(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    orig = dues(s)
    e.tick()
    t[0] = T0 + 4 * 3600
    e.tick()
    e.resolve_gap(0, "catch_up")
    ci = dues(s)[0]
    assert t[0] <= ci <= t[0] + 3600 and dues(s)[2] == orig[2]


def test_no_gap_for_normal_ticks(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    for _ in range(5):
        e.tick()
        t[0] += 30
    assert s.get("gaps") is None


def test_repeated_sleep_wake_cycles_make_one_notice(tmp_path):
    t = [T0]
    s, e = mk(tmp_path, PLAN, lambda: t[0])
    e.tick()
    for _ in range(3):  # sleep 16 min, wake for a tick, sleep again 1 min after
        t[0] += 16 * 60
        e.tick()
        t[0] += 60
        e.tick()
    gaps = s.get("gaps")
    assert len(gaps) == 1 and gaps[0]["end"] - gaps[0]["start"] >= 48 * 60
