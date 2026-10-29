#!/usr/bin/env python3
"""fixture_selfhosted.py: a copy of data/ at schema_version 2 in which some records are self-hosted, for the tests.

usage:
  python publish/fixture_selfhosted.py --data data --out DIR

data/ of version 1 has no self-hosted record, so the self-hosted tests of run.mjs skip on it, and the order check of
build.py --site has nothing to find. CI builds this copy and runs those tests on it, so a change of an ORDER BY in
site/worker/api.js or of the order of a page fails a pull request, not the next publish.

The copy marks every record of FORCE_SELF, no record of KEEP_HOSTED, and each other record whose SHA-256 of its rid
falls in one seventh of the range. So the copy has vendors whose every record is self-hosted, vendors with hosted and
self-hosted records, and vendors whose self-hosted record has a better verdict than their hosted ones. It sets
record.self_hosted (and self_hosted in the record JSON), recomputes entity.best_vorder by the rule of rank.js
bestVorder, and writes schema_version 2 and files_sha256, so build.py reads the copy as an export.

When data/ has a self-hosted record already, the copy is not needed: the tool writes nothing, says so, and exits 0. It
never writes data/. Exit codes: 0 written or not needed, 2 usage. Standard library only.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build  # noqa: E402

# the vendor of the case that showed the defect (the self-hosted OpenList software above a hosted public instance), and
# an exact name of a self-hosted vendor that fuzzy matches of hosted vendors list below others (a name lookup)
FORCE_SELF = ("github-openlistteam", "coder")
KEEP_HOSTED = ("chirmyram",)
SHARE = 7  # one record in SHARE


def sampled(rid):
    return int(hashlib.sha256(rid.encode("utf-8")).hexdigest()[:8], 16) % SHARE == 0


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def dump_jsonl(path, rows):
    """As publish/export.py writes a table."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def best_vorder(members):
    """rank.js bestVorder: the best vorder of the hosted records, of all records when every one is self-hosted."""
    hosted = [v for v, sh in members if not sh and v is not None]
    every = [v for v, _ in members if v is not None]
    return min(hosted) if hosted else (min(every) if every else None)


def make(data, out):
    tables = os.path.join(data, "tables")
    recs = read_jsonl(os.path.join(tables, "record.jsonl"))
    if any(r.get("self_hosted") for r in recs):
        print("fixture: %s has self-hosted records already; the tests read it as it is, and no copy is written" % data)
        return 0
    if os.path.exists(out) and os.listdir(out):
        print("fixture: %s is not empty; give a new or an empty directory" % out, file=sys.stderr)
        return 2
    if os.path.abspath(out) == os.path.abspath(os.path.join(ROOT, "data")):
        print("fixture: never write data/", file=sys.stderr)
        return 2
    if os.path.exists(out):
        os.rmdir(out)
    shutil.copytree(data, out)
    marked = set()
    for r in recs:
        sh = r["eid"] in FORCE_SELF or (r["eid"] not in KEEP_HOSTED and sampled(r["rid"]))
        r["self_hosted"] = int(sh)
        if sh:
            marked.add(r["rid"])
            p = os.path.join(out, "records", *(r["rid"] + ".json").split("/"))
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            doc["self_hosted"] = True
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    dump_jsonl(os.path.join(out, "tables", "record.jsonl"), recs)
    members = {}
    for r in recs:
        members.setdefault(r["eid"], []).append((r["vorder"], r["self_hosted"]))
    ents = read_jsonl(os.path.join(tables, "entity.jsonl"))
    for e in ents:
        e["best_vorder"] = best_vorder(members.get(e["eid"], []))
    ents.sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
    dump_jsonl(os.path.join(out, "tables", "entity.jsonl"), ents)
    with open(os.path.join(data, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    meta["schema_version"] = build.SCHEMA_VERSION
    meta["files_sha256"] = build.files_digest(out)
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    whole = sum(1 for m in members.values() if all(sh for _, sh in m))
    mixed = sum(1 for m in members.values() if any(sh for _, sh in m) and not all(sh for _, sh in m))
    print("fixture: %s at schema_version %s: %d of %d records self-hosted; %d vendors wholly self-hosted, %d mixed"
          % (out, build.SCHEMA_VERSION, len(marked), len(recs), whole, mixed))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out", required=True, help="a new or an empty directory")
    a = ap.parse_args(argv)
    if not os.path.isfile(os.path.join(a.data, "meta.json")):
        print("fixture: %s has no meta.json" % a.data, file=sys.stderr)
        return 2
    return make(a.data, a.out)


if __name__ == "__main__":
    sys.exit(main())
