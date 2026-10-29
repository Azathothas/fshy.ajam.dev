"""primer.py: the help text an agent reads before its first query, generated from a store.

text(db_path) -> str. Works on the public store and on the Worker copy: every table, column
and vocabulary line is read from the database it is given, so a table the store lacks is
never described. It names only what a reader of the public data can open. Standard library only.

EXAMPLES holds the worked queries; publish/test_publish.py runs each one against the
store in .tmp/fshy/ so the primer never shows a query that fails.
"""
import json
import os
import sqlite3
from urllib.request import pathname2url

PURPOSE = {
    "record": "one row per record; doc is the record JSON of data/records/<topic>/<slug>.json",
    "entity": "a vendor; groups records",
    "alias": "kind: name, provider, slug, alias, domain",
    "evidence": "what each source proved",
    "limit_row": "is_binding=1 for the kind named in binding",
    "claim": "parsed numbers; parse ok, partial or unparsed",
    "unknown": "placeholder, default or withheld values",
    "leaf": "the leaves of the record JSON; a record is lid BETWEEN lid_min AND lid_max",
    "edge": "kind: duplicate_of, variant_of, successor_of, same_offer_as, same-product, mentions",
    "drift": "records of one product that disagree",
    "ledger": "one row per amendment of a record value: when, which record and field, the rung and the source",
}
ORDER = ["record", "entity", "alias", "evidence", "limit_row", "claim", "unknown", "leaf", "edge", "drift",
         "history", "history_link", "ledger"]
MINOR = ["fx", "capture", "vocab", "meta", "keystat"]
# columns worth naming in the primer; the rest are counted and reachable with pragma_table_info
KEY_COLS = {
    "record": ["rid", "topic", "slug", "eid", "provider", "url", "category", "verdict", "vorder", "grp",
               "self_hosted", "confidence", "binding", "identity_kind", "identity_basis", "needs_card", "needs_phone",
               "needs_id", "needs_institution", "crypto", "interfaces", "usd_month", "usd_per_tb_month",
               "verified_basis", "checked_on", "stale_on", "summary", "duplicate_of", "doc", "rno"],
}
VOCAB_ORDER = ["verdict", "grp", "confidence", "binding", "identity_kind", "identity_basis", "verified_basis",
               "unknown_class"]
# domains whose terms explain themselves: listed without meanings, to keep the primer short
TERMS_ONLY = {"unknown_class"}
# domains that a RULES line explains: not repeated under VOCABULARIES
RULE_ONLY = {"self_hosted"}

