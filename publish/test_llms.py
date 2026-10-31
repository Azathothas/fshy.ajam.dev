#!/usr/bin/env python3
"""Selftest for llms.py: llms.txt, llms-full.txt and the Markdown alternates of the wiki pages.

It reads the public store that publish/build.py writes from data/, generates the files into a temporary
directory, and checks that they exist, follow the llmstxt.org shape, hold every published value, split within the
budget, and come out byte-identical under another hash seed. The build's own leak scan reads them (build.py); this
test checks once that the scan covers them. With --site it also checks a built site: every alternate link, the real
budgets, _headers, that the site's files equal a fresh generation from the store, and the HTML pages: the language of
each run of another script, a description, unique ids, the internal links, the pages without JavaScript, the feed,
and no build commit. What the projection withholds is tested in the research repository, where the projection runs.

usage:
  python publish/build.py --check && python publish/test_llms.py
  python publish/build.py --site site/dist && python publish/test_llms.py --site site/dist

Exit codes: 0 every check passed, 1 a check failed.
"""
import argparse
import collections
import email.utils
import glob
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402
import llms  # noqa: E402
import pages as pages_mod  # noqa: E402
project = build  # leaves() and jpath() are in build.py here

FAILS = []
RID_LINE = re.compile(r"^- `([^`]+)`" + re.escape(llms.SEP), re.M)
LINK = re.compile(r"\]\((" + re.escape(llms.BASE) + r"/[^)\s]*)\)")
ITEM = re.compile(r"^- \[[^\]]+\]\(" + re.escape(llms.BASE) + r"/[^)\s]*\)(?:: \S.*)?$")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, ("\n     " + str(detail)[:600]) if detail and not cond else ""))
    return cond


def flat(s):
    return " ".join(str(s).split())


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def generated(dist):
    """{relative path: text} of every file llms.py writes under dist."""
    out = {}
    for rel in ["llms.txt", "llms-full.txt", "index.md"]:
        if os.path.exists(os.path.join(dist, rel)):
            out[rel] = read(os.path.join(dist, rel))
    for pat in ("t/*.md", "t/*/rejected.md", "t/*/llms-full*.txt", "p/*.md", "need/*.md"):
        for p in glob.glob(os.path.join(dist, *pat.split("/"))):
            out[os.path.relpath(p, dist).replace("\\", "/")] = read(p)
    return out


def generate_in_subprocess(db, out, seed):
    code = "import sys; sys.path.insert(0, %r); import llms; llms.generate(%r, %r)" % (HERE, db, out)
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=900)
    return p.returncode, p.stderr


def same_tree(a, b):
    fa, fb = generated(a), generated(b)
    diff = sorted(set(fa) ^ set(fb)) + sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
    return not diff, diff[:5]


