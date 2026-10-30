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
        assert sum(slug in s["trades"] for s in photos.sets().values()) >= 4, slug


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
