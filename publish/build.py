#!/usr/bin/env python3
"""build.py: data/ (the published corpus) -> the fshy store (SQLite), and with --site the wiki, the API files
and the Worker copy.

usage:
  python publish/build.py --check               build the store into .tmp/fshy/, verify it, exit 0 or 1
  python publish/build.py --site site/dist      the store, the Worker copy, the wiki and the API files

The only input is data/. Every file in it is written by publish/export.py from the projection of the research
corpus; nothing in data/ is edited by hand. The store is derived and never committed. Standard library only.

The contract with the export: data/meta.json names the schema_version of the data, and data/tables/ holds one
file per table of schema.sql with exactly its columns. This build reads SCHEMA_VERSION only. It refuses data of
another version, an unknown table file and an unknown or missing column, because a load through the schema would
drop or blank that value without a message.
Exit codes: 0 ok, 1 a check failed, 2 usage, 3 data/ does not match this build (version, tables or columns).
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

SCHEMA_VERSION = "1"  # the version of data/ this build reads; publish/export.py writes the same one
DERIVED = ("rno", "lid_min", "lid_max", "doc", "sha256", "path")  # record columns build() makes, never in data/
TABLES = ("entity", "alias", "evidence", "limit_row", "claim", "fx", "unknown", "edge", "drift", "history",
          "history_link", "ledger", "capture", "vocab")
FTS_COLUMNS = ("name", "offer", "limits", "egress", "identity", "access", "notes", "evidence", "extras")
# Workers static assets: the largest file a version can hold. The build fails above it and warns above WARN_SHARE.
ASSET_MAX_BYTES = 25 * 1024 * 1024
WARN_SHARE = 0.7
TIMES = collections.OrderedDict()
_T = [time.perf_counter()]


def lap(name):
    t = time.perf_counter()
    TIMES[name] = round(t - _T[0], 2)
    _T[0] = t


def leaves(v, p=()):
    """Yield (path tuple, value) for every leaf; an empty dict or list is a leaf."""
    if isinstance(v, dict):
        if not v:
            yield p, v
        for k, x in v.items():
            yield from leaves(x, p + (k,))
    elif isinstance(v, list):
        if not v:
            yield p, v
        for i, x in enumerate(v):
            yield from leaves(x, p + (i,))
    else:
        yield p, v


def jpath(p):
    """SQLite JSON path that keeps dynamic keys exactly: $.extras."NAT Start".price."""
    out = "$"
    for k in p:
        if isinstance(k, int):
            out += "[%d]" % k
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            out += "." + k
        else:
            out += '."' + k.replace('"', '\\"') + '"'
    return out


CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]+")
URLISH = re.compile(r"^(?:https?:|probe:)")


def fts_text(s):
    """Index text: CJK runs also emitted as overlapping bigrams (shared rule: site/worker/text.js)."""
    def rep(m):
        t = m.group(0)
        return t + " " + (" ".join(t[i:i + 2] for i in range(len(t) - 1)) if len(t) > 1 else t)
    return CJK.sub(rep, s)


def _texts(v):
    for _, x in leaves(v):
        if isinstance(x, str) and x and not URLISH.match(x):
            yield x


def fts_columns(o, url, aliases, ent):
    """One row of text_fts: the record's prose grouped into the FTS_COLUMNS, CJK expanded."""
    g = lambda k: o.get(k)
    cols = {
        "name": [g("provider"), g("slug"), g("category"), g("tier"), ent["name"], ent["domain"] or "", url or ""] + list(aliases),
        "offer": list(_texts([g("free_tier"), g("per_object_cap"), g("retention"), g("price_per_tb_month")])),
        "limits": list(_texts([g("limits"), g("limits_note"), g("binding_note")])),
        "egress": list(_texts(g("egress"))),
        "identity": list(_texts(g("identity_cost"))),
        "access": list(_texts([g("interface"), g("interface_detail"), g("tooling"), g("endpoint")])),
        "notes": list(_texts([g("notes"), g("reliability_note"), g("chaining"), g("confidence_note")])),
        "evidence": [e.get("proved") or "" for e in (g("evidence") or []) if isinstance(e, dict)],
        "extras": list(_texts(g("extras"))),
    }
    return tuple(fts_text(" ".join(x for x in cols[c] if x)) for c in FTS_COLUMNS)


class DataError(Exception):
    """data/ is not what this build reads: another schema version, or another set of tables or columns."""


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def read_meta(data):
    """data/meta.json, after the version and the set of table files are checked."""
    meta = json.load(open(os.path.join(data, "meta.json"), encoding="utf-8"))
    v = meta.get("schema_version")
    if v != SCHEMA_VERSION:
        raise DataError("data/meta.json has schema_version %r, and this build reads schema_version %r only. The export "
                        "and publish/ disagree: update publish/ (schema.sql, build.py) to the version of the data, or "
                        "export again with this publish/." % (v, SCHEMA_VERSION))
    tdir = os.path.join(data, "tables")
    have = {f[:-len(".jsonl")] for f in os.listdir(tdir) if f.endswith(".jsonl")} if os.path.isdir(tdir) else set()
    want = {"record"} | set(TABLES)
    if have != want:
        raise DataError("data/tables/ has the unknown table file(s) %s and lacks %s"
                        % (sorted(have - want) or "none", sorted(want - have) or "none"))
    return meta