# ---------------------------------------------------------------------------------------------- checks
def shape_checks(dist, st):
    files = generated(dist)
    want = ["llms.txt", "llms-full.txt", "index.md"] + ["p/%s.md" % e for e in st.ents] + [
        "need/%s.md" % x["id"] for x in st.needs]
    for t, _, _ in st.topics:
        want += ["t/%s.md" % t, "t/%s/rejected.md" % t] + (["t/%s/llms-full.txt" % t] if any(
            c["topic"] == t for c in st.cards.values()) else [])
    missing = [w for w in want if w not in files]
    check("every file the module lists is written (%d files)" % len(files), not missing, missing[:8])
    check("every file is UTF-8 with LF line ends and a final newline",
          all("\r" not in v and v.endswith("\n") for v in files.values()),
          [k for k, v in files.items() if "\r" in v or not v.endswith("\n")][:5])

    lt = files.get("llms.txt", "").split("\n")
    sections = [l for l in lt if l.startswith("## ")]
    items, bad = 0, []
    in_section = False
    for l in lt:
        if l.startswith("## "):
            in_section = True
        elif in_section and l.startswith("- "):
            items += 1
            if not ITEM.match(l):
                bad.append(l[:120])
        elif in_section and l.strip():
            bad.append(l[:120])
    check("llms.txt opens with an H1 and a blockquote summary", lt[:1] == ["# fshy"] and lt[2].startswith("> ") and lt[1] == "",
          lt[:3])
    check("llms.txt sections hold only link items, '- [name](url): notes' (%d items)" % items, items > 0 and not bad, bad[:4])
    check("llms.txt has no heading deeper than H2, and ends with an Optional section",
          not [l for l in lt if l.startswith("###")] and sections and sections[-1] == "## Optional", sections)
    check("index.md is llms.txt", files.get("index.md") == files.get("llms.txt"))

    dead = []
    for rel, text in files.items():
        for u in LINK.findall(text):
            path = u[len(llms.BASE) + 1:]
            if re.search(r"\.(md|txt)$", path) and not path.startswith("api/") and not os.path.exists(os.path.join(dist, *path.split("/"))):
                dead.append("%s -> %s" % (rel, u))
    check("every link to a generated Markdown or text file resolves", not dead, dead[:5])

    parts = {k: v for k, v in files.items() if re.fullmatch(r"t/[^/]+/llms-full(-[a-z]+(-[a-z]+)?(-\d+)?)?\.txt", k)}
    seen = {}
    for rel, text in parts.items():
        for rid in RID_LINE.findall(text):
            seen.setdefault(rid, []).append(rel)
    once = [r for r in st.cards if len(seen.get(r, [])) != 1]
    check("every record is in exactly one llms-full part (%d records, %d files)" % (len(st.cards), len(parts)), not once,
          [(r, seen.get(r)) for r in once[:5]])
    off = [r for r, c in st.cards.items() if "- `%s`%s" % (r, llms.SEP) not in files.get("p/%s.md" % c["eid"], "")]
    check("every record is on its provider page", not off, off[:5])
    root = files.get("llms-full.txt", "")
    listed = set(LINK.findall(root))
    split_topics = [k for k, v in parts.items() if k.endswith("/llms-full.txt") and "## Parts" in v]
    unlisted = [k for k in parts if "%s/%s" % (llms.BASE, k) not in listed and k not in split_topics]
    check("the root llms-full.txt lists every part, or holds every record itself",
          not unlisted or all("- `%s`%s" % (r, llms.SEP) in root for r in st.cards), unlisted[:5])
    root_order_check(root, st, "")
    dates = set(DATE.findall(files.get("llms.txt", ""))) | set(DATE.findall(root.split("## How to read")[0]))
    check("the only date in llms.txt and the head of llms-full.txt is the data's own (%s)" % st.as_of, dates == {st.as_of}, dates)
    return files


def root_order_check(root, st, where):
    """The root llms-full.txt reads hosted first: as an index, every self-hosted part after every other file; as the
    whole corpus, every self-hosted record after every hosted one."""
    if "## Parts" in root:
        items = [ln for ln in root.split("\n## Parts\n", 1)[1].split("\n## ", 1)[0].split("\n") if ln.startswith("- [")]
        marks = ["/llms-full-%s" % llms.SELF_GROUP in ln for ln in items]
        what = "every self-hosted part after every other file of its Parts list (%d of %d)" % (sum(marks), len(items))
    else:
        items = RID_LINE.findall(root)
        marks = [llms.is_sh(st.cards[r]) for r in items]
        what = "every self-hosted record after every hosted one (%d of %d)" % (sum(marks), len(items))
    first = marks.index(True) if True in marks else len(marks)
    above = [items[i][:120] for i in range(first, len(marks)) if not marks[i]]
    check("%sthe root llms-full.txt lists %s" % (where, what), not above, above[:3])


def whole_check(db, st):
    """A budget that holds the whole corpus: llms-full.txt is every record in one file, the self-hosted ones last."""
    old = llms.BUDGET
    out = tempfile.mkdtemp(prefix="llms-whole-")
    try:
        llms.BUDGET = 10 ** 10
        llms.generate(db, out)
        root = read(os.path.join(out, "llms-full.txt"))
        seen = RID_LINE.findall(root)
        check("at a budget over the corpus, the root llms-full.txt holds every record once",
              sorted(seen) == sorted(st.cards), (len(seen), len(st.cards)))
        root_order_check(root, st, "at a budget over the corpus, ")
    finally:
        llms.BUDGET = old
        shutil.rmtree(out, ignore_errors=True)


def published_check(files, st):
    """Every published string and number of every record is on its provider page. Returns the published strings."""
    missing, public, n = [], set(), 0
    for rid, doc in st.docs.items():
        page = files.get("p/%s.md" % st.cards[rid]["eid"], "")
        for p, v in project.leaves(doc):
            if isinstance(v, str) and flat(v):
                n += 1
                public.add(flat(v))
                if flat(v) not in page and llms.day(flat(v)) not in page:  # a midnight date-time is printed as its day
                    missing.append((rid, project.jpath(p), v[:80]))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                n += 1
                if json.dumps(v) not in page:
                    missing.append((rid, project.jpath(p), v))
    check("every published value of every record is in its Markdown (%d values)" % n, not missing, missing[:5])
    return public


