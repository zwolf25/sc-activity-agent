import pathlib
import random
import re
import xml.etree.ElementTree as ET
import zipfile

from sc_activity_agent import photos

FILE = pathlib.Path(__file__).parent.parent / "sc_activity_agent" / "SCActivityAgentIssueList.xlsx"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def issue_rows():
    """Rows of the Issues sheet as {column letter: text}."""
    z = zipfile.ZipFile(FILE)
    strings = ["".join(t.text or "" for t in si.iter(M + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    for r in ET.fromstring(z.read("xl/worksheets/sheet2.xml")).iter(M + "row"):
        yield {re.match(r"[A-Z]+", c.get("r")).group(): strings[int(c.find(M + "v").text)] if c.get("t") == "s" else c.find(M + "v").text
               for c in r.findall(M + "c") if c.find(M + "v") is not None}


def test_every_attachment_required_issue_in_the_shared_issue_list_has_a_photo_set():
    rows = [r for r in issue_rows() if r.get("K", "").strip().lower() in ("yes", "true", "1", "required")]
    assert len(rows) == 7
    for r in rows:
        text = f"{r['B']} {r['C']}".lower()
        hit = next((ids for pat, ids in photos.BY_ISSUE if re.search(pat, text)), [])   # a rule that names a set of the issue's own kind, not just any set of the trade
        assert hit and photos.pick(r["D"].strip(), "before", random.Random(1), issue=text)[0] in hit, r
