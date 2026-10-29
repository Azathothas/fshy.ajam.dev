"""selfhosted.py: the one rule for self-hosted records in every list that the build writes, and its check.

A self-hosted record (record.self_hosted = 1) is software or a node that the user installs, runs and maintains. The
site is for users who have no hardware, so a self-hosted record is the last resort. In every list, self_hosted
ascending is the first sort key: every hosted record in the list's own order, then every self-hosted record in the
same order. A self-hosted row is never starred or highlighted: its label is LABEL, not its verdict pill. The Worker
(site/worker/rank.js hostedFirst, sortEntities) and the research repository (fr.py hosted_first) follow the same rule.

The check: build.py --site calls start() with the self-hosted records of the store. Then pages.py and llms.py give each
page or file that they write to check(), which reads the text that is already in memory, so the check reads no file.
A problem is a hosted row below a self-hosted row of the same page or file, or a self-hosted row with a verdict pill or
a star. problems() gives them, and the build fails on one. Standard library only.
"""
import re

LABEL = "self-hosted, last resort"
PILL = '<span class="v v-self-hosted">%s</span>' % LABEL
MEANING = "software or a node that the user installs, runs and maintains"
NOTE = "Self-hosted options are listed last, because this site is for users who have no hardware."
STAR = "★"


def hosted_first(items, is_self_hosted):
    """Every hosted item, then every self-hosted one; each part keeps the order it had (a stable partition)."""
    return [x for x in items if not is_self_hosted(x)] + [x for x in items if is_self_hosted(x)]


def is_sh(card):
    """True for a card (a dict of record columns) of a self-hosted record. A store of the data version 1 has 0."""
    return bool(card.get("self_hosted"))


# an offer row of a wiki list, and the record id in the link of its name: /p/<eid>/#<topic>--<slug> or a record page
ROW = re.compile(r'<li class="e"[^>]*>(.*?)</li>', re.S)
ROW_RID = re.compile(r'<a class="n" href="/p/[^/"]+/#?([^/"#]+?)/?"')
# a record section of a provider page or a record page; its anchor is <topic>--<slug>
SECTION = re.compile(r'<section class="rec[^"]*" id="([^"]+)"')
VERDICT_PILL = re.compile(r'class="v v-([a-z-]+)"')
# a line of a Markdown index (a link to the provider page, then the record id) and the head line of a record block
MD_ENTRY = re.compile(r"^(?:- |\d+\. ).*?/p/[^)\s]+\.md\) `([^`]+)`: (.*)$")
MD_HEAD = re.compile(r"^- `([^`]+)` \| (.*)$")

_STATE = {"rids": None, "problems": []}


def start(rids):
    """Check every page from now on, against this set of self-hosted record ids."""
    _STATE["rids"] = frozenset(rids)
    _STATE["problems"] = []


def problems():
    return list(_STATE["problems"])


def check(rel, text):
    """Check one written page or file, when start() ran. -> the problems of this text."""
    rids = _STATE["rids"]
    if rids is None:
        return []
    rel = rel.replace("\\", "/")
    if rel.endswith(".html"):
        found = html_problems(text, rids)
    elif rel.endswith((".md", ".txt")):
        found = md_problems(text, rids)
    else:
        return []
    found = [(rel, p) for p in found]
    _STATE["problems"].extend(found)
    return found


def _order(items, rids, marked):
    """items: [(rid, text of the row)] in page order. -> problems: a hosted row below a self-hosted one, and a
    self-hosted row that marked(text) says is starred or highlighted."""
    out, first = [], None
    for rid, row in items:
        if rid in rids:
            first = first or rid
            why = marked(row)
            if why:
                out.append("the self-hosted row %s %s" % (rid, why))
        elif first:
            out.append("the hosted row %s is below the self-hosted row %s" % (rid, first))
    return out


def _html_mark(row):
    pills = [p for p in VERDICT_PILL.findall(row) if p != "self-hosted"]
    if STAR in row:
        return "carries a star"
    if pills:
        return "carries the verdict pill %s instead of the label %r" % (pills[0], LABEL)
    if "v-self-hosted" not in row:
        return "has no label %r" % LABEL
    return ""


def html_problems(text, rids):
    rows = []
    for m in ROW.finditer(text):
        h = ROW_RID.search(m.group(1))
        if h:
            rows.append((h.group(1).replace("--", "/", 1), m.group(1)))
    marks = list(SECTION.finditer(text))
    secs = [(m.group(1).replace("--", "/", 1), text[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(text))])
            for i, m in enumerate(marks)]
    # the facts of a record section hold its verdict; its evidence and notes are provider text, not a mark of the site
    secs = [(rid, s.split("</dl>", 1)[0]) for rid, s in secs]
    return _order(rows, rids, _html_mark) + _order(secs, rids, _html_mark)


def _md_mark(line):
    if STAR in line:
        return "carries a star"
    if LABEL not in line:
        return "has no label %r" % LABEL
    return ""


def md_problems(text, rids):
    entries, heads = [], []
    for line in text.split("\n"):
        m = MD_ENTRY.match(line)
        if m:
            entries.append((m.group(1), line))
            continue
        m = MD_HEAD.match(line)
        if m:
            heads.append((m.group(1), line))
    return _order(entries, rids, _md_mark) + _order(heads, rids, _md_mark)
