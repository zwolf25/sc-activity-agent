import random

from sc_activity_agent import photos
from sc_activity_agent.client import multipart


def test_every_set_has_all_three_files_and_known_trades():
    assert len(photos.sets()) >= 50
    for s in photos.sets().values():
        assert set(s["trades"]) <= set(photos.SLUG.values())
        for k in photos.KINDS:
            assert (photos.DIR / s[k]).stat().st_size > 1000, s["id"]


def test_every_supported_trade_has_several_sets():
    for slug in photos.SLUG.values():
        assert sum(slug in s["trades"] for s in photos.sets().values()) >= (2 if slug.endswith("equipment") else 4), slug   # equipment trades have 2 to 5 sets each (the 7 required-attachment issues)


def test_pick_matches_the_trade_and_reuses_a_set_by_id():
    rng = random.Random(1)
    sid, name, data = photos.pick("HVAC", "both", rng)
    assert "hvac" in photos.sets()[sid]["trades"] and name == photos.sets()[sid]["both"] and data[:2] == b"\xff\xd8"
    other = photos.pick("Plumbing", "after", rng, set_id=sid)   # the id wins over the trade: same story for one WO
    assert other[0] == sid and other[1] == photos.sets()[sid]["after"]


def test_pick_with_an_unknown_trade_returns_nothing():
    assert photos.pick("Snow Removal", "both", random.Random(1)) is None
    assert photos.trade_slug("Door/Lock") == "doors"


def test_multipart_body_carries_a_json_part_and_a_file_part():
    body, ctype = multipart([("meta", None, "application/json", b"{}"), ("file", "a.jpg", "image/jpeg", b"\xff\xd8")])
    boundary = ctype.split("boundary=")[1].encode()
    assert body.count(b"--" + boundary) == 3 and b'name="file"; filename="a.jpg"' in body and body.endswith(b"--" + boundary + b"--\r\n")


def test_issue_rules_name_real_sets_and_pick_a_matching_scene():
    import random
    assert {i for _, ids in photos.BY_ISSUE for i in ids} <= set(photos.sets())
    rng = random.Random(1)
    assert photos.pick("HVAC", "before", rng, issue="HVAC RTU Filter change")[0] == "hvac-rooftop-filter"
    assert photos.pick("PLUMBING", "before", rng, issue="Water Heater Leaking")[0] == "plumbing-water-heater-valve"
    assert photos.pick("ELECTRICAL", "before", rng, issue="Exit Signs, Emergency Lights Battery backup failed")[0] in ("electrical-exit-sign", "electrical-emergency-light")
    # a rule whose sets are not tagged with the WO's trade is ignored: the trade still decides
    assert "plumbing" in photos.sets()[photos.pick("PLUMBING", "before", rng, issue="Automatic Door stuck")[0]]["trades"]
    assert "hvac" in photos.sets()[photos.pick("HVAC", "before", rng, issue="no rule matches xyz")[0]]["trades"]
    assert photos.pick("PLUMBING", "before", rng, issue="Water Heater Pilot light out")[0] in ("plumbing-water-heater-valve", "water-heater-pilot-out")
    assert photos.pick("PLUMBING", "before", rng, issue="Backflow Preventer leaking")[0] == "backflow-preventer-spraying"
    assert photos.pick("DOOR/LOCK", "before", rng, issue="Overhead Door off track")[0] in ("overhead-door-off-track", "door-sweep-worn", "door-kick-plate")
    assert photos.pick("GENERAL MAINTENANCE", "before", rng, issue="Flag pole halyard broken")[0] == "flagpole-halyard-frayed"
    # B-95: every issue that requires an attachment finds a set of its own kind
    for trade, issue, ids in (("KITCHEN EQUIPMENT", "Fryer Installation", ("kitchen-fryer-install", "kitchen-fryer-install-b")),
                              ("KITCHEN EQUIPMENT", "Hanging Dial Scale Broken Chain", ("kitchen-dial-scale-chain", "kitchen-dial-scale-chain-b")),
                              ("KITCHEN EQUIPMENT", "Hanging Dial Scale Needle not working", ("kitchen-dial-scale-needle", "kitchen-dial-scale-glass")),
                              ("KITCHEN EQUIPMENT", "Digital Hanging Scale No Power", ("kitchen-digital-scale-nopower",)),
                              ("FREIGHT EQUIPMENT", "Fork Lift Battery", ("freight-forklift-battery", "freight-forklift-battery-b"))):
        assert photos.pick(trade, "before", rng, issue=issue)[0] in ids, issue


def test_pick_avoids_recent_sets_while_another_fits_and_recent_reads_the_last_wos(tmp_path):
    import random
    from sc_activity_agent.store import Store
    fits = sorted(i for i, x in photos.sets().items() if "hvac" in x["trades"])
    rng = random.Random(1)
    for _ in range(20):
        assert photos.pick("HVAC", "before", rng, avoid=fits[:-1])[0] == fits[-1]
    assert photos.pick("HVAC", "before", rng, avoid=fits)[0] in fits   # all recent: still picks one
    s = Store(tmp_path)
    for i, sid in enumerate(["a", "b", None]):
        s.db.execute("INSERT INTO work_orders(sc_id, location, trade, state, created_at, ctx) VALUES(?,?,?,?,?,?)",
                     (i + 1, "HQ-NYC", "HVAC", "active", 0, '{"photo_set": "%s"}' % sid if sid else "{}"))
    s.db.commit()
    assert photos.recent(s, "HQ-NYC") == ["b", "a"] and photos.recent(s, "ZW123") == []
