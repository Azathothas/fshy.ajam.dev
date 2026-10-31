#!/usr/bin/env python3
"""export.py: one commit of the research corpus -> data/, the published corpus. Only a merge session runs it.

usage:
  python publish/export.py --source PATH                PATH is a checkout of the private research repository
  python publish/export.py --source PATH --ref COMMIT   export another commit; it must be on origin/main

1. Fetch origin in PATH and resolve the ref (default origin/main) to one commit. A commit that is not on
   origin/main is refused, because only merged research is published.
2. Check out that commit into a temporary clone that shares the objects of PATH. The export never reads the
   working tree of PATH, so an edit that is not committed cannot reach data/. The fetch is the only write to PATH.
3. Build the public store in that clone with the research repository's own projection and leak scan:
   python CLONE/scripts/fshy/build.py --repo CLONE --public TMP. The projection rules stay in that repository,
   because they name what they remove.
4. Check the contract: the store's schema version, tables and columns are the ones publish/schema.sql gives,
   and rules/needs.json is the research copy. A store of an older version that build.py reads (build.OLDER) is
   checked without the columns that the version lacks, and data/ gets that version.
5. Write each record as data/records/<topic>/<slug>.json and each other table as data/tables/<table>.jsonl,
   sorted, with no row numbers, so the diff of a publish shows exactly which records changed. meta.json names
   the commit as source_commit.
6. Build a store from the written files with publish/build.py and compare each table with the research store.
   A value that the build drops or changes stops the export.
7. Scan every written file with this repository's leak rules, of both levels, and with the research
   repository's leak rules. meta.json gets files_sha256, a digest of every written file, which build.py checks.

With one failed check or one leak hit, data/ does not change. The target is data/ of this repository, or a new or
empty directory: the export refuses any other --data, because it replaces its target.
Exit codes: 0 written, 1 a check failed, 2 usage, 3 the source is not a research checkout.
"""
import argparse
import collections
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402

DEFAULT_REF = "origin/main"
# files a commit must hold to be a commit of the research repository
RESEARCH_PATHS = ("dossier", "scripts/fshy/build.py", "scripts/fshy/schema.sql", "scripts/fshy/rules/projection.json",
                  "scripts/fshy/rules/needs.json")
# record columns that are positions in one build, or that describe a private file
RECORD_DROP = ("rno", "lid_min", "lid_max", "doc", "sha256", "path")
# columns that point at files in the research repository; data/ keeps the hash and the URL instead
NULLED = {"evidence": ("capture",), "capture": ("path",)}
META_KEEP = ("schema_version", "as_of")


