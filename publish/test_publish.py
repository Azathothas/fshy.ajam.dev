#!/usr/bin/env python3
"""Selftest of the publish tools: what test_llms.py and the Worker tests do not cover.

1. The contract between export and build: build.py refuses data/ of another schema version, an unknown table
   file, an unknown or a missing column, and files that do not match files_sha256, with exit 3 and a message that
   names the problem.
2. The export refuses a source that is not a research checkout (exit 3), a test export into data/ (exit 2), and a
   --data that is not data/ and not empty (exit 2), and it keeps the files of that directory.
3. The leak rules, of both levels, match each leak sample and pass each technical sample; the history title rule
   matches a narrative title and passes a correction; build.py --scan finds a leak in a text file. The commit-msg
   hook refuses every credit line of a tool and passes a message that only names a provider.
4. The lists agree. rules/topics.json is the one list of topics: pages.py reads it, app.js holds no copy and
   reads the topic bar, and the New offer form lists the same topics. The verdict labels of pages.py and app.js
   agree. When the store exists, its vocabulary and its topics agree with them.
5. When the store exists: each worked query of primer.py runs, so /api/v1/help.txt never shows a query that
   fails.
6. The helpers that the pages and the files for agents share: the lang of a run of another script, the label that
   tells two records of one provider apart, the one line of a row, the order of a tie in a ranked list, the words of
   a category, the anchor of a history entry, the pictographs that quoted text loses, the parallel leak scan, and
   the twin of the Worker's name normaliser against site/worker/test/parity.json.

Parts 1 to 4 and 6 need no data and run on a fresh clone. The store parts read .tmp/fshy/public.db, which
`python publish/build.py --check` or `--site` writes; without it, they are skipped with a line that says so.

usage:
  python publish/test_publish.py [--db .tmp/fshy/public.db]

Exit codes: 0 every check passed, 1 a check failed.
"""
import argparse
import contextlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402
import export  # noqa: E402
import llms  # noqa: E402
import pages  # noqa: E402
import primer  # noqa: E402
import site_gen  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, ("\n     " + str(detail)[:600]) if detail and not cond else ""))
    return cond


def quiet(fn, *a):
    """Run fn and capture what it prints to stderr. -> (result, stderr text)"""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        r = fn(*a)
    return r, err.getvalue()


