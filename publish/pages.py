"""pages.py: HTML for the fshy wiki, written from the context site_gen.emit_data returns.

Pages: / , /t/<topic>/ , /t/<topic>/paid/ , /t/<topic>/rejected/ , /p/<eid>/ (and /p/<eid>/<topic>--<slug>/ for a
provider with many records), /need/<id>/ , /graveyard/ , /changes/ (+ changes.xml), /compare/ , /search/ , /about/ ,
404.html. Plain HTML, one stylesheet, one script; no framework.
Everything shown comes from the public store; nothing here adds a fact. Every list puts the self-hosted records after
every hosted one, under their own label (selfhosted.py).
"""
import collections
import datetime
import email.utils
import hashlib
import html
import json
import os
import re
from urllib.parse import quote

import llms
import selfhosted
from selfhosted import is_sh

# the topics, their names and descriptions, in the order of the topic bar: rules/topics.json is the one list
TOPICS = [(t["id"], t["name"], t["description"]) for t in json.load(open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules", "topics.json"), encoding="utf-8"))["topics"]]
TOPIC_NAME = {t: n for t, n, _ in TOPICS}
GROUPS = [("usable", "Usable"), ("trial", "Trial"), ("paid", "Paid only"), ("rejected", "Rejected"), ("dead", "Dead")]
VERDICT_LABEL = {"qualifies": "★ qualifies", "qualifies-with-caveat": "caveat", "trial-only": "trial",
                 "paid-only": "paid", "fails-identity": "fails: identity", "fails-egress": "fails: egress",
                 "fails-quota": "fails: quota", "dead": "dead"}
SORT_LABEL = {"vorder": "verdict, best first", "usd_per_tb_month": "USD per TB-month, cheapest first",
              "usd_month": "USD per month, cheapest first", "usd": "USD price, cheapest first"}
UTIL = [("/need/", "Best per need"), ("/graveyard/", "Graveyard"), ("/changes/", "Changes"), ("/about/", "About and API")]
URL_RX = re.compile(r"(https?://[^\s<>\"')\]]+)")
CODE_RX = re.compile(r"`([^`]+)`")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "static", "assets")
# the classes of unknown values that are bookkeeping of the projection, not a fact about the offer: a record page
# does not list them (the JSON keeps them)
HIDDEN_UNKNOWN = {"process", "withheld", "partly-held", "private-url", "defaulted", "identity-defaulted", "boilerplate"}


def field_label(path):
    """The words of a JSON path of a record: $.egress.terms -> egress terms, $.limits[0].value -> limits 1 value."""
    p = re.sub(r'^\$\.?', "", path or "")
    p = re.sub(r"\[(\d+)\]", lambda m: " %d" % (int(m.group(1)) + 1), p)
    p = re.sub(r'"([^"]*)"', r"\1", p)
    return re.sub(r"\s+", " ", p.replace(".", " ").replace("_", " ")).strip() or path
# a category written in capitals or as an acronym; the rest is lower case with spaces
CAT_WORDS = {"paas": "PaaS", "iaas": "IaaS", "saas": "SaaS", "cdn": "CDN", "p2p": "P2P", "vps": "VPS", "gpu": "GPU",
             "ml": "ML", "nat": "NAT", "api": "API", "apis": "APIs", "ci": "CI", "ipv6": "IPv6", "ipv4": "IPv4",
             "udp": "UDP", "tcp": "TCP", "hpc": "HPC", "isp": "ISP", "vm": "VM", "vms": "VMs", "dns": "DNS", "kv": "KV",
             "s3": "S3", "ftp": "FTP", "sftp": "SFTP", "ssh": "SSH", "http": "HTTP", "https": "HTTPS", "vpn": "VPN",
             "macos": "macOS", "ckan": "CKAN", "l4": "L4", "ai": "AI", "llm": "LLM", "smtp": "SMTP", "imap": "IMAP",
             "webdav": "WebDAV", "iptv": "IPTV", "sms": "SMS", "rss": "RSS", "url": "URL"}
# a category that says how the research filed the record, not what the offer is
NO_CATEGORY = {"rejected-provider"}
# symbols that quoted provider text carries and a reader does not need: pictographs, emoji, their variation selector
EMOJI_RX = re.compile("[\U0001F000-\U0001FAFF☀-⛿⭐⭕⬛⬜️✅✨❌❎"
                      "❓-❕❗❤➕-➗➰➿]‍?")
# runs of a script that is not Latin, for lang (WCAG 3.1.2): CJK (kana makes it Japanese, Hangul Korean), Cyrillic,
# Arabic, Hebrew and Thai. A run takes the punctuation of its script, and a space before another letter of it.
_KANA = "぀-ヿㇰ-ㇿ"
_HANGUL = "가-힯ᄀ-ᇿ㄰-㆏"
_CJK = _KANA + "㐀-䶿一-鿿豈-﫿" + _HANGUL
_SCRIPTS = [("cjk", _CJK, "　-〿＀-￯"), ("ru", "Ѐ-ӿ", ""), ("ar", "؀-ۿݐ-ݿ", ""),
            ("he", "֐-׿", ""), ("th", "฀-๿", "")]
SCRIPT_RX = re.compile("|".join("(?P<%s>[%s](?:[%s%s]|[ \\-](?=[%s]))*)" % (k, c, c, p, c) for k, c, p in _SCRIPTS))
KANA_RX = re.compile("[%s]" % _KANA)
HANGUL_RX = re.compile("[%s]" % _HANGUL)
TAG_RX = re.compile(r"(<[^>]*>)")
TITLE_ONLY_DATE = re.compile(r"^(Corrected|Decided|Superseded|Observed|Reconciled|Restored) on \d{4}-\d{2}-\d{2}$")


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def lang_of(run, kind):
    if kind != "cjk":
        return kind
    return "ja" if KANA_RX.search(run) else "ko" if HANGUL_RX.search(run) else "zh"


def lang_wrap(h):
    """Mark each run of a non-Latin script in the text of an HTML fragment with its lang, outside the tags."""
    if h.isascii():
        return h
    parts = TAG_RX.split(h)
    for i in range(0, len(parts), 2):
        if not parts[i].isascii():
            parts[i] = SCRIPT_RX.sub(lambda m: '<span lang="%s">%s</span>' % (lang_of(m.group(0), m.lastgroup), m.group(0)), parts[i])
    return "".join(parts)


def text(s):
    """Escape a plain value, drop its pictographs, and mark the language of its runs of another script."""
    return lang_wrap(e(EMOJI_RX.sub("", "" if s is None else str(s))))


def prose(s):
    """Escape, drop pictographs, mark `code` spans, link bare URLs, mark the language of other scripts."""
    if s is None:
        return '<span class="na">not published</span>'
    t = e(EMOJI_RX.sub("", str(s)))
    t = CODE_RX.sub(lambda m: "<code>%s</code>" % m.group(1), t)
    t = URL_RX.sub(lambda m: '<a href="%s" rel="nofollow noopener">%s</a>' % (m.group(1), m.group(1)), t)
    return lang_wrap(t)


def repeat_html(r):
    """The note of a cell whose text an earlier row holds. r is the (kind, label) of llms.repeat_of: the earlier row has
    the same text, or holds the text as a part."""
    return '<span class="na">%s, above</span>' % (("the text of %s" if r[0] == "same" else "part of the text of %s") % e(r[1]))


def prose_once(said, label, value):
    """The HTML of the prose `value` of the row `label`, or None when the row is left out: the value is empty, or an
    earlier row has the same text. When an earlier row holds the value as a part, the cell is the note that names that
    row. `said` is a list of (label, normalised text), one for each value printed in full; this call adds to it."""
    if not isinstance(value, str):
        return prose(value) if value else None
    n = norm_text(value)
    if not n:
        return None
    r = llms.repeat_of(said, n)
    if r is None:
        said.append((label, n))
        return prose(value)
    return None if r[0] == "same" else repeat_html(r)


EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
LEDGER_FEED = 30  # the newest ledger rows that the feed carries, next to the history entries


def rfc822(when):
    """(datetime in UTC, the date as RSS 2.0 wants it, RFC 822) of an ISO date-time, or None when it does not parse."""
    try:
        t = datetime.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    t = (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)).astimezone(datetime.timezone.utc)
    return t, email.utils.format_datetime(t, usegmt=True)


def ledger_field(path):
    """The field of a ledger row in words: the JSON path without its root, 'the whole record' for the root, or 'not
    named' when the row names none."""
    p = str(path or "")
    if p == "$":
        return "the whole record"
    return p[2:] if p.startswith("$.") else (p.lstrip("$") or "not named")


# The title of a ledger row: what the row did, by its op. The published ledger holds no old or new value. A row with no
# op (data of schema_version 2 and older) or an op not named here gets the title of its shape: LEDGER_NO_OP["field"]
# when it names a field, "url" when it names only a source, "none" when it names neither. LEDGER_TITLE and LEDGER_NO_OP
# of site/worker/api.js hold the same words for the worklist changes; test_publish.py checks the copy.
LEDGER_TITLE = {
    "set": "amended; the old and the new value are not published",
    "basis": "amended; the old and the new value are not published",
    "confirm": "confirmed on its source; only the check date changed",
    "dead": "marked dead",
    "undo": "an earlier change undone",
    "undo_skipped": "undo skipped; the value did not change",
    "append_evidence": "evidence row added",
    "drop_evidence": "evidence row removed",
    "relate": "relation to another record added",
    "add_record": "record added",
}
LEDGER_NO_OP = {
    "field": "amended; the old and the new value are not published",
    "url": "evidence row or relation changed; the row does not say how",
    "none": "record changed; the row names no field",
}