class Refused(Exception):
    """A check failed. code is the exit code."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise Refused("git %s failed in %s: %s" % (" ".join(args), repo, (r.stderr or r.stdout).strip()[-400:]))
    return r if not check else r.stdout.strip()


def rmtree(path):
    """Remove a tree that holds read-only git objects (Windows)."""
    def again(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if not os.path.exists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def cleanup(path):
    """Remove the scratch tree; a failure is a warning, never the result of the export."""
    try:
        rmtree(path)
    except OSError as e:
        print("export: warning: could not remove %s: %s" % (path, e), file=sys.stderr)


def resolve(source, ref, fetch, allow_unmerged):
    """-> (top of the checkout, commit). Refuses a source that is not a research checkout."""
    r = git(source, "rev-parse", "--show-toplevel", check=False)
    if r.returncode != 0:
        raise Refused("%s is not a git checkout" % source, 3)
    top = os.path.abspath(r.stdout.strip())
    if fetch:
        git(top, "fetch", "--quiet", "origin")
    r = git(top, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
    if r.returncode != 0:
        raise Refused("%s names no commit in %s" % (ref, top), 2)
    commit = r.stdout.strip()
    missing = [p for p in RESEARCH_PATHS if git(top, "cat-file", "-e", "%s:%s" % (commit, p), check=False).returncode]
    if missing:
        raise Refused("commit %s of %s has no %s: it is not a research checkout" % (commit[:12], top, ", ".join(missing)), 3)
    if not allow_unmerged and git(top, "merge-base", "--is-ancestor", commit, DEFAULT_REF, check=False).returncode:
        raise Refused("commit %s is not on %s; only merged research is published" % (commit[:12], DEFAULT_REF))
    return top, commit


def checkout(top, commit, dest):
    """A clone of `top` at `commit` that shares its objects. The bytes are the committed bytes: no line-end
    conversion, whatever the settings of the machine."""
    git(top, "clone", "--quiet", "--shared", "--no-checkout", top, dest)
    git(dest, "-c", "core.autocrlf=false", "-c", "core.eol=lf", "checkout", "--quiet", "--detach", commit)
    got = git(dest, "rev-parse", "HEAD")
    if got != commit:
        raise Refused("the clone is at %s, not at %s" % (got, commit))


def dump_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def tables_of(db):
    """{table: [columns]} of every table in a store, the full-text tables included."""
    return {t: [c[1] for c in db.execute('PRAGMA table_info("%s")' % t)]
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}


def drift(tree):
    """Copies that should be equal in both repositories, and whose difference does not change data/: the worked
    queries of the primer and the commit-msg hook. -> [warning]; the export prints them and goes on."""
    import importlib.util
    warnings = []
    ours = os.path.join(ROOT, ".githooks", "commit-msg")
    theirs = os.path.join(tree, ".githooks", "commit-msg")
    if os.path.exists(theirs) and open(ours, "rb").read() != open(theirs, "rb").read():
        warnings.append(".githooks/commit-msg differs from the research copy; copy the newer one to the other repository")
    path = os.path.join(tree, "scripts", "fshy", "primer.py")
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location("research_primer", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            import primer
            if getattr(mod, "EXAMPLES", None) != primer.EXAMPLES:
                warnings.append("the worked queries (EXAMPLES) of publish/primer.py differ from the research primer")
        except Exception as e:  # a primer that does not load is a warning too, never a stop
            warnings.append("the research primer does not load: %s" % e)
    return warnings


def store_version(pub_db):
    db = sqlite3.connect("file:%s?mode=ro" % pub_db, uri=True)
    try:
        return (db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() or [None])[0]
    finally:
        db.close()


def contract(pub_db, tree):
    """The research store and its rules against this repository's schema and rules. -> [problem]. A store of a version
    of build.OLDER is checked against schema.sql without the columns that the version lacks, and is exported at its
    version: a change of the schema lands here first, and the next publish does not stop."""
    problems = []
    want_db = sqlite3.connect(":memory:")
    want_db.executescript(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    want = tables_of(want_db)
    want_db.close()
    db = sqlite3.connect("file:%s?mode=ro" % pub_db, uri=True)
    have = tables_of(db)
    db.close()
    version = store_version(pub_db)
    if version != build.SCHEMA_VERSION and version not in build.OLDER:
        problems.append("the research store has schema_version %r; publish/build.py reads %r and %s"
                        % (version, build.SCHEMA_VERSION, ", ".join(map(repr, sorted(build.OLDER)))))
    for t, cs in build.OLDER.get(version, {}).items():
        want[t] = [c for c in want.get(t, []) if c not in cs]
    for t in sorted(set(want) | set(have)):
        if t not in have:
            problems.append("table %s is in publish/schema.sql but not in the research store" % t)
        elif t not in want:
            problems.append("table %s is in the research store but not in publish/schema.sql" % t)
        elif want[t] != have[t]:
            problems.append("table %s has columns %s in the research store and %s in publish/schema.sql"
                            % (t, ",".join(have[t]), ",".join(want[t])))
    ours = json.load(open(os.path.join(HERE, "rules", "needs.json"), encoding="utf-8"))
    theirs = json.load(open(os.path.join(tree, "scripts", "fshy", "rules", "needs.json"), encoding="utf-8"))
    if ours != theirs:
        problems.append("publish/rules/needs.json differs from scripts/fshy/rules/needs.json of the research commit")
    schema_json = os.path.join(tree, "scripts", "dossier", "schema.json")
    if os.path.exists(schema_json):
        enum = json.load(open(schema_json, encoding="utf-8")).get("properties", {}).get("topic", {}).get("enum") or []
        known = {t["id"] for t in json.load(open(os.path.join(HERE, "rules", "topics.json"), encoding="utf-8"))["topics"]}
        missing = sorted(set(enum) - known)
        if missing:
            problems.append("the research schema has the topic(s) %s, and publish/rules/topics.json does not" % missing)
    return problems


def export(pub_db, out, commit):
    db = sqlite3.connect("file:%s?mode=ro" % pub_db, uri=True)
    db.row_factory = sqlite3.Row
    os.makedirs(os.path.join(out, "records"))
    os.makedirs(os.path.join(out, "tables"))
    recs = []
    for r in db.execute("SELECT * FROM record ORDER BY rid"):
        row = {k: r[k] for k in r.keys()}
        p = os.path.join(out, "records", row["rid"] + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(json.loads(row["doc"]), ensure_ascii=False, indent=2) + "\n")
        recs.append({k: v for k, v in row.items() if k not in RECORD_DROP})
    dump_jsonl(os.path.join(out, "tables", "record.jsonl"), recs)
    counts = {"record": len(recs)}
    for t in build.TABLES:
        rows = []
        for r in db.execute("SELECT * FROM %s" % t):
            row = {k: r[k] for k in r.keys()}
            for k in NULLED.get(t, ()):
                row[k] = None
            rows.append(row)
        rows.sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
        dump_jsonl(os.path.join(out, "tables", t + ".jsonl"), rows)
        counts[t] = len(rows)
    meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
    db.close()
    if meta.get("commit") != commit:
        raise Refused("the research build stamped commit %r, not %s" % (meta.get("commit"), commit))
    m = {k: meta.get(k) for k in META_KEEP}
    m["source_commit"] = commit
    m["counts"] = json.loads(meta.get("counts") or "{}")  # the projection's own accounting, read by the wiki
    m["tables"] = counts
    m["files_sha256"] = build.files_digest(out)  # build.py recomputes it, so a hand edit of data/ shows
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return counts


def fts_terms(db):
    """Every (term, column, documents, occurrences) of the full-text index. The index holds no text
    (content=""), and the row numbers differ between two builds, so the term statistics are what can be compared."""
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_terms USING fts4aux(main, text_fts)")
    return collections.Counter(db.execute("SELECT term, col, documents, occurrences FROM temp.fts_terms"))


def roundtrip(pub_db, out, tmp):
    """Build a store from data/ with publish/build.py and compare each table with the research store."""
    store = os.path.join(tmp, "roundtrip.db")
    try:
        build.build(out, store)
    except build.DataError as e:
        return ["publish/build.py refuses the written data: %s" % e]
    a = sqlite3.connect("file:%s?mode=ro" % pub_db, uri=True)
    b = sqlite3.connect("file:%s?mode=ro" % store, uri=True)
    try:
        return compare_stores(a, b, build.OLDER.get(store_version(pub_db), {}))
    finally:
        a.close()
        b.close()


def compare_stores(a, b, lacks=None):
    """The research store a against the store b that publish/build.py made from data/. -> [problem]. lacks names the
    columns, by table, that the version of a does not have: b holds them with their defaults, and they are not
    compared."""
    problems = []
    lacks = lacks or {}

    def compare(name, x, y):
        if x == y:
            return
        if isinstance(x, dict) and not isinstance(x, collections.Counter):
            keys = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
            problems.append("%s: %d record(s) differ, first %s" % (name, len(keys), keys[:3]))
        else:
            x, y = collections.Counter(x), collections.Counter(y)
            problems.append("%s: %d research row(s) and %d built row(s) have no twin"
                            % (name, sum((x - y).values()), sum((y - x).values())))

    def table(db, t, drop=(), null=()):
        cur = db.execute("SELECT * FROM %s" % t)
        cols = [c[0] for c in cur.description]
        out = collections.Counter()
        for r in cur:
            row = {c: (None if c in null else v) for c, v in zip(cols, r) if c not in drop}
            out[json.dumps(row, sort_keys=True, ensure_ascii=False)] += 1
        return out

    for t in build.TABLES:
        compare(t, table(a, t, null=NULLED.get(t, ())), table(b, t, drop=lacks.get(t, ())))
    keep = [c for c in tables_of(a)["record"] if c not in RECORD_DROP]
    recs = []
    for db in (a, b):
        recs.append({r[0]: r[1:] for r in db.execute("SELECT %s, doc FROM record" % ",".join(keep))})
        for rid, v in recs[-1].items():
            recs[-1][rid] = v[:-1] + (json.loads(v[-1]),)
    compare("record", recs[0], recs[1])
    compare("text_fts", fts_terms(a), fts_terms(b))
    rno = [dict(db.execute("SELECT rno, rid FROM record")) for db in (a, b)]
    leaves = [set((m[r[0]],) + tuple(r[1:]) for r in db.execute("SELECT rno, path, type, value FROM leaf"))
              for db, m in zip((a, b), rno)]
    compare("leaf", *leaves)
    return problems


def source_leak_rx(tree):
    rules = json.load(open(os.path.join(tree, "scripts", "fshy", "rules", "projection.json"), encoding="utf-8"))
    return re.compile("|".join("(?:%s)" % p for p in rules["leak_scan"]))


def check_target(data, allow_unmerged):
    """The export replaces its target. It writes only to data/ of this repository, or to a directory that is new or
    empty, so a mistyped --data never deletes somebody's files."""
    default = os.path.normcase(data) == os.path.normcase(os.path.join(ROOT, "data"))
    if allow_unmerged and default:
        raise Refused("--allow-unmerged writes a test export only: give --data with another directory", 2)
    if not default and os.path.exists(data) and (not os.path.isdir(data) or os.listdir(data)):
        raise Refused("--data %s exists and is not empty. The export writes only to data/ of this repository, or to a "
                      "new or empty directory" % data, 2)