EXAMPLES = [
    ("Usable storage with no card, cheapest per TB-month first (NULL price last)",
     "SELECT rid, provider, usd_per_tb_month FROM record WHERE topic='storage' AND grp='usable' "
     "AND needs_card=0 AND identity_basis='stated' AND duplicate_of IS NULL "
     "ORDER BY self_hosted, usd_per_tb_month IS NULL, usd_per_tb_month LIMIT 10"),
    ("Full text, one column filter plus a prefix term (CJK: query bigrams, e.g. MATCH '百度')",
     "SELECT r.rid, r.verdict FROM text_fts JOIN record r ON r.rno = text_fts.docid "
     "WHERE text_fts MATCH 'offer:gpu* hours' ORDER BY r.self_hosted, r.vorder LIMIT 10"),
    ("Full text with filters: match in a subquery on record, because a JOIN with filters is refused",
     "SELECT r.rid, r.verdict FROM record r WHERE r.rno IN (SELECT docid FROM text_fts WHERE text_fts MATCH "
     "'offer:gpu*') AND r.topic IN ('compute','inference') AND r.grp IN ('usable','trial') "
     "AND r.duplicate_of IS NULL ORDER BY r.self_hosted, r.vorder LIMIT 10"),
    ("Every record of a vendor, by alias",
     "SELECT rid, topic, verdict FROM record WHERE eid IN "
     "(SELECT eid FROM alias WHERE alias LIKE 'hetzner%') ORDER BY self_hosted, vorder, rid LIMIT 20"),
    ("What goes stale in the next 30 days",
     "SELECT rid, stale_on, verified_basis FROM record WHERE stale_on <= date('now','+30 days') "
     "AND grp <> 'dead' ORDER BY self_hosted, vorder, stale_on LIMIT 20"),
    ("Parsed prices per TB in USD, with the FX date used",
     "SELECT rid, num, currency, usd, fx_date FROM claim WHERE kind='price-per-tb' "
     "AND usd IS NOT NULL ORDER BY usd LIMIT 10"),
    ("The binding request-rate limits, and who cites a host",
     "SELECT l.rid, l.value FROM limit_row l WHERE l.is_binding=1 AND l.kind='request-rate' "
     "AND l.rid IN (SELECT rid FROM evidence WHERE url LIKE '%github.com%') LIMIT 10"),
    ("Compute records that have a free allowance (claim has-free-tier = 1), best verdict first",
     "SELECT r.rid, r.verdict FROM record r JOIN claim c ON c.rid = r.rid AND c.kind = 'has-free-tier' AND c.num = 1 "
     "WHERE r.topic = 'compute' AND r.grp IN ('usable','trial') AND r.duplicate_of IS NULL ORDER BY r.vorder LIMIT 10"),
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
    w("store: %s; data as of %s, source commit %s; %s records, %s entities, %s evidence rows, %s parsed claims"
      % (target, meta.get("as_of") or "?", (meta.get("source_commit") or "?")[:12],
         counts.get("records", "?"), counts.get("entities", "?"), counts.get("evidence", "?"),
         counts.get("claims", "?")))
    w("The record files of data/records/ in the public repository are the source; this store is built from")
    w("them and never edited. The MCP tools are help, search, filter, get, entity, need, sql and worklist.")
    w("The HTTP API has the same operations: /api/v1/search, records (filter), record/TOPIC/SLUG (get),")
    w("entity-search and entity/ID.json (entity), need/ID, sql and worklist/KIND. The route list is /api/v1/.")
    w("")
    w("IDS")
    w("- rid = topic/slug, stable (storage/hetzner-storage-box). Quote rids; never show or store rno.")
    w("- rno is build-local: the text_fts docid and leaf key. Join on it, never cite it.")
    w("- eid = vendor entity. An entity only groups records; each record carries its own verdict.")
    w("")
    w("RULES")
    w("- needs_card, needs_phone, needs_id, needs_institution: 1 yes, 0 no, NULL UNKNOWN (never 'no').")
    w("  'No card' is needs_card=0 AND identity_basis='stated'. identity_basis='defaulted' or 'inferred' means unknown.")
    w("- Freshness: stale on day D when stale_on <= D (today UTC unless you pick as_of).")
    w("  verified_basis='inherited' means checked_on is only an upper bound.")
    w("- usd_month, usd_per_tb_month: headline USD prices, NULL when nothing parsed. Say how many rows a")
    w("  filter or sort on them drops for NULL. interfaces: comma list, NULL = unknown.")
    w("- duplicate_of IS NOT NULL marks a duplicate; the API and the MCP tools exclude them unless asked, and")
    w("  the wiki pages list them. So a page can count a few more records than the API.")
    w("- A need list that asks for no card or no phone ends with the rows whose card or phone requirement is not stated (NULL, or")
    w("  an identity that no source states), under the heading 'Card or phone requirement not stated'. They are never counted as no.")
    w("- A free allowance: the claim of the kind has-free-tier. claim.num 1: the record has a free allowance; 0: it has")
    w("  none; no row: unknown. free_unit is the unit of the headline offer, which can be a price, so it does not say")
    w("  this. Join: LEFT JOIN claim c ON c.rid = record.rid AND c.kind = 'has-free-tier' (example 8).")
    w("- TSV output ends with lines that start with '#': the row count, the limit, a cut. Read it with")
    w("  comment='#' in pandas, or drop those lines.")
    w("- vorder 0..7 orders verdicts best first; grp groups them.")
    if "self_hosted" in {r[1] for r in db.execute("SELECT * FROM pragma_table_info('record')")}:
        w("- self_hosted=1: the user installs and runs it, the last resort. Self-hosted options are listed last,")
        w("  because this site is for users who have no hardware: every list sorts on self_hosted first.")
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
        w("  A word matches anywhere in a column: free also matches 'no free tier'. Use a phrase ('\"always free\"'),")
        w("  a column (offer:free) or a filter on verdict, free_unit or grp. With filters, put the match in a")
        w("  subquery on record (example 3): a JOIN of text_fts with filters on record is refused.")
    if "record" in tables:
        n_doc = db.execute("SELECT count(*) FROM record WHERE doc IS NOT NULL").fetchone()[0]
        if not n_doc:
            w("  In this copy record.doc and evidence.proved are NULL: use get for them.")
        else:
            w("  The sql route and the sql tool read a smaller copy of this store: it has no leaf table, and record.doc")
            w("  and evidence.proved are NULL there. Use get, or the download /data/fshy-public.sqlite.gz, for them.")
    w("All columns: SELECT name FROM pragma_table_info('record'). Meanings: SELECT * FROM vocab.")
    w("")
    w("VOCABULARIES")
    vocab = {}
    for d, t, m in db.execute("SELECT domain, term, meaning FROM vocab ORDER BY domain, ord"):
        vocab.setdefault(d, []).append((t, m))
    for d in VOCAB_ORDER + sorted(set(vocab) - set(VOCAB_ORDER)):
        if d not in vocab or d in RULE_ONLY:
            continue
        if d in TERMS_ONLY:
            w("- %s: %s" % (d, ", ".join(t for t, _ in vocab[d])))
        else:  # one term a line: a meaning can hold a semicolon
            w("- %s:" % d)
            for t, m in vocab[d]:
                w("    %s = %s" % (t, m))
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
