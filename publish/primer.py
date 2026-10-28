"""primer.py: the help text an agent reads before its first query, generated from a store.

text(db_path) -> str. Works on the local store, the public store and the Worker copy:
every table, column and vocabulary line is read from the database it is given, so a
table the store lacks is never described. Standard library only.

EXAMPLES holds the worked queries; publish/test_build.py runs each one against the
stores in .tmp/fshy/ so the primer never shows a query that fails.
"""
import json
import os
import sqlite3
from urllib.request import pathname2url

PURPOSE = {
    "record": "one row per record; doc is the projected JSON",
    "entity": "a vendor; groups records",
    "alias": "kind: name, provider, slug, alias, domain",
    "evidence": "what each source proved",
    "limit_row": "is_binding=1 for the kind named in binding",
    "claim": "parsed numbers; parse ok, partial or unparsed",
    "unknown": "placeholder, default or withheld values",
    "leaf": "projected JSON leaves; a record is lid BETWEEN lid_min AND lid_max",
    "edge": "kind: duplicate_of, variant_of, successor_of, same_offer_as, same-product, mentions",
    "drift": "records of one product that disagree",
    "ledger": "one row per amendment (history/ledger.jsonl)",
    "raw": "LOCAL ONLY: verbatim source JSON",
    "strip_log": "LOCAL ONLY: what the public projection removed",
}
ORDER = ["record", "entity", "alias", "evidence", "limit_row", "claim", "unknown", "leaf", "edge", "drift",
         "history", "history_link", "ledger", "raw", "strip_log"]
MINOR = ["fx", "capture", "vocab", "meta"]
# columns worth naming in the primer; the rest are counted and reachable with pragma_table_info
KEY_COLS = {
    "record": ["rid", "topic", "slug", "eid", "provider", "url", "category", "verdict", "vorder", "grp",
               "confidence", "binding", "identity_kind", "identity_basis", "needs_card", "needs_phone",
               "needs_id", "needs_institution", "crypto", "interfaces", "usd_month", "usd_per_tb_month",
               "verified_basis", "checked_on", "stale_on", "summary", "duplicate_of", "doc", "rno"],
}
VOCAB_ORDER = ["verdict", "grp", "confidence", "binding", "identity_kind", "identity_basis", "verified_basis",
               "unknown_class"]
# domains whose terms explain themselves: listed without meanings to stay inside the token budget
TERMS_ONLY = {"binding", "identity_kind", "unknown_class"}

EXAMPLES = [
    ("Usable storage with no card, cheapest per TB-month first (NULL price last)",
     "SELECT rid, provider, usd_per_tb_month FROM record WHERE topic='storage' AND grp='usable' "
     "AND needs_card=0 AND identity_basis='stated' AND duplicate_of IS NULL "
     "ORDER BY usd_per_tb_month IS NULL, usd_per_tb_month LIMIT 10"),
    ("Full text, one column filter plus a prefix term (CJK: query bigrams, e.g. MATCH '百度')",
     "SELECT r.rid, r.verdict FROM text_fts JOIN record r ON r.rno = text_fts.docid "
     "WHERE text_fts MATCH 'offer:gpu* hours' ORDER BY r.vorder LIMIT 10"),
    ("Every record of a vendor, by alias",
     "SELECT rid, topic, verdict FROM record WHERE eid IN "
     "(SELECT eid FROM alias WHERE alias LIKE 'hetzner%') ORDER BY vorder, rid LIMIT 20"),
    ("What goes stale in the next 30 days",
     "SELECT rid, stale_on, verified_basis FROM record WHERE stale_on <= date('now','+30 days') "
     "AND grp <> 'dead' ORDER BY vorder, stale_on LIMIT 20"),
    ("Parsed prices per TB in USD, with the FX date used",
     "SELECT rid, num, currency, usd, fx_date FROM claim WHERE kind='price-per-tb' "
     "AND usd IS NOT NULL ORDER BY usd LIMIT 10"),
    ("The binding request-rate limits, and who cites a host",
     "SELECT l.rid, l.value FROM limit_row l WHERE l.is_binding=1 AND l.kind='request-rate' "
     "AND l.rid IN (SELECT rid FROM evidence WHERE url LIKE '%github.com%') LIMIT 10"),
]


def connect(db_path):
    return sqlite3.connect("file:%s?mode=ro" % pathname2url(os.path.abspath(db_path)), uri=True)


def _tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def text(db_path):
    db = connect(db_path)
    try:
        return _text(db)
    finally:
        db.close()