def lossless_checks(dist, st):
    files = generated(dist)
    published_check(files, st)
    sep = [k for k, v in files.items() if re.search(r"^- `[^`]+` \u00b7 ", v, re.M)]
    check("the files separate the items of a line with %r, which is ASCII (U-39)" % llms.SEP, not sep, sep[:3])
    index = {k: v for k, v in files.items() if k.startswith(("t/", "need/")) and k.endswith(".md")}
    unknown = [k for k, v in index.items() for ln in v.split("\n") if ln.startswith("- [") and
               not re.search(r"\| (no phone|phone|phone\?|any-phone\??|country-phone\??)( \||$|\.)", ln)]
    check("every index line says no phone, phone or phone? (U-24)", not unknown, unknown[:3])
    stale_checks(index, st)


def stale_word(c, as_of):
    """The freshness item that an index line and an HTML row must carry, from the card alone."""
    if c["grp"] == "dead" or not c["stale_on"]:
        return ""
    return ("stale since %s" if c["stale_on"] <= as_of else "stale on %s") % c["stale_on"]


def stale_checks(index, st):
    """Each line of a topic, rejected or need index names the stale date of its record, as 'stale since' when it is on
    or before the date of the data; a dead record names none (F-12)."""
    wrong, n = [], 0
    for k, v in index.items():
        for ln in v.split("\n"):
            m = re.search(r"\.md\) \[?`([^`]+)`", ln) if re.match(r"^(?:- |\d+\. )", ln) else None
            if not m or m.group(1) not in st.cards:
                continue
            n += 1
            want = stale_word(st.cards[m.group(1)], st.as_of)
            have = re.findall(r"\| (stale (?:on|since) \d{4}-\d{2}-\d{2})(?= \||\.|$)", ln)
            if have != ([want] if want else []):
                wrong.append((k, m.group(1), want, have))
    check("every index line names its stale date, 'stale since' when it is past the data date (F-12; %d lines)" % n,
          n and not wrong, wrong[:3])


