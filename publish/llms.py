"""llms.py: the public store -> llms.txt, llms-full.txt and Markdown alternates of the wiki pages.

Called by build.py --site DIR after site_gen. It reads the public store only (the projection the wiki is
built from), never dossier/, so nothing the projection withholds can reach these files. It writes, under DIR:

  llms.txt                              llmstxt.org index: topics, needs, the full text, the API and MCP
  index.md                              the home page's Markdown alternate: the same text as llms.txt
  llms-full.txt                         the whole corpus when it fits in BUDGET, else the index of its parts
  t/<topic>/llms-full.txt               one topic in full when it fits in BUDGET, else the index of its parts
  t/<topic>/llms-full-<group>[-<k>].txt a part: one verdict group, cut into k pieces when over BUDGET
  t/<topic>.md, t/<topic>/rejected.md   the two topic pages: one line per record
  p/<eid>.md                            a provider page: every record of that provider in full
  need/<id>.md                          a best-per-need ranking

One order everywhere: hosted before self-hosted (selfhosted.py), then verdict (usable first, dead last), then
provider name, then record id. A self-hosted record is the last resort: each index lists it in a last section, and its
line carries the label of selfhosted.py. One store gives the same bytes on every build: no clock and no commit is read, and the one date printed is the data's
own, the newest verification or evidence date among the records. Standard library only.
"""
import collections
import hashlib
import json
import math
import os
import re
import sqlite3
from urllib.request import pathname2url

import selfhosted
from selfhosted import is_sh

HERE = os.path.dirname(os.path.abspath(__file__))
# The site's origin and its source repository. A fork sets both in the environment of the build; every absolute
# link of the wiki, the sitemap, the feed and these files comes from them.
BASE = os.environ.get("FSHY_ORIGIN", "https://fshy.ajam.dev").rstrip("/")
REPO = os.environ.get("FSHY_REPO", "https://github.com/Azathothas/fshy.ajam.dev").rstrip("/")
LICENCE = "0BSD"

# The most bytes one file holds: what an agent can read whole and still work. The corpus measures 3.7 bytes
# per token (test_llms.py estimates it the way a cl100k or o200k tokenizer splits text), so 300,000 bytes is
# about 81,000 tokens: inside a 128K-token window with room for the question and the answer, and under half
# of a 200K one. The whole corpus is about 14 MB, 3.9M tokens, which no window holds, so it is split.
BUDGET = 300_000
BYTES_PER_TOKEN = 3.7

GROUPS = [("usable", "Usable"), ("trial", "Trial"), ("paid", "Paid only"), ("rejected", "Rejected"), ("dead", "Dead")]
MAIN_GROUPS = ("usable", "trial", "paid")  # /t/<topic>/ lists these; /t/<topic>/rejected/ the other two
CARD = ("rid", "eid", "topic", "slug", "provider", "tier", "verdict", "vorder", "grp", "self_hosted", "confidence", "binding",
        "identity_kind", "identity_basis", "needs_card", "needs_phone", "needs_id", "needs_institution",
        "verified_basis", "checked_on", "stale_on", "usd_month", "usd_per_tb_month", "summary", "duplicate_of",
        "evidence_newest", "free_unit")
URL = re.compile(r"https?://\S+")
# the separator of the items of one line: ASCII, like every character this module writes that the data does not hold
SEP = " | "
# the evidence rungs, strongest first: the order of a tie in a ranked list (site/worker/api.js RUNG is the same)
RUNG = {"measured": 0, "documented": 1, "reported": 2, "inferred": 3, "unverified": 4}
# a short phrase for each topic, for the summary line; a topic with no records is not named
TOPIC_PHRASE = {"storage": "storage", "compute": "compute and GPU time", "inference": "model inference",
                "egress": "egress and tunnels", "ip-proxy": "proxies", "crawler-scraper": "crawling", "debrid": "debrid",
                "netdisk-pan": "netdisks", "databases-kv": "databases", "email": "email", "domains-dns": "DNS and domains",
                "ci-cd-runners": "CI runners", "dev-services": "developer services", "data-apis": "data APIs",
                "coding-subs": "coding subscriptions"}

# Record fields in print order. A field not named here is printed after these under its own key, so a
# field the projection starts to publish reaches these files without a change here.
SECTIONS = [  # (key, label, sub-keys in order; the first is printed bare)
    ("free_tier", "free tier", ("stated", "unit", "metered_on", "read_on", "source_url", "notes")),
    ("per_object_cap", "per-object cap", ("stated", "bytes", "source_url", "notes")),
    ("retention", "retention", ("stated", "days", "source_url", "notes")),
    ("egress", "egress", ("terms", "metered", "free_allowance", "price_per_tb", "source_url")),
    ("identity_cost", "identity", ("kind", "detail", "country")),
]
SUBLABEL = {"metered_on": "metered on", "read_on": "read on", "source_url": "source", "free_allowance": "free allowance",
            "price_per_tb": "price per TB", "notes": "note"}
PROSE = [("interface_detail", "interface detail"), ("endpoint", "endpoint"), ("tooling", "tooling"),
         ("chaining", "composes with"), ("reliability_note", "reliability"), ("notes", "notes"),
         ("confidence_note", "evidence note")]
DONE = ({"topic", "slug", "provider", "url", "category", "tier", "verdict", "confidence", "binding", "verified_at",
         "price_per_tb_month", "interface", "limits", "limits_note", "binding_note", "evidence", "extras"}
        | {k for k, _, _ in SECTIONS} | {k for k, _ in PROSE})