def replace_dir(out, data):
    """Move `out` to `data`. An old `data` is renamed aside first and removed last, and it is put back if the move
    fails, so there is never a moment with no data/ and a failure leaves the old one."""
    old = None
    if os.path.exists(data):
        old = "%s.old-%d" % (data, os.getpid())
        os.rename(data, old)
    try:
        shutil.move(out, data)
    except OSError:
        if old:
            rmtree(data)
            os.rename(old, data)
        raise
    if old:
        cleanup(old)


def run(a):
    data = os.path.abspath(a.data)
    check_target(data, a.allow_unmerged)
    top, commit = resolve(os.path.abspath(a.source), a.ref, not a.no_fetch, a.allow_unmerged)
    tmp = tempfile.mkdtemp(prefix="fshy-export-")
    try:
        tree = os.path.join(tmp, "src")
        checkout(top, commit, tree)
        pub = os.path.join(tmp, "public.db")
        env = {k: v for k, v in os.environ.items() if k != "WORKERS_CI_COMMIT_SHA"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        r = subprocess.run([sys.executable, os.path.join(tree, "scripts", "fshy", "build.py"), "--repo", tree,
                            "--public", pub, "--quiet"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
        if r.returncode != 0 or not os.path.exists(pub):
            raise Refused("the research build refused (exit %d):\n%s" % (r.returncode, (r.stderr or r.stdout)[-2000:]))
        problems = contract(pub, tree)
        if problems:
            raise Refused("the research store does not match this repository:\n  " + "\n  ".join(problems))
        for w in drift(tree):
            print("export: warning: %s" % w, file=sys.stderr)
        out = os.path.join(tmp, "data")
        counts = export(pub, out, commit)
        problems = roundtrip(pub, out, tmp)
        if problems:
            raise Refused("publish/build.py does not rebuild the research store from the written data:\n  "
                          + "\n  ".join(problems))
        # both levels: a warn rule only warns in the build of data that is already on main, never in a new export
        hits = build.leak_scan(data=out, levels=("fail", "warn"))
        rx = source_leak_rx(tree)
        for root, _, files in os.walk(out):
            for fn in files:
                p = os.path.join(root, fn)
                if rx.search(open(p, encoding="utf-8").read()):
                    hits.append((os.path.relpath(p, out), "a research leak rule matched", "research"))
        if hits:
            for where, ctx, rid in hits[:40]:
                print("LEAK %s %s: %s" % (where, rid, ctx.replace("\n", " ")[:200]), file=sys.stderr)
            raise Refused("%d leak hit(s), by rule: %s" % (len(hits), ", ".join(
                "%s %d" % (k, v) for k, v in sorted(collections.Counter(h[2] for h in hits).items()))))
        replace_dir(out, data)
        return {"written": os.path.relpath(data, ROOT).replace(os.sep, "/"), "source_commit": commit, "counts": counts}
    finally:
        cleanup(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, help="checkout of the research repository")
    ap.add_argument("--ref", default=DEFAULT_REF, help="the commit to export (default %s)" % DEFAULT_REF)
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch origin first")
    ap.add_argument("--allow-unmerged", action="store_true",
                    help="export a commit that is not on %s; a test export into another --data only" % DEFAULT_REF)
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    a = ap.parse_args(argv)
    try:
        report = run(a)
    except Refused as e:
        print("export: %s" % e, file=sys.stderr)
        if e.code == 1:
            print("export: %s is unchanged" % a.data, file=sys.stderr)
        return e.code
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
