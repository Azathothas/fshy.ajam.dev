-- fshy store schema. One schema for the local store, the public download and the Worker copy.
-- publish/build.py loads it from data/: the record files and the table files that publish/export.py writes.
-- Never edited by hand and never committed: it is rebuilt from the JSON in seconds.
-- Full text is FTS4 (not FTS5) because the Worker runs sql.js, which has FTS3/FTS4 only.

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;

-- closed vocabularies with their meanings, in display order
CREATE TABLE vocab (domain TEXT NOT NULL, term TEXT NOT NULL, ord INTEGER, meaning TEXT,
  PRIMARY KEY (domain, term)) WITHOUT ROWID;

-- a vendor: a set of records that share an anchor (domain, platform owner or name)
CREATE TABLE entity (eid TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, resolved_by TEXT,
  topics TEXT, n_records INTEGER, best_vorder INTEGER, review TEXT) WITHOUT ROWID;
CREATE TABLE alias (eid TEXT NOT NULL, alias TEXT NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY (eid, alias, kind)) WITHOUT ROWID;

-- one row per record (topic/slug); card columns are derived, doc is the projected JSON
CREATE TABLE record (
  rid TEXT PRIMARY KEY,            -- topic/slug, stable
  rno INTEGER NOT NULL UNIQUE,     -- build-local number: text_fts docid and leaf key; never quote it
  topic TEXT NOT NULL, slug TEXT NOT NULL, eid TEXT NOT NULL,
  provider TEXT, url TEXT, domain TEXT, category TEXT, tier TEXT,
  verdict TEXT NOT NULL, vorder INTEGER NOT NULL,
  grp TEXT NOT NULL,               -- usable | trial | paid | rejected | dead
  self_hosted INTEGER NOT NULL DEFAULT 0,  -- 1 = the user installs and runs it: listed after every hosted (0) record
  confidence TEXT, binding TEXT,
  identity_kind TEXT, identity_basis TEXT,   -- stated | defaulted
  needs_card INTEGER, needs_phone INTEGER, needs_id INTEGER, needs_institution INTEGER,  -- 1 / 0 / NULL = unknown
  country TEXT,
  crypto INTEGER,                  -- 1 when a crypto rail is named, NULL when not stated
  free_unit TEXT, free_metered_on TEXT, egress_metered INTEGER,
  per_object_bytes INTEGER, retention_days INTEGER,
  interfaces TEXT,                 -- comma list; NULL = unknown
  verified_at TEXT, verified_basis TEXT,     -- live | inherited | unstated
  checked_on TEXT,                 -- effective date of the last check (an upper bound when inherited)
  stale_on TEXT,                   -- first day the staleness policy calls this record stale
  limit_days INTEGER, evidence_budget_days INTEGER,
  evidence_newest TEXT, evidence_oldest TEXT, n_evidence INTEGER,
  usd_month REAL, usd_per_tb_month REAL, -- headline normalised prices, NULL when not parsed
  summary TEXT,                    -- one line: the free tier as stated, clipped
  duplicate_of TEXT,               -- rid this record duplicates (registry/relations.tsv)
  n_unknown INTEGER, n_withheld INTEGER,
  lid_min INTEGER, lid_max INTEGER, -- range of this record's rows in leaf
  doc TEXT,                        -- the projected record as JSON (NULL in the Worker copy)
  sha256 TEXT, path TEXT
) WITHOUT ROWID;
CREATE INDEX record_topic ON record (topic, vorder);
CREATE INDEX record_eid ON record (eid);

-- every public leaf of every projected record, in record order (rno, then document order)
-- read one record's leaves with: WHERE lid BETWEEN record.lid_min AND record.lid_max
CREATE TABLE leaf (lid INTEGER PRIMARY KEY, rno INTEGER NOT NULL, path TEXT NOT NULL,
  type TEXT NOT NULL, value TEXT);

CREATE TABLE evidence (rid TEXT NOT NULL, ord INTEGER NOT NULL, url TEXT, url_kind TEXT,
  date TEXT, proved TEXT, capture TEXT, PRIMARY KEY (rid, ord)) WITHOUT ROWID;
CREATE TABLE limit_row (rid TEXT NOT NULL, ord INTEGER NOT NULL, kind TEXT, value TEXT,
  source TEXT, is_binding INTEGER, PRIMARY KEY (rid, ord)) WITHOUT ROWID;

-- parsed numbers per claim-bearing value; the text stays in leaf / doc
CREATE TABLE claim (rid TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
  num REAL, unit TEXT, per TEXT, currency TEXT, usd REAL, fx_date TEXT,
  parse TEXT NOT NULL,             -- ok | partial | unparsed
  PRIMARY KEY (rid, path)) WITHOUT ROWID;
CREATE TABLE fx (ccy TEXT NOT NULL, date TEXT NOT NULL, usd_per_unit REAL NOT NULL, source TEXT,
  PRIMARY KEY (ccy, date)) WITHOUT ROWID;

-- every placeholder, default, template or withheld value, with its class and rule
CREATE TABLE unknown (rid TEXT NOT NULL, path TEXT NOT NULL, class TEXT NOT NULL, rule TEXT,
  PRIMARY KEY (rid, path)) WITHOUT ROWID;

CREATE TABLE edge (src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY (src, dst, kind)) WITHOUT ROWID;
CREATE TABLE drift (kind TEXT NOT NULL, subject TEXT NOT NULL, other TEXT, field TEXT,
  a TEXT, b TEXT, detail TEXT);

CREATE TABLE history (hid TEXT PRIMARY KEY, when_utc TEXT, status TEXT, confidence TEXT,
  title TEXT, supersedes TEXT, body TEXT) WITHOUT ROWID;
CREATE TABLE history_link (hid TEXT NOT NULL, rid TEXT NOT NULL, PRIMARY KEY (hid, rid)) WITHOUT ROWID;
CREATE TABLE ledger (at TEXT, rid TEXT, path TEXT, old TEXT, new TEXT, rung TEXT,
  url TEXT, date TEXT, proved TEXT, reason TEXT);
CREATE TABLE capture (url TEXT NOT NULL, captured_at TEXT, path TEXT, sha256 TEXT);

-- full text, one row per record (docid = record.rno), one column per field group; contentless:
-- matchinfo() says which columns matched, the text itself is in record.doc / leaf / the JSON files
CREATE VIRTUAL TABLE text_fts USING fts4 (content="", name, offer, limits, egress, identity, access,
  notes, evidence, extras, tokenize=unicode61 "remove_diacritics=2");
