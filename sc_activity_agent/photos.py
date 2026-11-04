"""B-14: the bundled before/after photo library (photos/manifest.json). A set is one scene shot before, after and side by side,
under one id, tagged with every trade it fits. Pick a set by trade, then reuse its id for the same WO so the photos tell one story."""
import functools
import json
import pathlib
import re

DIR = pathlib.Path(__file__).parent / "photos"
KINDS = ("before", "after", "both")
SLUG = {"door": "doors", "general": "general-maintenance", "hvac": "hvac", "electric": "electrical", "plumb": "plumbing", "janitor": "janitorial"}


# Issue text ("<equipment> <problem>", lower case) -> sets that show that kind of fault. First rule that matches wins; no match falls
# back to any set of the WO's trade. Only the six trades the library covers appear here.
BY_ISSUE = [
    (r"water heater|pilot", ["plumbing-water-heater-valve", "water-heater-pilot-out"]),
    (r"automatic door", ["door-automatic-sensor"]),
    (r"glass|window", ["door-glass-cracked", "glass-door-entry"]),
    (r"overhead|dock door|weather", ["overhead-door-off-track", "door-sweep-worn", "door-kick-plate"]),
    (r"exterior door|door", ["door-steel-lockset", "door-storefront-closer", "door-storefront-panic-bar", "door-jamb-strike-plate", "door-jamb-splintered"]),
    (r"generator", ["generator-battery-corroded"]),
    (r"electrical panel|breaker", ["electrical-panel", "junction-box"]),
    (r"exit sign|emergency light", ["electrical-exit-sign", "electrical-emergency-light"]),
    (r"\bflag", ["flagpole-halyard-frayed"]),
    (r"\bsign\b|signage|pylon", ["pylon-sign-panels-dark"]),
    (r"pole", ["electrical-pole-base"]),
    (r"lighting|light|lamp|ballast", ["light-fixture-ceiling"]),
    (r"outlet|switch|burning", ["outlet-burnt", "electrical-switch-plate", "junction-box"]),
    (r"contactor|compressor", ["rtu-contactor-burnt"]),
    (r"thermostat", ["thermostat-replace", "thermostat-blank-display"]),
    (r"filter", ["hvac-rooftop-filter"]),
    (r"evaporator|frozen|\bice\b", ["hvac-evaporator-coil-frozen"]),
    (r"coil", ["hvac-condenser-coil", "hvac-evaporator-coil-frozen"]),
    (r"duct", ["hvac-flex-duct-torn"]),
    (r"belt|blower", ["hvac-blower-belt"]),
    (r"condensate|drain pan", ["hvac-condensate-pan"]),
    (r"insulation", ["hvac-refrigerant-line-insulation"]),
    (r"hvac rtu leaking", ["hvac-condensate-pan"]),
    (r"refrigerant|line set", ["hvac-refrigerant-line-insulation"]),
    (r"exhaust|fan", ["hvac-fan-guard-rusted"]),
    (r"diffuser|grille|\bvent", ["hvac-ceiling-diffuser", "hvac-return-grille-dusty"]),
    (r"flushometer", ["flushometer-valve-leaking"]),
    (r"toilet|urinal", ["toilet-tank-leak-a", "toilet-tank-leak-b", "plumbing-toilet-cracked-base"]),
    (r"faucet|sink", ["faucet-drip-dirty", "sink-trap-leak"]),
    (r"backflow", ["backflow-preventer-spraying"]),
    (r"hose|spigot", ["plumbing-hose-bib"]),
    (r"carpet", ["hallway-carpet"]),
    (r"restroom", ["restroom-sinks", "restroom-partition-grimy"]),
    (r"trip|transition|threshold", ["dock-floor-transition-strip"]),
    (r"floor|spill", ["floor-vinyl-tile-lifted", "floor-tile-grout", "floor-mat-wet-debris"]),
    (r"trash|debris|\bmat\b", ["entry-mat-stained", "floor-mat-wet-debris"]),
    (r"drain|gutter", ["roof-drain-clogged"]),
    (r"fence|gate", ["fence-bent-post"]),
    (r"ceiling|roof|leak", ["ceiling-tile-water-stain", "ceiling-grid-water-damage"]),
    (r"baseboard|corner", ["wall-baseboard-corner", "wall-corner-guard"]),
    (r"shelf|cabinet|drawer", ["wall-shelf-bracket"]),
    (r"wall|drywall|sheetrock|paint|graffiti|hanging pictures", ["wall-drywall-hole", "wall-peeling-paint"]),
]


@functools.cache
def sets():
    return {s["id"]: s for s in json.loads((DIR / "manifest.json").read_text())}


def trade_slug(name):
    n = (name or "").lower()
    return next((v for k, v in SLUG.items() if k in n), None)


def attach_parts(pic, description, as_list):
    """Multipart parts that attach a picked photo. The WO endpoint wants {"Attachments": [...]}; the note endpoint wants the bare list."""
    _, name, img = pic
    meta = {"Name": name, "Description": description, "Type": 1, "MediaType": "image/jpeg"}
    return [("AddAttachmentsRequest", None, "application/json", json.dumps([meta] if as_list else {"Attachments": [meta]}).encode()),
            ("file", name, "image/jpeg", img)]


def pick(trade, kind, rng, set_id=None, issue=""):
    """(set id, file name, jpeg bytes) of one `kind` image, or None when no set fits the trade. With set_id, that set is used whatever the
    trade. Otherwise sets that show the `issue` text (BY_ISSUE, only those tagged with the trade) are preferred over any set of the trade."""
    s = sets().get(set_id) if set_id else None
    if s is None:
        slug = trade_slug(trade)
        fits = sorted(i for i, x in sets().items() if slug in x["trades"])
        text = (issue or "").lower()
        hit = next((ids for pat, ids in BY_ISSUE if re.search(pat, text)), [])
        fits = [i for i in hit if i in fits] or fits
        if not fits:
            return None
        s = sets()[rng.choice(fits)]
    return s["id"], s[kind], (DIR / s[kind]).read_bytes()