def leak_scan_covers(dist):
    probe = tempfile.mkdtemp(prefix="llms-leak-")
    try:
        for rel in ("p/zz-probe.md", "t/zz/llms-full-usable-1.txt"):
            p = os.path.join(probe, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("The Terms of Service apply to this offer.\n")
        hits = {k.replace(os.sep, "/") for k, _, _ in build.leak_scan(dist=probe)}
        check("the build's leak scan reads .md and .txt files", {"p/zz-probe.md", "t/zz/llms-full-usable-1.txt"} <= hits, hits)
        hits = build.leak_scan(dist=dist)
        check("the build's leak scan passes the generated files", not hits, hits[:3])
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def split_checks(db, st, budget, want_cut):
    old = llms.BUDGET
    out = tempfile.mkdtemp(prefix="llms-split-")
    try:
        llms.BUDGET = budget
        files = llms.generate(db, out)
        text = {k: read(os.path.join(out, *k.split("/"))) for k in files if re.fullmatch(r"t/[^/]+/llms-full.*\.txt", k)}
        parts = {k: files[k] for k, v in text.items() if "## Parts" not in v}  # a whole topic, or one part of one
        over = [(k, n) for k, n in parts.items() if n > budget and text[k].count("\n## ") > 1]
        check("at a %d-byte budget the corpus splits into %d files, none over it unless one record alone is"
              % (budget, len(parts)), parts and not over, over[:5])
        seen = [r for k in parts for r in RID_LINE.findall(text[k])]
        check("at %d bytes, every record is still in exactly one file" % budget, sorted(seen) == sorted(st.cards),
              (len(seen), len(st.cards)))
        root = read(os.path.join(out, "llms-full.txt"))
        check("at %d bytes, the root llms-full.txt indexes every file" % budget,
              all("%s/%s" % (llms.BASE, k) in root for k in parts))
        root_order_check(root, st, "at %d bytes, " % budget)
        idx = [k for k, v in text.items() if "## Parts" in v]
        unindexed = [p for p in parts if re.search(r"llms-full-", p) and not any(
            "%s/%s" % (llms.BASE, p) in text[k] for k in idx if k.split("/")[1] == p.split("/")[1])]
        check("at %d bytes, each split topic's llms-full.txt indexes its parts (%d split)" % (budget, len(idx)), not unindexed,
              unindexed[:5])
        pages = {k: n for k, n in files.items() if re.fullmatch(r"(t/[^/]+(/rejected)?|need/[^/]+)\.md", k)}
        cut = [k for k in pages if "Summaries are cut to" in read(os.path.join(out, *k.split("/")))]
        over = [(k, n) for k, n in pages.items() if n > budget and "Summaries are cut to 0 " not in read(os.path.join(out, *k.split("/")))]
        check("at %d bytes, index pages over it cut their summaries to fit (%d cut)" % (budget, len(cut)),
              not over and (bool(cut) or not want_cut), over[:5])
        balanced = {}
        for k, n in parts.items():
            m = re.fullmatch(r"t/([^/]+)/llms-full-([a-z-]+)-\d+\.txt", k)
            if m:
                balanced.setdefault(m.groups(), []).append(n)
        lop = [(g, ns) for g, ns in balanced.items() if min(ns) < max(ns) / 4]
        check("the parts of a group are balanced, no tail under a quarter of the largest", not lop, lop[:3])
    finally:
        llms.BUDGET = old
        shutil.rmtree(out, ignore_errors=True)


def link_checks():
    cases = [("index.html", "/index.md"), ("t/storage/index.html", "/t/storage.md"),
             ("t/storage/rejected/index.html", "/t/storage/rejected.md"), ("p/oracle/index.html", "/p/oracle.md"),
             ("p\\oracle\\index.html", "/p/oracle.md"), ("need/free-gpu/index.html", "/need/free-gpu.md"),
             ("about/index.html", None), ("need/index.html", None), ("graveyard/index.html", None), ("404.html", None),
             ("changes/index.html", None), ("t/storage/x/index.html", None),
             ("p/amazon/storage--amazon-sqs/index.html", "/p/amazon.md")]
    bad = []
    for rel, href in cases:
        got = llms.alternate_link(rel)
        want = '<link rel="alternate" type="text/markdown" href="%s">' % href if href else ""
        if got != want:
            bad.append((rel, got))
    check("alternate_link maps each page to its Markdown version, and no other page", not bad, bad)


def price_checks():
    """A parsed price keeps cents from 1 and four significant figures under 1, so it is never USD 0 (F-19)."""
    prices = [(0.004, "USD 0.004"), (0.00003873, "USD 0.00003873"), (0.1247, "USD 0.1247"), (0.5, "USD 0.5"),
              (0.99996, "USD 1"), (4.999, "USD 5"), (12.3456, "USD 12.35"), (1234.4, "USD 1234"), (0, "USD 0")]
    bad = [(v, llms.money(v, ""), w) for v, w in prices if llms.money(v, "") != w]
    check("a price under 1 keeps four significant figures and is never USD 0 (F-19)", not bad, bad)


def site_checks(dist, store):
    st = llms.Store(store)
    files = generated(dist)
    shape_checks(dist, st)
    published_check(files, st)
    per_page, bad, n = {}, [], 0
    for root, _, fs in os.walk(dist):
        for fn in fs:
            if fn.endswith(".html"):
                rel = os.path.relpath(os.path.join(root, fn), dist).replace("\\", "/")
                hrefs = re.findall(r'<link rel="alternate" type="text/markdown" href="([^"]+)">', read(os.path.join(root, fn)))
                link = re.search(r'href="([^"]+)"', llms.alternate_link(rel))
                want = link.group(1) if link else None
                n += len(hrefs)
                if hrefs != ([want] if want else []) or (want and not os.path.exists(os.path.join(dist, *want.strip("/").split("/")))):
                    bad.append((rel, hrefs, want))
    check("every wiki page carries its one alternate link, and each resolves (%d links)" % n, n and not bad, bad[:5])
    held = {k: len(v.encode("utf-8")) for k, v in files.items() if not k.startswith("p/")}
    over = [(k, b) for k, b in held.items() if b > llms.BUDGET and files[k].count("\n## ") > 1]
    check("every llms-full part, index and need page is within %d bytes" % llms.BUDGET, not over, over[:5])
    big = sorted(((len(v.encode("utf-8")), k) for k, v in files.items() if k.startswith("p/")), reverse=True)[:1]
    print("     largest provider page: %s" % big)
    man = json.load(open(os.path.join(dist, "data", "manifest.json"), encoding="utf-8"))
    commit = man.get("commit") or ""
    check("no generated file names the build's commit", not commit or not [k for k, v in files.items() if commit[:10] in v])
    lt = files.get("llms.txt", "")
    have = {c["topic"] for c in st.cards.values()}
    every = llms.topics([])
    empty = [n for t, n, _ in every if t not in have]
    summary = lt.split("\n")[2] if lt.count("\n") > 2 else ""
    check("the summary of llms.txt names no topic without records (U-14)",
          not [n for n in empty if llms.TOPIC_PHRASE.get(dict((x[1], x[0]) for x in every)[n], n.lower()) in summary], empty)
    wrong, seen = [], 0
    for rel, text in files.items():
        if not (rel.startswith("t/") and rel.endswith(".md") and rel.count("/") == 1):
            continue
        for line in text.split("\n"):
            m = re.match(r"^- \[[^\]]*\]\([^)]*\) \[`([^`]+)`\]\([^)]*\): (.*)$", line) or re.match(r"^- \[[^\]]*\]\([^)]*\) `([^`]+)`: (.*)$", line)
            if m and m.group(1) in st.cards:
                seen += 1
                badges = m.group(2).split(llms.SEP)
                claim = st.cards[m.group(1)].get("free_claim")
                if ("free tier" in badges) != (claim == 1) or ("no free tier" in badges) != (claim == 0):
                    wrong.append((m.group(1), claim, badges[:3]))
    check("an index line says 'free tier' only when the claim has-free-tier is 1, 'no free tier' only when it is 0 (F-05, F-25; %d lines)" % seen,
          seen and not wrong, wrong[:4])
    for x in st.needs:
        flags = [f for f in ("needs_card", "needs_phone") if f + "=0" in x["sql"]]
        page = read(os.path.join(dist, "need", x["id"], "index.html"))
        if not flags:
            check("the need %s asks for no card or phone, so it has no section for a requirement that is not stated" % x["id"],
                  'id="unstated"' not in page and "requirement not stated" not in files["need/%s.md" % x["id"]])
            continue
        relaxed_sql = x["sql"]
        for cond in (" AND needs_card=0", " AND needs_phone=0", " AND identity_basis='stated'"):
            relaxed_sql = relaxed_sql.replace(cond, "")
        relaxed = {r[0] for r in st.db.execute(relaxed_sql)}
        confirmed = {r[0] for r in st.db.execute(x["sql"])}
        known = {rid for rid in relaxed if any(st.cards[rid][f] == 1 for f in flags)}
        want = relaxed - confirmed - known
        # a self-hosted row is in the last section, after every hosted row, the not stated ones included
        last = {rid for rid in want if st.cards[rid]["self_hosted"]}
        want -= last
        sect = page.split('id="unstated"')[1].split("<details>")[0].split('<h2 id="self-hosted"')[0] if 'id="unstated"' in page else ""
        md = files["need/%s.md" % x["id"]]
        mdrows = (md.split("## Card or phone requirement not stated")[1].split("\n## Self-hosted, the last resort")[0]
                  if "## Card or phone requirement not stated" in md else "")
        got = (sect.count('<li class="e"'), len(re.findall(r"^- \[", mdrows, re.M)))
        mdlast = md.split("\n## Self-hosted, the last resort")[1] if last else ""
        check("the need %s lists %d rows whose card or phone requirement is not stated, after the confirmed rows, none of them also confirmed and none dropped (page %d, Markdown %d)"
              % (x["id"], len(want), got[0], got[1]),
              want and got == (len(want), len(want)) and not (want & confirmed)
              and relaxed == confirmed | want | known | last and 'Card or phone requirement not stated <small>' in page
              and page.index('id="unstated"') > page.index('class="list')
              and all("`%s`" % r in mdlast for r in last), (len(want), got, sorted(last)[:3]))
    sitemap = read(os.path.join(dist, "sitemap.xml"))
    bare = [t for t, _, _ in every if t not in have]
    check("a topic with no record has no page, no Markdown file and no line in llms.txt or the sitemap (F-03, W-42)",
          bare and all(("t/%s.md" % t) not in files and ("/t/%s.md" % t) not in lt and ("/t/%s/" % t) not in sitemap
                       and not os.path.exists(os.path.join(dist, "t", t)) for t in bare) or not bare, bare)
    listed = [x for x in lt.split("## Topics")[1].split("## Best per need")[0].split("\n") if x.startswith("- [")]
    tiles = re.findall(r'class="tile" href="/t/', read(os.path.join(dist, "index.html")))
    check("the home page and llms.txt list the same topics, and each has records (F-03)", len(listed) == len(tiles) == len(have),
          (len(listed), len(tiles), len(have)))
    as_of = json.load(open(os.path.join(dist, "data", "manifest.json"), encoding="utf-8")).get("as_of")
    check("one data date on every surface: the manifest, llms.txt, the home page and help.txt (F-01)",
          st.as_of == as_of and ("as of %s" % as_of) in lt and as_of in read(os.path.join(dist, "index.html"))
          and as_of in read(os.path.join(dist, "api", "v1", "help.txt")), (st.as_of, as_of))
    check("the notice is in llms.txt and not in llms-full.txt (U-36)", "research and education" in lt and
          "research and education" not in files.get("llms-full.txt", ""))
    html_checks(dist, man, st)
    hdr = read(os.path.join(dist, "_headers"))
    check("_headers sets caching and CORS for every new path",
          all(p in hdr.split("\n") for p in ("/llms.txt", "/llms-full.txt", "/index.md", "/t/*.md", "/t/*.txt", "/p/*.md", "/need/*.md")))
    rules = header_rules(hdr)
    twice, nocharset, files_seen = [], [], 0
    for root, _, fs in os.walk(dist):
        for fn in fs:
            path = "/" + os.path.relpath(os.path.join(root, fn), dist).replace("\\", "/")
            hs = headers_of(rules, path)
            files_seen += 1
            names = [n for n, _ in hs]
            if len(names) != len(set(names)):
                twice.append((path, sorted(n for n in set(names) if names.count(n) > 1)))
            if path.endswith((".md", ".txt")) and not any(n == "content-type" and v.endswith("charset=utf-8") for n, v in hs):
                nocharset.append(path)
    check("no file gets one header from two rules of _headers: a second rule appends, it does not replace (W-23, %d files)" % files_seen,
          not twice, twice[:5])
    check("every .md and .txt file is served with a charset, so a client that reads text/* as Latin-1 reads UTF-8 (W-19)",
          not nocharset, nocharset[:5])
    fresh = tempfile.mkdtemp(prefix="llms-fresh-")
    try:
        code, err = generate_in_subprocess(store, fresh, 7)
        ok, diff = same_tree(dist, fresh)
        check("the site's files equal a fresh generation from its store, under another hash seed", code == 0 and ok, (err[-300:], diff))
    finally:
        shutil.rmtree(fresh, ignore_errors=True)
    total = sum(len(v.encode("utf-8")) for v in files.values())
    print("     %d generated files, %d bytes" % (len(files), total))


# a run of a script that is not Latin: pages.py marks each with lang (WCAG 3.1.2)
NON_LATIN = re.compile("[\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
LANG_SPAN = re.compile(r'<span lang="[a-z]{2}">[^<]*</span>')
# the verdict mark U+2605 of the label "qualifies" is the one symbol of the chrome
PICTOGRAPH = re.compile("[\U0001F000-\U0001FAFF\u2600-\u2604\u2606-\u26FF\u2B50\u2728\u274C\u2764]")
RFC822 = re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")
WORKER = ("/api/v1/search", "/api/v1/records", "/api/v1/sql", "/api/v1/need", "/api/v1/worklist", "/api/v1/record/",
          "/api/v1/entity-search", "/mcp", "/r/", "/data/fshy-public.sqlite.gz")


def header_rules(text):
    """[(path pattern, [(header name in lower case, value)])] of a Cloudflare _headers file."""
    rules = []
    for line in text.split("\n"):
        if line.strip() and not line[0].isspace():
            rules.append((line.strip(), []))
        elif line.strip() and rules:
            name, _, value = line.strip().partition(":")
            rules[-1][1].append((name.strip().lower(), value.strip()))
    return rules


def headers_of(rules, path):
    """The headers that the rules of a _headers file give a path; a * matches any run of characters, slashes too."""
    return [h for pat, hs in rules if re.fullmatch(re.escape(pat).replace(r"\*", ".*"), path) for h in hs]


def html_checks(dist, man, st=None):
    """The HTML pages that pages.py writes, checked on every page."""
    pages = {}
    for root, _, fs in os.walk(dist):
        for fn in fs:
            if fn.endswith(".html"):
                pages[os.path.relpath(os.path.join(root, fn), dist).replace("\\", "/")] = read(os.path.join(root, fn))
    nolang, nodesc, dupid, emoji, commit, dead, labels, shell, chips = [], [], [], [], [], set(), [], [], []
    have = set()
    for root, _, fs in os.walk(dist):
        for fn in fs:
            have.add("/" + os.path.relpath(os.path.join(root, fn), dist).replace("\\", "/"))
    for rel, h in pages.items():
        body = h.split("<body>", 1)[-1]
        if not h.isascii():
            bare = re.sub(r"<[^>]*>", " ", LANG_SPAN.sub(" ", body))
            if NON_LATIN.search(bare):
                nolang.append((rel, NON_LATIN.search(bare).group(0)))
            if PICTOGRAPH.search(body):
                emoji.append((rel, PICTOGRAPH.search(body).group(0)))
        if not re.search(r'<meta name="description" content="[^"]+">', h):
            nodesc.append(rel)
        ids = collections.Counter(re.findall(r'\sid="([^"]+)"', body))
        if any(n > 1 for n in ids.values()):
            dupid.append((rel, [i for i, n in ids.items() if n > 1][:3]))
        if man.get("commit") and man["commit"][:10] in h:
            commit.append(rel)
        for href in re.findall(r'href="(/[^"#?]*)', h):
            if href.startswith(WORKER) or href in ("/api/v1/",):
                continue
            want = href + "index.html" if href.endswith("/") else href
            if want not in have and want + "/index.html" not in have:
                dead.add((rel, href))
        # app.js reads these elements without a test for each: the topic bar and the search box on every page, and the
        # three parts of the filter bar
        if not all(x in body for x in ('class="topics"', 'id="q"', 'id="qr"')):
            shell.append(rel)
        if 'class="chips"' in body and not all(x in body for x in ('class="ifilter"', 'class="clear"', 'class="count"')):
            chips.append(rel)
        if rel.startswith("p/"):
            heads = re.findall(r'<h2><a href="#[^"]+">(.*?)</a></h2>', h)
            if len(heads) != len(set(heads)):
                labels.append(rel)
    check("every run of another script on %d pages has its lang (U-05)" % len(pages), not nolang, nolang[:5])
    check("no pictograph of quoted text is on a page (U-37)", not emoji, emoji[:5])
    check("every page has a meta description (U-29)", not nodesc, nodesc[:5])
    check("no id repeats on a page (U-28)", not dupid, dupid[:5])
    check("no page names the build's commit (P-03)", not commit, commit[:5])
    check("every internal link of every page resolves to a file (%d pages)" % len(pages), not dead, sorted(dead)[:5])
    check("no two records of a provider page share a heading (U-01)", not labels, labels[:5])
    check("every page has the topic bar and the search box that app.js reads (%d pages)" % len(pages), not shell, shell[:5])
    check("every filter bar has the interface box, the clear button and the count that app.js reads", not chips, chips[:5])
    search, compare = pages.get("search/index.html", ""), pages.get("compare/index.html", "")
    check("the search and compare pages say what to do without JavaScript (U-02)",
          "<noscript>" in search and "/api/v1/search?q=" in search and "<noscript>" in compare and "/api/v1/record/" in compare)
    for nid, (_, sections) in llms.NEED_SPLITS.items():
        page = pages.get("need/%s/index.html" % nid, "")
        page = page.split('id="unstated"')[0]  # the section of the requirements that are not stated has its own check
        got = re.findall(r'<h2 id="([a-z-]+)">[^<]*<small>(\d+)</small></h2>', page)
        rows = len(re.findall(r'<li class="e"', page))
        md = read(os.path.join(dist, "need", nid + ".md"))
        # the self-hosted rows of a split need are one last section of their own, after every split section; its
        # Markdown lines are a list, not a ranking
        split = [(k, n) for k, n in got if k != "self-hosted"]
        last = [(k, n) for k, n in got if k == "self-hosted"]
        md_sh = md.split("\n## Self-hosted, the last resort (", 1)[1] if last else ""
        md_rows = len(re.findall(r"^\d+\. ", md.split("\n## Self-hosted, the last resort (", 1)[0], re.M)) + \
            len(re.findall(r"^- \[", md_sh, re.M))
        check("the need %s is split into sections that name what they hold, and no row is lost (F-15, F-19)" % nid,
              split and [k for k, _ in split] == [k for k, _, _ in sections if k in {g for g, _ in split}]
              and got == split + last and len(last) <= 1
              and sum(int(n) for _, n in got) == rows == md_rows
              and all(("## %s (" % h) in md for k, h, _ in sections if k in {g for g, _ in split})
              and all(("## Self-hosted, the last resort (%s)" % n) in md for _, n in last), (got, rows))
    # F-12: each row of a topic, paid, rejected and need page names its stale date without the script
    wrong, n = [], 0
    for rel, h in pages.items():
        if not st or not re.fullmatch(r"(t/[^/]+/(?:paid/|rejected/)?|need/[^/]+/)index\.html", rel):
            continue
        for li in re.findall(r'<li class="e".*?</li>', h):
            a = re.search(r'<a class="n" href="/p/[^"/]+/(?:#|)([a-z0-9-]+?)--([^"/]+)/?"', li)
            c = st.cards.get("%s/%s" % a.groups()) if a else None
            if not c:
                continue
            n += 1
            want = stale_word(c, st.as_of)
            have = re.findall(r'<span class="fr"[^>]*>(stale (?:on|since) [0-9-]+)</span>', li)
            if have != ([want] if want else []):
                wrong.append((rel, c["rid"], want, have))
    check("every row of a topic or need page names its stale date without the script (F-12; %d rows)" % n,
          not st or (n and not wrong), wrong[:3])
    topic = pages.get("t/storage/index.html", "")
    check("the filter bar is hidden until the script shows it, and a key follows it (U-02, U-10)",
          '<div class="chips" role="group" aria-label="filters" hidden>' in topic and '<details class="key">' in topic)
    check("a topic page carries no paid row; the paid group has its own page (U-25)",
          not re.search(r'<li class="e"[^>]*><span class="v v-paid-only">', topic) and os.path.exists(os.path.join(dist, "t", "storage", "paid", "index.html")))
    feed = read(os.path.join(dist, "changes.xml"))
    dates = re.findall(r"<pubDate>([^<]*)</pubDate>", feed)
    check("the feed dates are RFC 822, each guid is not a link, and the feed names itself (U-31)",
          dates and all(RFC822.match(d) and email.utils.parsedate_to_datetime(d) for d in dates)
          and feed.count('<guid isPermaLink="false">') == feed.count("<item>") and 'rel="self"' in feed, dates[:2])
    changes = pages.get("changes/index.html", "")
    check("the Changes page and the feed say which field of which record was amended, and that no old or new value is published (W-13)",
          "holds no old or new value" in changes and re.search(r"<td><code>[a-z_.\[\]0-9]+</code></td>", changes)
          and "<code>$." not in changes and re.search(r"<title>[a-z-]+/[^<]+: [^<]+ amended</title>", feed)
          and "The old and the new value are not published" in feed, changes[:0])
    # a ledger row that names no field (an evidence row, a relation, a new record) is never titled amended
    cells = re.findall(r"<tr><td>[^<]*</td><td><a [^>]*>[^<]*</a></td><td>([^<]*)</td><td><code>([^<]*)</code></td>", changes)
    titles = set(pages_mod.LEDGER_TITLE.values()) | set(pages_mod.LEDGER_NO_OP.values())
    wrong = [c for c in cells if html.unescape(c[0]) not in titles or (c[1] == "not named" and "amended" in c[0])]
    items = re.findall(r"<item><title>([^<]*)</title><link>[^<]*/r/[^<]*</link>", feed)
    check("each ledger row of the Changes page and the feed says what the row did, and a row with no field is not "
          "titled amended (%d rows)" % len(cells), cells and not wrong and not [t for t in items if t.endswith(": not named amended")],
          wrong[:3])
    check("the feed and the changes page carry no history id as text (U-04)",
          not re.search(r"#\d{4}-\d{2}-\d{2}t", feed + pages.get("changes/index.html", "")))


def token_ratio(dist):
    """Bytes per token of the parts, estimated the way a cl100k or o200k tokenizer splits text: a word piece of
    up to 8 letters, a run of up to 3 digits, or a punctuation mark is one token. Holds BYTES_PER_TOKEN honest."""
    b = t = 0
    for k, v in generated(dist).items():
        if "llms-full" in k:
            b += len(v.encode("utf-8"))
            for m in re.finditer(r"[^\W\d_]+|\d+|[^\w\s]", v):
                s = m.group(0)
                t += math.ceil(len(s) / 3) if s[0].isdigit() else (math.ceil(len(s) / 8) if s[0].isalpha() else 1)
    return b / t if t else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", help="also check this built site directory")
    ap.add_argument("--store", default=os.path.join(REPO, ".tmp", "fshy", "public.db"),
                    help="the public store (publish/build.py --check or --site writes it)")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    link_checks()
    price_checks()
    if not os.path.exists(a.store):
        print("no store at %s: run python publish/build.py --check first" % a.store)
        return 1
    tmp = tempfile.mkdtemp(prefix="llms-selftest-")
    try:
        st = llms.Store(a.store)
        check("the store loads: %d records, %d providers" % (len(st.cards), len(st.ents)), len(st.cards) > 0)
        d1, d2 = (os.path.join(tmp, "dist%d" % i) for i in (1, 2))
        llms.generate(a.store, d1)
        shape_checks(d1, st)
        lossless_checks(d1, st)
        leak_scan_covers(d1)
        code, err = generate_in_subprocess(a.store, d2, 1)
        ok, diff = same_tree(d1, d2)
        check("a second generation under another hash seed is byte-identical", code == 0 and ok, (err[-300:], diff))
        split_checks(a.store, st, 120000, False)
        whole_check(a.store, st)
        r = token_ratio(d1)
        check("BYTES_PER_TOKEN (%.2f) is within 10%% of the estimate on this text (%.2f)" % (llms.BYTES_PER_TOKEN, r),
              abs(r - llms.BYTES_PER_TOKEN) <= 0.1 * llms.BYTES_PER_TOKEN)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.site:
        site_checks(os.path.abspath(a.site), a.store)
    print("\n%s: %d failed" % ("FAIL" if FAILS else "PASS", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