def table_rows(data, t, cols):
    """The rows of data/tables/<t>.jsonl, refused when their keys are not exactly `cols`."""
    rows = read_jsonl(os.path.join(data, "tables", t + ".jsonl"))
    keys = set().union(*rows) if rows else set()
    extra, lack = keys - set(cols), (set(cols) - keys) if rows else set()
    if extra or lack:
        raise DataError("data/tables/%s.jsonl has the column(s) %s that schema.sql does not have, and lacks %s"
                        % (t, sorted(extra) or "none", sorted(lack) or "none"))
    return rows


def git_info():
    """The commit of this checkout, and its commit time in UTC: a time zone names a place."""
    def run(*a):
        try:
            return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            return ""
    ts = run("log", "-1", "--format=%ct")
    when = (datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if ts.isdigit() else "")
    return os.environ.get("WORKERS_CI_COMMIT_SHA") or run("rev-parse", "HEAD"), when


def build(data, out_db):
    """data/ -> a public store at out_db. -> counts. Raises DataError when data/ is not what this build reads."""
    meta_in = read_meta(data)
    schema = sqlite3.connect(":memory:")
    schema.executescript(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    tcols = {t: [c[1] for c in schema.execute("PRAGMA table_info(%s)" % t)] for t in ("record",) + TABLES}
    schema.close()
    cols = tcols["record"]
    tables = {t: table_rows(data, t, tcols[t]) for t in TABLES}
    rows = sorted(table_rows(data, "record", [c for c in cols if c not in DERIVED]), key=lambda r: r["rid"])
    ents = {e["eid"]: e for e in tables["entity"]}
    aliases = collections.defaultdict(set)
    for a in tables["alias"]:
        if a["kind"] == "alias":
            aliases[a["eid"]].add(a["alias"])
    lap("read")
    if os.path.exists(out_db):
        os.remove(out_db)
    os.makedirs(os.path.dirname(os.path.abspath(out_db)), exist_ok=True)
    db = sqlite3.connect(out_db)
    db.execute("PRAGMA page_size=4096")
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript(open(os.path.join(HERE, "schema.sql"), encoding="utf-8").read())
    lid, leaf_rows, fts, recs = 0, [], [], []
    for rno, row in enumerate(rows, 1):
        rel = os.path.join("records", row["rid"] + ".json")
        b = open(os.path.join(data, rel), "rb").read()
        doc = json.loads(b.decode("utf-8"))
        lmin = lid + 1
        for p, v in leaves(doc):
            if v is None:
                continue
            lid += 1
            if isinstance(v, bool):
                typ, val = "bool", "true" if v else "false"
            elif isinstance(v, (int, float)):
                typ, val = "num", json.dumps(v)
            elif isinstance(v, str):
                typ, val = "text", v
            else:
                typ, val = ("object" if isinstance(v, dict) else "array"), json.dumps(v)
            leaf_rows.append((lid, rno, jpath(p), typ, val))
        r = dict(row, rno=rno, lid_min=lmin, lid_max=lid, path="data/" + rel.replace(os.sep, "/"),
                 doc=json.dumps(doc, ensure_ascii=False, separators=(",", ":")), sha256=hashlib.sha256(b).hexdigest())
        recs.append(tuple(r.get(c) for c in cols))
        fts.append((rno,) + fts_columns(doc, row.get("url"), sorted(aliases[row["eid"]]), ents[row["eid"]]))
    db.executemany("INSERT INTO record (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), recs)
    db.executemany("INSERT INTO leaf VALUES (?,?,?,?,?)", leaf_rows)
    counts = {"records": len(recs), "leaves": len(leaf_rows)}
    for t in TABLES:
        tc, trows = tcols[t], tables[t]
        db.executemany("INSERT OR IGNORE INTO %s (%s) VALUES (%s)" % (t, ",".join(tc), ",".join("?" * len(tc))),
                       [tuple(x.get(c) for c in tc) for x in trows])
        counts[t] = len(trows)
    db.executemany("INSERT INTO text_fts (docid, name, offer, limits, egress, identity, access, notes, evidence, extras)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?)", fts)
    commit, commit_time = git_info()
    meta = {"schema_version": SCHEMA_VERSION, "target": "public", "commit": commit, "commit_time": commit_time,
            "as_of": meta_in.get("as_of"), "source_commit": meta_in.get("source_commit"),
            "counts": json.dumps(dict(meta_in.get("counts") or {}, tables=counts), sort_keys=True)}
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.execute("INSERT INTO text_fts(text_fts) VALUES('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    lap("store")
    return counts


def make_worker_db(public_db, out_db):
    """The copy the Worker loads with sql.js: cards, claims, evidence URLs, entities and the FTS index.
    Record JSON, leaves and evidence quotes are served as static files instead (memory budget)."""
    shutil.copyfile(public_db, out_db)
    db = sqlite3.connect(out_db)
    db.executescript("DROP TABLE leaf; DROP TABLE unknown; UPDATE record SET doc = NULL;"
                     "UPDATE evidence SET proved = NULL; UPDATE history SET body = NULL;")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('target', 'worker')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    return os.path.getsize(out_db)


def leak_rx():
    pats = json.load(open(os.path.join(HERE, "rules", "leak.json"), encoding="utf-8"))["patterns"]
    return re.compile("|".join("(?:%s)" % p["re"] for p in pats))


def leak_scan(db_path=None, dist=None, data=None):
    """Every text value of every table, every text file of the site and of data/. -> [(where, context)]."""
    rx, hits = leak_rx(), []

    def hit(where, s):
        m = rx.search(s or "")
        if m:
            hits.append((where, s[max(0, m.start() - 60): m.end() + 40]))
    if db_path:
        db = sqlite3.connect(db_path)
        for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'text_fts%'"):
            for row in db.execute("SELECT * FROM %s" % t):
                for v in row:
                    if isinstance(v, str):
                        hit(t, v)
        # a public history entry is its date, status, title and linked records; the rest is process narrative
        for (hid,) in db.execute("SELECT hid FROM history WHERE body IS NOT NULL OR supersedes IS NOT NULL "
                                 "OR confidence IS NOT NULL"):
            hits.append(("history " + hid, "a public history row carries a body, a supersedes line or a confidence"))
        db.close()
    for top in (d for d in (dist, data) if d):
        for root, _, files in os.walk(top):
            for fn in files:
                p = os.path.join(root, fn)
                with open(p, "rb") as f:
                    b = f.read()
                if b"\0" not in b[:8192]:  # every text file, whatever its extension; a store or a gzip is binary
                    hit(os.path.relpath(p, top), b.decode("utf-8", errors="replace"))
    return hits


def asset_sizes(dist):
    """Files of dist over the Workers static asset limit (fail), and over WARN_SHARE of it (warn)."""
    over, near = [], []
    for root, _, files in os.walk(dist):
        for fn in files:
            p = os.path.join(root, fn)
            n = os.path.getsize(p)
            if n > ASSET_MAX_BYTES:
                over.append((os.path.relpath(p, dist), n))
            elif n > WARN_SHARE * ASSET_MAX_BYTES:
                near.append((os.path.relpath(p, dist), n))
    return over, near


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--db", default=os.path.join(ROOT, ".tmp", "fshy", "public.db"))
    ap.add_argument("--site", default=None, help="write the wiki and API files to this directory")
    ap.add_argument("--check", action="store_true", help="build the store, scan it, exit 0 or 1")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not (a.site or a.check):
        ap.error("give --check or --site DIR")
    if not os.path.exists(os.path.join(a.data, "meta.json")):
        print("build: %s has no meta.json; publish/export.py writes it" % a.data, file=sys.stderr)
        return 1
    try:
        report = {"store": build(a.data, a.db)}
    except DataError as e:
        print("build: %s" % e, file=sys.stderr)
        return 3
    hits = leak_scan(a.db, data=a.data)
    over = []
    if a.site:
        import site_gen  # noqa: E402
        report["files"] = site_gen.generate(ROOT, a.db, os.path.abspath(a.site), TIMES, lap)
        import llms  # noqa: E402
        llms.generate(a.db, os.path.abspath(a.site))
        lap("site-llms")
        hits += leak_scan(dist=os.path.abspath(a.site))
        lap("leak-scan")
        over, near = asset_sizes(os.path.abspath(a.site))
        for rel, n in near:
            print("build: warning: %s is %d bytes, over %d%% of the %d-byte asset limit"
                  % (rel, n, WARN_SHARE * 100, ASSET_MAX_BYTES), file=sys.stderr)
        for rel, n in over:
            print("build: %s is %d bytes; a static asset holds at most %d" % (rel, n, ASSET_MAX_BYTES), file=sys.stderr)
    report["leaks"] = len(hits)
    report["times"] = TIMES
    for where, ctx in hits[:40]:
        print("LEAK %s: ...%s..." % (where, ctx.replace("\n", " ")), file=sys.stderr)
    if not a.quiet:
        print(json.dumps(report))
    return 1 if hits or over else 0


if __name__ == "__main__":
    sys.exit(main())
