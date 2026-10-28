"""pages.py: HTML for the fshy wiki, written from the context site_gen.emit_data returns.

Pages: / , /t/<topic>/ , /t/<topic>/rejected/ , /p/<eid>/ , /need/<id>/ , /graveyard/ , /changes/ (+ changes.xml),
/compare/ , /search/ , /about/ , 404.html. Plain HTML, one stylesheet, one script; no framework.
Everything shown comes from the public store; nothing here adds a fact.
"""
import collections
import html
import json
import os
import re

TOPICS = [
    ("storage", "Storage", "Where bytes can live: object storage, drives, registries, academic repositories, hosts used as storage."),
    ("compute", "Compute", "Machines, sandboxes, notebooks, GPU time, platform hosts and how long each runs before it is reaped."),
    ("inference", "Inference", "Model APIs that answer a completion request, keyless or behind a free key."),
    ("egress", "Egress and tunnels", "Ways to get traffic out or a service in: tunnels, relays, IPv6 brokers, UDP forwards."),
    ("ip-proxy", "IP and proxies", "Exit addresses: proxy lists, VPN exits, address sources and what the upstream sees."),
    ("crawler-scraper", "Crawling", "Crawl, search, reader and unblocker APIs for reading the web at scale."),
    ("debrid", "Debrid", "Multi-hosters, premium-link generators, usenet and retrieval services."),
    ("netdisk-pan", "Netdisk and pan", "Pan drives and public AList/OpenList instances, and whether they mount."),
    ("databases-kv", "Databases and KV", "Hosted databases, vector stores and key-value stores."),
    ("email", "Email", "Sending, receiving, forwarding and inbox APIs."),
    ("domains-dns", "Domains and DNS", "Managed DNS, free domains and certificate authorities."),
    ("ci-cd-runners", "CI runners", "Hosted CI runners and registries, and what they will run."),
    ("coding-subs", "Coding subscriptions", "Coding-agent subscriptions and their price per unit of work."),
]
TOPIC_NAME = {t: n for t, n, _ in TOPICS}
GROUPS = [("usable", "Usable"), ("trial", "Trial"), ("paid", "Paid only"), ("rejected", "Rejected"), ("dead", "Dead")]
VERDICT_LABEL = {"qualifies": "★ qualifies", "qualifies-with-caveat": "caveat", "trial-only": "trial",
                 "paid-only": "paid", "fails-identity": "fails: identity", "fails-egress": "fails: egress",
                 "fails-quota": "fails: quota", "dead": "dead"}
RUNG = {"measured": "M", "documented": "D", "reported": "R", "inferred": "I", "unverified": "U"}
URL_RX = re.compile(r"(https?://[^\s<>\"')\]]+)")
CODE_RX = re.compile(r"`([^`]+)`")


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


def money(v, suffix):
    if v is None:
        return ""
    return "USD %s%s" % (("%.2f" % v).rstrip("0").rstrip(".") if v < 1000 else "%.0f" % v, suffix)


