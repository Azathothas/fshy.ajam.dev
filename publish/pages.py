"""pages.py: HTML for the fshy wiki, written from the context site_gen.emit_data returns.

Pages: / , /t/<topic>/ , /t/<topic>/rejected/ , /p/<eid>/ , /need/<id>/ , /graveyard/ , /changes/ (+ changes.xml),
/compare/ , /search/ , /about/ , 404.html. Plain HTML, one stylesheet, one script; no framework.
Everything shown comes from the public store; nothing here adds a fact.
"""
import collections
import hashlib
import html
import json
import os
import re
from urllib.parse import quote

import llms

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


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def prose(s):
    """Escape, then mark `code` spans and link bare URLs."""
    if s is None:
        return '<span class="na">not published</span>'
    t = e(s)
    t = CODE_RX.sub(lambda m: "<code>%s</code>" % m.group(1), t)
    t = URL_RX.sub(lambda m: '<a href="%s" rel="nofollow noopener">%s</a>' % (m.group(1), m.group(1)), t)
    return t


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


def money(v, suffix):
    if v is None:
        return ""
    return "USD %s%s" % (("%.2f" % v).rstrip("0").rstrip(".") if v < 1000 else "%.0f" % v, suffix)


def anchor(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "other"


def num(n):
    return "{:,}".format(n)


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

    def write(self, rel, body):
        p = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self.n += 1

    def page(self, rel, title, body, desc="", extra_head=""):
        extra_head = llms.alternate_link(rel) + extra_head
        commit = (self.meta.get("commit") or "")[:10]
        here = "/" + rel.replace("\\", "/")[:-len("index.html")] if rel.endswith("index.html") else ""

        def link(href, label):
            cur = ' aria-current="page"' if here == href else (' aria-current="true"' if here.startswith(href) else "")
            return '<a href="%s"%s>%s</a>' % (href, cur, e(label))
        nav = "".join(link("/t/%s/" % t, n) for t, n, _ in TOPICS)
        util = "".join(link(h, n) for h, n in UTIL)
        doc = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title><meta name=\"description\" content=\"%s\">"
            '<link rel="stylesheet" href="%s"><link rel="alternate" type="application/rss+xml" href="/changes.xml" title="fshy changes">'
            "%s</head><body>"
            '<a class="skip" href="#main">Skip to content</a>'
            '<header class="top"><a class="brand" href="/">fshy</a>'
            '<form class="q" action="/search/" role="search"><input id="q" name="q" type="search" autocomplete="off" '
            'placeholder="Search providers, quotas, limits" aria-label="Search the catalogue"><div id="qr" class="qr" hidden></div></form>'
            '<nav class="util" aria-label="Site">%s</nav></header>'
            '<nav class="topics" aria-label="Topics">%s</nav><main id="main">%s</main>'
            '<footer><p>Built from commit <code>%s</code>, data as of %s. Every value links to its source; freshness is computed '
            'in your browser against today. <a href="/about/#read">How to read a record</a> &middot; <a href="/changes.xml">RSS</a> '
            '&middot; <a href="/api/v1/help.txt">API primer</a></p><p>For research and education only; not legal advice. Code and data: <a href="/about/#licence">0BSD</a>. '
            '<a href="/about/#report">Report an error</a>.</p></footer>'
            '<script src="%s" defer></script></body></html>'
        ) % (e(title + " - fshy" if title != "fshy" else "fshy"), e(desc), self.css, extra_head, util, nav, body, e(commit), e(self.meta.get("as_of")),
             self.js)
        self.write(rel, doc)

    # ------------------------------------------------------------------ fragments
    def badges(self, c, with_topic=False):
        """The facts line under an offer: topic, identity, card, phone, binding, evidence rung, freshness, flags."""
        b = []
        if with_topic:
            b.append('<span class="tp">%s</span>' % e(TOPIC_NAME.get(c["topic"], c["topic"])))
        q = c["identity_basis"] == "defaulted"
        b.append('<span class="id"%s>%s%s</span>' % (' title="placeholder, not evidence"' if q else "", e(c["identity_kind"]), "?" if q else ""))
        if c["needs_card"] == 0 and not q:
            b.append('<span class="ok">no card</span>')
        elif c["needs_card"] == 1:
            if c["identity_kind"] != "card":
                b.append('<span class="w">card</span>')
        else:
            b.append('<span class="u" title="card requirement unknown">card?</span>')
        if c["needs_phone"] == 1 and c["identity_kind"] not in ("any-phone", "country-phone"):
            b.append('<span class="w">phone</span>')
        if c["binding"] and c["binding"] != "none":
            b.append('<span class="bd">%s</span>' % e(c["binding"]))
        b.append('<span class="rg">%s</span>' % e(c["confidence"]))
        b.append('<span class="fr" data-basis="%s" data-checked="%s"></span>' % (e(c["verified_basis"]), e(c["checked_on"])))
        if c["duplicate_of"]:
            b.append('<span class="w">duplicate</span>')
        if self.ctx["drift"].get(c["rid"]):
            b.append('<span class="w" title="sibling records disagree">disagrees</span>')
        return "".join(b)

    def verdict(self, c):
        return '<span class="v v-%s">%s</span>' % (e(c["verdict"]), e(VERDICT_LABEL.get(c["verdict"], c["verdict"])))

    @staticmethod
    def lane(cs):
        """Width class for a list's verdict lane, from its longest label: rows align without a page-wide grid."""
        w = max((len(VERDICT_LABEL.get(c["verdict"], c["verdict"])) for c in cs), default=15)
        return "list" + ("" if w > 11 else " lm" if w > 6 else " ls")

    def row_attrs(self, c):
        flags = []
        if c["needs_card"] == 0 and c["identity_basis"] == "stated":
            flags.append("nocard")
        if c["needs_phone"] == 0 and c["identity_basis"] == "stated":
            flags.append("nophone")
        if c["identity_kind"] == "anonymous":
            flags.append("anon")
        if c["confidence"] in ("measured", "documented"):
            flags.append("verified")
        return ' data-f="%s" data-i="%s" data-stale-on="%s"' % (" ".join(flags), e(c["interfaces"] or ""), e(c["stale_on"]))

    def entry(self, c, with_topic=False, price=None, summary=True):
        """One offer row: verdict lane, name, price, summary, facts line. The row carries the filter flags."""
        if price is None:
            price = money(c["usd_per_tb_month"], "/TB-mo") or money(c["usd_month"], "/mo")
        return '<li class="e"%s>%s<a class="n" href="/p/%s/#%s--%s">%s</a>%s%s<p class="f">%s</p></li>' % (
            self.row_attrs(c), self.verdict(c), e(c["eid"]), e(c["topic"]), e(c["slug"]), e(c["provider"]),
            ('<span class="pr">%s</span>' % e(price)) if price else "",
            ('<p class="s">%s</p>' % prose(c["summary"])) if summary and c["summary"] else "", self.badges(c, with_topic))

    def facts(self, c, o, n_ev):
        """The six facts a reader scans first on a record: verdict, price, identity, binding, evidence, freshness."""
        def cell(dt, dd, sub=""):
            return "<div><dt>%s</dt><dd>%s%s</dd></div>" % (dt, dd, ("<small>%s</small>" % sub) if sub else "")
        price = money(c["usd_per_tb_month"], "/TB-mo") or money(c["usd_month"], "/mo")
        q = c["identity_basis"] == "defaulted"
        card = "no card" if c["needs_card"] == 0 and not q else ("card required" if c["needs_card"] == 1 else "card unknown")
        phone = "no phone" if c["needs_phone"] == 0 and not q else ("phone required" if c["needs_phone"] == 1 else "phone unknown")
        bd = c["binding"] or "none"
        return '<dl class="facts">%s</dl>' % "".join((
            cell("Verdict", self.verdict(c), e(self.voc.get(("verdict", c["verdict"]), ""))),
            cell("Parsed price", e(price) if price else '<span class="na">none parsed</span>',
                 "parsed from the record, in USD" if price else ("see Price below" if o.get("price_per_tb_month") else "")),
            cell("Identity", e(c["identity_kind"]) + ("?" if q else ""),
                 ("placeholder, not evidence; " if q else "") + card + ", " + phone),
            cell("Binding limit", e(bd), e(self.voc.get(("binding", bd), ""))),
            cell("Evidence", e(c["confidence"]), "%d source%s; %s" % (n_ev, "" if n_ev == 1 else "s", e(self.voc.get(("confidence", c["confidence"]), "")))),
            cell("Freshness", '<span class="fr" data-basis="%s" data-checked="%s"></span>' % (e(c["verified_basis"]), e(c["checked_on"])),
                 "checked %s (%s); stale on %s" % (e(c["checked_on"]), e(c["verified_basis"]), e(c["stale_on"]))),
        ))

    def chips(self):
        return ('<div class="chips" role="group" aria-label="filters">'
                '<button data-chip="nocard">no card</button><button data-chip="nophone">no phone</button>'
                '<button data-chip="anon">anonymous</button><button data-chip="verified">measured or documented</button>'
                '<button data-chip="fresh">fresh</button>'
                '<input class="ifilter" placeholder="interface: s3, webdav, ssh..." aria-label="interface filter">'
                '<span class="count" aria-live="polite"></span></div>')

    # ------------------------------------------------------------------ pages
    def home(self, by_topic, counts):
        tiles = []
        for t, n, d in TOPICS:
            cs = by_topic.get(t, [])
            u = sum(1 for c in cs if c["grp"] == "usable")
            tiles.append('<a class="tile" href="/t/%s/"><b>%s</b><span class="m">%s usable of %s</span>'
                         '<i class="bar"><i style="width:%d%%"></i></i><span>%s</span></a>' % (
                             t, e(n), num(u), num(len(cs)), round(100 * u / len(cs)) if cs else 0, e(d)))
        needs = "".join('<li><a href="/need/%s/">%s</a></li>' % (e(x["id"]), e(x["title"])) for x in self.ctx["needs"]["needs"])
        db = self.ctx["db"]
        ch = "".join('<li><span class="d">%s</span>%s</li>' % (e((r[0] or "")[:10]), e(r[1]))
                     for r in db.execute("SELECT when_utc, title FROM history ORDER BY when_utc DESC LIMIT 8"))
        legend = "".join('<dt><span class="v v-%s">%s</span></dt><dd>%s</dd>' % (e(v), e(VERDICT_LABEL.get(v, v)), e(m))
                         for v, m in self.ctx["vocab"].get("verdict", []))
        total = sum(len(v) for v in by_topic.values())
        usable = sum(1 for v in by_topic.values() for c in v if c["grp"] == "usable")
        body = (
            '<section class="hero"><h1>Free, nearly free and cheapest-paid capacity</h1>'
            '<p class="lede">Storage, compute, GPU time, inference, egress, crawling, email, databases, DNS, CI and more. '
            'Each record states its quota, the constraint that binds it, the identity it costs (email, phone, card, ID), '
            'its evidence and how fresh that evidence is. Data as of %s.</p>'
            '<ul class="stats"><li class="st"><b>%s</b>offers</li><li class="st usable"><b>%s</b>usable</li>'
            '<li class="st"><b>%s</b>providers</li><li class="st"><b>%d</b>topics</li></ul></section>'
            '<h2>Topics</h2><nav class="tiles compact" aria-label="Topics overview">%s</nav>'
            '<div class="cols"><section><h2>Best per need</h2><ul class="plain">%s</ul></section>'
            '<section><h2>Recent corrections</h2><ul class="plain">%s</ul><p><a href="/changes/">All changes</a></p></section></div>'
            '<section><h2>Reading a verdict</h2><dl class="legend">%s</dl><p><a href="/about/#read">How to read a record</a></p></section>'
        ) % (e(self.meta.get("as_of")), num(total), num(usable), num(len(self.ctx["ents"])), len(TOPICS), "".join(tiles), needs, ch, legend)
        self.page("index.html", "fshy", body, "A searchable catalogue of free and cheap cloud capacity with evidence.")

    def stats(self, cs, groups, href):
        out = []
        for g, lbl in groups:
            k = sum(1 for c in cs if c["grp"] == g)
            if k:
                out.append('<li><a class="st %s" href="%s"><b>%s</b>%s</a></li>' % (g, href(g), num(k), e(lbl.lower())))
        return "".join(out)

    def topic(self, t, cs):
        name = TOPIC_NAME.get(t, t)
        desc = next((d for x, _, d in TOPICS if x == t), "")
        main, rest = [c for c in cs if c["grp"] in ("usable", "trial", "paid")], [c for c in cs if c["grp"] in ("rejected", "dead")]
        parts = ['<h1>%s</h1><p class="lede">%s</p>' % (e(name), e(desc))]
        if not cs:
            parts.append("<p>No record is in this topic yet.</p>")
        sts = self.stats(main, GROUPS[:3], lambda g: "#" + g)
        if rest:
            sts += '<li><a class="st rejected" href="rejected/"><b>%s</b>rejected or dead</a></li>' % num(len(rest))
        parts.append('<ul class="stats">%s</ul>' % sts)
        tn = [x for x in self.ctx["needs"]["needs"] if x.get("topic") == t]
        if tn:
            parts.append('<p class="needs"><b>Best per need</b>%s</p>' % "".join('<a href="/need/%s/">%s</a>' % (e(x["id"]), e(x["title"])) for x in tn))
        jump, secs = [], []
        for g, lbl in GROUPS[:3]:
            gs = [c for c in main if c["grp"] == g]
            if not gs:
                continue
            secs.append('<section class="grp" aria-labelledby="%s"><h2 id="%s">%s <small>%s</small></h2>' % (g, g, e(lbl), num(len(gs))))
            cats = collections.Counter((c["category"] or "other").lower() for c in gs)
            big = [k for k, v in cats.most_common() if v >= 3]
            if len(big) >= 2:
                order = big + ["other"]
                buckets = collections.defaultdict(list)
                for c in gs:
                    k = (c["category"] or "other").lower()
                    buckets[k if k in big else "other"].append(c)
                links = []
                for k in order:
                    if buckets.get(k):
                        hid = "%s-%s" % (g, anchor(k))
                        links.append('<a href="#%s">%s</a>' % (hid, e(k)))
                        secs.append('<h3 id="%s">%s <small>%s</small></h3><ul class="%s">%s</ul>' % (
                            hid, e(k), num(len(buckets[k])), self.lane(buckets[k]), "".join(self.entry(c) for c in buckets[k])))
                jump.append('<p class="jump"><b>%s</b>%s</p>' % (e(lbl), "".join(links)))
            else:
                secs.append('<ul class="%s">%s</ul>' % (self.lane(gs), "".join(self.entry(c) for c in gs)))
            secs.append("</section>")
        if jump:
            parts.append('<nav aria-label="On this page">%s</nav>' % "".join(jump))
        parts.append(self.chips())
        parts.extend(secs)
        self.page("t/%s/index.html" % t, name, "".join(parts), desc)
        rp = ['<p class="crumb"><a href="/">Home</a> / <a href="/t/%s/">%s</a></p><h1>%s: rejected and dead</h1>'
              '<p class="lede">Offers that fail on identity, egress or quota, and services that no longer exist. '
              'Each keeps its evidence: a dead end is a finding.</p>' % (t, e(name), e(name))]
        rjump, rsecs = [], []
        for g, lbl in GROUPS[3:]:
            gs = [c for c in rest if c["grp"] == g]
            if gs:
                by_v = collections.defaultdict(list)
                for c in gs:
                    by_v[c["verdict"]].append(c)
                rsecs.append('<section class="grp" aria-labelledby="%s"><h2 id="%s">%s <small>%s</small></h2>' % (g, g, e(lbl), num(len(gs))))
                for v in sorted(by_v, key=lambda v: VERDICT_LABEL.get(v, v)):
                    rjump.append('<a class="st %s" href="#%s"><b>%s</b>%s</a>' % (g, e(v), num(len(by_v[v])), e(VERDICT_LABEL.get(v, v))))
                    rsecs.append('<h3 id="%s">%s <small>%s</small></h3><ul class="%s">%s</ul>' % (
                        e(v), e(VERDICT_LABEL.get(v, v)), num(len(by_v[v])), self.lane(by_v[v]), "".join(self.entry(c) for c in by_v[v])))
                rsecs.append("</section>")
        if rjump:
            rp.append('<ul class="stats">%s</ul>' % "".join("<li>%s</li>" % x for x in rjump))
        rp.append(self.chips())
        rp.extend(rsecs)
        self.page("t/%s/rejected/index.html" % t, name + ": rejected and dead", "".join(rp))

    def kv(self, label, val):
        return "<tr><th>%s</th><td>%s</td></tr>" % (e(label), val)

    def record_section(self, f, solo=False):
        """One record. solo: the only record of its provider, so it is the page and its name is the h1."""
        c, o = f["card"], f["record"]
        rid = c["rid"]
        ft, pc, rt, eg, ic = (o.get(k) or {} for k in ("free_tier", "per_object_cap", "retention", "egress", "identity_cost"))
        rows = [
            self.kv("Free tier", prose(ft.get("stated")) + ('<div class="sub">unit %s; metered on %s%s</div>' % (
                e(ft.get("unit")), e(ft.get("metered_on")), ("; " + prose(ft.get("notes"))) if ft.get("notes") else ""))),
            self.kv("Price", e(o.get("price_per_tb_month")) if o.get("price_per_tb_month") else '<span class="na">none stated</span>'),
        ]
        lims = o.get("limits") or []
        if lims:
            li = "".join('<li%s><b>%s</b> %s%s</li>' % (' class="binding"' if lm.get("kind") == o.get("binding") else "",
                                                         e(lm.get("kind")), prose(lm.get("value")),
                                                         (' <a class="src" href="%s" rel="nofollow noopener">source</a>' % e(lm["source"]))
                                                         if str(lm.get("source") or "").startswith("http") else "")
                         for lm in lims if isinstance(lm, dict))
            rows.append(self.kv("Limits", "<ul>%s</ul>%s" % (li, ('<div class="sub">%s</div>' % prose(o.get("limits_note"))) if o.get("limits_note") else "")))
        if o.get("binding_note"):
            rows.append(self.kv("Binding", "<b>%s</b> %s" % (e(o.get("binding")), prose(o.get("binding_note")))))
        rows += [
            self.kv("Identity", "<b>%s</b>%s %s" % (e(ic.get("kind")), " (placeholder)" if c["identity_basis"] == "defaulted" else "",
                                                     prose(ic.get("detail")))),
            self.kv("Egress", prose(eg.get("terms")) + "".join('<div class="sub">%s: %s</div>' % (e(k), prose(eg.get(k)))
                                                         for k in ("free_allowance", "price_per_tb") if eg.get(k))),
            self.kv("Per-object cap", prose(pc.get("stated")) + ((" (%s bytes)" % e(pc.get("bytes"))) if pc.get("bytes") else "")),
            self.kv("Retention", prose(rt.get("stated")) + ((" (%s days)" % e(rt.get("days"))) if rt.get("days") else "")),
            self.kv("Interface", e(", ".join(o.get("interface") or [])) + (" " + prose(o.get("interface_detail")) if o.get("interface_detail") else "")
                    + ('<div class="sub">endpoint: %s</div>' % prose(o.get("endpoint")) if o.get("endpoint") else "")),
        ]
        for k, lbl in (("tooling", "Tooling"), ("chaining", "Composes with"), ("reliability_note", "Reliability"), ("notes", "Notes")):
            if o.get(k):
                rows.append(self.kv(lbl, prose(o.get(k))))
        if o.get("confidence_note"):
            rows.append(self.kv("Evidence note", "<b>%s</b> %s" % (e(o.get("confidence")), prose(o.get("confidence_note")))))
        claims = [x for x in f["claims"] if x.get("parse") == "ok" and x.get("num") is not None and x["kind"] != "free-quota"]
        if claims:
            rows.append(self.kv("Parsed numbers", "<ul>%s</ul>" % "".join(
                "<li><code>%s</code> %s %s%s%s%s</li>" % (e(x["path"]), e(x["kind"]), e(x.get("currency") or ""), e(x["num"]),
                                                       (" " + e(x["unit"])) if x.get("unit") else "", (" / " + e(x["per"])) if x.get("per") else "")
                for x in claims[:12])))
        ev = [x for x in (o.get("evidence") or []) if isinstance(x, dict)]
        evh = "".join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(x.get("date")), ('<a href="%s" rel="nofollow noopener">%s</a>' % (e(x["url"]), e(re.sub(r"^https?://", "", x["url"])[:60])))
            if str(x.get("url") or "").startswith("http") else source_text(x.get("url")), prose(x.get("proved")))
            for x in ev)
        extras = o.get("extras")
        exh = ('<details><summary>More fields <small>%d</small></summary><pre class="json">%s</pre></details>' % (
            len(extras), e(json.dumps(extras, ensure_ascii=False, indent=1)))) if extras else ""
        unk = f["unknown"]
        unh = ('<details><summary>Unknown or withheld values <small>%d</small></summary><ul>%s</ul></details>' % (
            len(unk), "".join("<li><code>%s</code> %s</li>" % (e(p), e(cl)) for p, cl in unk[:200]))) if unk else ""
        hs = "".join('<li><a href="/changes/#%s">%s</a> %s</li>' % (e(re.sub(r"[^a-z0-9]+", "-", h["hid"].lower())), e((h["when"] or "")[:10]), e(h["title"]))
                     for h in f["history"])
        dr = "".join('<li>%s: <code>%s</code> says %s, <a href="/r/%s">%s</a> says %s</li>' % (
            e(d["field"]), e(d["subject"]), e(d["a"]), e(d["other"]), e(d["other"]), e(d["b"])) for d in f["drift"])
        url = c["url"] or ""
        meta = []
        if url:
            meta.append('<a href="%s" rel="nofollow noopener">%s</a>' % (e(url), e(re.sub(r"^https?://", "", url)[:60])))
        if c["category"]:
            meta.append("<span>%s</span>" % e(c["category"]))
        meta += ["<code>%s</code>" % e(rid), '<a href="/api/v1/record/%s.json">JSON</a>' % e(rid),
                 '<a href="/compare/?r=%s">compare</a>' % e(rid),
                 '<a href="%s/issues/new?template=correction.yml&amp;record=%s">report an error</a>' % (e(llms.REPO), e(quote(rid)))]
        if solo:
            meta.append('<a href="/api/v1/entity/%s.json">provider JSON</a>' % e(c["eid"]))
            head = "<h1>%s</h1>" % e(c["provider"])
        else:
            head = '<h2><a href="#%s--%s">%s</a></h2><span class="tp">%s</span>' % (
                e(c["topic"]), e(c["slug"]), e(c["provider"]), e(TOPIC_NAME.get(c["topic"], c["topic"])))
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
        topics = sorted({f["card"]["topic"] for f in recs})
        tl = ", ".join('<a href="/t/%s/">%s</a>' % (t, e(TOPIC_NAME.get(t, t))) for t in topics)
        crumb = '<p class="crumb"><a href="/">Home</a>%s</p>' % ((" / " + tl) if len(topics) == 1 else "")
        if len(recs) == 1:
            body = crumb + self.record_section(recs[0], solo=True)
        else:
            toc = "".join(self.entry(f["card"], True, summary=False) for f in recs)
            body = ('%s<h1>%s</h1><p class="lede">%s%s records in %s &middot; <a href="/api/v1/entity/%s.json">JSON</a></p>'
                    '<h2 id="records">Records <small>%d</small></h2><ul class="%s">%s</ul>%s') % (
                crumb, e(ent["name"]), (e(ent["domain"]) + " &middot; ") if ent.get("domain") else "", len(recs), tl, e(eid),
                len(recs), self.lane([f["card"] for f in recs]), toc, "".join(self.record_section(f) for f in recs))
        self.page("p/%s/index.html" % eid, ent["name"], body, "%s: free tier, limits, identity cost and evidence." % ent["name"])

    def need(self, x, cards):
        db = self.ctx["db"]
        rows = db.execute(x["sql"]).fetchall()
        key = x["sort"]
        ranked = [r for r in rows if r[1] is not None]
        unranked = [r for r in rows if r[1] is None]
        ranked.sort(key=lambda r: (r[1], cards[r[0]]["vorder"], r[0]))
        unranked.sort(key=lambda r: (cards[r[0]]["vorder"], r[0]))
        show_val = key not in ("vorder",)
        wt = x.get("topic") is None

        def shown(c, v):
            if not show_val or v is None:
                return None
            if key == "usd":  # coalesce(usd_month, usd_per_tb_month): show the unit the value came from
                return money(c["usd_month"], "/mo") or money(c["usd_per_tb_month"], "/TB-mo")
            return money(v, "/TB-mo" if "tb" in key else "/mo")

        def items(rs):
            return "".join(self.entry(cards[r[0]], wt, shown(cards[r[0]], r[1])) for r in rs)
        body = ('<p class="crumb"><a href="/">Home</a> / <a href="/need/">Best per need</a></p><h1>%s</h1><p class="lede">%s</p>'
                '<p class="needs"><b>Ranked by</b>%s &middot; %s ranked%s</p>%s'
                '<ol class="%s rank">%s</ol>%s'
                '<details><summary>The query</summary><pre>%s\nORDER BY %s ASC NULLS LAST</pre><p>Run it yourself: '
                '<code>/api/v1/need/%s</code>, or the MCP tool <code>need</code>.</p></details>') % (
            e(x["title"]), e(x["scope"]), e(SORT_LABEL.get(key, key)), num(len(ranked)),
            (' &middot; <a href="#unranked">%s with no parsed number</a>' % num(len(unranked))) if unranked else "",
            self.chips(), self.lane([cards[r[0]] for r in ranked]), items(ranked),
            ('<h2 id="unranked">No parsed number <small>%s</small></h2><p class="lede">These match the filter but no price or quantity '
             'could be parsed from their text yet. They are listed, not dropped.</p><ul class="%s">%s</ul>' % (
                num(len(unranked)), self.lane([cards[r[0]] for r in unranked]), items(unranked)))
            if unranked else "", e(x["sql"]), e(key), e(x["id"]))
        self.page("need/%s/index.html" % x["id"], x["title"], body, x["scope"])

    def needs_index(self):
        items = "".join('<a class="tile" href="/need/%s/"><b>%s</b><span>%s</span>%s</a>' % (
            e(x["id"]), e(x["title"]), e(x["scope"]),
            ('<span class="m">%s</span>' % e(TOPIC_NAME.get(x["topic"], x["topic"]))) if x.get("topic") else '<span class="m">all topics</span>')
            for x in self.ctx["needs"]["needs"])
        self.page("need/index.html", "Best per need", '<h1>Best per need</h1><p class="lede">Each list is one query over '
                  'the store, shown under the list. Rows whose number did not parse are listed separately, never dropped.</p>'
                  '<nav class="tiles" aria-label="Needs">%s</nav>' % items)

    def graveyard(self, cards):
        dead = sorted((c for c in cards.values() if c["grp"] == "dead"), key=lambda c: (c["topic"], c["provider"] or ""))
        by_t = collections.defaultdict(list)
        for c in dead:
            by_t[c["topic"]].append(c)
        parts = ['<h1>Graveyard</h1><p class="lede">%s offers that no longer exist, with the evidence of their end. '
                 'Rejected offers that still exist are on each topic\'s <i>rejected</i> page.</p>' % num(len(dead))]
        parts.append('<ul class="stats">%s</ul>' % "".join('<li><a class="st dead" href="#%s"><b>%s</b>%s</a></li>' % (
            t, num(len(by_t[t])), e(TOPIC_NAME[t])) for t, _, _ in TOPICS if by_t.get(t)))
        for t, _, _ in TOPICS:
            if by_t.get(t):
                parts.append('<h2 id="%s">%s <small>%s</small></h2><ul class="list ls">%s</ul>' % (
                    t, e(TOPIC_NAME[t]), num(len(by_t[t])), "".join(self.entry(c) for c in by_t[t])))
        self.page("graveyard/index.html", "Graveyard", "".join(parts))

    def changes(self):
        db = self.ctx["db"]
        items, rss, n_corr = [], [], 0
        for hid, when, status, conf, title, sup, body in db.execute(
                "SELECT hid, when_utc, status, confidence, title, supersedes, body FROM history ORDER BY when_utc DESC, hid"):
            anchor = re.sub(r"[^a-z0-9]+", "-", hid.lower())
            n_corr += status in ("corrected", "superseded")
            links = [r for (r,) in db.execute("SELECT rid FROM history_link WHERE hid=? ORDER BY rid", (hid,))]
            meta = "".join("<span>%s</span>" % e(x) for x in ((when or "")[:10], status, conf) if x)
            items.append('<article class="chg" id="%s"><h3>%s</h3><p class="meta">%s%s</p>%s</article>' % (
                e(anchor), e(title), meta,
                ("<span>records: " + ", ".join('<a href="/r/%s">%s</a>' % (e(r), e(r)) for r in links[:12]) + "</span>") if links else "",
                ('<details><summary>What changed</summary><pre class="md">%s</pre></details>' % e(body)) if body else ""))
            rss.append("<item><title>%s</title><link>%s/changes/#%s</link><guid>%s</guid><pubDate>%s</pubDate></item>" % (
                e(title), e(llms.BASE), e(anchor), e(hid), e(when)))
        # the published ledger says when, which record and field, the rung and the source; the values are on the record
        led = db.execute("SELECT at, rid, path, rung, url FROM ledger ORDER BY at DESC LIMIT 500").fetchall()
        lh = "".join('<tr><td>%s</td><td><a href="/r/%s">%s</a></td><td><code>%s</code></td><td>%s</td><td>%s</td></tr>' % (
            e((a or "")[:10]), e(r), e(r), e(p or ""), e(g or ""), prose(u)) for a, r, p, g, u in led)
        other = len(items) - n_corr
        body = ('<h1>Changes</h1><p class="lede">Dated entries, newest first: corrections to earlier claims and the other '
                'changes of state, and every mechanical amendment from the change ledger. RSS: <a href="/changes.xml">/changes.xml</a>.</p>'
                '<ul class="stats"><li><a class="st" href="#corrections"><b>%s</b>corrections</a></li>%s%s</ul>'
                '<h2 id="corrections">Entries <small>%s</small></h2>%s%s') % (
            num(n_corr), ('<li><a class="st" href="#corrections"><b>%s</b>other entries</a></li>' % num(other)) if other else "",
            ('<li><a class="st" href="#ledger"><b>%s</b>ledger rows</a></li>' % num(len(led))) if lh else "",
            num(len(items)), "".join(items),
            ('<h2 id="ledger">Ledger <small>%s</small></h2><div class="tw"><table class="ev led"><thead><tr><th>date</th><th>record</th><th>field</th>'
             '<th>rung</th><th>source</th></tr></thead><tbody>%s</tbody></table></div>' % (num(len(led)), lh)) if lh else "")
        self.page("changes/index.html", "Changes", body)
        self.write("changes.xml", '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>fshy changes</title>'
                   '<link>%s/changes/</link><description>Corrections to the fshy corpus</description>%s</channel></rss>' % (
                       e(llms.BASE), "".join(rss[:100])))

    def about(self, counts):
        v = self.ctx["vocab"]

        def tbl(d):
            if d == "verdict":
                return "<table class=\"kv\">%s</table>" % "".join('<tr><th><span class="v v-%s">%s</span></th><td><code>%s</code> %s</td></tr>' % (
                    e(t), e(VERDICT_LABEL.get(t, t)), e(t), e(m)) for t, m in v.get(d, []))
            return "<table class=\"kv\">%s</table>" % "".join("<tr><th><code>%s</code></th><td>%s</td></tr>" % (e(t), e(m)) for t, m in v.get(d, []))
        disp = counts.get("dispositions", {})
        man = self.manifest
        body = (
            '<h1>About and API</h1>'
            '<p class="lede">fshy is a catalogue of free, nearly free and cheapest-paid cloud capacity. Each page is generated '
            'from one JSON record per offer; the records are the source, and every number on a page comes from a record.</p>'
            '<p><b>For research and education only.</b> The catalogue records technical facts about third-party services. '
            'It is not legal advice, and it makes no statement about whether a use is permitted. The rules that each '
            'provider publishes for its service apply to its use.</p>'
            '<div class="prose"><h2 id="read">How to read a record</h2><h3>Verdict</h3>%s<h3>Evidence rung</h3>%s<h3>Binding constraint</h3>%s'
            '<h3>Identity</h3>%s%s<p>A question mark after an identity value means the identity kind is a placeholder: card and phone '
            'requirements are unknown, not absent.</p><h3>Freshness</h3><p>Each record has a date it was last checked and a date '
            'its staleness window ends. The fresh or stale label is computed in your browser against today. <i>inherited</i> means the record '
            'was carried from an earlier source and its check date is an upper bound.</p><h3>Unknown values</h3>%s'
            '<h2 id="api">Query it</h2><ul>'
            '<li>Remote MCP for agents: <code>claude mcp add --transport http fshy %s/mcp</code> '
            '(tools: help, search, filter, get, entity, need, sql, worklist).</li>'
            '<li>HTTP: <code>/api/v1/search?q=</code>, <code>/api/v1/records?topic=storage&amp;no_card=1&amp;sort=usd_per_tb_month</code>, '
            '<code>/api/v1/sql?q=SELECT ...</code> (read-only), <code>/api/v1/need/&lt;id&gt;</code>, <code>/api/v1/record/&lt;topic&gt;/&lt;slug&gt;</code>, '
            '<code>/api/v1/entity/&lt;id&gt;.json</code>, <a href="/api/v1/help.txt">/api/v1/help.txt</a>, '
            '<a href="/api/v1/schema.sql">/api/v1/schema.sql</a>, <a href="/api/v1/vocab.json">/api/v1/vocab.json</a>.</li>'
            '<li>The whole store as SQLite: <a href="/data/fshy-public.sqlite.gz">fshy-public.sqlite.gz</a> (%s MB), '
            'sha256 <code>%s</code>.</li></ul>'
            '<h2 id="published">What is published</h2><p>Only technical data: quotas, limits, prices, identity requirements, interfaces, '
            'reliability events and the evidence for each. Process notes, personal details and terms-of-service or legality '
            'commentary are not published. Of %d source values, %d are published as written, %d were rewritten (for example an '
            'archive mirror replaced by its origin URL) and %d are not published; %d belong to %d records about '
            'infrastructure that is not a public offer.</p>'
            '<p>Build: commit <code>%s</code>, data as of %s, %d records, %d providers.</p>'
            '<h2 id="report">Report an error or a missing offer</h2><p>Each record has a <i>report an error</i> link. It '
            'opens the <a href="%s/issues/new?template=correction.yml">Correction form</a> with the record filled in. For an '
            'offer that the catalogue does not have, use the <a href="%s/issues/new?template=new-offer.yml">New offer form</a>. '
            'A report is a lead: a research lane checks it against the pages of the provider before a record changes. The issue '
            'closes when a publish carries the result.</p><p>Do not report a leaked secret, a personal detail or a vulnerability '
            'in a public issue. Read the <a href="%s/security/policy">security policy</a> first.</p>'
            '<h2 id="contribute">Contribute</h2><p>The site, the API, the MCP endpoint and the publish tools are in '
            '<a href="%s">the source repository</a>. A pull request that improves them is welcome: read '
            '<a href="%s/blob/main/CONTRIBUTING.md">CONTRIBUTING.md</a> first. A pull request that changes <code>data/</code> '
            'is not merged, because the export writes <code>data/</code> from the research corpus. Report a correction '
            'with an issue.</p>'
            '<h2 id="licence">Licence</h2><p>The code and the records are under the <a href="%s/blob/main/LICENSE">%s licence</a>. '
            'A record restates public facts in its own words and cites each source by URL. A short quote from the page of a '
            'provider identifies the sentence that proves a value, and stays with its owner. The search box uses MiniSearch '
            '(MIT) and the Worker uses sql.js (MIT).</p></div>'
        ) % (tbl("verdict"), tbl("confidence"), tbl("binding"), tbl("identity_kind"), tbl("identity_basis"), tbl("unknown_class"),
             e(llms.BASE), round(man["public_db"]["gzip_bytes"] / 1e6, 1), e(man["public_db"]["sha256"]),
             counts.get("leaves", 0), disp.get("kept", 0), disp.get("modified", 0), disp.get("withheld", 0), disp.get("excluded", 0),
             counts.get("excluded", 0), e(self.meta.get("commit")), e(self.meta.get("as_of")), counts.get("records", 0), counts.get("entities", 0),
             *([e(llms.REPO)] * 6 + [e(llms.LICENCE)]))
        self.page("about/index.html", "About and API", body)

    def simple(self):
        self.page("search/index.html", "Search", '<h1>Search</h1><div id="search-page"><p class="lede">Type in the box above. '
                  'Names match as you type; press Enter for a full-text search of every published field.</p><div id="sr"></div></div>')
        self.page("compare/index.html", "Compare", '<h1>Compare</h1><p class="lede">Add <code>?r=topic/slug,topic/slug</code> '
                  'to the address, or use the compare link on any record.</p><div id="cmp"></div>')
        self.page("404.html", "Not found", '<h1>Not found</h1><p class="lede">No page lives at this address. Try the search box, '
                  'a topic above, or <a href="/">the home page</a>.</p>')