def schema_columns():
    db = sqlite3.connect(":memory:")
    db.executescript(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    cols = {t: [c[1] for c in db.execute("PRAGMA table_info(%s)" % t)] for t in ("record",) + build.TABLES}
    db.close()
    return cols


def fake_data(top, version="1", tables=None, record_row=None):
    """A data/ directory with an empty file per table, except a record row when one is given."""
    os.makedirs(os.path.join(top, "tables"))
    with open(os.path.join(top, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": version, "as_of": "2026-10-28", "source_commit": "0" * 40}, f)
    for t in tables if tables is not None else ("record",) + build.TABLES:
        with open(os.path.join(top, "tables", t + ".jsonl"), "w", encoding="utf-8") as f:
            if t == "record" and record_row is not None:
                f.write(json.dumps(record_row) + "\n")


def contract_checks(tmp):
    cols = schema_columns()
    row = {c: None for c in cols["record"] if c not in build.DERIVED}
    cases = [
        ("an unknown schema_version", dict(version="99"), "schema_version '99'"),
        ("a missing schema_version", dict(version=None), "schema_version None"),
        ("an unknown table file", dict(tables=("record", "extra") + build.TABLES), "unknown table file(s) ['extra']"),
        ("a missing table file", dict(tables=("record",) + build.TABLES[1:]), "lacks ['%s']" % build.TABLES[0]),
        ("an unknown column", dict(record_row=dict(row, new_column=1)), "['new_column'] that schema.sql does not have"),
        ("a missing column", dict(record_row={k: v for k, v in row.items() if k != "usd_per_tb_month"}),
         "lacks ['usd_per_tb_month']"),
    ]
    for i, (what, kw, want) in enumerate(cases):
        d = os.path.join(tmp, "data%d" % i)
        fake_data(d, **kw)
        rc, err = quiet(build.main, ["--data", d, "--db", os.path.join(tmp, "s%d.db" % i), "--check", "--quiet"])
        check("build refuses %s with exit 3 and says so" % what, rc == 3 and want in err, (rc, err))
    d = os.path.join(tmp, "data-digest")
    fake_data(d)
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    meta["files_sha256"] = build.files_digest(d)
    json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"))
    check("files_sha256 matches the files it was made from", build.read_meta(d)["files_sha256"] == meta["files_sha256"])
    with open(os.path.join(d, "tables", "fx.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n")  # a hand edit that changes no row
    rc, err = quiet(build.main, ["--data", d, "--db", os.path.join(tmp, "sd.db"), "--check", "--quiet"])
    check("build refuses a hand edit of data/ after the export (files_sha256), with exit 3",
          rc == 3 and "files_sha256" in err, (rc, err))


def export_checks(tmp):
    plain = os.path.join(tmp, "not-git")
    os.makedirs(plain)
    rc, err = quiet(export.main, ["--source", plain, "--no-fetch", "--data", os.path.join(tmp, "out")])
    check("export refuses a directory that is not a git checkout (exit 3)", rc == 3 and "not a git checkout" in err, (rc, err))
    repo = os.path.join(tmp, "other-repo")
    os.makedirs(repo)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    for cmd in (["init", "--quiet"], ["commit", "--quiet", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=", "-c", "commit.gpgsign=false"] + cmd, env=env,
                       check=True, capture_output=True)
    rc, err = quiet(export.main, ["--source", repo, "--no-fetch", "--ref", "HEAD", "--data", os.path.join(tmp, "out")])
    check("export refuses a commit that is not of the research repository (exit 3)",
          rc == 3 and "not a research checkout" in err, (rc, err))
    rc, err = quiet(export.main, ["--source", repo, "--no-fetch", "--allow-unmerged"])
    check("export refuses a test export into data/ (exit 2)", rc == 2 and "--data" in err, (rc, err))
    check("export writes nothing to a --data it refused", not os.path.exists(os.path.join(tmp, "out")))
    keep = os.path.join(tmp, "notes")
    os.makedirs(keep)
    with open(os.path.join(keep, "KEEP.txt"), "w", encoding="utf-8") as f:
        f.write("my notes\n")
    rc, err = quiet(export.main, ["--source", repo, "--no-fetch", "--ref", "HEAD", "--data", keep])
    check("export refuses a --data that is not data/ and not empty (exit 2), before it reads the source",
          rc == 2 and "not empty" in err, (rc, err))
    check("export keeps the files of a --data it refused", os.path.exists(os.path.join(keep, "KEEP.txt")))


LEAK_SAMPLES = [  # (text, a leak rule must match it)
    (r"C:\Users\someone\Desktop", True), ("C:/Users/someone/Desktop", True), ("/Users/someone/Library", True),
    ("someone@gmail.com", True), ("a.person+x@proton.me", True), ("100.101.102.103", True),
    ("ghp_" + "a" * 36, True), ("see the Terms of Service", True), ("in .tmp/run/x", True),
    ("abuse@provider.example", False), ("grants@fal.ai", False), ("GET /api/Users/1/", False),
    ("/home/aistudio/work", False), ("127.0.0.1:9666", False), ("100.64.0.0/10", False), ("fshy.ajam.dev", False),
    # the research process: warn level
    ("Not in dossier/compute (searched: example, no record).", True), ("it is recorded once, in dossier/x/y.json", True),
    ("a number the census did not have", True), ("the compute census stops there", True),
    ("3 percent of the 1 TB a day serving target", True),
    ("the US Census Bureau API gives 500 calls a day", False), ("a dossier of the case", True),
    ("data/records/compute/x.json", False), ("results (search: free)", False),
    # round 3, warn level
    ("The dossier holds firebase-studio.json", True), ("the existing dossier record says dead", True),
    ("Cr" + chr(0xe9) + "er un dossier partag" + chr(0xe9), False), ("le dossier de partage", False),
    ("per BRIEF " + chr(0xa7) + "0.3 escalation ladder", True), ("the provider " + chr(0xa7) + "6.1c says", False),
    ("Two corrections to batch 1.", True), ("Batch 1 carried the 30-day expiry", True),
    ("Applications for Batch 4 are closed", False), ("Batch 256 MB per request", False),
    ("Candidates: (a) the Entrance plan", True), ("Three readings were considered.", True),
    ("Log x-project/evidence/experiments/05-worker/logs/final.json", True),
    ("https://example.com/evidence/experiments/1", False),
]
HID_SAMPLES = [
    ("2026-10-28T135534Z/operator-rulings-of-2026-10-28", True), ("2026-10-24T032000Z/review-found-58-defects", True),
    ("2026-10-22T041230Z/seed-corrections-reverted", True), ("2026-10-22T061500Z/own-the-disk-is-not-an-option", True),
    ("2026-10-22T030702Z/repod-range-claim-withdrawn", False), ("2026-10-22T144500Z/hetzner-fair-use", False),
    ("2026-10-22T030705Z", False),
]
TITLE_SAMPLES = [
    ("The operator decided seven open questions", True), ("A review found 58 defects in the three answers", True),
    ("The rung was the rung we wished it had", True), ("Two seed corrections were reverted", True),
    ("Hetzner's fair-use threshold is 250 TB/month, not 50 to 100", False),
    ("Kamatera's trial needs a card, not an email", False), ("The prober's answer rates were right", True),
]


def leak_checks(tmp):
    rx = build.leak_rx(("fail", "warn"))
    wrong = [(s, want) for s, want in LEAK_SAMPLES if bool(rx.search(s)) != want]
    check("the leak rules match the leak samples and pass the technical ones (%d samples)" % len(LEAK_SAMPLES), not wrong, wrong)
    titles = [re.compile(p["re"]) for p in build.leak_rules() if p.get("scope") == "history.title"]
    wrong = [(s, want) for s, want in TITLE_SAMPLES if any(r.search(s) for r in titles) != want]
    check("the history title rule matches a narrative title and passes a correction (%d samples)" % len(TITLE_SAMPLES),
          titles and not wrong, wrong)
    hids = [re.compile(p["re"]) for p in build.leak_rules() if p.get("scope") == "history.hid"]
    wrong = [(s, want) for s, want in HID_SAMPLES if any(r.search(s) for r in hids) != want]
    check("the history id rule matches a narrative id and passes a neutral one (%d samples)" % len(HID_SAMPLES),
          hids and not wrong, wrong)
    fails = {p["id"] for p in build.leak_rules() if p.get("level", "fail") == "fail"}
    check("the rules of the research process of round 2, L15 to L20, fail", {"L15", "L16", "L17", "L18", "L19", "L20"} <= fails,
          sorted(fails))
    levels = {p.get("level", "fail") for p in build.leak_rules()}
    check("every leak rule has the level fail or warn", levels <= {"fail", "warn"}, levels)
    bad, good = os.path.join(tmp, "body-bad.md"), os.path.join(tmp, "body-good.md")
    open(bad, "w", encoding="utf-8").write("Fixes the notes. Not in dossier/compute (searched: x).\n")
    open(good, "w", encoding="utf-8").write("Fixes the notes of three records.\n")
    rc_bad, err = quiet(build.main, ["--scan", bad])
    rc_good, _ = quiet(build.main, ["--scan", good])
    check("build.py --scan exits 1 on a leak in a text file and 0 on clean text", rc_bad == 1 and "LEAK" in err and rc_good == 0,
          (rc_bad, rc_good, err))


ROBOT = chr(0x1F916)
CREDIT_LINES = [  # each must be refused by .githooks/commit-msg, as the last line of a normal message
    ROBOT + " Generated with [Claude Code](https://claude.com/claude-code)",
    "Generated with [Claude Code](https://claude.com/claude-code)",
    "Generated with Claude Code",
    "Made with Claude",
    "Generated using Claude",
    "Written with the help of Claude Opus",
    "Assisted-by: Claude",
    "Reviewed-by: Claude",
    "Signed-off-by: GPT-5 <bot@example.invalid>",
    "Co-authored-by: Claude <noreply@anthropic.com>",
    "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
    "See claude.com/claude-code for the tool.",
    "Thanks: noreply@anthropic.com",
    "Built with Copilot.",
    "Drafted by an AI assistant.",
    ROBOT,
    # a model or an assistant by name or by family, a version included
    "Built using GPT-4o",
    "Powered by Gemini",
    "Powered by OpenAI",
    "Created with ChatGPT",
    "Written by an LLM",
    "Generated by Llama 3.1 70B",
    "Made using Mistral Large",
    "Assisted by Bard",
    "Made with Codex",
    "Built with Cursor",
    "Written by an AI.",
    "Model: GPT-4o",
    "AI-Assistant: Copilot",
    "Assisted-by: Gemini 2.5 Pro",
    # a credit in the middle of a line: after a punctuation mark, or with the change as its subject
    "This commit was generated by Claude",
    "Code written by ChatGPT",
    "Parts of this change were written with Copilot",
    "docs: the page (generated with Claude)",
    "- partially generated with Gemini",
    "This PR was drafted via Llama 3.1",
]
CLEAN_MESSAGES = [  # each must pass: a provider or a model is named, nothing is credited
    "coding-subs: the Claude Pro plan is USD 20 a month",
    "inference: Gemini free tier rate limit changed",
    "records: the Copilot quota was reviewed by the merge session",
    "worker: the plan check reads a cursor of rows once",
    "inference: Llama 3.1 8B is free on Groq, and Mistral Small on La Plateforme",
    "inference: the GPT-4o price per million tokens on OpenAI",
    "email: Brevo free tier; domains-dns: OpenAI is not a registrar",
    # a vendor that made a model is not a credit (the false alarm of the merge review of round 3)
    "inference: the models made by OpenAI and Mistral on the free tier",
    "inference: list the open models built by Mistral",
    "coding-subs: the assistant built by Anthropic costs USD 20 a month",
]


def hook_checks(tmp):
    import shutil
    sh = shutil.which("sh")
    if not sh:
        print("skip  the commit-msg hook cases: no sh")
        return
    hook = os.path.join(ROOT, ".githooks", "commit-msg")

    def run(text):
        p = os.path.join(tmp, "msg.txt")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return subprocess.run([sh, hook, p], capture_output=True).returncode
    passed = [c for c in CREDIT_LINES if run("site: a change\n\nThe body says why.\n\n" + c + "\n") == 0]
    check("the commit-msg hook refuses every credit line of a tool (%d lines)" % len(CREDIT_LINES), not passed, passed)
    refused = [m for m in CLEAN_MESSAGES if run(m + "\n\nThe body says why.\n") != 0]
    check("the commit-msg hook passes a message that names a provider (%d messages)" % len(CLEAN_MESSAGES), not refused, refused)
    check("the commit-msg hook refuses a subject that ends in a full stop", run("site: a change.\n") != 0)


def js_list(src, name):
    m = re.search(r"var %s = (\[[^\]]*\]|\{[^}]*\});" % name, src)
    if not m:
        return None
    text = re.sub(r"'", '"', m.group(1))
    text = re.sub(r"([{,]\s*)([A-Za-z_][\w]*)\s*:", r'\1"\2":', text)  # bare keys
    return json.loads(text)


def list_checks(db_path):
    js = open(os.path.join(ROOT, "site", "static", "assets", "app.js"), encoding="utf-8").read()
    vt, vl, tn = js_list(js, "VT"), js_list(js, "VL"), js_list(js, "TN")
    check("app.js VL is pages.VERDICT_LABEL in the order of VT", vt is not None and vl == [pages.VERDICT_LABEL.get(v) for v in vt],
          (vt, vl))
    rules = [t["id"] for t in json.load(open(os.path.join(HERE, "rules", "topics.json"), encoding="utf-8"))["topics"]]
    check("pages.TOPICS is rules/topics.json, in its order (%d topics)" % len(rules), [t for t, _, _ in pages.TOPICS] == rules)
    check("app.js holds no copy of the topic list and reads the topic bar",
          tn == {} and "$$('.topics a')" in js and not any("'%s'" % t in js for t in rules if "-" in t), tn)
    check("app.js VT is the verdicts of pages.VERDICT_LABEL", vt is not None and set(vt) == set(pages.VERDICT_LABEL), vt)
    form = open(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "new-offer.yml"), encoding="utf-8").read()
    block = re.search(r"label: Topic\n\s+options:\n((?:\s+- .+\n)+)", form)
    opts = re.findall(r"- (\S+)", block.group(1)) if block else []
    check("the New offer form lists the topics of rules/topics.json", sorted(opts) == sorted(rules), opts)
    if not db_path:
        return
    db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    verdicts = [t for (t,) in db.execute("SELECT term FROM vocab WHERE domain='verdict' ORDER BY ord")]
    topics = {t for (t,) in db.execute("SELECT DISTINCT topic FROM record")}
    db.close()
    check("app.js VT is the store's verdict vocabulary, in its order", vt == verdicts, (vt, verdicts))
    check("every topic of the store is in rules/topics.json", topics <= set(pages.TOPIC_NAME), sorted(topics - set(pages.TOPIC_NAME)))


def helper_checks(tmp):
    """Part 6: the shared helpers, on fixed cases."""
    lw = [("Alist\u8ffd\u756a", 'Alist<span lang="zh">\u8ffd\u756a</span>'),
          ("CNB \u4e91\u539f\u751f\u6784\u5efa", 'CNB <span lang="zh">\u4e91\u539f\u751f\u6784\u5efa</span>'),
          ("\u3053\u3093\u306b\u3061\u306f world", '<span lang="ja">\u3053\u3093\u306b\u3061\u306f</span> world'),
          ("\uac00\ub098\ub2e4 x", '<span lang="ko">\uac00\ub098\ub2e4</span> x'),
          ("\u042f\u043d\u0434\u0435\u043a\u0441 \u0414\u0438\u0441\u043a", '<span lang="ru">\u042f\u043d\u0434\u0435\u043a\u0441 \u0414\u0438\u0441\u043a</span>'),
          ('<a title="\u767e\u5ea6" href="/p/x/">\u767e\u5ea6 Pan</a>', '<a title="\u767e\u5ea6" href="/p/x/"><span lang="zh">\u767e\u5ea6</span> Pan</a>'),
          ("plain ASCII", "plain ASCII")]
    bad = [(i, pages.lang_wrap(i)) for i, o in lw if pages.lang_wrap(i) != o]
    check("lang_wrap marks each run of another script with its lang, and never a tag (U-05)", not bad, bad)
    out = pages.prose("fast \u2728 and \U0001f422 slow; \u26d4 closed")
    check("prose drops the pictographs of quoted text (U-37)", not pages.EMOJI_RX.search(out) and "fast" in out, out)
    card = {"eid": "torbox", "provider": "TorBox", "topic": "debrid", "tier": None}
    cards = {r: dict(card, rid=r, slug=r.split("/")[1], tier=t) for r, t in (
        ("debrid/torbox-pro", "pro"), ("debrid/torbox-free", "free"), ("debrid/torbox-standard", None),
        ("debrid/torbox-essential", "none; the page is gone"))}
    cards["compute/torbox"] = dict(card, rid="compute/torbox", slug="torbox", topic="compute")
    cards["debrid/torbox"] = dict(card, rid="debrid/torbox", slug="torbox", topic="debrid")
    cards["storage/other"] = dict(card, rid="storage/other", eid="other", provider="Other", slug="other", topic="storage")
    got = llms.labels(cards, {"compute": "Compute"})
    want = {"debrid/torbox-pro": "TorBox (pro)", "debrid/torbox-free": "TorBox (free)",
            "debrid/torbox-standard": "TorBox (standard)", "debrid/torbox-essential": "TorBox (essential)",
            "compute/torbox": "TorBox (Compute)", "debrid/torbox": "TorBox (debrid/torbox)", "storage/other": "Other"}
    check("labels tell the records of one provider apart: tier, then slug, then topic (U-01)", got == want,
          sorted(set(got.items()) ^ set(want.items())))
    hl = [("this free plan gives 10 GB of storage and a public share link for every file that is up...",
           None, "This free plan gives 10 GB of storage and a public share link for every file that is..."),
          ("Verbatim: 'new-user trial: join the group, fill in the form and receive CNY 50' a...",
           "Free tier of 5 GB a month. Then USD 1 per GB.", "Free tier of 5 GB a month."),
          ("Short line.", None, "Short line."), ("", None, ""),
          ("Quoted: 'USD 1 in free credits'", None, "'USD 1 in free credits'"),
          ("none: Compute Engine is billed pay-as-you-go.", None, "none: Compute Engine is billed pay-as-you-go."),
          ("None of the plans is free.", None, "None of the plans is free.")]
    bad = [(a, llms.headline(a, b)) for a, b, w in hl if llms.headline(a, b) != w]
    fw = [({"free_unit": None, "verdict": "qualifies"}, ""), ({"free_unit": "none", "verdict": "qualifies"}, "no free tier"),
          ({"free_unit": "hours", "verdict": "qualifies"}, "free tier"), ({"free_unit": "mixed", "verdict": "trial-only"}, "free tier"),
          ({"free_unit": "mixed", "verdict": "paid-only"}, "no free tier"), ({"free_unit": "GB", "verdict": "dead"}, "no free tier")]
    badw = [(c, llms.free_word(c)) for c, w in fw if llms.free_word(c) != w]
    check("free_word never says 'free tier' for a paid-only or a dead offer, or for a unit of none (F-05, F-25)", not badw, badw)
    days = [("2026-10-21T00:00:00.000Z", "2026-10-21"), ("2026-10-21", "2026-10-21"), ("2026-10-21T08:30:00Z", "2026-10-21T08:30:00Z")]
    badd = [(v, llms.day(v)) for v, w in days if llms.day(v) != w]
    check("a verified date prints as YYYY-MM-DD when its time is midnight (W-32)", not badd, badd)
    check("headline drops a cut word and a quote label, prefers a whole first sentence, starts with a capital (U-09)", not bad, bad)
    rows = [{"rid": "a/x", "vorder": 0, "confidence": "reported", "stale_on": "2026-12-01"},
            {"rid": "a/y", "vorder": 0, "confidence": "measured", "stale_on": "2026-11-01"},
            {"rid": "a/z", "vorder": 0, "confidence": "measured", "stale_on": "2026-12-01"},
            {"rid": "a/w", "vorder": 0, "confidence": "measured", "stale_on": None},
            {"rid": "a/v", "vorder": 1, "confidence": "measured", "stale_on": "2027-01-01"}]
    order = [r["rid"] for r in sorted(rows, key=llms.tie_key)]
    check("a tie in a ranked list goes by verdict, evidence, the later stale date, then id (U-13)",
          order == ["a/z", "a/y", "a/w", "a/x", "a/v"], order)
    cats = {"paas": "PaaS", "ml-hub": "ML hub", "gpu cloud": "GPU cloud", "nat vps": "NAT VPS", "cloud-drive": "Cloud drive",
            "tunnel software (self-hosted)": "Tunnel software (self hosted)"}
    bad = [(k, pages.cat_label(k)) for k, w in cats.items() if pages.cat_label(k) != w]
    check("cat_label writes a category in words and its acronyms in capitals (U-27)", not bad, bad)
    hid = "2026-10-28T135534Z/operator-rulings-of-2026-10-28"
    a = pages.hist_anchor(hid)
    check("the anchor of a history entry is stable and holds no text of its id (U-04)",
          a == pages.hist_anchor(hid) and re.fullmatch(r"c-[0-9a-f]{10}", a) and "operator" not in a, a)
    fx = json.load(open(os.path.join(ROOT, "site", "worker", "test", "parity.json"), encoding="utf-8"))
    bad = [(i, site_gen.js_normalize(i), o) for i, o in fx["text"]["normalize"] if site_gen.js_normalize(i) != o]
    check("site_gen.js_normalize gives the outputs of text.js normalize in parity.json (P-16, %d cases)"
          % len(fx["text"]["normalize"]), not bad, bad[:3])
    big = os.path.join(tmp, "scan")
    os.makedirs(big)
    for i in range(24):
        with open(os.path.join(big, "f%02d.txt" % i), "w", encoding="utf-8") as f:
            f.write(("technical text about a quota\n" * 30000) + ("The Terms of Service apply.\n" if i % 6 == 0 else ""))
    serial = build.scan_files(big, jobs=1)
    parallel = build.scan_files(big, jobs=4)
    check("the parallel leak scan finds what one process finds, in the same order (P-15, %d hits)" % len(serial),
          len(serial) == 4 and serial == parallel, (len(serial), len(parallel)))


def primer_checks(db_path):
    db = primer.connect(db_path)
    for what, sql in primer.EXAMPLES:
        try:
            n = len(db.execute(sql).fetchall())
            check("primer query runs (%d rows): %s" % (n, what), True)
        except sqlite3.Error as e:
            check("primer query runs: %s" % what, False, e)
    db.close()
    text = primer.text(db_path)
    check("primer text names every worked query", all(sql in text for _, sql in primer.EXAMPLES))
    private = [w for w in ("dossier", " fr ", "history/", "scripts/", "LOCAL ONLY", "projected", "in git") if w in text]
    check("the primer names only what a reader of the public data can open", not private, private)


def keystat_checks(db_path):
    """keystat holds the largest key of every column of every table, for the statement budget of the Worker."""
    db = sqlite3.connect(db_path)
    try:
        tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE "
                                           "'text_fts%' AND name <> 'keystat'")]
        want = {(t, c) for t in tables for (c,) in db.execute("SELECT name FROM pragma_table_info(?)", (t,))}
        have = {(t, c): (n, k) for t, c, n, k in db.execute("SELECT tbl, col, distinct_n, max_key FROM keystat")}
        check("keystat has a row for each column of each table (%d columns)" % len(want), set(have) == want,
              sorted(want ^ set(have))[:5])
        wrong = []
        for t, c in sorted(want)[::7]:
            q = 'SELECT count(*), coalesce(max(k), 0) FROM (SELECT count(*) AS k FROM "%s" GROUP BY "%s")' % (t, c)
            if tuple(db.execute(q).fetchone()) != have.get((t, c)):
                wrong.append((t, c))
        check("keystat matches a recount of its columns (every seventh)", not wrong, wrong)
        schema = open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read()
        check("keystat is derived by the build, not a table of the data contract", "keystat" not in schema)
    finally:
        db.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=os.path.join(ROOT, ".tmp", "fshy", "public.db"))
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the primer's examples hold CJK text
    tmp = tempfile.mkdtemp(prefix="fshy-test-")
    try:
        contract_checks(tmp)
        export_checks(tmp)
        leak_checks(tmp)
        hook_checks(tmp)
        helper_checks(tmp)
    finally:
        export.cleanup(tmp)
    db = a.db if os.path.exists(a.db) else None
    list_checks(db)
    if db:
        primer_checks(db)
        keystat_checks(db)
    else:
        print("skip  the store parts: no %s; build it with python publish/build.py --check" % a.db)
    print("%s: %d failed" % ("PASS" if not FAILS else "FAIL", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