EMPTY = (None, "", [], {})


def flat(s):
    return " ".join(str(s).split())


def scalar(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return flat(v)


def yn(v):
    return {1: "yes", 0: "no"}.get(v, "unknown")


def num(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------------------------- shared with pages.py
# A tier that names no plan: it cannot tell two records apart.
NO_TIER = re.compile(r"^(?:none|n/?a|-|unknown|dead|closed|not stated)\b", re.I)
TIER_MAX = 40


def _tier(c):
    t = flat(c.get("tier") or "")
    return t if t and len(t) <= TIER_MAX and not NO_TIER.match(t) else ""


def _slug_rest(c):
    """The part of the slug that the provider name and the entity id do not hold: 'torbox-pro' -> 'pro'."""
    slug = c["slug"] or ""
    for pre in (re.sub(r"[^a-z0-9]+", "-", (c["provider"] or "").lower()).strip("-"), c["eid"]):
        if pre and slug.startswith(pre + "-"):
            return slug[len(pre) + 1:].replace("-", " ")
        if pre and slug == pre:
            return ""
    return slug.replace("-", " ")


def shown(name, fallback):
    """A name to print: the name, or the fallback when the name holds no letter and no digit (one record is "?")."""
    n = flat(name or "")
    return n if re.search(r"\w", n) else flat(fallback or "")


def labels(cards, tname=None):
    """{rid: the name to print}. Records of one provider that share a name get a suffix that tells them apart: the
    tier when it is short and unique, else the rest of the slug, else the topic. The name alone otherwise."""
    tname = tname or {}
    groups = collections.defaultdict(list)
    for c in cards.values():
        groups[(c["eid"], flat(c["provider"] or c["slug"]).casefold())].append(c)
    out = {}
    for g in groups.values():
        if len(g) == 1:
            out[g[0]["rid"]] = shown(g[0]["provider"], g[0]["slug"])
            continue
        tiers = collections.Counter(_tier(c).casefold() for c in g)
        rests = collections.Counter(_slug_rest(c) for c in g)
        topics = collections.Counter(c["topic"] for c in g)
        for c in g:
            name = shown(c["provider"], c["slug"])  # its own spelling: the group ignores case
            t, r = _tier(c), _slug_rest(c)
            if t and tiers[t.casefold()] == 1 and t.casefold() not in name.casefold():
                suffix = t
            elif r and rests[r] == 1:
                suffix = r
            elif topics[c["topic"]] == 1:
                suffix = tname.get(c["topic"], c["topic"])
            else:
                suffix = c["rid"]
            out[c["rid"]] = "%s (%s)" % (name, suffix)
    return out


FIRST_SENTENCE = re.compile(r"(.{20,}?[.!?])\s+(?=[A-Z0-9(\"'])")
# a label in front of a quote of the provider: the quotation marks already say that it is a quote
QUOTE_LABEL = re.compile(r"^(?:Quoted|Verbatim|Quote):\s*", re.I)
CUT_TAIL = re.compile(r"\s*\S*(?:\.\.\.|\u2026)$")


def first_sentence(s):
    m = FIRST_SENTENCE.match(s or "")
    return m.group(1) if m else (s or "")


def headline(summary, stated=None):
    """The one line of a row: the summary, or the first sentence of the free tier when the summary was cut and that
    sentence is shorter. A cut summary loses its last, cut word; the first letter is a capital."""
    s = QUOTE_LABEL.sub("", flat(summary or ""))
    if not s:
        return ""
    cut = s.endswith("...") or s.endswith("\u2026")
    if cut and stated:
        first = first_sentence(flat(stated))
        if first and len(first) < len(s) and not first.endswith("..."):
            s, cut = first, False
    if cut:
        short = CUT_TAIL.sub("", s).rstrip(" ,;:(-")
        if len(short) >= 20:
            s = short + "..."
    return s[:1].upper() + s[1:]


def clip_words(s, cap):
    """s cut to at most cap characters at a space, with '...' when text was dropped."""
    if cap is None or len(s) <= cap:
        return s
    if cap <= 3:
        return ""
    head = s[:cap - 3]
    if " " in head[cap // 2:]:
        head = head[:head.rfind(" ")]
    return head.rstrip(" ,;:(-") + "..."


def later_first(d):
    """A key that sorts a later YYYY-MM-DD first, and no date last."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return tuple(-int(x) for x in m.groups()) if m else (1,)


def tie_key(c):
    """The order of a tie in a ranked list: verdict, evidence rung, the later stale date, record id."""
    return (c["vorder"], RUNG.get(c["confidence"], len(RUNG)), later_first(c["stale_on"]), c["rid"])


def free_word(c):
    """'free tier', 'no free tier', or '' when the record does not say."""
    u = c.get("free_unit")
    return "" if u is None else ("no free tier" if u == "none" else "free tier")


def money(v, suffix):
    if v is None:
        return ""
    return "USD %s%s" % (("%.2f" % v).rstrip("0").rstrip(".") if v < 1000 else "%.0f" % v, suffix)


def size(n):
    return "%s KB, about %sK tokens" % (num(max(1, round(n / 1000))), num(max(1, round(n / BYTES_PER_TOKEN / 1000))))


# ---------------------------------------------------------------------------------------------- the store
class Store:
    def __init__(self, pub_db):
        db = sqlite3.connect("file:%s?mode=ro" % pathname2url(os.path.abspath(pub_db)), uri=True)
        db.row_factory = sqlite3.Row
        self.db = db
        self.cards, self.docs = {}, {}
        for r in db.execute("SELECT %s, doc FROM record ORDER BY rid" % ",".join(CARD)):
            self.cards[r["rid"]] = {k: r[k] for k in CARD}
            self.docs[r["rid"]] = json.loads(r["doc"])
        self.ents = {r["eid"]: {"name": r["name"], "domain": r["domain"], "members": []}
                     for r in db.execute("SELECT eid, name, domain FROM entity ORDER BY eid")}
        for rid in self.order(self.cards):
            self.ents[self.cards[rid]["eid"]]["members"].append(rid)
        self.drift = {}
        for r in db.execute("SELECT subject, other, field, a, b FROM drift ORDER BY subject, other, field, a, b"):
            for k in {r["subject"], r["other"]} - {None}:
                self.drift.setdefault(k, []).append(dict(r))
        self.vocab = {}
        for r in db.execute("SELECT domain, term, meaning FROM vocab ORDER BY domain, ord, term"):
            self.vocab.setdefault(r["domain"], []).append((r["term"], r["meaning"]))
        self.needs = json.load(open(os.path.join(HERE, "rules", "needs.json"), encoding="utf-8"))["needs"]
        self.topics = topics(sorted({c["topic"] for c in self.cards.values()}))
        self.labels = labels(self.cards, {t: n for t, n, _ in self.topics})
        dates = [c["evidence_newest"] for c in self.cards.values() if c["evidence_newest"]]
        dates += [d["verified_at"][:10] for d in self.docs.values() if isinstance(d.get("verified_at"), str)]
        self.as_of = max(dates) if dates else "unknown"

    def order(self, rids):
        """The one order: hosted before self-hosted, then verdict, provider name, record id."""
        c = self.cards
        return sorted(rids, key=lambda r: (is_sh(c[r]), c[r]["vorder"], (c[r]["provider"] or "").casefold(), r))

    def need_rows(self, x):
        """A need's rows as its HTML page and the API rank them: by the sort value, then tie_key."""
        return need_rows(self.db, x, self.cards)


def need_rows(db, x, cards):
    """(ranked, unranked, self-hosted) rows of a need. The hosted rows by the sort value, then tie_key, and the rows
    with no value after them; then the self-hosted rows in the same order, the last resort (site/worker/api.js need)."""
    rows = db.execute(x["sql"]).fetchall()
    ranked = sorted((r for r in rows if r[1] is not None), key=lambda r: (r[1],) + tie_key(cards[r[0]]))
    unranked = sorted((r for r in rows if r[1] is None), key=lambda r: tie_key(cards[r[0]]))
    last = [r for r in ranked + unranked if is_sh(cards[r[0]])]
    return [r for r in ranked if not is_sh(cards[r[0]])], [r for r in unranked if not is_sh(cards[r[0]])], last


def topics(in_data):
    """(topic, name, description): the wiki's own list and order, then any topic only the data has."""
    known = []
    try:
        import pages  # noqa: E402
        for x in getattr(pages, "TOPICS", []):
            known.append((x[0], x[1] if len(x) > 1 else x[0], x[2] if len(x) > 2 else ""))
    except ImportError:
        pass
    seen = {t for t, _, _ in known}
    return known + [(t, t, "") for t in in_data if t not in seen]


# ---------------------------------------------------------------------------------------------- one record
def record_md(st, rid):
    """One record: every published field in a fixed order, each source URL numbered once."""
    c, o = st.cards[rid], st.docs[rid]
    srcs = []

    def src(u):
        if not isinstance(u, str) or not URL.fullmatch(u):
            return scalar(u)
        if u not in srcs:
            srcs.append(u)
        return "[%d]" % (srcs.index(u) + 1)

    out = ["## " + st.labels.get(rid, flat(c["provider"] or c["slug"])), ""]
    head = ["`%s`" % rid, c["verdict"]] + ([selfhosted.LABEL] if is_sh(c) else []) + ["evidence %s" % c["confidence"]]
    head += ["%s %s" % (k, flat(o[k])) for k in ("binding", "category", "tier") if o.get(k) not in EMPTY]
    out.append("- " + SEP.join(head))
    needs = ("needs card %s, phone %s, ID %s, institution %s" % (
        yn(c["needs_card"]), yn(c["needs_phone"]), yn(c["needs_id"]), yn(c["needs_institution"]))
        if c["identity_basis"] == "stated" else "identity a placeholder: card and phone unknown")
    va = o.get("verified_at")
    out.append("- %s | verified %s%s (%s) | stale on %s" % (
        needs, scalar(va) if va not in EMPTY else "unknown",
        "" if str(va)[:10] == c["checked_on"] else ", checked %s" % c["checked_on"], c["verified_basis"], c["stale_on"]))
    out.append("- %spage %s/p/%s.md" % (("url %s | " % flat(o["url"])) if o.get("url") else "", BASE, c["eid"]))
    price = [p for p in (money(c["usd_month"], "/mo"), money(c["usd_per_tb_month"], "/TB-mo")) if p]
    if o.get("price_per_tb_month") not in EMPTY or price:
        out.append("- price " + SEP.join(([scalar(o["price_per_tb_month"])] if o.get("price_per_tb_month") not in EMPTY else [])
                                           + (["parsed " + ", ".join(price)] if price else [])))
    if c["duplicate_of"]:
        out.append("- duplicate of `%s`" % c["duplicate_of"])
    for d in st.drift.get(rid, []):
        out.append("- disagrees on %s: `%s` says %s, `%s` says %s" % (d["field"], d["subject"], scalar(d["a"]),
                                                                    d["other"], scalar(d["b"])))
    for key, label, subs in SECTIONS:
        v = o.get(key)
        if not isinstance(v, dict):
            if v not in EMPTY:
                out.append("- %s: %s" % (label, scalar(v)))
            continue
        parts = []
        for sk in list(subs) + [k for k in v if k not in subs]:
            x = v.get(sk)
            if x in EMPTY:
                continue
            val = src(x) if sk == "source_url" else scalar(x)
            parts.append(val if sk == subs[0] else "%s: %s" % (SUBLABEL.get(sk, sk.replace("_", " ")), val))
        if parts:
            out.append("- %s: %s" % (label, SEP.join(parts)))
    if o.get("interface") not in EMPTY:
        out.append("- interface: " + (", ".join(scalar(t) for t in o["interface"]) if isinstance(o["interface"], list)
                                      else scalar(o["interface"])))
    lims = o.get("limits") or []
    if lims:
        out.append("- limits:")
        for lm in lims:
            if not isinstance(lm, dict):
                out.append("  - " + scalar(lm))
                continue
            rest = "".join("%s%s: %s" % (SEP, k, scalar(lm[k])) for k in lm if k not in ("kind", "value", "source")
                           and lm[k] not in EMPTY)
            out.append("  - %s%s: %s%s%s" % (scalar(lm.get("kind") or "limit"),
                                            " (binding)" if lm.get("kind") and lm.get("kind") == o.get("binding") else "",
                                            scalar(lm.get("value") or ""),
                                            (" " + src(lm["source"])) if lm.get("source") not in EMPTY else "", rest))
    # a prose value that an earlier line holds is not printed again: the later line names the earlier one, as
    # "the same as" when the two are equal and as "part of" when the earlier line holds more
    said = []
    ft = o.get("free_tier")
    if isinstance(ft, dict) and isinstance(ft.get("stated"), str) and flat(ft["stated"]):
        said.append(("the free tier", flat(ft["stated"])))

    def prose_line(key, label):
        v = o.get(key)
        if v in EMPTY:
            return
        text = scalar(v)
        out.append("- %s: %s" % (label, repeat_note(said, text) if isinstance(v, str) else text))
        if isinstance(v, str) and repeat_of(said, text) is None:
            said.append((label, text))
    prose_line("limits_note", "limits note")
    prose_line("binding_note", "binding note")
    for key, label in PROSE:
        prose_line(key, label)
    for key in [k for k in o if k not in DONE] + ["extras"]:
        rows = leaf_lines(o.get(key))
        if len(rows) == 1 and rows[0][0] == "":
            out.append("- %s: %s" % (key.replace("_", " "), rows[0][1]))
        elif rows:
            out.append("- %s:" % key.replace("_", " "))
            out.extend("  - %s: %s" % r for r in rows)
    ev = o.get("evidence") or []
    if ev:
        out.append("- evidence:")
        for e in ev:
            if not isinstance(e, dict):
                out.append("  - " + scalar(e))
                continue
            rest = "".join("%s%s: %s" % (SEP, k, scalar(e[k])) for k in e if k not in ("url", "date", "proved") and e[k] not in EMPTY)
            out.append("  - %s%s: %s%s" % (src(e["url"]) if e.get("url") not in EMPTY else "withheld",
                                          (" " + scalar(e["date"])) if e.get("date") not in EMPTY else "",
                                          scalar(e.get("proved") or ""), rest))
    if srcs:
        out.append("- sources:")
        out.extend("  - [%d] %s" % (i, u) for i, u in enumerate(srcs, 1))
    return "\n".join(out) + "\n"


def leaf_lines(v, p=""):
    """(dotted path, value) for each leaf; a list of scalars stays one value, joined by '; '."""
    if v in EMPTY:
        return []
    if isinstance(v, dict):
        return [row for k in v for row in leaf_lines(v[k], "%s.%s" % (p, k) if p else str(k))]
    if isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            vals = [scalar(x) for x in v if x not in EMPTY]
            return [(p, "; ".join(vals))] if vals else []
        return [row for i, x in enumerate(v) for row in leaf_lines(x, "%s[%d]" % (p, i))]
    return [(p, scalar(v))]


def repeat_of(said, text):
    """How the earlier prose values hold `text`. `said` is a list of (label, text) in the order of the lines.
    -> ("same", label) of the first value that equals it, else ("part", label) of the first value that holds it as a
    strict part, else None. A part starts and ends at a word boundary: "REST" is a part of "REST, OAI-PMH" and not
    of "RESTful"."""
    if not text:
        return None
    part = None
    rx = None
    for label, t in said:
        if text == t:
            return "same", label
        if part is None and text in t:
            rx = rx or re.compile(r"(?<!\w)" + re.escape(text) + r"(?!\w)")
            if rx.search(t):
                part = label
    return ("part", part) if part is not None else None


def repeat_note(said, text):
    """The words that a line prints in place of a value that an earlier line holds; the value itself when none does."""
    r = repeat_of(said, text)
    if r is None:
        return text
    return ("the same as " if r[0] == "same" else "part of ") + r[1]


def entry_md(st, rid, bullet="- ", cap=None):
    """One line of an index, with the badges the HTML lists show: verdict, free tier, identity, card, phone, evidence,
    price, then the summary, cut at a space to `cap` characters when a cap is given."""
    c = st.cards[rid]
    ft = st.docs[rid].get("free_tier")
    s = clip_words(headline(c["summary"], ft.get("stated") if isinstance(ft, dict) else None), cap)
    q = c["identity_basis"] != "stated"
    b = ([c["verdict"]] + ([selfhosted.LABEL] if is_sh(c) else []) + ([free_word(c)] if free_word(c) else [])
         + [str(c["identity_kind"]) + ("?" if q else "")])
    if c["needs_card"] == 0 and not q:
        b.append("no card")
    elif c["needs_card"] == 1:
        if c["identity_kind"] != "card":
            b.append("card")
    else:
        b.append("card?")
    if c["needs_phone"] == 0 and not q:
        b.append("no phone")
    elif c["needs_phone"] == 1:
        if c["identity_kind"] not in ("any-phone", "country-phone"):
            b.append("phone")
    else:
        b.append("phone?")
    b.append(str(c["confidence"]))
    price = money(c["usd_per_tb_month"], "/TB-month") or money(c["usd_month"], "/month")
    if price:
        b.append(price)
    if c["duplicate_of"]:
        b.append("duplicate")
    return "%s[%s](%s/p/%s.md) `%s`: %s%s" % (bullet, st.labels.get(rid, flat(c["provider"] or c["slug"])), BASE, c["eid"],
                                             rid, SEP.join(b), (". " + s) if s else "")


def fitted(render):
    """render(cap) -> page text. The page with whole summaries when it fits in BUDGET, else with every summary
    cut to the longest length that fits; the provider pages keep them whole."""
    text = render(None)
    if len(text.encode("utf-8")) <= BUDGET:
        return text
    lo, hi = 0, 400
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(render(mid).encode("utf-8")) <= BUDGET:
            lo = mid
        else:
            hi = mid - 1
    return render(lo)


def counts(cnt):
    """The counts of a topic: its hosted records by group, then its self-hosted records when it has any."""
    return ", ".join(["%s %s" % (num(cnt[g]), lbl.lower()) for g, lbl in GROUPS]
                     + (["%s self-hosted, listed last" % num(cnt["self-hosted"])] if cnt.get("self-hosted") else []))


def self_section(st, rids, cap):
    """The last section of an index: its self-hosted records, the last resort, in the order of the index."""
    if not rids:
        return []
    return (["## Self-hosted, the last resort (%s)" % num(len(rids)), "",
             "%s%s. %s" % (selfhosted.MEANING[:1].upper(), selfhosted.MEANING[1:], selfhosted.NOTE), ""]
            + [entry_md(st, r, cap=cap) for r in rids] + [""])


def cut_note(cap):
    return ([] if cap is None else ["Summaries are cut to %d characters to keep this page within %s; each provider page "
                                    "has them whole." % (cap, size(BUDGET)), ""])


# ---------------------------------------------------------------------------------------------- shared text
def summary_line(st, notice=True):
    """The summary of llms.txt: the topics that have records, the counts, and the one notice (llms.txt only)."""
    have = {c["topic"] for c in st.cards.values()}
    words = [TOPIC_PHRASE.get(t, name.lower()) for t, name, _ in st.topics if t in have]
    listed = ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)
    return ("> A catalogue of free, nearly free and cheapest-paid cloud capacity: %s. %s records from %s providers. "
            "Each record states its quota, the limit that runs out first, the identity a signup costs (email, phone, "
            "card, ID), its evidence and how fresh that evidence is.%s"
            % (listed, num(len(st.cards)), num(len(st.ents)),
               " For research and education only. It is not legal advice, and it makes no statement about whether a "
               "use is permitted." if notice else ""))


ONE_ORDER = "hosted before self-hosted, then verdict, provider name, record id"


def stamp(st, version):
    return ("Data as of %s, the newest verification or evidence date in the records. Version `%s`: the first 12 hex "
            "digits of the SHA-256 of every record's Markdown, topic by topic in the one order (%s); it changes "
            "whenever a record does." % (st.as_of, version, ONE_ORDER))


def reading_rules(st):
    v = st.vocab

    def terms(d):
        """One line for each term of a vocabulary, with its meaning: a meaning can hold a semicolon."""
        return ["  - `%s`: %s" % (t, m) if m else "  - `%s`" % t for t, m in v.get(d, [])]
    return [
        "## How to read a record",
        "",
        "Each record opens with its id (topic/slug), verdict, evidence, binding limit and category. Then it says what "
        "a signup needs, when the record was verified and when that check goes stale. Then it gives its URL and its "
        "provider page. Each line of the lists below is one term and its meaning.",
        "",
        "- verdict, best first:"] + terms("verdict") + [
        "- group, the verdicts that a topic page lists together:"] + terms("grp") + [
        "- evidence, how a claim is backed, strongest first:"] + terms("confidence") + [
        "- binding, the limit that runs out first:"] + terms("binding") + [
        "- identity, what a signup costs:"] + terms("identity_kind") + [
        "- `needs card, phone, ID, institution`: yes, no or unknown. Unknown never means no. In an index, `?` after "
        "the identity marks a placeholder that no source states, and `card?` or `phone?` an unknown requirement.",
        "- `free tier` or `no free tier` in an index: the record states a free allowance, or states that it has none. "
        "Neither word: the record does not say.",
        "- verified: when the record was last verified, with `checked` after it when the check date of the staleness "
        "policy differs; then the basis:"] + terms("verified_basis") + [
        "- stale on: the date that the evidence window of the check ends. Compare it with today.",
        "- price: the price as written, then `parsed` USD figures where a number parsed. No parsed figure means none "
        "parsed, not free.",
        "- `[n]`: a numbered source; the sources list of the record gives each URL once. An evidence line reads: source, "
        "date, what it proved.",
        "- `%s`: after the verdict, %s. Every list puts it after every hosted record. %s" % (
            selfhosted.LABEL, selfhosted.MEANING, selfhosted.NOTE),
        "- not stated, not recorded, not applicable: the value was not published, or does not apply. A field that a "
        "record does not show was not published: that is unknown, not absent.",
        "- the same as: the value equals an earlier line of the record, word for word.",
        "- part of: the value is a part of an earlier line of the record. That line holds it in full.",
        "",
    ]


def access_lines():
    return [
        "## Query it",
        "",
        "- [MCP endpoint](%s/mcp): Streamable HTTP, stateless and read-only; tools help, search, filter, get, entity, "
        "need, sql, worklist. Connect: `claude mcp add --transport http fshy %s/mcp`" % (BASE, BASE),
        "- [help.txt](%s/api/v1/help.txt): the query primer: tables, columns, vocabularies and worked SQL; read it first" % BASE,
        "- [search](%s/api/v1/search?q=gpu+hours&topic=compute): full-text search; `q` words, optional `topic`" % BASE,
        "- [records](%s/api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month): filter and sort record cards" % BASE,
        "- [sql](%s/api/v1/sql?q=SELECT+rid,verdict+FROM+record+LIMIT+5): read-only SQLite over the store" % BASE,
        "- [record](%s/api/v1/record/compute/oracle-cloud): one record as JSON, `/api/v1/record/<topic>/<slug>`" % BASE,
        "- [entity](%s/api/v1/entity/oracle.json): one provider and all its records as JSON, `/api/v1/entity/<id>.json`" % BASE,
        "- [schema.sql](%s/api/v1/schema.sql): the store's schema; [vocab.json](%s/api/v1/vocab.json): its vocabularies"
        % (BASE, BASE),
        "- [fshy-public.sqlite.gz](%s/data/fshy-public.sqlite.gz): the whole store as one SQLite file, gzip; "
        "data/manifest.json gives its SHA-256" % BASE,
        "",
    ]


def version_of(texts):
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:12]


def split_parts(blocks, budget, overhead):
    """Cut an ordered list of record blocks into the fewest runs whose text, with `overhead` bytes of header,
    fits in `budget`, balanced in size; a record is never cut, and one over budget alone gets a run."""
    sizes = [len(b.encode("utf-8")) + 1 for b in blocks]
    k = max(1, math.ceil(sum(sizes) / (budget - overhead)))
    while True:
        target = sum(sizes) / k
        runs, cum = [[] for _ in range(k)], 0
        for b, n in zip(blocks, sizes):
            runs[min(k - 1, int((cum + n / 2) / target))].append(b)
            cum += n
        runs = [r for r in runs if r]
        if all(len(r) == 1 or sum(len(b.encode("utf-8")) + 1 for b in r) + overhead <= budget for r in runs) or k >= len(blocks):
            return runs
        k += 1


class Writer:
    def __init__(self, dist):
        self.dist, self.files, self.dirs = dist, {}, set()

    def write(self, rel, text):
        selfhosted.check(rel, text)
        p = os.path.join(self.dist, *rel.split("/"))
        d = os.path.dirname(p)
        if d not in self.dirs:
            os.makedirs(d, exist_ok=True)
            self.dirs.add(d)
        b = text.encode("utf-8")
        with open(p, "wb") as f:
            f.write(b)
        self.files[rel] = len(b)
        return len(b)


# ---------------------------------------------------------------------------------------------- the files
def generate(pub_db, dist):
    """Write every file the module docstring lists under dist. Returns {relative path: bytes}."""
    st = Store(pub_db)
    w = Writer(dist)
    blocks = {rid: record_md(st, rid) for rid in st.cards}
    tname = {t: n for t, n, _ in st.topics}
    by_topic = {t: [] for t, _, _ in st.topics}
    for rid in st.order(st.cards):
        by_topic[st.cards[rid]["topic"]].append(rid)
    order = [rid for t, _, _ in st.topics for rid in by_topic[t]]
    version = version_of([blocks[r] for r in order])
    total = sum(len(blocks[r].encode("utf-8")) + 1 for r in order)

    # p/<eid>.md: a provider page, every record of that provider in full
    for eid, e in st.ents.items():
        ts = list(dict.fromkeys(tname.get(st.cards[r]["topic"], st.cards[r]["topic"]) for r in e["members"]))
        n = len(e["members"])
        self_link = " | page %s/p/%s.md" % (BASE, eid)
        w.write("p/%s.md" % eid, "\n".join([
            "# " + shown(e["name"], e["domain"] or eid), "",
            "> %s%s; %d record%s: free tier, limits, identity cost and evidence." % (
                (flat(e["domain"]) + SEP) if e["domain"] else "", ", ".join(ts), n, "" if n == 1 else "s"), "",
            "HTML %s/p/%s/ | JSON %s/api/v1/entity/%s.json | how to read a record: %s/llms-full.txt" % (
                BASE, eid, BASE, eid, BASE), ""] + [blocks[r].replace(self_link, "", 1) for r in e["members"]]))

    # t/<topic>.md and t/<topic>/rejected.md: the topic pages; t/<topic>/llms-full*.txt: the topic in full
    topic_rows, parts_index = [], []
    for t, name, desc in st.topics:
        rids = by_topic[t]
        cnt = {g: sum(1 for r in rids if st.cards[r]["grp"] == g and not is_sh(st.cards[r])) for g, _ in GROUPS}
        cnt["self-hosted"] = sum(1 for r in rids if is_sh(st.cards[r]))
        topic_rows.append((t, name, desc, rids, cnt))
        needs = [x for x in st.needs if x.get("topic") == t]
        for rel, groups, title, other in (
                ("t/%s.md" % t, MAIN_GROUPS, name, "the usable, trial and paid-only records; the rejected and dead "
                 "ones are on %s/t/%s/rejected.md" % (BASE, t)),
                ("t/%s/rejected.md" % t, ("rejected", "dead"), name + ": rejected and dead",
                 "the rejected and dead records, each with the evidence that rejected it; the usable, trial and "
                 "paid-only ones are on %s/t/%s.md" % (BASE, t))):
            def render(cap, title=title, groups=groups, other=other):
                full = ("In full: %s/t/%s/llms-full.txt." % (BASE, t)) if rids else "No record is in this topic yet."
                lines = ["# " + title, "", "> " + (desc or name), "",
                         "%s records: %s. This page lists %s. Each line: provider (its page in Markdown), record id, "
                         "verdict, free tier, identity, card, phone, evidence, parsed price, summary. %s"
                         % (num(len(rids)), counts(cnt), other, full), ""] + cut_note(cap)
                if needs and groups == MAIN_GROUPS:
                    lines += ["Best per need: " + ", ".join("[%s](%s/need/%s.md)" % (x["title"], BASE, x["id"]) for x in needs), ""]
                for g, lbl in GROUPS:
                    gs = [r for r in rids if st.cards[r]["grp"] == g and not is_sh(st.cards[r])]
                    if g in groups and gs:
                        lines += ["## %s (%s)" % (lbl, num(len(gs))), ""] + [entry_md(st, r, cap=cap) for r in gs] + [""]
                lines += self_section(st, [r for r in rids if is_sh(st.cards[r]) and st.cards[r]["grp"] in groups], cap)
                return "\n".join(lines)
            w.write(rel, fitted(render))
        if not rids:
            continue
        head = ["# fshy: %s in full" % name, "", "> " + (desc or name), "", stamp(st, version), "",
                "How to read a record, and the other topics: %s/llms-full.txt. One line per record: %s/t/%s.md." % (BASE, BASE, t), ""]
        body = "\n".join(head) + "\n" + "\n".join(blocks[r] for r in rids)
        if len(body.encode("utf-8")) <= BUDGET:
            n = w.write("t/%s/llms-full.txt" % t, body)
            parts_index.append("- [%s](%s/t/%s/llms-full.txt): all %s records; %s" % (name, BASE, t, num(len(rids)), size(n)))
            continue
        index = head[:4] + [stamp(st, version), "",
                            "This topic is %s in full, more than the %s one file holds, so it is split: by verdict group, "
                            "and a group over that size into balanced parts, each in the one order (%s). How to read a "
                            "record: %s/llms-full.txt." % (size(len(body.encode("utf-8"))), size(BUDGET), ONE_ORDER, BASE),
                            "", "## Parts", ""]
        for g, lbl in GROUPS:
            gs = [r for r in rids if st.cards[r]["grp"] == g]
            if not gs:
                continue

            def phead(k, of):
                return ["# fshy: %s, %s%s" % (name, lbl.lower(), (", part %d of %d" % (k, of)) if of > 1 else ""), "",
                        "> " + (desc or name), "", stamp(st, version), "",
                        "This topic's parts: %s/t/%s/llms-full.txt. How to read a record: %s/llms-full.txt." % (BASE, t, BASE), ""]
            runs = split_parts([blocks[r] for r in gs], BUDGET, len(("\n".join(phead(99, 99)) + "\n").encode("utf-8")))
            at = 0
            for k, run in enumerate(runs, 1):
                first, last = st.cards[gs[at]], st.cards[gs[at + len(run) - 1]]
                at += len(run)
                rel = "t/%s/llms-full-%s%s.txt" % (t, g, ("-%d" % k) if len(runs) > 1 else "")
                n = w.write(rel, "\n".join(phead(k, len(runs))) + "\n" + "\n".join(run))
                what = "%s records" % num(len(run))
                if len(runs) > 1:
                    what += ", %s (%s) to %s (%s)" % (flat(first["provider"]), first["verdict"], flat(last["provider"]), last["verdict"])
                label = lbl + ((" part %d of %d" % (k, len(runs))) if len(runs) > 1 else "")
                index.append("- [%s](%s/%s): %s; %s" % (label, BASE, rel, what, size(n)))
                parts_index.append("- [%s: %s](%s/%s): %s; %s" % (name, label, BASE, rel, what, size(n)))
        w.write("t/%s/llms-full.txt" % t, "\n".join(index) + "\n")

    # need/<id>.md: a best-per-need ranking, as its HTML page ranks it
    for x in st.needs:
        ranked, unranked, last = st.need_rows(x)
        key = x["sort"]

        def render(cap, x=x, ranked=ranked, unranked=unranked, last=last, key=key):
            lines = ["# " + x["title"], "", "> " + flat(x["scope"]), "",
                     "Ranked by `%s`, ascending; the rows with no parsed number follow, listed and not dropped, and the "
                     "self-hosted rows come last. The same list: `%s/api/v1/need/%s`, the MCP tool `need`, or this SQL:"
                     % (key, BASE, x["id"]), "",
                     "```sql", x["sql"], "ORDER BY self_hosted, %s ASC NULLS LAST" % key, "```", ""] + cut_note(cap)
            if ranked:
                lines += ["## Ranked (%s)" % num(len(ranked)), ""]
                for i, r in enumerate(ranked, 1):
                    val = "" if key == "vorder" else money(r[1], "/TB-month" if "tb" in key else "/month")
                    lines.append(entry_md(st, r[0], "%d. %s" % (i, (val + SEP) if val else ""), cap))
                lines.append("")
            if unranked:
                lines += ["## No parsed number (%s)" % num(len(unranked)), ""] + [entry_md(st, r[0], cap=cap) for r in unranked] + [""]
            lines += self_section(st, [r[0] for r in last], cap)
            return "\n".join(lines)
        w.write("need/%s.md" % x["id"], fitted(render))

    # llms-full.txt: the whole corpus when it fits in one file, else the index of the parts
    head = ["# fshy: the corpus in full", "", summary_line(st, notice=False), "", stamp(st, version), ""]
    if total + 8_000 <= BUDGET:
        body = head + reading_rules(st)
        for t, name, _ in st.topics:
            if by_topic[t]:
                body += ["# " + name, ""] + [blocks[r] for r in by_topic[t]]
        w.write("llms-full.txt", "\n".join(body))
    else:
        w.write("llms-full.txt", "\n".join(head + [
            "All %s records are %s in Markdown, more than any context window holds, so the text is split: one file per "
            "topic when the topic fits in %s, else one per verdict group, and a group over that size into balanced "
            "parts. Every record is in exactly one part, in the one order (%s). To answer "
            "a question, read the topic's one-line index, %s/t/<topic>.md, then the provider pages it links, "
            "%s/p/<id>.md; or query the store." % (num(len(order)), size(total), size(BUDGET), ONE_ORDER, BASE, BASE), ""]
            + reading_rules(st) + ["## Parts", ""] + parts_index + [""] + access_lines()))

    # llms.txt: the llmstxt.org index; index.md, the home page's alternate, is the same text
    lines = ["# fshy", "", summary_line(st), "",
             "Every file here is generated from the published records and nothing else. " + stamp(st, version), "",
             "Start with a topic's index: one line per record with its verdict, free tier, identity, card, phone, "
             "evidence, parsed price and summary. Each line links the provider's page in Markdown, `%s/p/<id>.md`, which holds every "
             "record of that provider in full. Every wiki page that has a Markdown version names it in "
             "`<link rel=\"alternate\" type=\"text/markdown\">`. Before quoting a value, read how to read a record "
             "in %s/llms-full.txt." % (BASE, BASE), "",
             "Four rules hold in these files and in the API alike. Card, phone and ID requirements are yes, no or "
             "unknown (1, 0 or NULL), and unknown never means no. A record goes stale on its `stale on` date "
             "(`stale_on`); compare it with today. A price that did not parse is unknown (NULL), not free. A self-hosted "
             "record (`self_hosted`, labelled `%s`) is %s, and every list puts it after every hosted record. %s"
             % (selfhosted.LABEL, selfhosted.MEANING, selfhosted.NOTE), "",
             "To report an error in a record or an offer that is missing, open an issue with the Correction form or "
             "the New offer form: %s/issues/new/choose. A report is a lead: a research lane checks it against the "
             "provider's own pages before a record changes. The code and the records are under the %s licence, "
             "%s/blob/main/LICENSE; a quote from a provider's page stays with its owner." % (REPO, LICENCE, REPO), "",
             "## Topics", ""]
    for t, name, desc, rids, cnt in topic_rows:
        if not rids:  # a topic of the schema with no record yet: no rejected page to name, no full text
            lines.append("- [%s](%s/t/%s.md): %sNo record is in this topic yet." % (name, BASE, t, (desc + " ") if desc else ""))
            continue
        lines.append("- [%s](%s/t/%s.md): %s%s records: %s. Rejected and dead: %s/t/%s/rejected.md; in full: %s/t/%s/llms-full.txt"
                     % (name, BASE, t, (desc + " ") if desc else "", num(len(rids)), counts(cnt), BASE, t, BASE, t))
    lines += ["", "## Best per need", ""]
    lines += ["- [%s](%s/need/%s.md): %s" % (x["title"], BASE, x["id"], flat(x["scope"])) for x in st.needs]
    lines += [""] + access_lines() + [
        "## Optional", "",
        "- [llms-full.txt](%s/llms-full.txt): every record in full, %s, split by topic and verdict group; how to read a record"
        % (BASE, size(total)),
        "- [Graveyard](%s/graveyard/): offers that no longer exist, with the evidence of their end" % BASE,
        "- [Changes](%s/changes/): corrections to earlier claims, newest first" % BASE,
        ""]
    w.write("llms.txt", "\n".join(lines))
    w.write("index.md", "\n".join(lines))
    st.db.close()
    return w.files


def alternate_link(rel):
    """The <link> a wiki page at output path `rel` carries to its Markdown version; '' for a page with none."""
    rel = rel.replace("\\", "/")
    m = re.fullmatch(r"(p|need)/([^/]+)/index\.html|t/([^/]+)(/rejected)?/index\.html|index\.html", rel)
    if not m:
        return ""
    href = ("/%s/%s.md" % m.group(1, 2) if m.group(1) else "/t/%s%s.md" % (m.group(3), m.group(4) or "") if m.group(3)
            else "/index.md")
    return '<link rel="alternate" type="text/markdown" href="%s">' % href