def render(repo, dist, ctx):
    s = Site(dist, ctx)
    cards = ctx["cards"]
    by_topic = collections.defaultdict(list)
    for c in cards.values():
        by_topic[c["topic"]].append(c)
    for t in by_topic:
        by_topic[t].sort(key=lambda c: (c["vorder"], {"measured": 0, "documented": 1, "reported": 2}.get(c["confidence"], 3), (c["provider"] or "").lower()))
    counts = ctx["manifest"]["counts"]
    s.home(by_topic, counts)
    for t, _, _ in TOPICS:
        s.topic(t, by_topic.get(t, []))
    for eid, ent in ctx["ents"].items():
        members = sorted(ctx["by_eid"][eid], key=lambda c: (c["vorder"], c["rid"]))
        s.entity(eid, ent, [ctx["full"][c["rid"]] for c in members])
    for x in ctx["needs"]["needs"]:
        s.need(x, cards)
    s.needs_index()
    s.graveyard(cards)
    s.changes()
    s.about(counts)
    s.simple()
    base = llms.BASE
    urls = (["/", "/need/", "/graveyard/", "/changes/", "/about/"] + ["/t/%s/" % t for t, _, _ in TOPICS]
            + ["/t/%s/rejected/" % t for t, _, _ in TOPICS] + ["/need/%s/" % x["id"] for x in ctx["needs"]["needs"]]
            + ["/p/%s/" % eid for eid in sorted(ctx["ents"])])
    s.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
            % "".join("<url><loc>%s%s</loc></url>" % (base, u) for u in urls))
    s.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % base)
    return s.n