def _text(db):
    meta = dict(db.execute("SELECT key, value FROM meta"))
    try:
        counts = json.loads(meta.get("counts") or "{}")
    except ValueError:
        counts = {}
    tables = set(_tables(db))
    target = meta.get("target", "?")
    out = []
    w = out.append
    w("fshy: the fshy corpus as one read-only SQLite store")
    w("store: %s; commit %s (%s); as_of %s; %s records, %s entities, %s evidence rows, %s parsed claims"
      % (target, (meta.get("commit") or "?")[:12], meta.get("commit_time") or "?", meta.get("as_of") or "?",
         counts.get("records", "?"), counts.get("entities", "?"), counts.get("evidence", "?"),
         counts.get("claims", "?")))
    w("The dossier JSON in git is the truth; this store is derived from it and never edited.")
    w("Operations: help, search, filter, get, entity, need, sql, worklist (same names in fr, the API and MCP).")
    w("")
    w("IDS")
    w("- rid = topic/slug, stable (storage/hetzner-storage-box). Quote rids; never show or store rno.")
    w("- rno is build-local: the text_fts docid and leaf key. Join on it, never cite it.")
    w("- eid = vendor entity. An entity only groups records; each record carries its own verdict.")
    w("")
    w("RULES")
    w("- needs_card, needs_phone, needs_id, needs_institution: 1 yes, 0 no, NULL UNKNOWN (never 'no').")
    w("  'No card' is needs_card=0 AND identity_basis='stated'. identity_basis='defaulted' means unknown.")
    w("- Freshness: stale on day D when stale_on <= D (today UTC unless you pick as_of).")
    w("  verified_basis='inherited' means checked_on is only an upper bound.")
    w("- usd_month, usd_per_tb_month: headline USD prices, NULL when nothing parsed. Say how many rows a")
    w("  filter or sort on them drops for NULL. interfaces: comma list, NULL = unknown.")
    w("- duplicate_of IS NOT NULL marks a duplicate; lists exclude them unless asked.")
    w("- vorder 0..7 orders verdicts best first; grp groups them.")
    w("")
    w("TABLES (key columns)")
    def sig(t):
        cols = [r[1] for r in db.execute("SELECT * FROM pragma_table_info(?)", (t,))]
        keep = [c for c in KEY_COLS.get(t, cols) if c in cols]
        more = len(cols) - len(keep)
        return "%s(%s%s)" % (t, ", ".join(keep), (", +%d more" % more) if more > 0 else "")
    rest = sorted(t for t in tables - set(ORDER) - set(MINOR) if not t.startswith(("text_fts", "sqlite_")))
    for t in ORDER + rest:
        if t in tables:
            w("- " + sig(t) + (": " + PURPOSE[t] if t in PURPOSE else ""))
    minor = [sig(t) for t in MINOR if t in tables]
    if minor:
        w("- also " + ", ".join(minor))
    if "text_fts" in tables:
        w("- text_fts: FTS4, contentless, one row per record (docid = record.rno). Columns in order:")
        w("  name, offer, limits, egress, identity, access, notes, evidence, extras. Terms are AND-ed;")
        w("  'word*' is a prefix, 'col:word' limits to a column. CJK text is indexed as runs plus")
        w("  overlapping bigrams: query a CJK run as its bigrams separated by spaces.")
    if "record" in tables:
        n_doc = db.execute("SELECT count(*) FROM record WHERE doc IS NOT NULL").fetchone()[0]
        if not n_doc:
            w("  In this copy record.doc, evidence.proved and history.body are NULL: use get for them.")
    w("All columns: SELECT name FROM pragma_table_info('record'). Meanings: SELECT * FROM vocab.")
    w("")
    w("VOCABULARIES")
    vocab = {}
    for d, t, m in db.execute("SELECT domain, term, meaning FROM vocab ORDER BY domain, ord"):
        vocab.setdefault(d, []).append((t, m))
    for d in VOCAB_ORDER + sorted(set(vocab) - set(VOCAB_ORDER)):
        if d not in vocab:
            continue
        if d in TERMS_ONLY:
            w("- %s: %s" % (d, ", ".join(t for t, _ in vocab[d])))
        else:
            w("- %s: %s" % (d, "; ".join("%s = %s" % (t, m) for t, m in vocab[d])))
    w("")
    w("EXAMPLES (each runs as written)")
    for i, (what, sql) in enumerate(EXAMPLES, 1):
        w("%d. %s" % (i, what))
        w("   " + sql)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", ".tmp", "fshy", "public.db")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text(path))
