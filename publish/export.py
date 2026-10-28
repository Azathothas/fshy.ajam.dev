#!/usr/bin/env python3
"""export.py: the research corpus -> data/, the published corpus. Only the merge agent runs it.

usage:
  python publish/export.py --source PATH        PATH is a checkout of the private research repository

1. Build the public store with the research repository's own projection and leak scan:
   python PATH/scripts/fshy/build.py --repo PATH --public TMP. The projection rules stay in that repository,
   because they name what they remove.
2. Write each record as data/records/<topic>/<slug>.json and each other table as data/tables/<table>.jsonl,
   sorted, with no row numbers, so the diff of a publish shows exactly which records changed.
3. Scan every written file with this repository's leak rules and with the research repository's leak rules.
   With one hit, nothing is written to data/.

Exit codes: 0 written, 1 a check failed, 2 usage, 3 the source is not a research checkout.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402

# record columns that are positions in one build, or that describe a private file
RECORD_DROP = ("rno", "lid_min", "lid_max", "doc", "sha256", "path")
# columns that point at files in the research repository; data/ keeps the hash and the URL instead
NULLED = {"evidence": ("capture",), "capture": ("path",)}
META_KEEP = ("schema_version", "as_of", "commit")


def dump_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def export(pub_db, out):
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
    m = {k: meta.get(k) for k in META_KEEP}
    m["source_commit"] = m.pop("commit")
    m["counts"] = json.loads(meta.get("counts") or "{}")  # the projection's own accounting, read by the wiki
    m["tables"] = counts
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return counts


def source_leak_rx(source):
    rules = json.load(open(os.path.join(source, "scripts", "fshy", "rules", "projection.json"), encoding="utf-8"))
    return re.compile("|".join("(?:%s)" % p for p in rules["leak_scan"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, help="checkout of the research repository")
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    a = ap.parse_args(argv)
    source = os.path.abspath(a.source)
    script = os.path.join(source, "scripts", "fshy", "build.py")
    if not os.path.exists(script):
        print("export: %s is not a research checkout (no scripts/fshy/build.py)" % source, file=sys.stderr)
        return 3
    tmp = tempfile.mkdtemp(prefix="fshy-export-")
    try:
        pub = os.path.join(tmp, "public.db")
        r = subprocess.run([sys.executable, script, "--repo", source, "--public", pub, "--quiet"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.exists(pub):
            print("export: the research build refused (exit %d):\n%s" % (r.returncode, (r.stderr or r.stdout)[-2000:]),
                  file=sys.stderr)
            return 1
        out = os.path.join(tmp, "data")
        counts = export(pub, out)
        hits = build.leak_scan(data=out)
        rx = source_leak_rx(source)
        for root, _, files in os.walk(out):
            for fn in files:
                p = os.path.join(root, fn)
                m = rx.search(open(p, encoding="utf-8").read())
                if m:
                    hits.append((os.path.relpath(p, out), "a research leak rule matched"))
        if hits:
            for where, ctx in hits[:40]:
                print("LEAK %s: %s" % (where, ctx.replace("\n", " ")[:200]), file=sys.stderr)
            print("export: %d leak hit(s); data/ is unchanged" % len(hits), file=sys.stderr)
            return 1
        if os.path.isdir(a.data):
            shutil.rmtree(a.data)
        shutil.move(out, a.data)
        print(json.dumps({"written": os.path.relpath(a.data, ROOT), "counts": counts}))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