def ledger_title(op, path, url):
    """The title of a ledger row, as the Worker's worklist changes gives it."""
    if op in LEDGER_TITLE:
        return LEDGER_TITLE[op]
    return LEDGER_NO_OP["field" if path else "url" if url else "none"]


def ledger_feed(at, rid, path, url, op):
    """(title, description) of a ledger row in the feed. A row that amends a field names the field; the other rows give
    their title."""
    day, title = (at or "")[:10], ledger_title(op, path, url)
    if title == LEDGER_NO_OP["field"]:
        what = ("The whole record %s" % rid) if path == "$" else ("The field %s of the record %s" % (ledger_field(path), rid))
        return ("%s: %s amended" % (rid, ledger_field(path)),
                "%s was amended on %s%s. The old and the new value are not published: open the record to read the "
                "current value." % (what, day, (", source " + url) if url else ""))
    field = (", " + ledger_field(path)) if path else ""
    named = ("" if not path else ", the whole record" if path == "$" else ", the field " + ledger_field(path))
    return ("%s%s: %s" % (rid, field, title),
            "The record %s, on %s%s: %s.%s Open the record to read the current value." % (
                rid, day, named, title, (" URL of the row: %s." % url) if url else ""))


def extra_html(v):
    """The cell of a field that the record holds outside its schema: text as prose, a flag as yes or no, a number as it
    is, and a list or a table as compact JSON."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return e(str(v))
    if isinstance(v, str):
        return prose(v)
    return "<code>%s</code>" % lang_wrap(e(EMOJI_RX.sub("", json.dumps(v, ensure_ascii=False, separators=(",", ": ")))))


def source_text(url):
    """The source cell of an evidence row that has no web URL: a probe, a probe whose output is not published, or
    a source that the record does not publish."""
    if not url:
        return '<span class="na">source not published</span>'
    if url.startswith("probe:"):
        what = url[len("probe:"):].strip()
        if not what or what == "kept-privately":
            return '<span class="na">a probe; its output is not published</span>'
        return 'probe: <code>%s</code>' % e(what)
    return e(url)


money = llms.money  # one rule for a price on every page and in every file


def price_of(c):
    return money(c["usd_per_tb_month"], "/TB-month") or money(c["usd_month"], "/month")


def anchor(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "other"


def hist_anchor(hid):
    """The anchor of a history entry on /changes/: a hash of its id, so the page and the feed carry no id text."""
    return "c-" + hashlib.sha256(str(hid).encode("utf-8")).hexdigest()[:10]


def cat_label(k):
    words = [CAT_WORDS.get(w, w) for w in re.split(r"[-_\s]+", str(k).strip()) if w]
    s = " ".join(words)
    return s[:1].upper() + s[1:] if s[:1].islower() else s


def num(n):
    return "{:,}".format(n)


def norm_text(s):
    s = " ".join(str(s).lower().split())
    return re.sub(r"(?:\.\.\.|…|\.)$", "", s).strip()


# where the reason of a verdict is, field by field, best first: a sub-field is (field, key)
REASON_FIELDS = {"fails-identity": [("identity_cost", "detail"), "binding_note", "notes"],
                 "fails-egress": [("egress", "terms"), "binding_note", "notes"],
                 "fails-quota": ["binding_note", "notes", ("free_tier", "stated")],
                 "dead": ["notes", "reliability_note", "binding_note"]}
# a note this many records share word for word is a template, not the reason of one record
COMMON_NOTE = 10


def reason(o, verdict, common=frozenset()):
    """Why a record is rejected or dead, in one sentence, from the field that holds it for the verdict."""
    short = ""
    for f in REASON_FIELDS.get(verdict, ["binding_note", "notes"]):
        v = (o.get(f[0]) or {}).get(f[1]) if isinstance(f, tuple) and isinstance(o.get(f[0]), dict) else o.get(f) if isinstance(f, str) else None
        if not isinstance(v, str) or not v.strip():
            continue
        t = " ".join(v.split())
        if norm_text(t) in common or t.lower().startswith(("no reliability event", "not recorded", "not stated")):
            continue
        if len(t) < 20 and not short:  # one word, such as "Institution": a later field may say more
            short = t
            continue
        return llms.clip_words(llms.first_sentence(t), 220)
    return short


def source_url(s):
    """The URL at the start of a source value: some values add a date after a comma."""
    m = re.match(r"https?://[^\s,]+", str(s or ""))
    return m.group(0).rstrip(".);") if m else ""


def asset(name):
    """/assets/<name>?v=<content hash>: a changed stylesheet or script gets a new URL, so no browser keeps a stale copy."""
    try:
        with open(os.path.join(ASSETS, name), "rb") as f:
            return "/assets/%s?v=%s" % (name, hashlib.sha256(f.read()).hexdigest()[:10])
    except OSError:
        return "/assets/" + name


class Site:
    def __init__(self, dist, ctx):
        self.dist = dist
        self.ctx = ctx
        self.meta = ctx["meta"]
        self.manifest = ctx["manifest"]
        self.voc = {(d, t): m for d, rows in ctx["vocab"].items() for t, m in rows}
        self.css, self.js = asset("style.css"), asset("app.js")
        self.n = 0
        cards = ctx["cards"]
        self.have = {c["topic"] for c in cards.values()}  # topics with records: the topic bar names only these
        self.labels = llms.labels(cards, TOPIC_NAME)
        self.over = self.manifest.get("record_pages_over") or 0
        self.split = {eid for eid, cs in ctx["by_eid"].items() if self.over and len(cs) > self.over}
        self.urls = []
        notes = collections.Counter(norm_text(f["record"].get(k)) for f in ctx["full"].values()
                                    for k in ("binding_note", "notes", "reliability_note") if isinstance(f["record"].get(k), str))
        self.common = frozenset(t for t, n in notes.items() if n >= COMMON_NOTE)

    def write(self, rel, body):
        p = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        selfhosted.check(rel, body)
        self.n += 1

    def page(self, rel, title, body, desc, extra_head=""):
        extra_head = llms.alternate_link(rel) + extra_head
        here = "/" + rel.replace("\\", "/")[:-len("index.html")] if rel.endswith("index.html") else ""
        if rel.endswith("index.html") and here not in ("/404",):
            self.urls.append(here)

        def link(href, label):
            cur = ' aria-current="page"' if here == href else (' aria-current="true"' if here.startswith(href) else "")
            return '<a href="%s"%s>%s</a>' % (href, cur, e(label))
        nav = "".join(link("/t/%s/" % t, n) for t, n, _ in TOPICS if t in self.have)
        util = "".join(link(h, n) for h, n in UTIL)
        doc = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title>%s"
            '<link rel="stylesheet" href="%s"><link rel="alternate" type="application/rss+xml" href="/changes.xml" title="fshy changes">'
            "%s</head><body>"
            '<a class="skip" href="#main">Skip to content</a>'
            '<header class="top"><a class="brand" href="/">fshy</a>'
            '<form class="q" action="/search/" role="search"><input id="q" name="q" type="search" autocomplete="off" '
            'placeholder="Search providers" aria-label="Search the catalogue"><div id="qr" class="qr" hidden></div></form>'
            '<nav class="util" aria-label="Site">%s</nav></header>'
            '<nav class="topics" aria-label="Topics">%s</nav><main id="main">%s</main>'
            '<footer><p>Data as of %s. Each value links to its source. Your browser compares each check date with today. '
            '<a href="/about/#read">How to read a record</a> &middot; <a href="/changes.xml">RSS</a> &middot; '
            '<a href="/api/v1/help.txt">API primer</a></p><p>For research and education only. It is not legal advice. '
            'Code and data: <a href="/about/#licence">0BSD</a>. <a href="/about/#report">Report an error</a>.</p></footer>'
            '<script src="%s" defer></script></body></html>'
        ) % (e(title + " | fshy" if title != "fshy" else "fshy"),
             ('<meta name="description" content="%s">' % e(desc)) if desc else "", self.css, extra_head, util, nav, body,
             e(self.meta.get("as_of")), self.js)
        self.write(rel, doc)

    # ------------------------------------------------------------------ fragments
    def label(self, c):
        return self.labels.get(c["rid"]) or c["provider"] or c["slug"]

    def href(self, c):
        """The page of a record: its own page for a provider with many records, else its anchor on the provider page."""
        if c["eid"] in self.split:
            return "/p/%s/%s--%s/" % (e(c["eid"]), e(c["topic"]), e(c["slug"]))
        return "/p/%s/#%s--%s" % (e(c["eid"]), e(c["topic"]), e(c["slug"]))

    def fresh(self, c):
        """The freshness item. The build writes the stale date, as 'stale since' when it is on or before the date of
        the data (llms.fresh_word); the script turns it into 'fresh until' or 'stale since' against today. A dead record
        shows its check date only."""
        word = llms.fresh_word(c, self.meta.get("as_of") or "")
        if not word:
            return '<span class="fr done">checked %s</span>' % e(c["checked_on"] or "on an unknown date")
        return '<span class="fr" data-basis="%s" data-checked="%s">%s</span>' % (
            e(c["verified_basis"]), e(c["checked_on"]), e(word))

    def badges(self, c, with_topic=False):
        """The facts line under an offer: topic, free tier, identity, card, phone, limit, evidence, freshness, flags.
        Each label is in the markup, so a reader mode, a text browser and an agent read it."""
        b = []
        if with_topic:
            b.append('<span class="tp">%s</span>' % e(TOPIC_NAME.get(c["topic"], c["topic"])))
        if is_sh(c):  # the lane holds the self-hosted label, so the verdict is a plain word here
            b.append('<span><i>verdict</i> %s</span>' % e(c["verdict"]))
        fw = llms.free_word(c)
        if fw and c["grp"] not in ("paid", "dead"):
            b.append('<span class="%s">%s</span>' % ("w" if fw == "no free tier" else "ok", fw))
        q = c["identity_basis"] != "stated"
        b.append('<span class="id"><i>identity</i> %s%s</span>' % (e(c["identity_kind"]), "?" if q else ""))
        if c["needs_card"] == 0 and not q:
            b.append('<span class="ok">no card</span>')
        elif c["needs_card"] == 1:
            if c["identity_kind"] == "anonymous":
                b.append('<span class="w">payment card</span>')
            elif c["identity_kind"] != "card":
                b.append('<span class="w">card</span>')
        else:
            b.append('<span class="u">card?</span>')
        if c["needs_phone"] == 1 and c["identity_kind"] not in ("any-phone", "country-phone"):
            b.append('<span class="w">phone</span>')
        if c["binding"] and c["binding"] != "none":
            b.append('<span class="bd"><i>limit</i> %s</span>' % e(c["binding"]))
        b.append('<span class="rg"><i>evidence</i> %s</span>' % e(c["confidence"]))
        b.append(self.fresh(c))
        if c["duplicate_of"]:
            b.append('<span class="w">duplicate</span>')
        if self.ctx["drift"].get(c["rid"]):
            b.append('<span class="w">disagrees</span>')
        return "".join(b)

    def verdict(self, c):
        """The pill of a row: the verdict, or for a self-hosted record the plain label of the last resort, never a star."""
        if is_sh(c):
            return selfhosted.PILL
        return '<span class="v v-%s">%s</span>' % (e(c["verdict"]), e(VERDICT_LABEL.get(c["verdict"], c["verdict"])))

    @staticmethod
    def lane(cs):
        """Width class for a list's verdict lane, from its longest label: rows align without a page-wide grid."""
        w = max((len(selfhosted.LABEL if is_sh(c) else VERDICT_LABEL.get(c["verdict"], c["verdict"])) for c in cs), default=15)
        return "list" + ("" if w > 11 else " lm" if w > 6 else " ls")

    def row_attrs(self, c):
        flags = []
        stated = c["identity_basis"] == "stated"
        if c["needs_card"] == 0 and stated:
            flags.append("nocard")
        if c["needs_phone"] == 0 and stated:
            flags.append("nophone")
        if c["identity_kind"] == "anonymous":
            flags.append("anon")
        if c["confidence"] in ("measured", "documented"):
            flags.append("verified")
        if llms.free_word(c) == "free tier":
            flags.append("free")
        if c["verified_basis"] == "live":
            flags.append("live")
        stale = "" if c["grp"] == "dead" or not c["stale_on"] else ' data-stale-on="%s"' % e(c["stale_on"])
        return ' data-f="%s" data-i="%s"%s' % (" ".join(flags), e(c["interfaces"] or ""), stale)

    def line(self, c):
        """The one line under the name: why, for a rejected or dead offer; else the headline of the free tier."""
        o = self.ctx["full"][c["rid"]]["record"]
        if c["grp"] in ("rejected", "dead"):
            r = reason(o, c["verdict"], self.common)
            if r:
                return '<p class="s"><i>why</i> %s</p>' % prose(r[:1].upper() + r[1:])
        ft = o.get("free_tier")
        h = llms.headline(c["summary"], ft.get("stated") if isinstance(ft, dict) else None)
        return ('<p class="s">%s</p>' % prose(h)) if h else ""

    def entry(self, c, with_topic=False, price=None, summary=True, rid_anchor=False):
        """One offer row: verdict lane, name, price, one line, facts line. The row carries the filter flags."""
        if price is None:
            price = price_of(c)
        return '<li class="e"%s%s>%s<a class="n" href="%s">%s</a>%s%s<p class="f">%s</p></li>' % (
            (' id="%s--%s"' % (e(c["topic"]), e(c["slug"]))) if rid_anchor else "",
            self.row_attrs(c), self.verdict(c), self.href(c), text(self.label(c)),
            ('<span class="pr">%s</span>' % e(price)) if price else "",
            self.line(c) if summary else "", self.badges(c, with_topic))

    def facts(self, c, o, n_ev):
        """The facts a reader scans first on a record: the free allowance, then verdict, cost, identity, binding
        limit, evidence and freshness."""
        def cell(dt, dd, sub="", wide=False):
            return '<div%s><dt>%s</dt><dd>%s%s</dd></div>' % (' class="wide"' if wide else "", dt, dd,
                                                            ("<small>%s</small>" % sub) if sub else "")
        price = price_of(c)
        fw = llms.free_word(c)
        if fw == "free tier":
            cost, sub = "free tier", ("paid plans from " + e(price)) if price else ""
        elif price:
            cost, sub = e(price), "parsed from the record, in USD"
        else:
            cost = '<span class="na">%s</span>' % ("no price stated" if fw else "not stated")
            sub = "see Price below" if o.get("price_per_tb_month") else ""
        ft = o.get("free_tier") if isinstance(o.get("free_tier"), dict) else {}
        stated = ft.get("stated")
        first = llms.clip_words(llms.first_sentence(" ".join(str(stated).split())), 300) if stated else ""
        allowance = (prose(first[:1].upper() + first[1:]) if stated
                     else '<span class="na">%s</span>' % ("none" if fw == "no free tier" else "not published"))
        q = c["identity_basis"] != "stated"
        card = "no card" if c["needs_card"] == 0 and not q else ("card required" if c["needs_card"] == 1 else "card unknown")
        phone = "no phone" if c["needs_phone"] == 0 and not q else ("phone required" if c["needs_phone"] == 1 else "phone unknown")
        bd = c["binding"] or "none"
        vals = [lm.get("value") for lm in (o.get("limits") or []) if isinstance(lm, dict) and lm.get("kind") == bd and lm.get("value")]
        bsub = prose(llms.clip_words("; ".join(" ".join(str(v).split()) for v in vals), 240)) if vals else e(self.voc.get(("binding", bd), ""))
        if c["grp"] == "dead" or not c["stale_on"]:
            fsub = "checked %s (%s)" % (e(c["checked_on"]), e(c["verified_basis"]))
        else:
            fsub = "checked %s (%s); stale on %s" % (e(c["checked_on"]), e(c["verified_basis"]), e(c["stale_on"]))
        return '<dl class="facts">%s</dl>' % "".join((
            cell("Free allowance", allowance, wide=True),
            cell("Verdict", self.verdict(c), e(("verdict %s: %s. %s" % (c["verdict"], self.voc.get(("verdict", c["verdict"]), ""),
                                                                    selfhosted.NOTE)) if is_sh(c) else self.voc.get(("verdict", c["verdict"]), ""))),
            cell("Cost", cost, sub),
            cell("Identity", e(c["identity_kind"]) + ("?" if q else ""),
                 ("placeholder, not evidence; " if q else "") + card + ", " + phone),
            cell("Binding limit", e(bd), bsub),
            cell("Evidence", e(c["confidence"]), "%d source%s; %s" % (n_ev, "" if n_ev == 1 else "s", e(self.voc.get(("confidence", c["confidence"]), "")))),
            cell("Freshness", self.fresh(c), fsub),
        ))

    def chips(self):
        # hidden until the script runs: without it the buttons would do nothing
        return ('<div class="chips" role="group" aria-label="filters" hidden>'
                '<button data-chip="free">free tier</button><button data-chip="nocard">no card</button>'
                '<button data-chip="nophone">no phone</button><button data-chip="anon">anonymous</button>'
                '<button data-chip="verified">measured or documented</button><button data-chip="fresh">fresh</button>'
                '<button data-chip="live">checked live</button>'
                '<input class="ifilter" placeholder="interface: s3, webdav, ssh..." aria-label="interface filter">'
                '<button class="clear" hidden>clear</button><span class="count" aria-live="polite"></span></div>')

    def key(self):
        """What each word and mark of a row means, under the filter bar of every list page."""
        vs = "".join('<dt>%s</dt><dd>%s</dd>' % (self.verdict({"verdict": v}), e(m)) for v, m in self.ctx["vocab"].get("verdict", []))
        vs += '<dt>%s</dt><dd>%s. %s</dd>' % (selfhosted.PILL, e(selfhosted.MEANING), e(selfhosted.NOTE))
        rows = [
            ("free tier, no free tier", "the record states a free allowance, or states that it has none"),
            ("identity email", "what a signup asks for. A question mark after it: a placeholder, not read from a source"),
            ("no card, card, card?", "a payment card is not asked, is asked, or the record does not say"),
            ("limit", "the limit that runs out first, for example request-rate or volume-quota"),
            ("evidence", "how the record is backed, strongest first: measured, documented, reported, inferred, unverified"),
            ("fresh until, stale since", "the check is inside its window, or past it, on today's date"),
            ("inherited, checked live", "inherited: the record was carried from an earlier source, and its check date is an upper bound. Checked live: the record was checked against the service. The chip filters on it"),
            ("verdict", "a judgement of the whole offer for the need of its topic. The data holds no number as a cut-off. Read the free allowance and the limits of the record, and decide for your own need"),
            ("duplicate, disagrees", "another record holds the same offer, or a sibling record states another value"),
        ]
        return ('<details class="key"><summary>Key</summary><dl class="legend">%s%s</dl>'
                '<p><a href="/about/#read">How to read a record</a></p></details>') % (
            vs, "".join("<dt>%s</dt><dd>%s</dd>" % (e(a), e(b)) for a, b in rows))

    def filters(self):
        return self.chips() + self.key()

    # ------------------------------------------------------------------ pages
    def home(self, by_topic, counts):
        tiles = []
        for t, n, d in TOPICS:
            cs = by_topic.get(t, [])
            if not cs:
                continue
            u = sum(1 for c in cs if c["grp"] == "usable" and not is_sh(c))
            tiles.append('<a class="tile" href="/t/%s/"><b>%s</b><span class="m">%s usable of %s</span>'
                         '<i class="bar"><i style="width:%d%%"></i></i><span>%s</span></a>' % (
                             t, e(n), num(u), num(len(cs)), round(100 * u / len(cs)), e(d)))
        needs = "".join('<li><a href="/need/%s/">%s</a></li>' % (e(x["id"]), e(x["title"])) for x in self.ctx["needs"]["needs"])
        linked = {h for (h,) in self.ctx["db"].execute("SELECT DISTINCT hid FROM history_link")}
        ch = "".join('<li><span class="d">%s</span><a href="/changes/#%s">%s</a></li>' % (e((w or "")[:10]), hist_anchor(h), e(t))
                     for h, w, t in [x for x in self.history_items() if x[0] in linked][:8])
        legend = "".join('<dt><span class="v v-%s">%s</span></dt><dd>%s</dd>' % (e(v), e(VERDICT_LABEL.get(v, v)), e(m))
                         for v, m in self.ctx["vocab"].get("verdict", []))
        legend += '<dt>%s</dt><dd>%s. %s</dd>' % (selfhosted.PILL, e(selfhosted.MEANING), e(selfhosted.NOTE))
        total = sum(len(v) for v in by_topic.values())
        usable = sum(1 for v in by_topic.values() for c in v if c["grp"] == "usable" and not is_sh(c))
        body = (
            '<section class="hero"><h1>Free, nearly free and cheapest-paid capacity</h1>'
            '<p class="lede">Storage, compute, GPU time, inference, egress, crawling, email, databases, DNS, CI and more. '
            'Each record states its quota and the limit that runs out first. It states what a signup costs: email, phone, '
            'card or ID. It gives its evidence and the date of the last check. Data as of %s.</p>'
            '<ul class="stats"><li class="st"><b>%s</b>offers</li><li class="st usable"><b>%s</b>usable</li>'
            '<li class="st"><b>%s</b>providers</li><li class="st"><b>%d</b>topics</li></ul></section>'
            '<section><h2>Best per need</h2><ul class="plain two">%s</ul></section>'
            '<h2>Topics</h2><nav class="tiles compact" aria-label="Topics overview">%s</nav>'
            '<div class="cols"><section><h2>Recent corrections</h2><ul class="plain">%s</ul><p><a href="/changes/">All changes</a></p></section>'
            '<section><h2>Reading a verdict</h2><dl class="legend">%s</dl><p><a href="/about/#read">How to read a record</a></p></section></div>'
        ) % (e(self.meta.get("as_of")), num(total), num(usable), num(len(self.ctx["ents"])), len(tiles), needs, "".join(tiles), ch, legend)
        self.page("index.html", "fshy", body, "A searchable catalogue of free and cheap cloud capacity with evidence.")

    def stats(self, cs, groups, href):
        out = []
        for g, lbl in groups:
            k = sum(1 for c in cs if c["grp"] == g)
            if k:
                out.append('<li><a class="st %s" href="%s"><b>%s</b>%s</a></li>' % (g, href(g), num(k), e(lbl.lower())))
        return "".join(out)

    def group_section(self, g, lbl, gs, jump):
        """One verdict group of a topic: its heading, and its rows by category when two or more categories are large."""
        out = ['<section class="grp" aria-labelledby="%s"><h2 id="%s">%s <small>%s</small></h2>' % (g, g, e(lbl), num(len(gs)))]
        cats = collections.Counter((c["category"] or "other").lower() for c in gs)
        big = [k for k, v in cats.most_common() if v >= 3 and k not in NO_CATEGORY]
        if len(big) >= 2:
            buckets = collections.defaultdict(list)
            for c in gs:
                k = (c["category"] or "other").lower()
                buckets[k if k in big else "other"].append(c)
            links = []
            for k in big + ["other"]:
                if buckets.get(k):
                    hid = "%s-%s" % (g, anchor(k))
                    links.append('<a href="#%s">%s</a>' % (hid, e(cat_label(k))))
                    out.append('<h3 id="%s">%s <small>%s</small></h3><ul class="%s">%s</ul>' % (
                        hid, e(cat_label(k)), num(len(buckets[k])), self.lane(buckets[k]), "".join(self.entry(c) for c in buckets[k])))
            jump.append('<p class="jump"><b>%s</b>%s</p>' % (e(lbl), "".join(links)))
        else:
            out.append('<ul class="%s">%s</ul>' % (self.lane(gs), "".join(self.entry(c) for c in gs)))
        out.append("</section>")
        return "".join(out)

    def self_section(self, cs, with_topic=False, more=""):
        """The last section of a list page: its self-hosted records, in the order of the page, under their own heading.
        more: HTML that says where the topic's other self-hosted records are."""
        if not cs:
            return ""
        return ('<section class="grp" aria-labelledby="self-hosted"><h2 id="self-hosted">Self-hosted, the last resort '
                '<small>%s</small></h2><p class="lede">%s. %s%s</p><ul class="%s">%s</ul></section>') % (
            num(len(cs)), e(selfhosted.MEANING[:1].upper() + selfhosted.MEANING[1:]), e(selfhosted.NOTE),
            (" " + more) if more else "", self.lane(cs), "".join(self.entry(c, with_topic) for c in cs))

    @staticmethod
    def self_stat(n, href="#self-hosted"):
        return ('<li><a class="st" href="%s"><b>%s</b>self-hosted, listed last</a></li>' % (href, num(n))) if n else ""

    def topic(self, t, cs):
        name = TOPIC_NAME.get(t, t)
        desc = next((d for x, _, d in TOPICS if x == t), "")
        # each page lists its hosted records by group, then its self-hosted records in one last section
        main = [c for c in cs if c["grp"] in ("usable", "trial") and not is_sh(c)]
        paid = [c for c in cs if c["grp"] == "paid" and not is_sh(c)]
        rest = [c for c in cs if c["grp"] in ("rejected", "dead") and not is_sh(c)]
        sh_main = [c for c in cs if c["grp"] in ("usable", "trial") and is_sh(c)]
        sh_paid = [c for c in cs if c["grp"] == "paid" and is_sh(c)]
        sh_rest = [c for c in cs if c["grp"] in ("rejected", "dead") and is_sh(c)]
        n_paid, n_rest = len(paid) + len(sh_paid), len(rest) + len(sh_rest)
        parts = ['<h1>%s</h1><p class="lede">%s</p>' % (e(name), e(desc))]
        # the counts of the topic, as llms.counts() gives them: each group counts its hosted records, and the topic's
        # self-hosted records of any group are counted once
        sts = self.stats(main, GROUPS[:2], lambda g: "#" + g)
        if paid:
            sts += '<li><a class="st paid" href="paid/"><b>%s</b>paid only</a></li>' % num(len(paid))
        if rest:
            sts += '<li><a class="st rejected" href="rejected/"><b>%s</b>rejected or dead</a></li>' % num(len(rest))
        n_sh = len(sh_main) + len(sh_paid) + len(sh_rest)
        sts += self.self_stat(n_sh, "#self-hosted" if sh_main else "paid/#self-hosted" if sh_paid else "rejected/#self-hosted")
        parts.append('<ul class="stats">%s</ul>' % sts)
        elsewhere = [('<a href="paid/#self-hosted">%s paid-only</a>' % num(len(sh_paid))) if sh_paid else "",
                     ('<a href="rejected/#self-hosted">%s rejected or dead</a>' % num(len(sh_rest))) if sh_rest else ""]
        elsewhere = " and ".join(x for x in elsewhere if x)
        more = ("This page lists the usable and trial ones; the %s ones are at the end of their pages." % elsewhere
                if elsewhere else "")
        tn = [x for x in self.ctx["needs"]["needs"] if x.get("topic") == t]
        if tn:
            parts.append('<p class="needs"><b>Best per need</b>%s</p>' % "".join('<a href="/need/%s/">%s</a>' % (e(x["id"]), e(x["title"])) for x in tn))
        jump, secs = [], []
        for g, lbl in GROUPS[:2]:
            gs = [c for c in main if c["grp"] == g]
            if gs:
                secs.append(self.group_section(g, lbl, gs, jump))
        if n_paid:
            # the paid group has its own page: a reader who looks for free capacity does not load it
            secs.append('<section class="grp" aria-labelledby="paid"><h2 id="paid">Paid only <small>%s</small></h2>'
                        '<p>%s hosted offers have no free allowance and are listed for their price, on '
                        '<a href="paid/">%s: paid only</a>%s.</p></section>' % (
                            num(len(paid)), num(len(paid)), e(name),
                            (", with %s self-hosted at its end" % num(len(sh_paid))) if sh_paid else ""))
        secs.append(self.self_section(sh_main, more=more))
        if jump:
            parts.append('<nav aria-label="On this page">%s</nav>' % "".join(jump))
        if main or sh_main:
            parts.append(self.filters())
        parts.extend(secs)
        self.page("t/%s/index.html" % t, name, "".join(parts), desc)
        crumb = '<p class="crumb"><a href="/">Home</a> / <a href="/t/%s/">%s</a></p>' % (t, e(name))
        if n_paid:
            pj = []
            sec = self.group_section("paid", "Paid only", paid, pj) if paid else ""
            self.page("t/%s/paid/index.html" % t, name + ": paid only", crumb + (
                '<h1>%s: paid only</h1><p class="lede">Offers with no free allowance, listed for their price. The usable '
                'and trial offers are on <a href="/t/%s/">%s</a>.</p>%s%s%s%s') % (
                e(name), t, e(name), ('<nav aria-label="On this page">%s</nav>' % "".join(pj)) if pj else "", self.filters(), sec,
                self.self_section(sh_paid)),
                "%s offers of %s with no free allowance, listed for their price." % (num(n_paid), name))
        if not n_rest:
            return
        rp = [crumb + '<h1>%s: rejected and dead</h1><p class="lede">Offers that fail on identity, egress or quota, and '
              'services that no longer exist. Each keeps its evidence, because a dead end is a finding.</p>' % e(name)]
        rjump, rsecs = [], []
        for g, lbl in GROUPS[3:]:
            gs = [c for c in rest if c["grp"] == g]
            if gs:
                by_v = collections.defaultdict(list)
                for c in gs:
                    by_v[c["verdict"]].append(c)
                rsecs.append('<section class="grp" aria-labelledby="%s"><h2 id="%s">%s <small>%s</small></h2>' % (g, g, e(lbl), num(len(gs))))
                for v in sorted(by_v, key=lambda v: VERDICT_LABEL.get(v, v)):
                    rjump.append('<a class="st %s" href="#v-%s"><b>%s</b>%s</a>' % (g, e(v), num(len(by_v[v])), e(VERDICT_LABEL.get(v, v))))
                    rsecs.append('<h3 id="v-%s">%s <small>%s</small></h3><ul class="%s">%s</ul>' % (
                        e(v), e(VERDICT_LABEL.get(v, v)), num(len(by_v[v])), self.lane(by_v[v]), "".join(self.entry(c) for c in by_v[v])))
                rsecs.append("</section>")
        if rjump or sh_rest:
            rp.append('<ul class="stats">%s%s</ul>' % ("".join("<li>%s</li>" % x for x in rjump), self.self_stat(len(sh_rest))))
        rp.append(self.filters())
        rp.extend(rsecs)
        rp.append(self.self_section(sh_rest))
        self.page("t/%s/rejected/index.html" % t, name + ": rejected and dead", "".join(rp),
                  "%s offers of %s that fail on identity, egress or quota, or no longer exist, with the evidence." % (num(n_rest), name))

    def kv(self, label, val):
        return "<tr><th>%s</th><td>%s</td></tr>" % (e(label), val)

    def record_section(self, f, solo=False):
        """One record. solo: the record is the page (the only record of its provider, or a record page of a provider
        with many records), so its name is the h1."""
        c, o = f["card"], f["record"]
        rid = c["rid"]
        ft, pc, rt, eg, ic = (o.get(k) or {} for k in ("free_tier", "per_object_cap", "retention", "egress", "identity_cost"))
        said = []  # (label, normalised text) of the prose rows printed so far

        def once(label, value):
            return prose_once(said, label, value)

        def applies(v):
            return v is not None and norm_text(v) not in ("not applicable", "not recorded", "n/a")
        once("Free tier", ft.get("stated"))
        rows = [
            self.kv("Free tier", prose(ft.get("stated")) + ('<div class="sub">unit %s; metered on %s%s</div>' % (
                e(ft.get("unit")), e(ft.get("metered_on")), ("; " + prose(ft.get("notes"))) if ft.get("notes") else ""))),
            self.kv("Price", text(o.get("price_per_tb_month")) if o.get("price_per_tb_month") else '<span class="na">none stated</span>'),
        ]
        lims = o.get("limits") or []
        if lims:
            li = "".join('<li><b>%s</b>%s %s%s</li>' % (e(lm.get("kind")), ' <span class="na">(binding)</span>' if lm.get("kind") == o.get("binding") else "",
                                                        prose(lm.get("value")),
                                                        (' <a class="src" href="%s" rel="nofollow noopener">source</a>' % e(source_url(lm.get("source"))))
                                                        if source_url(lm.get("source")) else "")
                         for lm in lims if isinstance(lm, dict))
            for lm in lims:
                if isinstance(lm, dict):
                    once("Limits", lm.get("value"))
            note = once("Limits", o.get("limits_note"))
            rows.append(self.kv("Limits", "<ul>%s</ul>%s" % (li, ('<div class="sub">%s</div>' % note) if note else "")))
        bnote = once("Binding", o.get("binding_note"))
        if bnote:
            rows.append(self.kv("Binding", "<b>%s</b> %s" % (e(o.get("binding")), bnote)))
        rows.append(self.kv("Identity", "<b>%s</b>%s %s" % (e(ic.get("kind")), " (placeholder)" if c["identity_basis"] == "defaulted" else (" (inferred, not read)" if c["identity_basis"] == "inferred" else ""),
                                                           prose(ic.get("detail")))))
        rows.append(self.kv("Egress", prose(eg.get("terms")) + "".join('<div class="sub">%s: %s</div>' % (e(k.replace("_", " ")), prose(eg.get(k)))
                                                                     for k in ("free_allowance", "price_per_tb") if eg.get(k))))
        if applies(pc.get("stated")):
            rows.append(self.kv("Per-object cap", prose(pc.get("stated")) + ((" (%s bytes)" % e(pc.get("bytes"))) if pc.get("bytes") else "")))
        if applies(rt.get("stated")):
            rows.append(self.kv("Retention", prose(rt.get("stated")) + ((" (%s days)" % e(rt.get("days"))) if rt.get("days") else "")))
        idet = once("Interface", o.get("interface_detail"))
        rows.append(self.kv("Interface", e(", ".join(o.get("interface") or [])) + (" " + idet if idet else "")
                            + ('<div class="sub">endpoint: %s</div>' % prose(o.get("endpoint")) if o.get("endpoint") else "")))
        for k, lbl in (("tooling", "Tooling"), ("chaining", "Composes with"), ("reliability_note", "Reliability"), ("notes", "Notes")):
            cell = once(lbl, o.get(k))
            if cell:
                rows.append(self.kv(lbl, cell))
        enote = once("Evidence note", o.get("confidence_note"))
        if enote:
            rows.append(self.kv("Evidence note", "<b>%s</b> %s" % (e(o.get("confidence")), enote)))
        claims = [x for x in f["claims"] if x.get("parse") == "ok" and x.get("num") is not None and x["kind"] != "free-quota"]
        if claims:
            rows.append(self.kv("Parsed numbers", "<ul>%s</ul>" % "".join(
                "<li>%s %s%s%s%s</li>" % (e(x["kind"].replace("limit:", "")), e((x.get("currency") or "") + " " if x.get("currency") else ""),
                                          e(("%g" % x["num"]) if isinstance(x["num"], float) else x["num"]),
                                          (" " + e(x["unit"])) if x.get("unit") else "", (" / " + e(x["per"])) if x.get("per") else "")
                for x in claims[:12])))
        ev = [x for x in (o.get("evidence") or []) if isinstance(x, dict)]

        def proved(x):
            p = x.get("proved")
            r = llms.repeat_of(said, norm_text(p)) if isinstance(p, str) and norm_text(p) else None
            return repeat_html(r) if r else prose(p)
        evh = "".join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(x.get("date")), ('<a href="%s" rel="nofollow noopener">%s</a>' % (e(x["url"]), text(re.sub(r"^https?://", "", x["url"])[:60])))
            if str(x.get("url") or "").startswith("http") else source_text(x.get("url")), proved(x))
            for x in ev)
        extras = {k: v for k, v in (o.get("extras") if isinstance(o.get("extras"), dict) else {}).items() if v not in (None, "", [], {})}
        exh = ('<details><summary>More fields <small>%d</small></summary><table class="kv">%s</table></details>' % (
            len(extras), "".join("<tr><th>%s</th><td>%s</td></tr>" % (text(k.replace("_", " ")), extra_html(v))
                                 for k, v in extras.items()))) if extras else ""
        unk = [(p, cl) for p, cl in f["unknown"] if cl not in HIDDEN_UNKNOWN]
        unh = ('<details><summary>Unknown values <small>%d</small></summary><ul>%s</ul></details>' % (
            len(unk), "".join('<li><b>%s</b>: %s</li>' % (e(field_label(p)), e(self.voc.get(("unknown_class", cl), cl)))
                              for p, cl in unk[:200]))) if unk else ""
        hs = "".join('<li><a href="/changes/#%s">%s</a> %s</li>' % (hist_anchor(h["hid"]), e((h["when"] or "")[:10]), e(h["title"]))
                     for h in f["history"])
        dr = "".join('<li>%s: <code>%s</code> says %s, <a href="/r/%s">%s</a> says %s</li>' % (
            e(d["field"]), e(d["subject"]), text(d["a"]), e(d["other"]), e(d["other"]), text(d["b"])) for d in f["drift"])
        url = c["url"] or ""
        meta = []
        if url:
            meta.append('<a href="%s" rel="nofollow noopener">%s</a>' % (e(url), text(re.sub(r"^https?://", "", url)[:60])))
        if c["category"] and c["category"].lower() not in NO_CATEGORY:
            meta.append("<span>%s</span>" % text(cat_label(c["category"])))
        meta += ["<code>%s</code>" % e(rid), '<a href="/api/v1/record/%s.json">JSON</a>' % e(rid),
                 '<a href="/compare/?r=%s">compare</a>' % e(rid),
                 '<a href="%s/issues/new?template=correction.yml&amp;record=%s">report an error</a>' % (e(llms.REPO), e(quote(rid)))]
        if solo:
            meta.append('<a href="/api/v1/entity/%s.json">provider JSON</a>' % e(c["eid"]))
            head = "<h1>%s</h1>" % text(self.label(c))
        else:
            head = '<h2><a href="#%s--%s">%s</a></h2><span class="tp">%s</span>' % (
                e(c["topic"]), e(c["slug"]), text(self.label(c)), e(TOPIC_NAME.get(c["topic"], c["topic"])))
        return (
            '<section class="rec%s" id="%s--%s"%s><div class="rh">%s</div><p class="meta">%s</p>%s%s'
            '<table class="kv">%s</table>'
            '<details%s><summary>Evidence <small>%d</small></summary><table class="ev"><thead><tr><th>date</th><th>source</th>'
            '<th>what it proved</th></tr></thead><tbody>%s</tbody></table></details>'
            '%s%s%s</section>'
        ) % (" solo" if solo else "", e(c["topic"]), e(c["slug"]), self.row_attrs(c), head, "".join(meta),
             ('<div class="warnbox"><p>Sibling records disagree:</p><ul>%s</ul></div>' % dr) if dr else "",
             self.facts(c, o, len(ev)), "".join(rows), " open" if len(ev) <= 3 else "", len(ev), evh, exh, unh,
             ('<%s>Corrections</%s><ul>%s</ul>' % ("h2" if solo else "h3", "h2" if solo else "h3", hs)) if hs else "")

    def entity(self, eid, ent, recs):
        ent = dict(ent, name=llms.shown(ent["name"], ent.get("domain") or eid))
        topics = sorted({f["card"]["topic"] for f in recs})
        tl = ", ".join('<a href="/t/%s/">%s</a>' % (t, e(TOPIC_NAME.get(t, t))) for t in topics)
        crumb = '<p class="crumb"><a href="/">Home</a>%s</p>' % ((" / " + tl) if len(topics) == 1 else "")
        desc = "%s: free tier, limits, identity cost and evidence." % ent["name"]
        if len(recs) == 1:
            body = crumb + self.record_section(recs[0], solo=True)
        elif eid in self.split:
            # a provider with many records: this page lists them, and each record has its own page
            body = ('%s<h1>%s</h1><p class="lede">%s%s records in %s &middot; <a href="/api/v1/entity/%s.json">JSON</a></p>'
                    '<p>Each record has its own page. Open one from the list.</p>%s'
                    '<h2 id="records">Records <small>%d</small></h2><ul class="%s">%s</ul>') % (
                crumb, text(ent["name"]), (e(ent["domain"]) + " &middot; ") if ent.get("domain") else "", len(recs), tl, e(eid),
                self.filters(), len(recs), self.lane([f["card"] for f in recs]),
                "".join(self.entry(f["card"], True, rid_anchor=True) for f in recs))
            pcrumb = '<p class="crumb"><a href="/">Home</a> / <a href="/p/%s/">%s</a></p>' % (e(eid), text(ent["name"]))
            for f in recs:
                c = f["card"]
                self.page("p/%s/%s--%s/index.html" % (eid, c["topic"], c["slug"]), self.label(c),
                          pcrumb + self.record_section(f, solo=True),
                          "%s, %s: free tier, limits, identity cost and evidence." % (self.label(c), TOPIC_NAME.get(c["topic"], c["topic"])))
        else:
            toc = "".join(self.entry(f["card"], True, summary=False) for f in recs)
            body = ('%s<h1>%s</h1><p class="lede">%s%s records in %s &middot; <a href="/api/v1/entity/%s.json">JSON</a></p>'
                    '<h2 id="records">Records <small>%d</small></h2><ul class="%s">%s</ul>%s') % (
                crumb, text(ent["name"]), (e(ent["domain"]) + " &middot; ") if ent.get("domain") else "", len(recs), tl, e(eid),
                len(recs), self.lane([f["card"] for f in recs]), toc, "".join(self.record_section(f) for f in recs))
        self.page("p/%s/index.html" % eid, ent["name"], body, desc)

    def need(self, x, cards):
        key = x["sort"]
        # the parts of the list: the hosted rows ranked, with no number and with the card or phone not stated, then
        # every self-hosted row in the same order, the last resort (llms.need_lists)
        ranked, unranked, unstated, unstated_text, last, last_unstated = llms.need_lists(self.ctx["db"], x, cards)
        show_val = key not in ("vorder",)
        wt = x.get("topic") is None

        def shown(c, v):
            if not show_val or v is None:
                return None
            if key == "usd":  # coalesce(usd_month, usd_per_tb_month): show the unit the value came from
                return money(c["usd_month"], "/month") or money(c["usd_per_tb_month"], "/TB-month")
            return money(v, "/TB-month" if "tb" in key else "/month")

        def items(rs):
            return "".join(self.entry(cards[r[0]], wt, shown(cards[r[0]], r[1])) for r in rs)
        # a list that mixes kinds of offer is split into sections by what the fields say (llms.NEED_SPLITS); each section
        # keeps the order of the list
        sections = llms.need_sections(cards, x, ranked + unranked)
        if sections:
            lists = '<p class="jump"><b>Sections</b>%s</p>%s' % (
                "".join('<a href="#%s">%s <small>%s</small></a>' % (e(k), e(h), num(len(rs))) for k, h, _, rs in sections),
                "".join('<h2 id="%s">%s <small>%s</small></h2><p class="lede">%s</p><ol class="%s rank">%s</ol>' % (
                    e(k), e(h), num(len(rs)), e(t), self.lane([cards[r[0]] for r in rs]), items(rs)) for k, h, t, rs in sections))
        else:
            lists = '<ol class="%s rank">%s</ol>%s' % (
                self.lane([cards[r[0]] for r in ranked]), items(ranked),
                ('<h2 id="unranked">No parsed number <small>%s</small></h2><p class="lede">These match the filter, but no '
                 'price or quantity parsed from their text yet. They are listed, not dropped.</p><ul class="%s">%s</ul>' % (
                    num(len(unranked)), self.lane([cards[r[0]] for r in unranked]), items(unranked))) if unranked else "")
        # a need that asks for no card or no phone: the records whose requirement is not stated follow, in a section of
        # their own, never counted as no and never dropped (llms.need_unstated); the self-hosted ones close the
        # self-hosted section under the same heading
        phone = "needs_phone=0" in x["sql"]

        def unstated_rows(rs):
            out = []
            for r in rs:
                c = cards[r[0]]
                row = self.entry(c, wt, shown(c, r[1]), summary=False)  # no summary: the section is long
                if phone and c["needs_phone"] is None and c["identity_basis"] == "stated":
                    row = row[:-len("</p></li>")] + '<span class="u">phone?</span></p></li>'
                out.append(row)
            return "".join(out)
        if unstated:
            lists += '<h2 id="unstated">%s <small>%s</small></h2><p class="lede">%s</p><ul class="%s">%s</ul>' % (
                e(llms.UNSTATED_HEADING), num(len(unstated)), e(unstated_text), self.lane([cards[r[0]] for r in unstated]),
                unstated_rows(unstated))
        if last or last_unstated:
            lists += ('<h2 id="self-hosted">Self-hosted, the last resort <small>%s</small></h2><p class="lede">%s. %s They '
                      'follow the same order: ranked, then with no parsed number%s.</p>' % (
                          num(len(last) + len(last_unstated)), e(selfhosted.MEANING[:1].upper() + selfhosted.MEANING[1:]),
                          e(selfhosted.NOTE), ", then, under their own heading, with the card or phone not stated" if last_unstated else ""))
            if last:
                lists += '<ul class="%s">%s</ul>' % (self.lane([cards[r[0]] for r in last]), items(last))
            if last_unstated:
                lists += '<h3 id="self-hosted-unstated">%s <small>%s</small></h3><p class="lede">%s</p><ul class="%s">%s</ul>' % (
                    e(llms.UNSTATED_HEADING), num(len(last_unstated)), e(unstated_text),
                    self.lane([cards[r[0]] for r in last_unstated]), unstated_rows(last_unstated))
        body = ('<p class="crumb"><a href="/">Home</a> / <a href="/need/">Best per need</a></p><h1>%s</h1><p class="lede">%s</p>'
                '<p class="needs"><b>Ranked by</b>%s, then the evidence &middot; %s %sranked%s</p>%s%s'
                '<details><summary>The query</summary><pre>%s\nORDER BY self_hosted, %s ASC NULLS LAST</pre><p>Run it yourself: '
                '<a href="/api/v1/need/%s">/api/v1/need/%s</a>, or the MCP tool <code>need</code>.</p></details>') % (
            e(x["title"]), e(x["scope"]), e(SORT_LABEL.get(key, key)), num(len(ranked)), "hosted " if last or last_unstated else "",
            ((' &middot; <a href="#unranked">%s with no parsed number</a>' % num(len(unranked))) if unranked else "") +
            ((' &middot; <a href="#unstated">%s with the card or phone not stated</a>' % num(len(unstated))) if unstated else "") +
            ((' &middot; <a href="#self-hosted">%s self-hosted, listed last</a>' % num(len(last) + len(last_unstated)))
             if last or last_unstated else ""),
            self.filters(), lists, e(x["sql"]), e(key), e(x["id"]), e(x["id"]))
        self.page("need/%s/index.html" % x["id"], x["title"], body, x["scope"])

    def needs_index(self):
        items = "".join('<a class="tile" href="/need/%s/"><b>%s</b><span>%s</span>%s</a>' % (
            e(x["id"]), e(x["title"]), e(x["scope"]),
            ('<span class="m">%s</span>' % e(TOPIC_NAME.get(x["topic"], x["topic"]))) if x.get("topic") else '<span class="m">all topics</span>')
            for x in self.ctx["needs"]["needs"])
        self.page("need/index.html", "Best per need", '<h1>Best per need</h1><p class="lede">Each list is one query over '
                  'the store, and its page shows the query. Rows with no parsed number come after the ranked rows, and '
                  'self-hosted rows come last. No row is dropped.</p><nav class="tiles" aria-label="Needs">%s</nav>' % items,
                  "Ranked lists of free and cheap offers for one need each, with the query of each list.")

    def graveyard(self, cards):
        dead = sorted((c for c in cards.values() if c["grp"] == "dead"), key=lambda c: (c["topic"], c["provider"] or ""))
        by_t = collections.defaultdict(list)
        for c in dead:
            if not is_sh(c):
                by_t[c["topic"]].append(c)
        last = [c for c in dead if is_sh(c)]
        parts = ['<h1>Graveyard</h1><p class="lede">%s offers that no longer exist, with the evidence of their end. '
                 'The rejected offers that still exist are on the <i>rejected</i> page of each topic.</p>' % num(len(dead))]
        parts.append('<ul class="stats">%s%s</ul>' % ("".join('<li><a class="st dead" href="#%s"><b>%s</b>%s</a></li>' % (
            t, num(len(by_t[t])), e(TOPIC_NAME[t])) for t, _, _ in TOPICS if by_t.get(t)), self.self_stat(len(last))))
        for t, _, _ in TOPICS:
            if by_t.get(t):
                parts.append('<h2 id="%s">%s <small>%s</small></h2><ul class="list ls">%s</ul>' % (
                    t, e(TOPIC_NAME[t]), num(len(by_t[t])), "".join(self.entry(c) for c in by_t[t])))
        parts.append(self.self_section(last, with_topic=True))
        self.page("graveyard/index.html", "Graveyard", "".join(parts),
                  "Offers that no longer exist, with the evidence of their end.")

    def history_items(self):
        """(hid, when, title) of the history entries that say something: an entry titled with only its status and date
        takes the records it links as its title, and one that links no record is left out."""
        db = self.ctx["db"]
        out = []
        for hid, when, title in db.execute("SELECT hid, when_utc, title FROM history ORDER BY when_utc DESC, hid"):
            if TITLE_ONLY_DATE.match(title or ""):
                links = [r for (r,) in db.execute("SELECT rid FROM history_link WHERE hid=? ORDER BY rid", (hid,))]
                if not links:
                    continue
                title = "%s: %s%s" % (title, ", ".join(links[:3]), (" and %d more" % (len(links) - 3)) if len(links) > 3 else "")
            out.append((hid, when, title))
        return out

    def changes(self):
        db = self.ctx["db"]
        status = dict(db.execute("SELECT hid, status FROM history"))
        corr, other, rss = [], [], []
        for hid, when, title in self.history_items():
            st = status.get(hid)
            links = [r for (r,) in db.execute("SELECT rid FROM history_link WHERE hid=? ORDER BY rid", (hid,))]
            meta = "".join("<span>%s</span>" % e(x) for x in ((when or "")[:10], st) if x)
            art = '<article class="chg" id="%s"><h3>%s</h3><p class="meta">%s%s</p></article>' % (
                hist_anchor(hid), e(title), meta,
                ("<span>records: " + ", ".join('<a href="/r/%s">%s</a>' % (e(r), e(r)) for r in links[:12]) + "</span>") if links else "")
            (corr if st in ("corrected", "superseded") else other).append(art)
            t = rfc822(when)
            desc = "%s%s" % (st or "changed", (": " + ", ".join(links)) if links else "")
            rss.append((t[0] if t else EPOCH, '<item><title>%s</title><link>%s/changes/#%s</link><guid isPermaLink="false">%s</guid>'
                        '<description>%s</description>%s</item>' % (
                            e(title), e(llms.BASE), hist_anchor(hid), hist_anchor(hid), e(desc), ("<pubDate>%s</pubDate>" % t[1]) if t else "")))
        # the published ledger says when, which record, what the row did, the field, the evidence and the source. It holds
        # no old or new value, so the page says so and sends the reader to the record, where the current value is
        n_led = db.execute("SELECT count(*) FROM ledger").fetchone()[0]
        led = db.execute("SELECT at, rid, path, rung, url, op FROM ledger ORDER BY at DESC LIMIT 500").fetchall()
        lh = "".join('<tr><td>%s</td><td><a href="/r/%s">%s</a></td><td>%s</td><td><code>%s</code></td><td>%s</td><td>%s</td></tr>' % (
            e((a or "")[:10]), e(r), e(r), e(ledger_title(o, p, u)), e(ledger_field(p)), e(g or ""), prose(u))
            for a, r, p, g, u, o in led)
        for a, r, p, g, u, o in led[:LEDGER_FEED]:
            t = rfc822(a)
            if t:
                title, desc = ledger_feed(a, r, p, u, o)
                rss.append((t[0], '<item><title>%s</title><link>%s/r/%s</link><guid isPermaLink="false">%s</guid>'
                            '<description>%s</description><pubDate>%s</pubDate></item>' % (
                                e(title), e(llms.BASE), e(r), hist_anchor("ledger|%s|%s|%s" % (a, r, p)), e(desc), t[1])))
        body = ('<h1>Changes</h1><p class="lede">Dated entries, newest first: the corrections of earlier claims, the other '
                'changes of state, and the newest rows of the change ledger. A ledger row says what changed in which record, '
                'on which date and on which source: a field that was amended, an evidence row that was added or removed, a '
                'relation or a new record. It holds no old or new value, so open the record to read the current one. RSS: '
                '<a href="/changes.xml">/changes.xml</a>.</p>'
                '<ul class="stats"><li><a class="st" href="#corrections"><b>%s</b>corrections</a></li>%s%s</ul>'
                '<h2 id="corrections">Corrections <small>%s</small></h2>%s%s%s') % (
            num(len(corr)), ('<li><a class="st" href="#other"><b>%s</b>other entries</a></li>' % num(len(other))) if other else "",
            ('<li><a class="st" href="#ledger"><b>%s</b>ledger rows</a></li>' % num(n_led)) if lh else "",
            num(len(corr)), "".join(corr),
            ('<h2 id="other">Other entries <small>%s</small></h2>%s' % (num(len(other)), "".join(other))) if other else "",
            ('<h2 id="ledger">Ledger <small>%s of %s</small></h2><p>The newest %s rows. The API gives every row: '
             '<a href="/api/v1/worklist/changes">/api/v1/worklist/changes</a>.</p><div class="tw"><table class="ev led"><thead><tr><th>date</th><th>record</th><th>change</th><th>field</th>'
             '<th>evidence</th><th>source</th></tr></thead><tbody>%s</tbody></table></div>' % (num(len(led)), num(n_led), num(len(led)), lh)) if lh else "")
        self.page("changes/index.html", "Changes", body, "Corrections and other dated changes of the fshy catalogue, newest first.")
        self.write("changes.xml", '<?xml version="1.0" encoding="utf-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
                   '<channel><title>fshy changes</title><link>%s/changes/</link><description>Corrections to the fshy records</description>'
                   '<atom:link href="%s/changes.xml" rel="self" type="application/rss+xml"/>%s</channel></rss>' % (
                       e(llms.BASE), e(llms.BASE), "".join(x for _, x in sorted(rss, key=lambda y: y[0], reverse=True)[:100])))

    def about(self, counts):
        v = self.ctx["vocab"]

        def tbl(d, skip=()):
            if d == "verdict":
                return "<table class=\"kv\">%s%s</table>" % ("".join('<tr><th><span class="v v-%s">%s</span></th><td><code>%s</code> %s</td></tr>' % (
                    e(t), e(VERDICT_LABEL.get(t, t)), e(t), e(m)) for t, m in v.get(d, [])),
                    '<tr><th>%s</th><td><code>self_hosted = 1</code> %s. %s Its row shows this label in place of its verdict.</td></tr>' % (
                        selfhosted.PILL, e(selfhosted.MEANING), e(selfhosted.NOTE)))
            return "<table class=\"kv\">%s</table>" % "".join("<tr><th><code>%s</code></th><td>%s</td></tr>" % (e(t), e(m))
                                                              for t, m in v.get(d, []) if t not in skip)
        disp = counts.get("dispositions", {})
        man = self.manifest
        b = llms.BASE
        api = [("/api/v1/search?q=gpu", "full-text search, names first"),
               ("/api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month", "records that meet conditions, sorted"),
               ("/api/v1/records?topic=storage&iface=s3&free=1", "records with a free allowance (free=1)"),
               ("/api/v1/sql?q=SELECT+rid,verdict+FROM+record+LIMIT+5", "one read-only SQL statement"),
               ("/api/v1/need/", "the best-per-need lists"),
               ("/api/v1/record/compute/oracle-cloud", "one record as JSON"),
               ("/api/v1/entity/oracle.json", "one provider and all its records"),
               ("/api/v1/", "the list of routes"),
               ("/api/v1/help.txt", "the query primer: tables, columns, vocabularies and worked SQL"),
               ("/api/v1/schema.sql", "the schema of the store"), ("/api/v1/vocab.json", "the vocabularies")]
        body = (
            '<h1>About and API</h1>'
            '<p class="lede">fshy is a catalogue of free, nearly free and cheapest-paid cloud capacity. The build writes each '
            'page from one JSON record per offer. The records are the source, and every number on a page comes from a record.</p>'
            '<nav class="needs" aria-label="On this page"><b>On this page</b><a href="#api">Query it</a><a href="#read">How to read a record</a>'
            '<a href="#published">What is published</a><a href="#report">Report an error</a><a href="#licence">Licence</a></nav>'
            '<p><b>For research and education only.</b> The catalogue records technical facts about third-party services. '
            'It is not legal advice, and it makes no statement about whether a use is permitted. The rules that each '
            'provider publishes for its service apply to its use.</p>'
            '<div class="prose"><h2 id="api">Query it</h2><ul>'
            '<li>Remote MCP for agents: <code>claude mcp add --transport http fshy %s/mcp</code>. '
            'The tools are help, search, filter, get, entity, need, sql and worklist. A batch holds at most 5 messages, '
            'and at most 1 of them calls sql.</li>'
            '<li>HTTP, JSON by default and TSV with <code>.tsv</code>:<ul>%s</ul>The API and the MCP tools leave out the records '
            'that are marked as duplicates unless you ask for them. The pages list them, so a page can count a few more '
            'records than the API.</li>'
            '<li>The whole store as SQLite: <a href="/data/fshy-public.sqlite.gz">fshy-public.sqlite.gz</a> (%s MB), '
            'SHA-256 of the file after gunzip: <code>%s</code>.</li>'
            '<li>Files for agents: <a href="/llms.txt">/llms.txt</a>, and a Markdown version of each topic and provider page.</li>'
            '<li>Permalinks: <code>/r/&lt;topic&gt;/&lt;slug&gt;</code> opens the page of a record.</li></ul>'
            '<h2 id="read">How to read a record</h2><h3>Verdict</h3><p>A verdict is a judgement of the whole offer for the need of its topic. The data holds no '
            'number as a cut-off. A quota is too small (<code>fails-quota</code>) or enough by the judgement of the record. '
            'A trial (<code>trial-only</code>) is time-boxed or one-time. Read the free allowance and the limits of the '
            'record, and decide for your own need.</p>%s<h3>Evidence</h3>%s<h3>Binding constraint</h3>%s'
            '<h3>Identity</h3>%s%s<p>A question mark after an identity value means that the identity kind is a placeholder. '
            'Then the card and phone requirements are unknown, not absent.</p><h3>Freshness</h3><p>Each record has the date '
            'of its last check and the date when its staleness window ends. Your browser compares the second date with '
            'today: <i>fresh until</i> or <i>stale since</i>. <i>inherited</i> means that the record was carried from an '
            'earlier source, and its check date is an upper bound.</p><h3>Unknown values</h3>%s'
            '<h2 id="published">What is published</h2><p>Only technical data is published: quotas, limits, prices, identity '
            'requirements, interfaces, reliability events and the evidence for each. Process notes, personal details and '
            'terms-of-service or legality commentary are not published. Of the %s values of the source:</p><ul>'
            '<li>%s are published as written;</li><li>%s are rewritten, for example an archive mirror replaced by its origin URL;</li>'
            '<li>%s are not published;</li><li>%s belong to %s records about infrastructure that is not a public offer.</li></ul>'
            '<p>Data as of %s, from source commit <code>%s</code>: %s records, %s providers.</p>'
            '<h2 id="report">Report an error or a missing offer</h2><p>Each record has a <i>report an error</i> link. It '
            'opens the <a href="%s/issues/new?template=correction.yml">Correction form</a> with the record filled in. For an '
            'offer that the catalogue does not have, use the <a href="%s/issues/new?template=new-offer.yml">New offer form</a>. '
            'A report is checked against the pages of the provider before a record changes. The issue '
            'closes when a publish carries the result.</p><p>Do not report a leaked secret, a personal detail or a vulnerability '
            'in a public issue. Read the <a href="%s/security/policy">security policy</a> first.</p>'
            '<h2 id="contribute">Contribute</h2><p>The site, the API, the MCP endpoint and the publish tools are in '
            '<a href="%s">the source repository</a>. A pull request that improves them is welcome: read '
            '<a href="%s/blob/main/CONTRIBUTING.md">CONTRIBUTING.md</a> first. A pull request that changes <code>data/</code> '
            'is not merged, because <code>data/</code> is generated by the export and never edited by hand. Report a correction '
            'with an issue.</p>'
            '<h2 id="licence">Licence</h2><p>The code and the records are under the <a href="%s/blob/main/LICENSE">%s licence</a>. '
            'A record restates public facts in its own words and cites each source by URL. A short quote from the page of a '
            'provider identifies the sentence that proves a value, and stays with its owner. The search box uses MiniSearch '
            '(MIT) and the Worker uses sql.js (MIT).</p></div>'
        ) % (e(b), "".join('<li><a href="%s">%s</a>: %s</li>' % (e(u), e(u), e(w)) for u, w in api),
             round(man["public_db"]["gzip_bytes"] / 1e6, 1), e(man["public_db"]["sha256"]),
             tbl("verdict"), tbl("confidence"), tbl("binding"), tbl("identity_kind"), tbl("identity_basis"),
             tbl("unknown_class", HIDDEN_UNKNOWN),
             num(counts.get("leaves", 0)), num(disp.get("kept", 0)), num(disp.get("modified", 0)), num(disp.get("withheld", 0)),
             num(disp.get("excluded", 0)), num(counts.get("excluded", 0)),
             e(self.meta.get("as_of")), e((self.meta.get("source_commit") or "")[:12]), num(counts.get("records", 0)),
             num(counts.get("entities", 0)), *([e(llms.REPO)] * 6 + [e(llms.LICENCE)]))
        self.page("about/index.html", "About and API", body,
                  "How to query fshy over MCP and HTTP, how to read a record, what is published, and how to report an error.")

    def simple(self):
        self.page("search/index.html", "Search", '<h1>Search</h1><div id="search-page"><p class="lede">Type in the box above. '
                  'Names match as you type. Press Enter to search every published field. A word matches anywhere in a '
                  'record, so <q>no card</q> also finds a record that says a card is needed: for offers with no card, no '
                  'phone or no account, use the lists of <a href="/need/">Best per need</a> or the filters of a topic '
                  'page.</p><div id="sr"><noscript>'
                  '<p>This page needs JavaScript. Without it, ask the API: <a href="/api/v1/search?q=gpu">/api/v1/search?q=gpu</a> '
                  '(put your words after <code>q=</code>), or read <a href="/llms.txt">/llms.txt</a> and the topic pages.</p>'
                  '</noscript></div></div>', "Search the names and the text of every fshy record.")
        self.page("compare/index.html", "Compare", '<h1>Compare</h1><p class="lede">Add <code>?r=topic/slug,topic/slug</code> '
                  'to the address, or use the compare link on any record, then add records below the table.</p><div id="cmp">'
                  '<noscript><p>This page needs JavaScript. Without it, read each record as JSON: '
                  '<a href="/api/v1/record/compute/oracle-cloud">/api/v1/record/compute/oracle-cloud</a> '
                  '(put the topic and the slug of a record after <code>/record/</code>).</p></noscript></div>',
                  "Compare records of fshy side by side.")
        self.page("404.html", "Not found", '<h1>Not found</h1><p class="lede">No page lives at this address. Try the search box, '
                  'a topic above, or <a href="/">the home page</a>.</p>', "This page does not exist.")


