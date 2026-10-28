#!/usr/bin/env python3
"""Selftest of the publish tools: what test_llms.py and the Worker tests do not cover.

1. The contract between export and build: build.py refuses data/ of another schema version, an unknown table
   file, and an unknown or a missing column, with exit 3 and a message that names the problem.
2. The export refuses a source that is not a research checkout (exit 3), and a test export into data/ (exit 2).
3. The leak rules match each leak sample and pass each technical sample.
4. The lists that are copied by hand agree: the topics and the verdict labels in pages.py, app.js and the New
   offer form, and, when the store exists, the store's own vocabularies and topics.
5. When the store exists: each worked query of primer.py runs, so /api/v1/help.txt never shows a query that
   fails.

Parts 1 to 4 need no data and run on a fresh clone. The store parts read .tmp/fshy/public.db, which
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
import pages  # noqa: E402
import primer  # noqa: E402

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


LEAK_SAMPLES = [  # (text, a leak rule must match it)
    (r"C:\Users\someone\Desktop", True), ("C:/Users/someone/Desktop", True), ("/Users/someone/Library", True),
    ("someone@gmail.com", True), ("a.person+x@proton.me", True), ("100.101.102.103", True),
    ("ghp_" + "a" * 36, True), ("see the Terms of Service", True), ("in .tmp/run/x", True),
    ("abuse@provider.example", False), ("grants@fal.ai", False), ("GET /api/Users/1/", False),
    ("/home/aistudio/work", False), ("127.0.0.1:9666", False), ("100.64.0.0/10", False), ("fshy.ajam.dev", False),
]


def leak_checks():
    rx = build.leak_rx()
    wrong = [(s, want) for s, want in LEAK_SAMPLES if bool(rx.search(s)) != want]
    check("the leak rules match the leak samples and pass the technical ones (%d samples)" % len(LEAK_SAMPLES), not wrong, wrong)


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
    check("app.js TN is pages.TOPICS", tn == pages.TOPIC_NAME, (tn, pages.TOPIC_NAME))
    check("app.js VT is the verdicts of pages.VERDICT_LABEL", vt is not None and set(vt) == set(pages.VERDICT_LABEL), vt)
    form = open(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "new-offer.yml"), encoding="utf-8").read()
    block = re.search(r"label: Topic\n\s+options:\n((?:\s+- .+\n)+)", form)
    opts = re.findall(r"- (\S+)", block.group(1)) if block else []
    check("the New offer form lists the topics of pages.TOPICS", sorted(opts) == sorted(pages.TOPIC_NAME), opts)
    if not db_path:
        return
    db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    verdicts = [t for (t,) in db.execute("SELECT term FROM vocab WHERE domain='verdict' ORDER BY ord")]
    topics = {t for (t,) in db.execute("SELECT DISTINCT topic FROM record")}
    db.close()
    check("app.js VT is the store's verdict vocabulary, in its order", vt == verdicts, (vt, verdicts))
    check("every topic of the store has a page in pages.TOPICS", topics <= set(pages.TOPIC_NAME), sorted(topics - set(pages.TOPIC_NAME)))


def primer_checks(db_path):
    db = primer.connect(db_path)
    for what, sql in primer.EXAMPLES:
        try:
            n = len(db.execute(sql).fetchall())
            check("primer query runs (%d rows): %s" % (n, what), True)
        except sqlite3.Error as e:
            check("primer query runs: %s" % what, False, e)
    db.close()
    check("primer text names every worked query", all(sql in primer.text(db_path) for _, sql in primer.EXAMPLES))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=os.path.join(ROOT, ".tmp", "fshy", "public.db"))
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the primer's examples hold CJK text
    tmp = tempfile.mkdtemp(prefix="fshy-test-")
    try:
        contract_checks(tmp)
        export_checks(tmp)
    finally:
        export.cleanup(tmp)
    leak_checks()
    db = a.db if os.path.exists(a.db) else None
    list_checks(db)
    if db:
        primer_checks(db)
    else:
        print("skip  the store parts: no %s; build it with python publish/build.py --check" % a.db)
    print("%s: %d failed" % ("PASS" if not FAILS else "FAIL", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