class Site:
    def __init__(self, dist, ctx):
        self.dist = dist
        self.ctx = ctx
        self.meta = ctx["meta"]
        self.manifest = ctx["manifest"]
        self.n = 0

    def write(self, rel, body):
        p = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        self.n += 1

    def page(self, rel, title, body, desc="", extra_head=""):
        commit = (self.meta.get("commit") or "")[:10]
        nav = "".join('<a href="/t/%s/">%s</a>' % (t, e(n)) for t, n, _ in TOPICS)
        doc = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title><meta name=\"description\" content=\"%s\">"
            '<link rel="stylesheet" href="/assets/style.css"><link rel="alternate" type="application/rss+xml" href="/changes.xml" title="fshy changes">'
            "%s</head><body>"
            '<header class="top"><a class="brand" href="/">fshy</a>'
            '<form class="q" action="/search/" role="search"><input id="q" name="q" type="search" autocomplete="off" '
            'placeholder="Search providers, quotas, limits  ( / )" aria-label="Search"><div id="qr" class="qr" hidden></div></form>'
            '<nav class="util"><a href="/need/">Best per need</a><a href="/graveyard/">Graveyard</a><a href="/changes/">Changes</a>'
            '<a href="/about/">About and API</a></nav></header>'
            '<nav class="topics">%s</nav><main>%s</main>'
            '<footer>Built from commit <code>%s</code>, data as of %s. Every value links to its source; '
            'freshness badges are computed in your browser. <a href="/about/">How to read this</a>. '
            'For research and education only; not legal advice.</footer>'
            '<script src="/assets/app.js" defer></script></body></html>'
        ) % (e(title + " - fshy" if title != "fshy" else "fshy"), e(desc), extra_head, nav, body, e(commit), e(self.meta.get("as_of")))
        self.write(rel, doc)

    # ------------------------------------------------------------------ fragments
    def badges(self, c, with_topic=False):
        b = []
        if with_topic:
            b.append('<span class="b t">%s</span>' % e(TOPIC_NAME.get(c["topic"], c["topic"])))
        b.append('<span class="b v-%s" title="verdict">%s</span>' % (e(c["verdict"]), e(VERDICT_LABEL.get(c["verdict"], c["verdict"]))))
        q = "?" if c["identity_basis"] == "defaulted" else ""
        b.append('<span class="b id" title="identity required%s">%s%s</span>' % (
            " (placeholder, not evidence)" if q else "", e(c["identity_kind"]), q))
        if c["needs_card"] == 0 and c["identity_basis"] == "stated":
            b.append('<span class="b ok" title="no payment card">no card</span>')
        elif c["needs_card"] == 1:
            b.append('<span class="b warn">card</span>')
        else:
            b.append('<span class="b unk" title="card requirement unknown">card?</span>')
        if c["needs_phone"] == 1:
            b.append('<span class="b warn">phone</span>')
        b.append('<span class="b r r-%s" title="evidence rung: %s">%s</span>' % (
            e(c["confidence"]), e(c["confidence"]), RUNG.get(c["confidence"], "?")))
        b.append('<span class="b fr" data-stale-on="%s" data-basis="%s" data-checked="%s"></span>' % (
            e(c["stale_on"]), e(c["verified_basis"]), e(c["checked_on"])))
        if c["binding"] and c["binding"] != "none":
            b.append('<span class="b bind" title="binding constraint">%s</span>' % e(c["binding"]))
        if c["duplicate_of"]:
            b.append('<span class="b warn">duplicate</span>')
        if self.ctx["drift"].get(c["rid"]):
            b.append('<span class="b warn" title="sibling records disagree">disagrees</span>')
        return "".join(b)

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

    def entry(self, c, with_topic=False):
        price = money(c["usd_per_tb_month"], "/TB-mo") or money(c["usd_month"], "/mo")
        return ('<li class="e"%s><a class="n" href="/p/%s/#%s--%s">%s</a> %s%s<div class="s">%s</div></li>' % (
            self.row_attrs(c), e(c["eid"]), e(c["topic"]), e(c["slug"]), e(c["provider"]),
            self.badges(c, with_topic), (' <span class="price">%s</span>' % e(price)) if price else "",
            prose(c["summary"]) if c["summary"] else ""))

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
            tiles.append('<a class="tile" href="/t/%s/"><b>%s</b><span>%d usable of %d</span><p>%s</p></a>' % (t, e(n), u, len(cs), e(d)))
        needs = "".join('<li><a href="/need/%s/">%s</a></li>' % (e(x["id"]), e(x["title"])) for x in self.ctx["needs"]["needs"])
        db = self.ctx["db"]
        ch = "".join('<li><span class="d">%s</span> %s</li>' % (e((r[0] or "")[:10]), e(r[1]))
                     for r in db.execute("SELECT when_utc, title FROM history ORDER BY when_utc DESC LIMIT 8"))
        total = sum(len(v) for v in by_topic.values())
        body = (
            '<section class="hero"><h1>Free, nearly free and cheapest-paid capacity</h1>'
            '<p>%d offers from %d providers across %d topics: storage, compute, GPU time, inference, egress, crawling, '
            'email, databases, DNS, CI and more. Each record states its quota, the constraint that binds it, the identity '
            'it costs (email, phone, card, ID), its evidence and how fresh that evidence is.</p></section>'
            '<section class="tiles">%s</section>'
            '<section class="cols"><div><h2>Best per need</h2><ul class="plain">%s</ul></div>'
            '<div><h2>Recent corrections</h2><ul class="plain">%s</ul><p><a href="/changes/">All changes</a></p></div></section>'
        ) % (total, len(self.ctx["ents"]), len(TOPICS), "".join(tiles), needs, ch)
        self.page("index.html", "fshy", body, "A searchable catalogue of free and cheap cloud capacity with evidence.")

    def topic(self, t, cs):
        name = TOPIC_NAME.get(t, t)
        desc = next((d for x, _, d in TOPICS if x == t), "")
        main, rest = [c for c in cs if c["grp"] in ("usable", "trial", "paid")], [c for c in cs if c["grp"] in ("rejected", "dead")]
        parts = ['<h1>%s</h1><p class="lede">%s</p>' % (e(name), e(desc))]
        parts.append('<p class="stats">%d records: %s. <a href="rejected/">%d rejected or dead</a>.</p>' % (
            len(cs), ", ".join("%d %s" % (sum(1 for c in cs if c["grp"] == g), lbl.lower()) for g, lbl in GROUPS[:3]), len(rest)))
        tn = [x for x in self.ctx["needs"]["needs"] if x.get("topic") == t]
        if tn:
            parts.append('<p class="needs">Best per need: %s</p>' % ", ".join('<a href="/need/%s/">%s</a>' % (e(x["id"]), e(x["title"])) for x in tn))
        parts.append(self.chips())
        for g, lbl in GROUPS[:3]:
            gs = [c for c in main if c["grp"] == g]
            if not gs:
                continue
            parts.append('<section class="grp"><h2 id="%s">%s <small>%d</small></h2>' % (g, e(lbl), len(gs)))
            cats = collections.Counter((c["category"] or "other").lower() for c in gs)
            big = [k for k, v in cats.most_common() if v >= 3]
            if len(big) >= 2:
                order = big + ["other"]
                buckets = collections.defaultdict(list)
                for c in gs:
                    k = (c["category"] or "other").lower()
                    buckets[k if k in big else "other"].append(c)
                for k in order:
                    if buckets.get(k):
                        parts.append('<h3>%s <small>%d</small></h3><ul class="list">%s</ul>' % (
                            e(k), len(buckets[k]), "".join(self.entry(c) for c in buckets[k])))
            else:
                parts.append('<ul class="list">%s</ul>' % "".join(self.entry(c) for c in gs))
            parts.append("</section>")
        self.page("t/%s/index.html" % t, name, "".join(parts), desc)
        rp = ['<h1>%s: rejected and dead</h1><p class="lede">Offers that fail on identity, egress or quota, and services '
              'that no longer exist. Each keeps its evidence: a dead end is a finding.</p>' % e(name), self.chips()]
        for g, lbl in GROUPS[3:]:
            gs = [c for c in rest if c["grp"] == g]
            if gs:
                by_v = collections.defaultdict(list)
                for c in gs:
                    by_v[c["verdict"]].append(c)
                rp.append('<section class="grp"><h2 id="%s">%s <small>%d</small></h2>' % (g, e(lbl), len(gs)))
                for v in sorted(by_v, key=lambda v: VERDICT_LABEL.get(v, v)):
                    rp.append('<h3>%s <small>%d</small></h3><ul class="list">%s</ul>' % (
                        e(VERDICT_LABEL.get(v, v)), len(by_v[v]), "".join(self.entry(c) for c in by_v[v])))
                rp.append("</section>")
        self.page("t/%s/rejected/index.html" % t, name + ": rejected and dead", "".join(rp))

    def kv(self, label, val):
        return "<tr><th>%s</th><td>%s</td></tr>" % (e(label), val)

    def record_section(self, f):
        c, o = f["card"], f["record"]
        rid = c["rid"]
        ft, pc, rt, eg, ic = (o.get(k) or {} for k in ("free_tier", "per_object_cap", "retention", "egress", "identity_cost"))
        rows = [
            self.kv("Free tier", prose(ft.get("stated")) + ('<div class="sub">unit %s; metered on %s%s</div>' % (
                e(ft.get("unit")), e(ft.get("metered_on")), ("; " + prose(ft.get("notes"))) if ft.get("notes") else ""))),
            self.kv("Price", e(o.get("price_per_tb_month")) if o.get("price_per_tb_month") else '<span class="na">none stated</span>'),
            self.kv("Per-object cap", prose(pc.get("stated")) + ((" (%s bytes)" % e(pc.get("bytes"))) if pc.get("bytes") else "")),
            self.kv("Retention", prose(rt.get("stated")) + ((" (%s days)" % e(rt.get("days"))) if rt.get("days") else "")),
            self.kv("Egress", prose(eg.get("terms")) + "".join('<div class="sub">%s: %s</div>' % (e(k), prose(eg.get(k)))
                                                         for k in ("free_allowance", "price_per_tb") if eg.get(k))),
            self.kv("Identity", "<b>%s</b>%s %s" % (e(ic.get("kind")), " (placeholder)" if c["identity_basis"] == "defaulted" else "",
                                                     prose(ic.get("detail")))),
        ]
        lims = o.get("limits") or []
        if lims:
            li = "".join('<li%s><b>%s</b> %s%s</li>' % (' class="binding"' if lm.get("kind") == o.get("binding") else "",
                                                         e(lm.get("kind")), prose(lm.get("value")),
                                                         (' <a class="src" href="%s" rel="nofollow noopener">source</a>' % e(lm["source"]))
                                                         if str(lm.get("source") or "").startswith("http") else "")
                         for lm in lims if isinstance(lm, dict))
            rows.append(self.kv("Limits", "<ul>%s</ul>%s" % (li, ('<div class="sub">%s</div>' % prose(o.get("limits_note"))) if o.get("limits_note") else "")))
        rows.append(self.kv("Binding", "<b>%s</b> %s" % (e(o.get("binding")), prose(o.get("binding_note")) if o.get("binding_note") else "")))
        rows.append(self.kv("Interface", e(", ".join(o.get("interface") or [])) + (" " + prose(o.get("interface_detail")) if o.get("interface_detail") else "")
                            + ('<div class="sub">endpoint: %s</div>' % prose(o.get("endpoint")) if o.get("endpoint") else "")))
        for k, lbl in (("tooling", "Tooling"), ("chaining", "Composes with"), ("reliability_note", "Reliability"), ("notes", "Notes")):
            if o.get(k):
                rows.append(self.kv(lbl, prose(o.get(k))))
        rows.append(self.kv("Evidence rung", "<b>%s</b> %s" % (e(o.get("confidence")), prose(o.get("confidence_note")) if o.get("confidence_note") else "")))
        rows.append(self.kv("Checked", '%s (%s); stale on %s <span class="b fr" data-stale-on="%s" data-basis="%s" data-checked="%s"></span>' % (
            e(c["checked_on"]), e(c["verified_basis"]), e(c["stale_on"]), e(c["stale_on"]), e(c["verified_basis"]), e(c["checked_on"]))))
        claims = [x for x in f["claims"] if x.get("parse") == "ok" and x.get("num") is not None and x["kind"] != "free-quota"]
        if claims:
            rows.append(self.kv("Parsed numbers", "<ul>%s</ul>" % "".join(
                "<li><code>%s</code> %s %s%s%s%s</li>" % (e(x["path"]), e(x["kind"]), e(x.get("currency") or ""), e(x["num"]),
                                                       (" " + e(x["unit"])) if x.get("unit") else "", (" / " + e(x["per"])) if x.get("per") else "")
                for x in claims[:12])))
        ev = o.get("evidence") or []
        evh = "".join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e(x.get("date")), ('<a href="%s" rel="nofollow noopener">%s</a>' % (e(x["url"]), e(re.sub(r"^https?://", "", x["url"])[:60])))
            if str(x.get("url") or "").startswith("http") else e(x.get("url") or "withheld"), prose(x.get("proved")))
            for x in ev if isinstance(x, dict))
        extras = o.get("extras")
        exh = ('<details><summary>More fields (%d)</summary><pre class="json">%s</pre></details>' % (
            len(extras), e(json.dumps(extras, ensure_ascii=False, indent=1)))) if extras else ""
        unk = f["unknown"]
        unh = ('<details><summary>Unknown or withheld values (%d)</summary><ul>%s</ul></details>' % (
            len(unk), "".join("<li><code>%s</code> %s</li>" % (e(p), e(cl)) for p, cl in unk[:200]))) if unk else ""
        hs = "".join('<li><a href="/changes/#%s">%s</a> %s</li>' % (e(re.sub(r"[^a-z0-9]+", "-", h["hid"].lower())), e((h["when"] or "")[:10]), e(h["title"]))
                     for h in f["history"])
        dr = "".join('<li>%s: <code>%s</code> says %s, <a href="/r/%s">%s</a> says %s</li>' % (
            e(d["field"]), e(d["subject"]), e(d["a"]), e(d["other"]), e(d["other"]), e(d["b"])) for d in f["drift"])
        return (
            '<section class="rec" id="%s--%s"%s><h2><a href="#%s--%s">%s</a> <small>%s</small></h2><div class="badges">%s</div>'
            '<p class="meta"><a href="%s" rel="nofollow noopener">%s</a> &middot; %s &middot; <code>%s</code> &middot; '
            '<a href="/api/v1/record/%s.json">JSON</a> &middot; <a href="/compare/?r=%s">compare</a></p>'
            '%s<table class="kv">%s</table>'
            '<details%s><summary>Evidence (%d)</summary><table class="ev"><thead><tr><th>date</th><th>source</th><th>what it proved</th></tr></thead><tbody>%s</tbody></table></details>'
            '%s%s%s</section>'
        ) % (e(c["topic"]), e(c["slug"]), self.row_attrs(c), e(c["topic"]), e(c["slug"]), e(c["provider"]),
             e(TOPIC_NAME.get(c["topic"], c["topic"])), self.badges(c),
             e(c["url"] or ""), e(re.sub(r"^https?://", "", c["url"] or "")[:60]), e(c["category"]), e(rid), e(rid), e(rid),
             ('<p class="warnbox">Sibling records disagree:</p><ul>%s</ul>' % dr) if dr else "",
             "".join(rows), " open" if len(ev) <= 3 else "", len(ev), evh, exh, unh,
             ('<h3>Corrections</h3><ul>%s</ul>' % hs) if hs else "")

    def entity(self, eid, ent, recs):
        topics = sorted({f["card"]["topic"] for f in recs})
        toc = "".join('<li><a href="#%s--%s">%s</a> %s</li>' % (e(f["card"]["topic"]), e(f["card"]["slug"]), e(f["card"]["provider"]),
                                                            self.badges(f["card"], True)) for f in recs) if len(recs) > 1 else ""
        body = ('<p class="crumb"><a href="/">fshy</a> / %s</p><h1>%s</h1><p class="lede">%s%s &middot; %d record%s &middot; '
                '<a href="/api/v1/entity/%s.json">JSON</a></p>%s%s') % (
            " / ".join('<a href="/t/%s/">%s</a>' % (t, e(TOPIC_NAME.get(t, t))) for t in topics), e(ent["name"]),
            (e(ent["domain"]) + " &middot; ") if ent.get("domain") else "", e(", ".join(TOPIC_NAME.get(t, t) for t in topics)),
            len(recs), "" if len(recs) == 1 else "s", e(eid),
            ('<ul class="toc">%s</ul>' % toc) if toc else "", "".join(self.record_section(f) for f in recs))
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
        def table(rs):
            out = []
            for i, r in enumerate(rs, 1):
                c = cards[r[0]]
                val = ""
                if show_val and r[1] is not None:
                    val = money(r[1], "/TB-mo" if "tb" in key else "/mo")
                out.append('<tr%s><td>%d</td><td><a href="/p/%s/#%s--%s">%s</a><div class="s">%s</div></td><td>%s</td><td class="badges">%s</td></tr>' % (
                    self.row_attrs(c), i, e(c["eid"]), e(c["topic"]), e(c["slug"]), e(c["provider"]), prose(c["summary"]) if c["summary"] else "",
                    e(val), self.badges(c, x.get("topic") is None)))
            return "".join(out)
        body = ('<p class="crumb"><a href="/need/">Best per need</a></p><h1>%s</h1><p class="lede">%s</p>%s'
                '<table class="need"><thead><tr><th>#</th><th>offer</th><th>%s</th><th>badges</th></tr></thead><tbody>%s</tbody></table>%s'
                '<details><summary>The query</summary><pre>%s\nORDER BY %s ASC NULLS LAST</pre><p>Run it yourself: '
                '<code>/api/v1/need/%s</code>, the MCP tool <code>need</code>, or <code>fr need %s</code>.</p></details>') % (
            e(x["title"]), e(x["scope"]), self.chips(), e("price" if show_val else ""), table(ranked),
            ('<h2>No parsed number <small>%d</small></h2><p>These match the filter but no price or quantity could be parsed '
             'from their text yet. They are listed, not dropped.</p><table class="need"><tbody>%s</tbody></table>' % (len(unranked), table(unranked)))
            if unranked else "", e(x["sql"]), e(key), e(x["id"]), e(x["id"]))
        self.page("need/%s/index.html" % x["id"], x["title"], body, x["scope"])

    def needs_index(self):
        items = "".join('<li><a href="/need/%s/">%s</a><div class="s">%s</div></li>' % (e(x["id"]), e(x["title"]), e(x["scope"]))
                        for x in self.ctx["needs"]["needs"])
        self.page("need/index.html", "Best per need", '<h1>Best per need</h1><p class="lede">Each list is one query over '
                  'the store, shown under the list. Rows whose number did not parse are listed separately, never dropped.</p>'
                  '<ul class="list">%s</ul>' % items)

    def graveyard(self, cards):
        dead = sorted((c for c in cards.values() if c["grp"] == "dead"), key=lambda c: (c["topic"], c["provider"] or ""))
        by_t = collections.defaultdict(list)
        for c in dead:
            by_t[c["topic"]].append(c)
        parts = ['<h1>Graveyard</h1><p class="lede">%d offers that no longer exist, with the evidence of their end. '
                 'Rejected offers that still exist are on each topic\'s <i>rejected</i> page.</p>' % len(dead)]
        for t, _, _ in TOPICS:
            if by_t.get(t):
                parts.append('<h2>%s <small>%d</small></h2><ul class="list">%s</ul>' % (
                    e(TOPIC_NAME[t]), len(by_t[t]), "".join(self.entry(c) for c in by_t[t])))
        self.page("graveyard/index.html", "Graveyard", "".join(parts))

    def changes(self):
        db = self.ctx["db"]
        items, rss = [], []
        for hid, when, status, conf, title, sup, body in db.execute(
                "SELECT hid, when_utc, status, confidence, title, supersedes, body FROM history ORDER BY when_utc DESC, hid"):
            anchor = re.sub(r"[^a-z0-9]+", "-", hid.lower())
            links = [r for (r,) in db.execute("SELECT rid FROM history_link WHERE hid=? ORDER BY rid", (hid,))]
            items.append('<article class="chg" id="%s"><h2>%s</h2><p class="meta">%s &middot; %s &middot; %s%s</p>%s</article>' % (
                e(anchor), e(title), e((when or "")[:10]), e(status), e(conf),
                (" &middot; records: " + ", ".join('<a href="/r/%s">%s</a>' % (e(r), e(r)) for r in links[:12])) if links else "",
                ('<details><summary>What changed</summary><pre class="md">%s</pre></details>' % e(body)) if body else ""))
            rss.append("<item><title>%s</title><link>https://fshy.ajam.dev/changes/#%s</link><guid>%s</guid><pubDate>%s</pubDate></item>" % (
                e(title), e(anchor), e(hid), e(when)))
        led = db.execute("SELECT at, rid, path, old, new, url, reason FROM ledger ORDER BY at DESC LIMIT 500").fetchall()
        lh = "".join('<tr><td>%s</td><td><a href="/r/%s">%s</a></td><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            e((a or "")[:10]), e(r), e(r), e(p), e(o), e(n), prose(u)) for a, r, p, o, n, u, _ in led)
        body = ('<h1>Changes</h1><p class="lede">Corrections to earlier claims, newest first, and every mechanical '
                'amendment from the change ledger. RSS: <a href="/changes.xml">/changes.xml</a>.</p>%s%s') % (
            ('<h2>Ledger</h2><table class="ev"><thead><tr><th>date</th><th>record</th><th>field</th><th>old</th><th>new</th><th>source</th></tr></thead><tbody>%s</tbody></table>' % lh) if lh else "",
            "".join(items))
        self.page("changes/index.html", "Changes", body)
        self.write("changes.xml", '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>fshy changes</title>'
                   '<link>https://fshy.ajam.dev/changes/</link><description>Corrections to the fshy corpus</description>%s</channel></rss>' % "".join(rss[:100]))

    def about(self, counts):
        v = self.ctx["vocab"]
        def tbl(d):
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
            '<h2>How to read a record</h2><h3>Verdict</h3>%s<h3>Evidence rung</h3>%s<h3>Binding constraint</h3>%s'
            '<h3>Identity</h3>%s%s<p>A question mark after an identity badge means the identity kind is a placeholder: card and phone '
            'requirements are unknown, not absent.</p><h3>Freshness</h3><p>Each record has a date it was last checked and a date '
            'its staleness window ends. The badge is computed in your browser against today. <i>inherited</i> means the record '
            'was carried from an earlier source and its check date is an upper bound.</p><h3>Unknown values</h3>%s'
            '<h2>Query it</h2><ul>'
            '<li>Remote MCP for agents: <code>claude mcp add --transport http fshy https://fshy.ajam.dev/mcp</code> '
            '(tools: help, search, filter, get, entity, need, sql, worklist).</li>'
            '<li>HTTP: <code>/api/v1/search?q=</code>, <code>/api/v1/records?topic=storage&amp;no_card=1&amp;sort=usd_per_tb_month</code>, '
            '<code>/api/v1/sql?q=SELECT ...</code> (read-only), <code>/api/v1/need/&lt;id&gt;</code>, <code>/api/v1/record/&lt;topic&gt;/&lt;slug&gt;</code>, '
            '<code>/api/v1/entity/&lt;id&gt;.json</code>, <a href="/api/v1/help.txt">/api/v1/help.txt</a>, '
            '<a href="/api/v1/schema.sql">/api/v1/schema.sql</a>, <a href="/api/v1/vocab.json">/api/v1/vocab.json</a>.</li>'
            '<li>The whole store as SQLite: <a href="/data/fshy-public.sqlite.gz">fshy-public.sqlite.gz</a> (%s MB), '
            'sha256 <code>%s</code>.</li></ul>'
            '<h2>What is published</h2><p>Only technical data: quotas, limits, prices, identity requirements, interfaces, '
            'reliability events and the evidence for each. Process notes, personal details and terms-of-service or legality '
            'commentary are not published. Of %d source values, %d are published as written, %d were rewritten (for example an '
            'archive mirror replaced by its origin URL) and %d are not published; %d belong to %d records about '
            'infrastructure that is not a public offer.</p>'
            '<p>Build: commit <code>%s</code>, data as of %s, %d records, %d providers.</p>'
        ) % (tbl("verdict"), tbl("confidence"), tbl("binding"), tbl("identity_kind"), tbl("identity_basis"), tbl("unknown_class"),
             round(man["public_db"]["gzip_bytes"] / 1e6, 1), e(man["public_db"]["sha256"]),
             counts.get("leaves", 0), disp.get("kept", 0), disp.get("modified", 0), disp.get("withheld", 0), disp.get("excluded", 0),
             counts.get("excluded", 0), e(self.meta.get("commit")), e(self.meta.get("as_of")), counts.get("records", 0), counts.get("entities", 0))
        self.page("about/index.html", "About and API", body)

    def simple(self):
        self.page("search/index.html", "Search", '<h1>Search</h1><div id="search-page"><p class="lede">Type in the box above. '
                  'Names match as you type; press Enter for a full-text search of every published field.</p><div id="sr"></div></div>')
        self.page("compare/index.html", "Compare", '<h1>Compare</h1><p class="lede">Add <code>?r=topic/slug,topic/slug</code> '
                  'to the address, or use the compare link on any record.</p><div id="cmp"></div>')
        self.page("404.html", "Not found", '<h1>Not found</h1><p>Try the search box, or <a href="/">the home page</a>.</p>')


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
    base = "https://fshy.ajam.dev"
    urls = (["/", "/need/", "/graveyard/", "/changes/", "/about/"] + ["/t/%s/" % t for t, _, _ in TOPICS]
            + ["/t/%s/rejected/" % t for t, _, _ in TOPICS] + ["/need/%s/" % x["id"] for x in ctx["needs"]["needs"]]
            + ["/p/%s/" % eid for eid in sorted(ctx["ents"])])
    s.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
            % "".join("<url><loc>%s%s</loc></url>" % (base, u) for u in urls))
    s.write("robots.txt", "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % base)
    man = ctx["manifest"]
    lines = [
        "# fshy",
        "",
        "> A catalogue of free, nearly free and cheapest-paid cloud capacity: storage, compute, GPU time, inference,",
        "> egress, crawling, email, databases, DNS, CI, proxies, debrid and netdisks. One record per offer, each with",
        "> its quota, binding constraint, identity cost (email, phone, card, ID), evidence and freshness.",
        "> For research and education only. It is not legal advice, and it makes no statement about whether a use is permitted.",
        "",
        "Data as of %s; %d records; %d providers." % (man.get("as_of"), man["counts"].get("records", 0), man["counts"].get("entities", 0)),
        "",
        "## Query it (read-only)",
        "",
        "- MCP (Streamable HTTP, stateless): %s/mcp  (tools: help, search, filter, get, entity, need, sql, worklist)" % base,
        "- Primer, schema and vocabularies: %s/api/v1/help.txt , %s/api/v1/schema.sql , %s/api/v1/vocab.json" % (base, base, base),
        "- Search: %s/api/v1/search?q=WORDS&topic=TOPIC" % base,
        "- Filter: %s/api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month" % base,
        "- SQL (SQLite, read-only): %s/api/v1/sql?q=SELECT+rid,verdict+FROM+record+LIMIT+5" % base,
        "- One record: %s/api/v1/record/TOPIC/SLUG ; one provider: %s/api/v1/entity/ID.json" % (base, base),
        "- Whole store as SQLite: %s/%s" % (base, man["public_db"]["path"]),
        "",
        "## Rules for reading the data",
        "",
        "- needs_card / needs_phone are 1, 0 or NULL; NULL means unknown, never no.",
        "- A record is stale on the date in stale_on; compare it with today.",
        "- usd_month and usd_per_tb_month are NULL when no price parsed; filters on them report what NULL excluded.",
        "",
        "## Topics",
        "",
    ] + ["- [%s](%s/t/%s/): %s" % (n, base, t, d) for t, n, d in TOPICS] + ["", "## Best per need", ""] + [
        "- [%s](%s/need/%s/)" % (x["title"], base, x["id"]) for x in ctx["needs"]["needs"]]
    s.write("llms.txt", "\n".join(lines) + "\n")
    return s.n