def render(repo, dist, ctx):
    s = Site(dist, ctx)
    cards = ctx["cards"]
    by_topic = collections.defaultdict(list)
    for c in cards.values():
        by_topic[c["topic"]].append(c)
    for t in by_topic:
        by_topic[t].sort(key=lambda c: (is_sh(c), c["vorder"], llms.RUNG.get(c["confidence"], len(llms.RUNG)),
                                        (c["provider"] or "").lower(), c["rid"]))
    counts = ctx["manifest"]["counts"]
    s.home(by_topic, counts)
    for t, _, _ in TOPICS:
        if t in by_topic:  # a topic with no record yet has no page, no sitemap line and no Markdown file
            s.topic(t, by_topic[t])
    for eid, ent in ctx["ents"].items():
        members = sorted(ctx["by_eid"][eid], key=lambda c: (is_sh(c), c["vorder"], c["rid"]))
        s.entity(eid, ent, [ctx["full"][c["rid"]] for c in members])
    for x in ctx["needs"]["needs"]:
        s.need(x, cards)
    s.needs_index()
    s.graveyard(cards)
    s.changes()
    s.about(counts)
    s.simple()
    base = llms.BASE
    skip = {"/search/", "/compare/"}  # pages that show nothing without a query
    s.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
            % "".join("<url><loc>%s%s</loc></url>" % (base, u) for u in sorted(set(s.urls) - skip, key=lambda u: (u.count("/"), u))))
    s.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % base)
    s.write(".well-known/security.txt", security_txt(s.meta.get("as_of"), base))
    return s.n


def security_txt(as_of, base):
    """RFC 9116: where to report a vulnerability, which the about page asks a reader to read first. It expires a year after
    the data date, so a site that stops being built says that its file is out of date; the build reads no clock."""
    try:
        exp = datetime.date.fromisoformat(str(as_of)[:10]) + datetime.timedelta(days=365)
    except ValueError:
        exp = datetime.date(2000, 1, 1)
    return ("Contact: %s/security/advisories/new\nExpires: %sT00:00:00Z\nPolicy: %s/security/policy\n"
            "Preferred-Languages: en\nCanonical: %s/.well-known/security.txt\n" % (llms.REPO, exp.isoformat(), llms.REPO, base))
