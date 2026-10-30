"""B-14: the bundled before/after photo library (photos/manifest.json). A set is one scene shot before, after and side by side,
under one id, tagged with every trade it fits. Pick a set by trade, then reuse its id for the same WO so the photos tell one story."""
import functools
import json
import pathlib

DIR = pathlib.Path(__file__).parent / "photos"
KINDS = ("before", "after", "both")
SLUG = {"door": "doors", "general": "general-maintenance", "hvac": "hvac", "electric": "electrical", "plumb": "plumbing", "janitor": "janitorial"}


@functools.cache
def sets():
    return {s["id"]: s for s in json.loads((DIR / "manifest.json").read_text())}


def trade_slug(name):
    n = (name or "").lower()
    return next((v for k, v in SLUG.items() if k in n), None)


def pick(trade, kind, rng, set_id=None):
    """(set id, file name, jpeg bytes) of one `kind` image, or None when no set fits the trade. With set_id, that set is used whatever the trade."""
    s = sets().get(set_id) if set_id else None
    if s is None:
        slug = trade_slug(trade)
        fits = sorted(i for i, x in sets().items() if slug in x["trades"])
        if not fits:
            return None
        s = sets()[rng.choice(fits)]
    return s["id"], s[kind], (DIR / s[kind]).read_bytes()
