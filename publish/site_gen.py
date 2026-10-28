"""site_gen.py: the public store -> the static wiki and API files under site/dist.

Called by build.py --site DIR after the public store is built. Writes:
  data/       the Worker DB (chunked), the public DB download, manifest.json
  api/v1/     record and entity JSON, names index, needs, vocab, schema, help
  HTML pages  home, topics, entities, record permalinks, needs, graveyard, changes, compare, search, about
Standard library only; no wall clock in any output (dates come from the commit).
"""
import collections
import gzip
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SITE = os.path.join(HERE, "..", "site")
CHUNK = 20 * 1024 * 1024
CARD_COLS = ("rid", "eid", "topic", "slug", "provider", "url", "domain", "category", "tier", "verdict", "vorder", "grp",
             "confidence", "binding", "identity_kind", "identity_basis", "needs_card", "needs_phone", "needs_id",
             "needs_institution", "country", "crypto", "interfaces", "egress_metered", "per_object_bytes", "retention_days",
             "verified_at", "verified_basis", "checked_on", "stale_on", "n_evidence", "usd_month", "usd_per_tb_month",
             "summary", "duplicate_of", "n_unknown")


def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if mode == "wb":
        with open(path, "wb") as f:
            f.write(text)
    else:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def emit_data(repo, pub_db, dist):
    """Data files every other layer reads. Returns a context dict for the HTML layer."""
    sys.path.insert(0, HERE)
    import build  # noqa: E402
    db = sqlite3.connect("file:%s?mode=ro" % pub_db, uri=True)
    db.row_factory = sqlite3.Row
    meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}

    # worker DB, chunked under the 25 MiB asset limit, content-addressed
    wdb = os.path.join(os.path.dirname(pub_db), "worker.db")
    build.make_worker_db(pub_db, wdb)
    blob = open(wdb, "rb").read()
    h = sha(blob)
    chunks = []
    for i in range(0, len(blob), CHUNK):
        rel = "data/w/%s.%03d" % (h[:16], i // CHUNK)
        write(os.path.join(dist, rel), blob[i:i + CHUNK], "wb")
        chunks.append(rel)
    pub = open(pub_db, "rb").read()
    gz = gzip.compress(pub, 6, mtime=0)
    write(os.path.join(dist, "data", "fshy-public.sqlite.gz"), gz, "wb")

    cards, by_eid, docs = {}, collections.defaultdict(list), {}
    for r in db.execute("SELECT %s, doc FROM record ORDER BY rid" % ",".join(CARD_COLS)):
        c = {k: r[k] for k in CARD_COLS}
        cards[c["rid"]] = c
        by_eid[c["eid"]].append(c)
        docs[c["rid"]] = r["doc"]
    claims = collections.defaultdict(list)
    for r in db.execute("SELECT * FROM claim ORDER BY rid, path"):
        claims[r["rid"]].append({k: r[k] for k in r.keys() if k != "rid"})
    unknown = collections.defaultdict(list)
    for r in db.execute("SELECT * FROM unknown ORDER BY rid, path"):
        unknown[r["rid"]].append([r["path"], r["class"]])
    hist = collections.defaultdict(list)
    for r in db.execute("SELECT l.rid, h.hid, h.when_utc, h.status, h.title FROM history_link l JOIN history h USING (hid) ORDER BY h.when_utc DESC"):
        hist[r["rid"]].append({"hid": r["hid"], "when": r["when_utc"], "status": r["status"], "title": r["title"]})
    drift = collections.defaultdict(list)
    for r in db.execute("SELECT * FROM drift"):
        d = {k: r[k] for k in r.keys()}
        drift[r["subject"]].append(d)
        if r["other"]:
            drift[r["other"]].append(d)
    full = {}
    for rid, c in cards.items():
        full[rid] = {"rid": rid, "card": c, "record": json.loads(docs[rid]), "claims": claims.get(rid, []),
                     "unknown": unknown.get(rid, []), "history": hist.get(rid, []), "drift": drift.get(rid, [])}
    ents = {}
    for r in db.execute("SELECT * FROM entity ORDER BY eid"):
        e = {k: r[k] for k in r.keys()}
        e["topics"] = (e["topics"] or "").split(",")
        e["aliases"] = sorted({a for (a,) in db.execute("SELECT alias FROM alias WHERE eid=? AND kind IN ('name','provider','alias','domain')", (e["eid"],))})
        ents[e["eid"]] = e
        members = sorted(by_eid[e["eid"]], key=lambda c: (c["vorder"], c["rid"]))
        write(os.path.join(dist, "api", "v1", "entity", e["eid"] + ".json"),
              jdump({**e, "records": [full[c["rid"]] for c in members]}))
    # name index for MiniSearch: one row per entity
    names = []
    for eid, e in sorted(ents.items()):
        recs = by_eid[eid]
        flags = 0
        for c in recs:
            flags |= 1 << c["vorder"]
        names.append([eid, e["name"], [a for a in e["aliases"] if a != e["name"]][:12], e["domain"], e["topics"],
                      e["best_vorder"], len(recs), flags])
    write(os.path.join(dist, "api", "v1", "names.json"), jdump(names))
    vocab = collections.defaultdict(list)
    for r in db.execute("SELECT domain, term, meaning FROM vocab ORDER BY domain, ord"):
        vocab[r["domain"]].append([r["term"], r["meaning"]])
    write(os.path.join(dist, "api", "v1", "vocab.json"), jdump(vocab))
    shutil.copyfile(os.path.join(HERE, "schema.sql"), os.path.join(dist, "api", "v1", "schema.sql"))
    needs = json.load(open(os.path.join(HERE, "rules", "needs.json"), encoding="utf-8"))
    write(os.path.join(dist, "api", "v1", "needs.json"), jdump(needs))
    try:
        import primer  # noqa: E402
        write(os.path.join(dist, "api", "v1", "help.txt"), primer.text(pub_db))
    except ImportError:
        pass
    manifest = {"schema_version": meta.get("schema_version"), "commit": meta.get("commit"),
                "commit_time": meta.get("commit_time"), "as_of": meta.get("as_of"),
                "worker_db": {"chunks": chunks, "bytes": len(blob), "sha256": h},
                "public_db": {"path": "data/fshy-public.sqlite.gz", "bytes": len(pub), "gzip_bytes": len(gz), "sha256": sha(pub)},
                "counts": json.loads(meta.get("counts") or "{}")}
    write(os.path.join(dist, "data", "manifest.json"), jdump(manifest))
    return {"db": db, "meta": meta, "full": full, "cards": cards, "by_eid": by_eid, "ents": ents, "needs": needs, "vocab": vocab,
            "manifest": manifest, "hist": hist, "drift": drift, "unknown": unknown, "claims": claims, "docs": docs}


def generate(repo, pub_db, dist, times=None, lap=None):
    if os.path.isdir(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)
    ctx = emit_data(repo, pub_db, dist)
    if lap:
        lap("site-data")
    try:
        import pages  # noqa: E402
        pages.render(repo, dist, ctx)
    except ImportError:
        pass
    static = os.path.join(REPO_SITE, "static")
    if os.path.isdir(static):
        for root, _, files in os.walk(static):
            for fn in files:
                src = os.path.join(root, fn)
                rel = os.path.relpath(src, static)
                dst = os.path.join(dist, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
    if lap:
        lap("site-pages")
    ctx["db"].close()
    n = sum(len(f) for _, _, f in os.walk(dist))
    return n
