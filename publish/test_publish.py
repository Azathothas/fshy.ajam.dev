#!/usr/bin/env python3
"""Selftest of the publish tools: what test_llms.py and the Worker tests do not cover.

1. The contract between export and build: build.py refuses data/ of another schema version, an unknown table
   file, an unknown or a missing column, and files that do not match files_sha256, with exit 3 and a message that
   names the problem. It reads data of the older version 1, which has no self_hosted column, as hosted records.
2. The export refuses a source that is not a research checkout (exit 3), a test export into data/ (exit 2), and a
   --data that is not data/ and not empty (exit 2), and it keeps the files of that directory.
3. The leak rules, of both levels, match each leak sample and pass each technical sample; the history title rule
   matches a narrative title and passes a correction; build.py --scan finds a leak in a text file. The commit-msg
   hook refuses every credit line of a tool and passes a message that only names a provider.
4. The lists agree. rules/topics.json is the one list of topics: pages.py reads it, app.js holds no copy and
   reads the topic bar, and the New offer form lists the same topics. The verdict labels of pages.py and app.js
   agree. When the store exists, its vocabulary and its topics agree with them.
5. Each worked query of primer.py that lists record ids sorts on self_hosted first. When the store exists: each one
   runs, so /api/v1/help.txt never shows a query that fails, and without its LIMIT it lists every hosted row first.
6. The helpers that the pages and the files for agents share: the lang of a run of another script, the label that
   tells two records of one provider apart, the one line of a row, the order of a tie in a ranked list, the words of
   a category, the anchor of a history entry, the pictographs that quoted text loses, the parallel leak scan, and
   the twin of the Worker's name normaliser against site/worker/test/parity.json.
7. Self-hosted last (selfhosted.py): the stable split of a list, the rows of a need, and the check of the build, which
   finds a hosted row below a self-hosted one, a starred self-hosted row, and a Markdown line whose verdict comes
   before the label, and passes a list in the right order; and the rule of entity.best_vorder against rank.js.

Parts 1 to 4, 6 and 7 need no data and run on a fresh clone. The store parts read .tmp/fshy/public.db, which
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
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402
import export  # noqa: E402
import llms  # noqa: E402
import pages  # noqa: E402
import primer  # noqa: E402
import selfhosted  # noqa: E402
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


def fake_data(top, version=build.SCHEMA_VERSION, tables=None, record_row=None, entity_row=None):
    """A data/ directory with an empty file per table, except a record row and an entity row when they are given. With
    an entity row, the record also gets its record file, so the build can load it."""
    os.makedirs(os.path.join(top, "tables"))
    with open(os.path.join(top, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": version, "as_of": "2026-10-28", "source_commit": "0" * 40}, f)
    for t in tables if tables is not None else ("record",) + build.TABLES:
        with open(os.path.join(top, "tables", t + ".jsonl"), "w", encoding="utf-8") as f:
            if t == "record" and record_row is not None:
                f.write(json.dumps(record_row) + "\n")
            if t == "entity" and entity_row is not None:
                f.write(json.dumps(entity_row) + "\n")
    if record_row is not None and entity_row is not None:
        p = os.path.join(top, "records", record_row["rid"] + ".json")
        os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"topic": record_row["topic"], "slug": record_row["slug"], "verdict": record_row["verdict"]}, f)


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
    # data of version 1 has no self_hosted column: the build reads it, and each record is hosted
    rec = dict(row, rid="storage/x", topic="storage", slug="x", eid="x", verdict="qualifies", vorder=0, grp="usable")
    ent = {c: None for c in cols["entity"]}
    ent.update(eid="x", name="X", best_vorder=0)
    for version, r, want in (("1", {k: v for k, v in rec.items() if k != "self_hosted"}, 0), (build.SCHEMA_VERSION, dict(rec, self_hosted=1), 1)):
        d = os.path.join(tmp, "data-v%s" % version)
        fake_data(d, version=version, record_row=r, entity_row=ent)
        out = os.path.join(tmp, "v%s.db" % version)
        rc, err = quiet(build.main, ["--data", d, "--db", out, "--check", "--quiet"])
        got = sqlite3.connect(out).execute("SELECT self_hosted FROM record").fetchall() if rc == 0 else None
        check("build reads data of schema_version %s, and the record has self_hosted %d" % (version, want),
              rc == 0 and got == [(want,)], (rc, err, got))
    d = os.path.join(tmp, "data-v2-lack")
    fake_data(d, record_row={k: v for k, v in rec.items() if k != "self_hosted"}, entity_row=ent)
    rc, err = quiet(build.main, ["--data", d, "--db", os.path.join(tmp, "lack.db"), "--check", "--quiet"])
    check("build refuses data of schema_version %s with no self_hosted column (exit 3)" % build.SCHEMA_VERSION,
          rc == 3 and "lacks ['self_hosted']" in err, (rc, err))


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
    ("2 percent of the daily serving target", True),
    ("the US Census Bureau API gives 500 calls a day", False), ("a dossier of the case", True),
    ("data/records/compute/x.json", False), ("results (search: free)", False),
    # L21 to L26
    ("The dossier holds firebase-studio.json", True), ("the existing dossier record says dead", True),
    ("Cr" + chr(0xe9) + "er un dossier partag" + chr(0xe9), False), ("le dossier de partage", False),
    ("per PLAN " + chr(0xa7) + "0.3 steps", True), ("the provider " + chr(0xa7) + "6.1c says", False),
    ("Two corrections to batch 1.", True), ("Batch 1 carried the 30-day expiry", True),
    ("Applications for Batch 4 are closed", False), ("Batch 256 MB per request", False),
    ("Candidates: (a) the Entrance plan", True), ("Three readings were considered.", True),
    ("Log x-project/evidence/experiments/05-worker/logs/final.json", True),
    ("https://example.com/evidence/experiments/1", False),
]
HID_SAMPLES = [
    ("2026-11-02T101500Z/operator-notes-of-2026-11-02", True), ("2026-11-01T032000Z/review-of-the-parser", True),
    ("2026-10-31T041230Z/seed-values-restored", True), ("2026-10-31T061500Z/disk-plans-dropped", True),
    ("2026-10-30T030702Z/range-claim-withdrawn", False), ("2026-10-30T144500Z/provider-fair-use", False),
    ("2026-10-30T030705Z", False),
]
TITLE_SAMPLES = [
    ("The operator chose two of five options", True), ("A review found 12 gaps in the first draft", True),
    ("The first draft was what we expected", True), ("Two seed claims were removed", True),
    ("Hetzner's fair-use threshold is 250 TB/month, not 50 to 100", False),
    ("Kamatera's trial needs a card, not an email", False), ("The prober's timing was right", True),
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
    check("the rules L15 to L20, which refuse the shapes of the research process, fail", {"L15", "L16", "L17", "L18", "L19", "L20"} <= fails,
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
    # a vendor that made a model is not a credit (a false alarm of the credit rule)
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
    m = re.search(r"var SH = '([^']*)';", js)
    check("app.js SH is the self-hosted label of selfhosted.py", m and m.group(1) == selfhosted.LABEL, m and m.group(1))
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
    fw = [({"free_claim": None}, ""), ({"free_claim": 0}, "no free tier"), ({"free_claim": 1}, "free tier"), ({}, ""),
          ({"free_claim": 1, "free_unit": "none", "verdict": "paid-only"}, "free tier")]
    badw = [(c, llms.free_word(c)) for c, w in fw if llms.free_word(c) != w]
    check("free_word prints 'free tier' only for the claim 1, 'no free tier' for 0, and nothing for no claim (F-05, F-25)", not badw, badw)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE claim (rid TEXT, path TEXT, kind TEXT, num REAL)")
    cs = {"a": {}, "b": {}, "c": {}}
    db.executemany("INSERT INTO claim VALUES (?, ?, ?, ?)", [("a", "$.free_tier", "has-free-tier", 1.0), ("b", "$.free_tier", "has-free-tier", 0.0),
                                                              ("a", "$.price", "price-per-tb", 3.0), ("c", "$.price", "price-per-tb", 0.0)])
    llms.attach_free_claims(db, cs)
    got = {k: v["free_claim"] for k, v in cs.items()}
    check("a record's free claim is the claim has-free-tier of the data: 1, 0, or none for a record with no such row (F-05)",
          got == {"a": 1, "b": 0, "c": None}, got)
    kinds = [({"verdict": "trial-only", "free_claim": 1, "free_unit": "hours"}, "trial"), ({"verdict": "qualifies", "free_claim": 1, "free_unit": "hours"}, "time"),
             ({"verdict": "qualifies-with-caveat", "free_claim": 1, "free_unit": "seconds"}, "time"), ({"verdict": "qualifies", "free_claim": 1, "free_unit": "mixed"}, "other"),
             ({"verdict": "qualifies", "free_claim": 1, "free_unit": "GiB"}, "other"), ({"verdict": "qualifies", "free_claim": 0, "free_unit": "hours"}, "none"),
             ({"verdict": "qualifies", "free_claim": None, "free_unit": "hours"}, "unknown")]
    badk = [(c, llms.allowance_kind(c)) for c, w in kinds if llms.allowance_kind(c) != w]
    check("allowance_kind puts a trial first; then only a claim of 1 gives a free allowance, in time or in another unit (F-15)", not badk, badk)
    cards = {"a": {"verdict": "qualifies", "free_claim": 0, "free_unit": "hours", "topic": "compute"},
             "b": {"verdict": "trial-only", "free_claim": 1, "free_unit": "mixed", "topic": "compute"},
             "c": {"verdict": "qualifies", "free_claim": 1, "free_unit": "hours", "topic": "compute"},
             "d": {"verdict": "qualifies", "free_claim": 1, "free_unit": "hours", "topic": "inference"},
             "e": {"verdict": "qualifies", "free_claim": None, "free_unit": "none", "topic": "compute"}}
    rows = [("a", 0), ("b", 1), ("c", 1), ("d", 2), ("e", 3)]
    sec = llms.need_sections(cards, {"id": "free-gpu"}, rows)
    inf = llms.need_sections(cards, {"id": "inference-no-card-no-phone"}, rows)
    check("a need that mixes kinds is split into its sections in order, with the empty ones left out and the order of the list kept (F-15, F-19)",
          [(k, [r[0] for r in rs]) for k, _, _, rs in sec] == [("time", ["c", "d"]), ("trial", ["b"]), ("none", ["a"]), ("unknown", ["e"])]
          and [(k, [r[0] for r in rs]) for k, _, _, rs in inf] == [("inference", ["d"]), ("other", ["a", "b", "c", "e"])]
          and llms.need_sections(cards, {"id": "free-storage-no-card"}, rows) is None, (sec, inf))
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
    said = [("the free tier", "10 gb free, then usd 1 per gb"), ("interface detail", "rest, oai-pmh")]
    cases = [("10 gb free, then usd 1 per gb", "the same as the free tier"), ("usd 1 per gb", "part of the free tier"),
             ("rest", "part of interface detail"), ("rest, oai-pmh", "the same as interface detail"),
             ("restful", "restful"), ("a", "a"), ("10 gb free", "part of the free tier"), ("", "")]
    bad = [(t, llms.repeat_note(said, t)) for t, w in cases if llms.repeat_note(said, t) != w]
    check("llms.repeat_note says 'the same as' for an equal text, 'part of' for a part at word boundaries, and nothing else", not bad, bad)
    first = [("the free tier", "x y"), ("notes", "x")]
    check("llms.repeat_of names an equal text before an earlier line that only holds it",
          llms.repeat_of(first, "x") == ("same", "notes") and llms.repeat_of(first, "y") == ("part", "the free tier"), llms.repeat_of(first, "x"))
    card = {"provider": "Example", "slug": "x", "verdict": "qualifies", "confidence": "documented", "identity_basis": "stated",
            "needs_card": 0, "needs_phone": 0, "needs_id": 0, "needs_institution": 0, "checked_on": "2026-10-28",
            "verified_basis": "page", "stale_on": "2027-01-01", "eid": "example", "usd_month": None, "usd_per_tb_month": None,
            "duplicate_of": None}
    doc = {"free_tier": {"stated": "10 GB free."}, "limits_note": "10 GB free.", "binding_note": "free",
           "interface_detail": "REST, OAI-PMH", "tooling": "REST", "reliability_note": "REST, OAI-PMH", "notes": "RESTful clients"}
    md = llms.record_md(types.SimpleNamespace(cards={"t/x": card}, docs={"t/x": doc}, labels={}, drift={}), "t/x")
    want = ["- limits note: the same as the free tier", "- binding note: part of the free tier", "- tooling: part of interface detail",
            "- reliability: the same as interface detail", "- notes: RESTful clients"]
    check("a record file says 'the same as' for an equal line and 'part of' for a part, and prints a text that no line holds",
          all(w in md.split("\n") for w in want), md)
    key = "\n".join(llms.reading_rules(types.SimpleNamespace(vocab={})))
    check("the key of the files for agents says that 'the same as' is an equal line and 'part of' a part of one",
          "- the same as: the value equals an earlier line" in key and "- part of: the value is a part of an earlier line" in key)
    said = []
    got = [pages.prose_once(said, "Free tier", "10 GB free, then USD 1 per GB."), pages.prose_once(said, "Notes", "10 gb free, then usd 1 per gb"),
           pages.prose_once(said, "Limits", "USD 1 per GB"), pages.prose_once(said, "Tooling", "per gb of RESTful"), pages.prose_once(said, "Binding", ""),
           pages.prose_once(said, "Binding", None)]
    check("a row that repeats an earlier text is left out, a part gets a note that names the row, other text is printed",
          got == ["10 GB free, then USD 1 per GB.", None, '<span class="na">part of the text of Free tier, above</span>',
                  "per gb of RESTful", None, None], got)
    check("an evidence cell says 'the text of' for an equal text and 'part of the text of' for a part",
          pages.repeat_html(("same", "Notes")) == '<span class="na">the text of Notes, above</span>' and
          pages.repeat_html(("part", "Notes")) == '<span class="na">part of the text of Notes, above</span>')
    cats = {"paas": "PaaS", "ml-hub": "ML hub", "gpu cloud": "GPU cloud", "nat vps": "NAT VPS", "cloud-drive": "Cloud drive",
            "tunnel software (self-hosted)": "Tunnel software (self hosted)"}
    bad = [(k, pages.cat_label(k)) for k, w in cats.items() if pages.cat_label(k) != w]
    check("cat_label writes a category in words and its acronyms in capitals (U-27)", not bad, bad)
    hid = "2026-11-02T101500Z/example-notes-of-2026-11-02"
    a = pages.hist_anchor(hid)
    check("the anchor of a history entry is stable and holds no text of its id (U-04)",
          a == pages.hist_anchor(hid) and re.fullmatch(r"c-[0-9a-f]{10}", a) and "example" not in a and "notes" not in a, a)
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


def selfhosted_checks():
    """Part 7: self-hosted last, on fixed cases."""
    got = selfhosted.hosted_first(["a", "s1", "b", "s2", "c"], lambda x: x.startswith("s"))
    check("hosted_first keeps every hosted item first and each part in its order", got == ["a", "b", "c", "s1", "s2"], got)
    fx = json.load(open(os.path.join(ROOT, "site", "worker", "test", "parity.json"), encoding="utf-8"))
    bad = [c for c in fx["rank"]["hostedFirst"] if selfhosted.hosted_first(c[0], lambda x, sh=c[1]: x in sh) != c[2]]
    check("hosted_first gives the outputs of rank.js hostedFirst in parity.json (%d cases)" % len(fx["rank"]["hostedFirst"]),
          not bad, bad[:3])
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE n (rid TEXT, v REAL)")
    db.executemany("INSERT INTO n VALUES (?, ?)", [("t/h1", 3), ("t/s1", 1), ("t/h2", None), ("t/s2", None), ("t/h3", 2)])
    cards = {r: {"rid": r, "vorder": 0, "confidence": "documented", "stale_on": None, "self_hosted": int("/s" in r)}
             for (r,) in db.execute("SELECT rid FROM n")}
    ranked, unranked, last = llms.need_rows(db, {"sql": "SELECT rid, v FROM n"}, cards)
    got = [[r[0] for r in x] for x in (ranked, unranked, last)]
    check("a need lists hosted ranked, hosted with no number, then self-hosted ranked and with no number",
          got == [["t/h3", "t/h1"], ["t/h2"], ["t/s1", "t/s2"]], got)
    db.close()
    # a need that asks for no card: the hosted rows whose card is not stated follow the hosted rows, and every
    # self-hosted row, the one whose card is not stated too, comes after them
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE n (rid TEXT, v REAL, needs_card INTEGER, identity_basis TEXT)")
    db.executemany("INSERT INTO n VALUES (?, ?, ?, ?)", [("t/h1", 1, 0, "stated"), ("t/s1", 0, 0, "stated"),
                                                        ("t/hu", 2, None, "stated"), ("t/su", 3, None, "defaulted"),
                                                        ("t/hx", 0, 1, "stated")])
    cards = {r: {"rid": r, "vorder": 0, "confidence": "documented", "stale_on": None, "self_hosted": int("/s" in r),
                 "needs_card": c} for r, c in db.execute("SELECT rid, needs_card FROM n")}
    x = {"sql": "SELECT rid, v FROM n WHERE v IS NOT NULL AND needs_card=0 AND identity_basis='stated'"}
    ranked, unranked, unstated, text, last, last_unstated = llms.need_lists(db, x, cards)
    got = [[r[0] for r in y] for y in (ranked, unranked, unstated, last, last_unstated)]
    check("a need that asks for no card lists hosted ranked, hosted not stated, then the self-hosted rows, those whose card "
          "is not stated apart", got == [["t/h1"], [], ["t/hu"], ["t/s1"], ["t/su"]] and text, got)
    db.close()
    sh = {"storage/self"}

    def row(rid, pill):
        t, s = rid.split("/")
        return '<li class="e" data-f="">%s<a class="n" href="/p/e/#%s--%s">x</a><p class="f"></p></li>' % (pill, t, s)
    ok_pill, star = selfhosted.PILL, '<span class="v v-qualifies">\u2605 qualifies</span>'
    good = row("storage/hosted", star) + row("storage/self", ok_pill)
    cases = [("a hosted row, then the self-hosted row with its label", good, 0),
             ("a self-hosted row above a hosted row", row("storage/self", ok_pill) + row("storage/hosted", star), 1),
             ("a self-hosted row with the star of its verdict", row("storage/hosted", star) + row("storage/self", star), 1),
             ("a record section of a self-hosted record above a hosted one",
              '<section class="rec" id="storage--self"><dl class="facts">%s</dl></section>'
              '<section class="rec" id="storage--hosted"><dl class="facts">%s</dl></section>' % (ok_pill, star), 1)]
    bad = [(what, selfhosted.html_problems(h, sh)) for what, h, n in cases if len(selfhosted.html_problems(h, sh)) != n]
    check("the check of the build finds a self-hosted row above a hosted one, or starred, in HTML (%d cases)" % len(cases),
          not bad, bad)

    def md(rid, label="first", link=False):
        words = {"first": selfhosted.LABEL + " | verdict qualifies", "after": "qualifies | " + selfhosted.LABEL,
                 None: "qualifies"}[label if rid == "storage/self" else None]
        code = ("[`%s`](https://example.invalid/api/v1/record/%s)" % (rid, rid)) if link else "`%s`" % rid
        return "- [X](https://example.invalid/p/e.md) %s: %s | free tier" % (code, words)
    cases = [("a hosted line, then the self-hosted line", md("storage/hosted") + "\n" + md("storage/self"), 0),
             ("a self-hosted line above a hosted line", md("storage/self") + "\n" + md("storage/hosted"), 1),
             ("a self-hosted line with no label", md("storage/hosted") + "\n" + md("storage/self", None), 1),
             ("a self-hosted line with its verdict before the label", md("storage/hosted") + "\n" + md("storage/self", "after"), 1),
             ("lines that link the JSON of their record, a self-hosted one above a hosted one",
              md("storage/self", link=True) + "\n" + md("storage/hosted", link=True), 1),
             ("a linked self-hosted line with its verdict before the label",
              md("storage/hosted", link=True) + "\n" + md("storage/self", "after", link=True), 1),
             ("linked lines in order", md("storage/hosted", link=True) + "\n" + md("storage/self", link=True), 0),
             ("a numbered need line", "1. USD 2/month | " + md("storage/hosted")[2:] + "\n2. " + md("storage/self")[2:], 0),
             ("a record block of a self-hosted record above a hosted one",
              "- `storage/self` | %s | verdict qualifies | evidence measured\n- `storage/hosted` | qualifies | evidence "
              "measured" % selfhosted.LABEL, 1),
             ("a record block of a self-hosted record with its verdict first",
              "- `storage/hosted` | qualifies | evidence measured\n- `storage/self` | qualifies | %s | evidence measured"
              % selfhosted.LABEL, 1)]
    bad = [(what, selfhosted.md_problems(t, sh)) for what, t, n in cases if len(selfhosted.md_problems(t, sh)) != n]
    check("the check of the build finds a self-hosted line above a hosted one, or with no label first, in Markdown (%d "
          "cases)" % len(cases), not bad, bad)
    c = {"verdict": "qualifies", "self_hosted": 1}
    check("a self-hosted record's Markdown line opens with the label, then its verdict",
          llms.verdict_words(c) == [selfhosted.LABEL, "verdict qualifies"] and llms.verdict_words(dict(c, self_hosted=0)) ==
          ["qualifies"], llms.verdict_words(c))
    # entity.best_vorder: the SQL rule of the build gives the outputs of rank.js bestVorder in parity.json
    rows = []
    for members, want in fx["rank"]["bestVorder"]:
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE record (rid TEXT, eid TEXT, vorder INTEGER, self_hosted INTEGER)")
        db.execute("CREATE TABLE entity (eid TEXT, best_vorder INTEGER)")
        db.executemany("INSERT INTO record VALUES (?, 'e', ?, ?)", [("t/%d" % i, v, s) for i, (v, s) in enumerate(members)])
        db.execute("INSERT INTO entity VALUES ('e', ?)", (want,))
        ok = not selfhosted.best_vorder_problems(db)
        db.execute("UPDATE entity SET best_vorder = coalesce(best_vorder, 0) + 1")
        rows.append((ok and len(selfhosted.best_vorder_problems(db)) == 1, members, want))
        db.close()
    bad = [r[1:] for r in rows if not r[0]]
    check("best_vorder_problems follows rank.js bestVorder in parity.json (%d cases), and finds a wrong value" % len(rows),
          not bad, bad)


# a worked query that lists record ids, and the first key of its ORDER BY
LISTS_RIDS = re.compile(r"^SELECT (?:\w+\.)?rid\b")
SELF_HOSTED_FIRST = re.compile(r"\bORDER BY (?:\w+\.)?self_hosted\b")
LIMIT_TAIL = re.compile(r"\s+LIMIT \d+\s*$")


def primer_order_checks():
    """Every worked query of the primer that lists record ids sorts on self_hosted first, so a reader who pages it or
    raises its LIMIT still gets every hosted row before a self-hosted one."""
    lists = [(what, sql) for what, sql in primer.EXAMPLES if LISTS_RIDS.match(sql)]
    bad = [what for what, sql in lists if not SELF_HOSTED_FIRST.search(sql)]
    check("each worked query of the primer that lists record ids sorts on self_hosted first (%d queries)" % len(lists),
          lists and not bad, bad)


def primer_checks(db_path):
    db = primer.connect(db_path)
    sh = {r for (r,) in db.execute("SELECT rid FROM record WHERE self_hosted = 1")}
    for what, sql in primer.EXAMPLES:
        try:
            n = len(db.execute(sql).fetchall())
            check("primer query runs (%d rows): %s" % (n, what), True)
            if LISTS_RIDS.match(sql):
                # the whole list, without its LIMIT: a hosted row is never below a self-hosted one
                flags = [r[0] in sh for r in db.execute(LIMIT_TAIL.sub("", sql))]
                check("primer query lists every hosted row first, without its LIMIT (%d rows, %d self-hosted): %s"
                      % (len(flags), sum(flags), what), flags == sorted(flags))
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
        selfhosted_checks()
        primer_order_checks()
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
