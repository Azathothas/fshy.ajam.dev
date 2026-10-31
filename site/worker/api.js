// The operations of the fshy query contract (search, filter, get, entity, need, sql, worklist, help)
// over the Worker DB, plus their JSON and TSV renderings. The HTTP API (index.js) and the MCP
// tools (mcp.js) both call these functions, so the two surfaces return the same rows.

import { all, asset, capped, discard, engineFailed, HEAP_LIMIT_MIB, HttpError, nameIndex } from './db.js';
import { guard, GuardError } from './guard.js';
import { checkPlan } from './plan.js';
import { bestVorder, bm25, buildNameIndex, hostedFirst, resolveEntity, scoreNames, sortEntities as orderEntities } from './rank.js';
import { clip, ftsMatch } from './text.js';

// ------------------------------------------------------------------ shapes

export const CARD_COLUMNS = ['rid', 'provider', 'verdict', 'self_hosted', 'confidence', 'identity', 'card', 'phone',
  'usd_month', 'usd_per_tb_month', 'stale_on', 'summary'];
// self_hosted is yes for software or a node that the user installs and runs: every list puts it after every hosted row
const CARD_SELECT = `rid, provider, verdict, CASE self_hosted WHEN 1 THEN 'yes' ELSE 'no' END AS self_hosted, confidence,
  coalesce(identity_kind, '') || CASE WHEN identity_basis <> 'stated' THEN '?' ELSE '' END AS identity,
  CASE needs_card WHEN 1 THEN 'yes' WHEN 0 THEN 'no' ELSE '?' END AS card,
  CASE needs_phone WHEN 1 THEN 'yes' WHEN 0 THEN 'no' ELSE '?' END AS phone,
  usd_month, usd_per_tb_month, stale_on, summary`;
const SUMMARY = CARD_COLUMNS.indexOf('summary');

// record columns a caller may name in get(fields) for card detail (never rno, doc, leaf ranges)
const RECORD_FIELDS = new Set(['rid', 'topic', 'slug', 'eid', 'provider', 'url', 'domain', 'category', 'tier',
  'verdict', 'vorder', 'grp', 'self_hosted', 'confidence', 'binding', 'identity_kind', 'identity_basis', 'needs_card',
  'needs_phone', 'needs_id', 'needs_institution', 'country', 'crypto', 'free_unit', 'free_metered_on',
  'egress_metered', 'per_object_bytes', 'retention_days', 'interfaces', 'verified_at', 'verified_basis',
  'checked_on', 'stale_on', 'limit_days', 'evidence_budget_days', 'evidence_newest', 'evidence_oldest',
  'n_evidence', 'usd_month', 'usd_per_tb_month', 'summary', 'duplicate_of', 'n_unknown', 'n_withheld',
  'sha256', 'path']);

// the evidence rungs, strongest first: the order of a tie in a ranked list
const RUNG = { measured: 0, documented: 1, reported: 2, inferred: 3, unverified: 4 };
const RUNG_UNKNOWN = 5;

const SORTS = new Set(['vorder', 'usd_month', 'usd_per_tb_month', 'stale_on', 'provider', 'verified_at']);
const PRICE = new Set(['usd_month', 'usd_per_tb_month']);
const LOCAL_ONLY_KINDS = new Set(['unknown', 'held']);
const KINDS = new Set(['stale', 'drift', 'changes', 'unparsed']);

// The title of a ledger row in the worklist changes: what the row did, by its op. The published ledger holds no old
// or new value. A row with no op (data of schema_version 2 and older) or an op not named here gets the title of its
// shape: LEDGER_NO_OP.field when it names a field, .url when it names only a source, .none when it names neither.
// LEDGER_TITLE and LEDGER_NO_OP of publish/pages.py hold the same words; test_publish.py checks the copy.
export const LEDGER_TITLE = {
  set: 'amended; the old and the new value are not published',
  basis: 'amended; the old and the new value are not published',
  confirm: 'confirmed on its source; only the check date changed',
  dead: 'marked dead',
  undo: 'an earlier change undone',
  undo_skipped: 'undo skipped; the value did not change',
  append_evidence: 'evidence row added',
  drop_evidence: 'evidence row removed',
  relate: 'relation to another record added',
  add_record: 'record added'
};
export const LEDGER_NO_OP = {
  field: 'amended; the old and the new value are not published',
  url: 'evidence row or relation changed; the row does not say how',
  none: 'record changed; the row names no field'
};
const sqlText = (s) => "'" + String(s).replace(/'/g, "''") + "'";
// the SQL of the title of a ledger row, over the columns op, path and url (and old and new, which only a local store
// fills)
export const LEDGER_TITLE_SQL = `CASE WHEN old IS NOT NULL OR new IS NOT NULL THEN coalesce(old, '') || ' -> ' || coalesce(new, '')
  ${Object.entries(LEDGER_TITLE).map(([op, t]) => `WHEN op = ${sqlText(op)} THEN ${sqlText(t)}`).join(' ')}
  WHEN path IS NOT NULL THEN ${sqlText(LEDGER_NO_OP.field)} WHEN url IS NOT NULL THEN ${sqlText(LEDGER_NO_OP.url)}
  ELSE ${sqlText(LEDGER_NO_OP.none)} END`;

/** A tabular result. rows are arrays aligned with columns. */
function table(columns, rows, extra = {}) {
  return { columns, rows, total: rows.length, truncated: false, offset: 0, notes: [], excluded: {}, ...extra };
}

// ------------------------------------------------------------------ parameters

const bad = (m) => new HttpError(400, m);

function str(v, name, max = 200) {
  if (v == null || v === '') return null;
  if (Array.isArray(v)) v = v[v.length - 1];
  if (typeof v !== 'string' && typeof v !== 'number') throw bad(name + ' must be a string');
  const s = String(v).trim();
  if (s.length > max) throw bad(name + ' is longer than ' + max + ' characters');
  return s || null;
}

function list(v, name) {
  if (v == null || v === '') return [];
  const parts = (Array.isArray(v) ? v : [v]).flatMap((x) => String(x).split(','));
  const out = parts.map((x) => x.trim()).filter(Boolean);
  if (out.length > 50) throw bad(name + ': at most 50 values');
  for (const x of out) if (x.length > 200) throw bad(name + ': value too long');
  return out;
}

const TRUE = new Set([true, 1, '1', 'true', 'yes']);
const FALSE = new Set([false, 0, '0', 'false', 'no', '', null, undefined]);

/** A flag: 1, true or yes; 0, false, no or absent. Any other value is a 400, so a typo never reads as false. */
function bool(v, name) {
  if (Array.isArray(v)) v = v[v.length - 1];
  if (typeof v === 'string') v = v.trim().toLowerCase();
  if (TRUE.has(v)) return true;
  if (FALSE.has(v)) return false;
  throw bad(name + ' must be 1, true or yes, or 0, false or no');
}

function int(v, name, def, min, max) {
  if (Array.isArray(v)) v = v[v.length - 1];
  if (v == null || v === '') return def;
  const n = Number(v);
  if (!Number.isInteger(n)) throw bad(name + ' must be an integer');
  if (n < min || n > max) throw bad(name + ' must be between ' + min + ' and ' + max);
  return n;
}

function num(v, name) {
  if (Array.isArray(v)) v = v[v.length - 1];
  if (v == null || v === '') return null;
  const n = Number(v);
  if (!Number.isFinite(n)) throw bad(name + ' must be a number');
  return n;
}

function day(v, name) {
  const s = str(v, name, 10);
  if (!s) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || Number.isNaN(Date.parse(s + 'T00:00:00Z'))) throw bad(name + ' must be YYYY-MM-DD');
  return s;
}

function addDays(d, n) {
  const t = new Date(Date.parse(d + 'T00:00:00Z') + n * 86400000);
  return t.toISOString().slice(0, 10);
}

const marks = (n) => new Array(n).fill('?').join(',');

/** Note every parameter the operation does not know, so a typo is visible rather than silent. */
function unknownParams(p, known) {
  const out = [];
  for (const k of Object.keys(p)) if (!known.has(k) && k !== 'format') out.push('ignored parameter: ' + k);
  return out;
}

// ------------------------------------------------------------------ vocabularies

/**
 * The terms a filter may name: {topic, verdict, grp, confidence, binding}, each a Set in display order. The topics are
 * the ones that data/manifest.json lists, in the order of the topic bar, and then any topic that has records and is not
 * listed. A topic with no records yet is still a topic: it is valid and its list is empty.
 */
export function vocabOf(store) {
  if (store.cache.vocab) return store.cache.vocab;
  const v = { verdict: new Set(), grp: new Set(), confidence: new Set(), binding: new Set() };
  for (const [d, t] of rows(store.db, 'SELECT domain, term FROM vocab ORDER BY domain, ord')) if (v[d]) v[d].add(t);
  const have = rows(store.db, 'SELECT DISTINCT topic FROM record ORDER BY topic').map((r) => r[0]);
  const order = (store.manifest && store.manifest.topics) || [];
  v.topic = new Set([...order, ...have.filter((t) => !order.includes(t))]);
  store.cache.vocab = v;
  return v;
}

/** Check a list of terms against a vocabulary. Every vocabulary is closed: an unknown term is a 400 that lists the terms. */
function terms(store, domain, vals) {
  const known = vocabOf(store)[domain];
  const unknown = vals.filter((x) => !known.has(x));
  if (unknown.length) {
    throw bad('unknown ' + domain + ' ' + unknown.map((x) => JSON.stringify(x)).join(', ') + '; ' + domain + ' is one of ' + [...known].join(', '));
  }
  return vals;
}

// ------------------------------------------------------------------ database helpers

function rows(db, sql, params = []) {
  const st = db.prepare(sql);
  try {
    if (params.length) st.bind(params);
    const out = [];
    while (st.step()) out.push(st.get());
    return out;
  } finally {
    st.free();
  }
}

function scalar(db, sql, params = []) {
  const r = rows(db, sql, params);
  return r.length ? r[0][0] : null;
}

function fixCard(r) {
  r[SUMMARY] = clip(r[SUMMARY], 120);
  return r;
}

function cardsByRid(db, rids) {
  const map = new Map();
  for (let i = 0; i < rids.length; i += 400) {
    const part = rids.slice(i, i + 400);
    for (const r of rows(db, `SELECT ${CARD_SELECT} FROM record WHERE rid IN (${marks(part.length)})`, part)) {
      map.set(r[0], fixCard(r));
    }
  }
  return map;
}

/**
 * The self-hosted records and entities of the store, once per isolate, from one pass over the records: {rids, eids,
 * best}. eids holds the entities whose every record is self-hosted; best maps each entity to rank.bestVorder of its
 * records, the best verdict of its hosted ones, so a self-hosted record never lifts its vendor in a name search. A
 * self-hosted record is the last resort: every list puts it after every hosted one.
 */
function selfHosted(store) {
  if (!store.cache.selfHosted) {
    const rids = new Set();
    const members = new Map();
    for (const [rid, eid, vorder, sh] of rows(store.db, 'SELECT rid, eid, vorder, self_hosted FROM record')) {
      if (sh) rids.add(rid);
      if (!members.has(eid)) members.set(eid, []);
      members.get(eid).push([vorder, sh]);
    }
    const eids = new Set();
    const best = new Map();
    for (const [eid, m] of members) {
      if (m.every(([, sh]) => sh)) eids.add(eid);
      best.set(eid, bestVorder(m));
    }
    store.cache.selfHosted = { rids, eids, best };
  }
  return store.cache.selfHosted;
}

const SELF_HOSTED_NOTE = (n, what) => `self-hosted: ${n} ${what}, listed after every hosted ${what === 'rows' ? 'row' : 'record'}`;

function sortEntities(store, hits) {
  const { eids, best } = selfHosted(store);
  return orderEntities(hits, (eid) => best.get(eid) ?? 99, (eid) => eids.has(eid));
}

// ------------------------------------------------------------------ search

const SEARCH_KEYS = new Set(['q', 'topic', 'grp', 'limit', 'offset', 'include_duplicates']);

export function search(store, p) {
  const db = store.db;
  const q = str(p.q, 'q');
  if (!q) throw bad('q is required');
  const limit = int(p.limit, 'limit', 20, 1, 50);
  const offset = int(p.offset, 'offset', 0, 0, 100000);
  const notes = unknownParams(p, SEARCH_KEYS);
  const topics = terms(store, 'topic', list(p.topic, 'topic'));
  const grps = terms(store, 'grp', list(p.grp, 'grp'));
  const where = [];
  const args = [];
  if (topics.length) { where.push(`topic IN (${marks(topics.length)})`); args.push(...topics); }
  if (grps.length) { where.push(`grp IN (${marks(grps.length)})`); args.push(...grps); }
  if (!bool(p.include_duplicates, 'include_duplicates')) where.push('duplicate_of IS NULL');

  // 1. names
  const idx = nameIndex(store);
  const named = sortEntities(store, scoreNames(idx, q));
  const order = [];
  const matched = new Map();
  if (named.length) {
    const byEid = new Map();
    const eids = named.map((e) => e.eid);
    for (let i = 0; i < eids.length; i += 400) {
      const part = eids.slice(i, i + 400);
      const sql = `SELECT eid, rid, provider, slug FROM record WHERE eid IN (${marks(part.length)})` +
        (where.length ? ' AND ' + where.join(' AND ') : '') + ' ORDER BY vorder, rid';
      for (const [eid, rid, provider, slug] of rows(db, sql, [...part, ...args])) {
        if (!byEid.has(eid)) byEid.set(eid, []);
        byEid.get(eid).push([rid, provider, slug]);
      }
    }
    const ents = store.cache.entities || new Map();
    for (const e of named) {
      for (const rid of nameHitRecords(q, e, ents.get(e.eid), byEid.get(e.eid) || [])) {
        if (matched.has(rid)) continue;
        matched.set(rid, ['name(' + e.how + ')']);
        order.push(rid);
      }
    }
  }
  const nName = order.length;

  // 2. full text
  const match = ftsMatch(q);
  let nText = 0;
  if (match) {
    let hits = [];
    try {
      const st = db.prepare(
        `SELECT r.rid, r.vorder, matchinfo(text_fts, 'pcnalx') FROM text_fts JOIN record r ON r.rno = text_fts.docid
         WHERE text_fts MATCH ?` + (where.length ? ' AND ' + where.join(' AND ') : ''));
      try {
        st.bind([match, ...args]);
        while (st.step()) {
          const [rid, vorder, mi] = st.get();
          const s = bm25(mi);
          hits.push({ rid, vorder, score: s.score, cols: s.matched });
        }
      } finally {
        st.free();
      }
    } catch (e) {
      notes.push('full-text query not run: ' + String(e.message || e));
      hits = [];
    }
    hits.sort((a, b) => b.score - a.score || a.vorder - b.vorder || (a.rid < b.rid ? -1 : 1));
    for (const h of hits) {
      if (matched.has(h.rid)) {
        matched.get(h.rid).push(...h.cols);
        continue;
      }
      matched.set(h.rid, h.cols);
      order.push(h.rid);
      nText++;
    }
  }

  // 3. hosted first: the whole list, name hits and then text hits, splits in two, and each part keeps its order
  const sh = selfHosted(store).rids;
  const all = hostedFirst(order, (rid) => sh.has(rid));
  const nSelf = all.filter((rid) => sh.has(rid)).length;
  const page = all.slice(offset, offset + limit);
  const cards = cardsByRid(db, page);
  const out = page.filter((rid) => cards.has(rid)).map((rid) => [...cards.get(rid), matched.get(rid).join(',')]);
  notes.push(`name hits: ${nName} records; text hits: ${nText} more`);
  if (nSelf) notes.push(SELF_HOSTED_NOTE(nSelf, 'records'));
  return table([...CARD_COLUMNS, 'matched'], out, {
    total: all.length, offset, truncated: offset + out.length < all.length, notes,
  });
}

/** The best score of a few names against a query, by the rules of rank.scoreNames; 0 when none matches. */
function ownScore(q, names) {
  const hits = scoreNames(buildNameIndex(names.filter(Boolean).map((alias) => ({ eid: '-', alias }))), q);
  return hits.length ? hits[0].score : 0;
}

/**
 * The records that a name hit of an entity lifts to the top of a search. When the vendor's own name or domain scores as
 * well as the alias that matched, every record of the vendor; else the records whose own name (provider or slug) scores
 * that well, so one record's name ("Google Cloud Storage Always Free tier") does not lift every other record of its
 * vendor above the records whose text matches. A hit through an alias that no record's name carries (a record's
 * extras.aliases) keeps every record. recs: [[rid, provider, slug]] in list order. fr.py op_search is the twin.
 */
function nameHitRecords(q, hit, ent, recs) {
  if (!ent || ownScore(q, [ent.name, ent.domain]) >= hit.score) return recs.map((r) => r[0]);
  const mine = recs.filter(([, provider, slug]) => ownScore(q, [provider, slug]) >= hit.score);
  return (mine.length ? mine : recs).map((r) => r[0]);
}

// ------------------------------------------------------------------ entity search (names only)

const ENTITY_SEARCH_KEYS = new Set(['q', 'limit', 'offset']);

export function entitySearch(store, p) {
  const q = str(p.q, 'q');
  if (!q) throw bad('q is required');
  const limit = int(p.limit, 'limit', 20, 1, 50);
  const offset = int(p.offset, 'offset', 0, 0, 100000);
  nameIndex(store);
  const hits = sortEntities(store, scoreNames(store.cache.names, q));
  const ents = store.cache.entities;
  const { eids: sh, best } = selfHosted(store);
  const out = hits.slice(offset, offset + limit).map((h) => {
    const e = ents.get(h.eid) || {};
    return [h.eid, e.name, e.domain, e.topics, e.n_records, best.get(h.eid) ?? e.best_vorder, h.score, h.how, h.alias];
  });
  const notes = unknownParams(p, ENTITY_SEARCH_KEYS);
  const nSelf = hits.filter((h) => sh.has(h.eid)).length;
  if (nSelf) notes.push(`self-hosted: ${nSelf} entities whose every record is self-hosted, listed after every other entity`);
  return table(['eid', 'name', 'domain', 'topics', 'n_records', 'best_vorder', 'score', 'match', 'alias'], out, {
    total: hits.length, offset, truncated: offset + out.length < hits.length, notes,
  });
}

// ------------------------------------------------------------------ filter

const FILTER_KEYS = new Set(['topic', 'verdict', 'grp', 'confidence', 'no_card', 'no_phone', 'anonymous', 'iface',
  'binding', 'crypto', 'max_usd_month', 'max_usd_tb', 'include_duplicates', 'sort', 'order', 'limit', 'offset']);

export function filter(store, p) {
  const db = store.db;
  const notes = unknownParams(p, FILTER_KEYS);
  const where = [];
  const args = [];
  const inList = (col, vals) => {
    if (vals.length) { where.push(`${col} IN (${marks(vals.length)})`); args.push(...vals); }
  };
  for (const d of ['topic', 'verdict', 'grp', 'confidence', 'binding']) inList(d, terms(store, d, list(p[d], d)));
  if (bool(p.no_card, 'no_card')) where.push("needs_card = 0 AND identity_basis = 'stated'");
  if (bool(p.no_phone, 'no_phone')) where.push("needs_phone = 0 AND identity_basis = 'stated'");
  if (bool(p.anonymous, 'anonymous')) where.push("identity_kind = 'anonymous' AND identity_basis = 'stated'");
  const iface = str(p.iface, 'iface');
  if (iface) { where.push('instr(lower(coalesce(interfaces, \'\')), lower(?)) > 0'); args.push(iface); }
  if (p.crypto != null && p.crypto !== '') where.push(bool(p.crypto, 'crypto') ? 'crypto = 1' : 'crypto IS NOT 1');
  if (!bool(p.include_duplicates, 'include_duplicates')) where.push('duplicate_of IS NULL');

  const sort = str(p.sort, 'sort') || 'vorder';
  if (!SORTS.has(sort)) throw bad('sort must be one of ' + [...SORTS].join(', '));
  const order = (str(p.order, 'order') || 'asc').toLowerCase();
  if (order !== 'asc' && order !== 'desc') throw bad('order must be asc or desc');
  const limit = int(p.limit, 'limit', 50, 1, 200);
  const offset = int(p.offset, 'offset', 0, 0, 1000000);

  // price conditions: rows with a NULL price are excluded and counted, never dropped silently
  const price = new Map();
  const mu = num(p.max_usd_month, 'max_usd_month');
  const mt = num(p.max_usd_tb, 'max_usd_tb');
  if (mu != null) price.set('usd_month', mu);
  if (mt != null) price.set('usd_per_tb_month', mt);
  if (PRICE.has(sort) && !price.has(sort)) price.set(sort, null);
  const base = where.length ? where.join(' AND ') : '1';
  const excluded = {};
  for (const col of price.keys()) {
    excluded[col] = scalar(db, `SELECT count(*) FROM record WHERE ${base} AND ${col} IS NULL`, args);
  }
  const fw = [...where];
  const fa = [...args];
  for (const [col, max] of price) {
    fw.push(`${col} IS NOT NULL`);
    if (max != null) { fw.push(`${col} <= ?`); fa.push(max); }
  }
  const W = fw.length ? fw.join(' AND ') : '1';
  const total = scalar(db, `SELECT count(*) FROM record WHERE ${W}`, fa);
  const dir = order.toUpperCase();
  const extra = CARD_COLUMNS.includes(sort) || sort === 'vorder' ? [] : [sort];
  const sql = `SELECT ${CARD_SELECT}${extra.map((c) => ', ' + c).join('')} FROM record WHERE ${W}
    ORDER BY self_hosted, ${sort} IS NULL, ${sort} ${dir}, vorder, rid LIMIT ? OFFSET ?`;
  const out = rows(db, sql, [...fa, limit, offset]).map(fixCard);
  const nSelf = scalar(db, `SELECT count(*) FROM record WHERE ${W} AND self_hosted = 1`, fa);
  if (nSelf) notes.push(SELF_HOSTED_NOTE(nSelf, 'records'));
  return table([...CARD_COLUMNS, ...extra], out, {
    total, offset, truncated: offset + out.length < total, notes, excluded,
  });
}

// ------------------------------------------------------------------ get

const ENTITY_CACHE_MAX = 32;

async function entityDoc(store, env, eid) {
  const c = store.cache.entityDocs || (store.cache.entityDocs = new Map());
  if (c.has(eid)) {
    const v = c.get(eid);
    c.delete(eid);
    c.set(eid, v);
    return v;
  }
  if (!/^[A-Za-z0-9._-]+$/.test(eid)) throw new HttpError(404, 'unknown entity');
  const doc = await asset(env, 'api/v1/entity/' + eid + '.json', 'json');
  c.set(eid, doc);
  if (c.size > ENTITY_CACHE_MAX) c.delete(c.keys().next().value);
  return doc;
}

/** The full record object {rid, card, record, claims, unknown, history, drift}, or null. */
export async function fullRecord(store, env, rid) {
  const r = all(store.db, 'SELECT eid FROM record WHERE rid = ?', [rid]);
  if (!r.length) return null;
  const doc = await entityDoc(store, env, r[0].eid);
  const hit = (doc.records || []).find((x) => x && x.rid === rid);
  if (!hit) throw new HttpError(500, 'record ' + rid + ' missing from its entity file');
  return hit.card ? hit : { rid, card: hit };
}

function pick(obj, path) {
  let cur = obj;
  for (const k of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = cur[k];
  }
  return cur;
}

const GET_KEYS = new Set(['ids', 'detail', 'fields']);

export async function get(store, env, p) {
  const ids = list(p.ids ?? p.id, 'ids');
  if (!ids.length) throw bad('ids is required (rid list, topic/slug)');
  const detail = str(p.detail, 'detail') || 'card';
  const fields = list(p.fields, 'fields');
  const notes = unknownParams(p, GET_KEYS);
  if (detail === 'card') {
    if (ids.length > 50) throw bad('detail=card takes at most 50 ids');
    let cols = CARD_COLUMNS;
    let found;
    if (fields.length) {
      const badF = fields.filter((f) => !RECORD_FIELDS.has(f));
      if (badF.length) throw bad('unknown field(s): ' + badF.join(', ') + '; card fields are record columns');
      cols = ['rid', ...fields.filter((f) => f !== 'rid')];
      found = new Map(rows(store.db, `SELECT ${cols.join(', ')} FROM record WHERE rid IN (${marks(ids.length)})`, ids).map((r) => [r[0], r]));
    } else {
      found = cardsByRid(store.db, ids);
    }
    const out = ids.filter((id) => found.has(id)).map((id) => found.get(id));
    const missing = ids.filter((id) => !found.has(id));
    if (missing.length) notes.push('not found: ' + missing.join(', '));
    return table(cols, out, { notes });
  }
  if (detail !== 'full') throw bad('detail must be card or full');
  if (ids.length > 5) throw bad('detail=full takes at most 5 ids');
  const records = [];
  const missing = [];
  for (const id of ids) {
    const full = await fullRecord(store, env, id);
    if (!full) { missing.push(id); continue; }
    if (fields.length) {
      const o = { rid: id };
      for (const f of fields) o[f] = pick(full, f) ?? null;
      records.push(o);
    } else {
      records.push(full);
    }
  }
  if (missing.length) notes.push('not found: ' + missing.join(', '));
  return { json: { records, missing, notes } };
}

// ------------------------------------------------------------------ entity

const ENTITY_KEYS = new Set(['id', 'name', 'q', 'include_duplicates']);

export function entity(store, p) {
  const db = store.db;
  const id = str(p.id, 'id');
  const name = str(p.name ?? p.q, 'name');
  if (!id && !name) throw bad('id or name is required');
  const notes = unknownParams(p, ENTITY_KEYS);
  let e = id ? all(db, 'SELECT * FROM entity WHERE eid = ?', [id])[0] : null;
  if (!e) {
    nameIndex(store);
    // one answer, not a list: the best score wins, so an exact name is never beaten by a fuzzy match of another vendor
    // (rank.resolveEntity); the other matches keep the hosted-first order of sortEntities
    const hits = sortEntities(store, scoreNames(store.cache.names, name || id));
    const hit = resolveEntity(hits);
    if (!hit) throw new HttpError(404, 'no entity matches ' + JSON.stringify(name || id));
    e = all(db, 'SELECT * FROM entity WHERE eid = ?', [hit.eid])[0];
    notes.push(`resolved by name (${hit.how}: ${hit.alias})`);
    const others = hits.filter((h) => h !== hit);
    if (others.length) {
      notes.push('other matches: ' + others.slice(0, 5).map((h) => `${h.eid} (${h.how})`).join(', ') +
        (others.length > 5 ? `, and ${others.length - 5} more` : ''));
    }
  }
  if (selfHosted(store).eids.has(e.eid)) notes.push('self-hosted: every record of this entity is self-hosted, so it is the last resort');
  // a duplicate (record.duplicate_of) is left out, as in every other list, unless asked for; the footer counts it
  const dups = rows(db, 'SELECT rid, duplicate_of FROM record WHERE eid = ? AND duplicate_of IS NOT NULL ORDER BY rid', [e.eid]);
  const withDups = bool(p.include_duplicates, 'include_duplicates');
  const out = rows(db, `SELECT ${CARD_SELECT} FROM record WHERE eid = ?` + (withDups ? '' : ' AND duplicate_of IS NULL') +
    ' ORDER BY self_hosted, vorder, rid', [e.eid]).map(fixCard);
  if (dups.length) {
    notes.push((withDups ? `${dups.length} duplicates listed: ` : `${dups.length} duplicates left out (include_duplicates=1 lists them): `) +
      dups.slice(0, 5).map(([rid, of]) => `${rid} of ${of}`).join(', ') + (dups.length > 5 ? `, and ${dups.length - 5} more` : ''));
  }
  notes.unshift(`entity ${e.eid}: ${e.name}` + (e.domain ? ` (${e.domain})` : '') +
    `; topics ${e.topics}; ${e.n_records} records; resolved by ${e.resolved_by}` + (e.review ? '; review: ' + e.review : ''));
  return table(CARD_COLUMNS, out, { notes, entity: e });
}

// ------------------------------------------------------------------ need

async function needs(store, env) {
  if (!store.cache.needs) store.cache.needs = await asset(env, 'api/v1/needs.json', 'json');
  return store.cache.needs;
}

const NEED_KEYS = new Set(['id', 'limit', 'offset']);

// A need that asks for no card or no phone lists its confirmed rows. The records whose requirement is not stated (NULL, or an
// identity that no source states) follow in a section of their own, read from the need's SQL without its conditions on the
// card, the phone and a stated identity. publish/llms.py need_unstated is the same rule.
const STATED_CONDITION = /\s+AND\s+(?:needs_card=0|needs_phone=0|identity_basis='stated')(?=\s|$)/g;
export const UNSTATED_HEADING = 'Card or phone requirement not stated';

export async function need(store, env, p) {
  const id = str(p.id, 'id');
  const doc = await needs(store, env);
  const notes = unknownParams(p, NEED_KEYS);
  if (!id) {
    const out = doc.needs.map((n) => [n.id, n.title, n.topic, n.sort, clip(n.scope, 160)]);
    return table(['id', 'title', 'topic', 'sort', 'scope'], out, { notes });
  }
  const n = doc.needs.find((x) => x.id === id);
  // the ids themselves, not a route: the HTTP API and the MCP tool give the same answer
  if (!n) throw new HttpError(404, 'unknown need ' + JSON.stringify(id) + '; the needs are ' + doc.needs.map((x) => x.id).join(', '));
  const limit = int(p.limit, 'limit', 50, 1, 200);
  const offset = int(p.offset, 'offset', 0, 0, 100000);
  // the need's own SQL (shipped with the build), joined to the record for the order of a tie: the verdict, the
  // evidence rung, the later stale date, then the record id. publish/llms.py need_key is the same order. Self-hosted
  // rows come after every hosted row: hosted ranked, with no number and not stated, then the self-hosted rows in the
  // same order (publish/llms.py need_lists).
  const hits = all(store.db, `SELECT h.*, r.vorder AS _vorder, r.confidence AS _conf, r.stale_on AS _stale,
    r.self_hosted AS _sh FROM (${n.sql}) AS h JOIN record r ON r.rid = h.rid`);
  const key = n.sort;
  const ev = (x) => RUNG[x._conf] ?? RUNG_UNKNOWN;
  const later = (x, y) => ((y._stale || '') < (x._stale || '') ? -1 : (y._stale || '') > (x._stale || '') ? 1 : 0);
  const tie = (x, y) => x._vorder - y._vorder || ev(x) - ev(y) || later(x, y) || (x.rid < y.rid ? -1 : x.rid > y.rid ? 1 : 0);
  const ranked = hits.filter((h) => h[key] != null).sort((x, y) => x[key] - y[key] || tie(x, y));
  const nulls = hits.filter((h) => h[key] == null).sort(tie);
  const flags = ['needs_card', 'needs_phone'].filter((f) => n.sql.includes(f + '=0'));
  let unstated = [];
  if (flags.length) {
    const relaxed = all(store.db, `SELECT h.*, r.vorder AS _vorder, r.confidence AS _conf, r.stale_on AS _stale, r.needs_card AS _card,
      r.needs_phone AS _phone, r.self_hosted AS _sh FROM (${n.sql.replace(STATED_CONDITION, '')}) AS h JOIN record r ON r.rid = h.rid`);
    const have = new Set(hits.map((h) => h.rid));
    const rest = relaxed.filter((h) => !have.has(h.rid) && flags.every((f) => (f === 'needs_card' ? h._card : h._phone) !== 1));
    unstated = [...rest.filter((h) => h[key] != null).sort((x, y) => x[key] - y[key] || tie(x, y)), ...rest.filter((h) => h[key] == null).sort(tie)];
  }
  // hosted first: the whole list (ranked, with no number, not stated) splits in two, and each part keeps its order
  const isSelf = (h) => h._sh === 1;
  const seq = hostedFirst([...ranked, ...nulls, ...unstated], isSelf);
  const nSelf = seq.filter(isSelf).length;
  const page = seq.slice(offset, offset + limit);
  const isUnstated = new Set(unstated.map((h) => h.rid));
  const cards = cardsByRid(store.db, page.map((h) => h.rid));
  const extra = CARD_COLUMNS.includes(key) ? [] : [key];
  const toRow = (h) => [...cards.get(h.rid), ...extra.map((k) => h[k])];
  const inPage = (h) => cards.has(h.rid);
  const hosted = (h) => !isSelf(h) && inPage(h);
  const out = page.filter((h) => hosted(h) && !isUnstated.has(h.rid) && h[key] != null).map(toRow);
  const nullOut = page.filter((h) => hosted(h) && !isUnstated.has(h.rid) && h[key] == null).map(toRow);
  const unstatedOut = page.filter((h) => hosted(h) && isUnstated.has(h.rid)).map(toRow);
  const selfOut = page.filter((h) => isSelf(h) && inPage(h) && !isUnstated.has(h.rid)).map(toRow);
  const selfUnstatedOut = page.filter((h) => isSelf(h) && inPage(h) && isUnstated.has(h.rid)).map(toRow);
  notes.unshift(`${n.title}: ${n.scope}`);
  // one count for each part: the hosted rows ranked, with no number and not stated, then the self-hosted rows
  // (pages.py need())
  const nHosted = (xs) => xs.filter((h) => !isSelf(h)).length;
  const hw = nSelf ? 'hosted ' : '';
  notes.push(`sorted by ${key} ascending; ${nHosted(ranked)} ${hw}ranked, ${nHosted(nulls)} ${hw}with no parsed ${key}` +
    (nSelf ? `, ${nSelf} self-hosted` : ''));
  if (flags.length) {
    notes.push(`${nHosted(unstated)} ${hw}rows with the card or phone requirement not stated follow the others; they are not counted as no`);
  }
  if (nSelf) {
    const nSelfUnstated = unstated.filter(isSelf).length;
    notes.push(SELF_HOSTED_NOTE(nSelf, 'rows') + `, in self_hosted_rows: ranked, then with no parsed ${key}` +
      (nSelfUnstated ? `; ${nSelfUnstated} of them with the card or phone requirement not stated, in self_hosted_unstated_rows` : ''));
  }
  return table([...CARD_COLUMNS, ...extra], out, {
    total: seq.length, offset, truncated: offset + page.length < seq.length, notes, nullRows: nullOut, nullKey: key,
    unstatedRows: unstatedOut, selfRows: selfOut, selfUnstatedRows: selfUnstatedOut,
    need: { id: n.id, title: n.title, topic: n.topic, sort: key, scope: n.scope, sql: n.sql },
  });
}

// ------------------------------------------------------------------ sql

export function sql(store, p) {
  const query = typeof (p.q ?? p.query) === 'string' ? (p.q ?? p.query) : null;
  if (!query) throw bad('q (the SQL text) is required');
  const limit = int(p.limit, 'limit', 100, 1, 200);
  let g;
  try {
    // one row past the cap tells whether more rows exist
    g = guard(query, limit + 1);
  } catch (e) {
    if (e instanceof GuardError) throw bad('refused: ' + e.message);
    throw e;
  }
  let r;
  try {
    checkPlan(store, g.sql); // the statement budget: the rows that the plan reads (issue #5)
    r = capped(store, g.sql, limit);
  } catch (e) {
    throw sqlFailure(store, e);
  }
  const out = r.rows.map((row) => row.map((v) => (v instanceof Uint8Array ? blobText(v) : v)));
  const notes = [];
  if (g.appendedLimit) notes.push('LIMIT ' + limit + ' applied');
  if (r.truncated) notes.push('row cap ' + limit + ' reached; more rows exist');
  return table(r.columns, out, { truncated: r.truncated, total: out.length, notes, open: r.truncated });
}

/**
 * The error that the caller sees for a statement that failed: a refusal of the guard, the budget or the result cap,
 * an "out of memory" of the heap limit (400), a failure of the engine itself (503, and the next request opens a new
 * copy of the store on the same engine), else the SQLite error (400). A statement that the platform stops at
 * limits.cpu_ms never gets here: the caller sees the error page of the platform (error 1102, HTTP 503).
 */
function sqlFailure(store, e) {
  if (e instanceof HttpError) return e;
  if (e instanceof GuardError) return bad('refused: ' + e.message);
  const m = String((e && e.message) || e);
  if (/out of memory|string or blob too big/i.test(m)) {
    return bad('refused: the statement needs more than the ' + HEAP_LIMIT_MIB + ' MiB that one statement may use; ' +
      'select fewer rows or shorter values');
  }
  if (engineFailed(e)) {
    discard(store);
    console.error('fshy sql engine failed:', m);
    return new HttpError(503, 'the SQL engine failed on this statement and the store is opened again; send a smaller statement');
  }
  return bad('SQL error: ' + m);
}

function blobText(b) {
  const n = Math.min(b.length, 64);
  let h = '';
  for (let i = 0; i < n; i++) h += b[i].toString(16).padStart(2, '0');
  return "x'" + h + "'" + (b.length > n ? ` (${b.length} bytes)` : '');
}

// ------------------------------------------------------------------ worklist

const WORK_KEYS = new Set(['kind', 'topic', 'as_of', 'forecast_days', 'limit', 'offset']);

export function worklist(store, p) {
  const db = store.db;
  const kind = str(p.kind, 'kind');
  if (!kind) throw bad('kind is required: stale, drift, changes or unparsed');
  if (LOCAL_ONLY_KINDS.has(kind)) throw bad('worklist ' + kind + ' is not in the public store');
  if (!KINDS.has(kind)) throw bad('kind must be stale, drift, changes or unparsed');
  const notes = unknownParams(p, WORK_KEYS);
  const topic = str(p.topic, 'topic');
  if (topic) terms(store, 'topic', [topic]);
  const limit = int(p.limit, 'limit', 50, 1, 200);
  const offset = int(p.offset, 'offset', 0, 0, 1000000);
  const page = (cols, countSql, sel, args) => {
    const total = scalar(db, countSql, args);
    const out = rows(db, sel + ' LIMIT ? OFFSET ?', [...args, limit, offset]);
    return table(cols, out, { total, offset, truncated: offset + out.length < total, notes });
  };

  if (kind === 'stale') {
    const asOf = day(p.as_of, 'as_of') || new Date().toISOString().slice(0, 10);
    const fd = int(p.forecast_days, 'forecast_days', 0, 0, 3650);
    const cutoff = addDays(asOf, fd);
    const w = ['stale_on IS NOT NULL', 'stale_on <= ?', 'duplicate_of IS NULL'];
    const a = [cutoff];
    if (topic) { w.push('topic = ?'); a.push(topic); }
    notes.push(`as_of ${asOf}, forecast_days ${fd}: stale when stale_on <= ${cutoff}; verified_basis inherited means checked_on is an upper bound`);
    const W = w.join(' AND ');
    const t = page([...CARD_COLUMNS, 'checked_on', 'verified_basis'], `SELECT count(*) FROM record WHERE ${W}`,
      `SELECT ${CARD_SELECT}, checked_on, verified_basis FROM record WHERE ${W} ORDER BY self_hosted, vorder, stale_on, rid`, a);
    t.rows.forEach(fixCard);
    return t;
  }
  if (kind === 'drift') {
    const W = topic ? 'WHERE d.subject LIKE ? OR d.other LIKE ?' : '';
    const a = topic ? [topic + '/%', topic + '/%'] : [];
    // a pair of records: the self_hosted of its subject is the first key (fr.py worklist drift)
    return page(['kind', 'subject', 'other', 'field', 'a', 'b', 'detail'], `SELECT count(*) FROM drift d ${W}`,
      `SELECT d.kind, d.subject, d.other, d.field, d.a, d.b, d.detail FROM drift d LEFT JOIN record r ON r.rid = d.subject
       ${W} ORDER BY coalesce(r.self_hosted, 0), d.kind, d.subject, d.other`, a);
  }
  if (kind === 'changes') {
    const hw = topic ? 'WHERE h.hid IN (SELECT hid FROM history_link WHERE rid LIKE ?)' : '';
    const lw = topic ? 'WHERE rid LIKE ?' : '';
    const a = topic ? [topic + '/%', topic + '/%'] : [];
    const body = `SELECT h.when_utc AS at, 'history' AS source, h.hid AS ref, h.status AS status, h.title AS title,
        (SELECT group_concat(rid, ' ') FROM history_link l WHERE l.hid = h.hid) AS rids FROM history h ${hw}
      UNION ALL
      SELECT at, 'ledger', CASE WHEN path LIKE '$.%' THEN substr(path, 3) ELSE path END, rung, ${LEDGER_TITLE_SQL}, rid
        FROM ledger ${lw}`;
    return page(['at', 'source', 'ref', 'status', 'title', 'rids'], `SELECT count(*) FROM (${body})`,
      `SELECT * FROM (${body}) ORDER BY at DESC, ref`, a);
  }
  // unparsed
  const W = "c.parse = 'unparsed'" + (topic ? ' AND r.topic = ?' : '');
  const a = topic ? [topic] : [];
  notes.push('claims whose value carries no parsed number; the text is in the record (get detail=full)');
  return page(['rid', 'provider', 'verdict', 'path', 'kind'],
    `SELECT count(*) FROM claim c JOIN record r USING (rid) WHERE ${W}`,
    `SELECT c.rid, r.provider, r.verdict, c.path, c.kind FROM claim c JOIN record r USING (rid) WHERE ${W}
     ORDER BY r.self_hosted, r.vorder, c.rid, c.path`, a);
}

// ------------------------------------------------------------------ help

export async function help(store, env) {
  try {
    return await asset(env, 'api/v1/help.txt');
  } catch (e) {
    if (!(e instanceof HttpError) || e.status !== 404) throw e;
  }
  if (store.cache.help) return store.cache.help;
  const db = store.db;
  const topics = rows(db, 'SELECT topic, count(*) FROM record GROUP BY topic ORDER BY topic').map((r) => `${r[0]} ${r[1]}`);
  const vocab = {};
  for (const [d, t] of rows(db, 'SELECT domain, term FROM vocab ORDER BY domain, ord')) (vocab[d] = vocab[d] || []).push(t);
  const cols = rows(db, "SELECT name FROM pragma_table_info('record')").map((r) => r[0]).filter((c) => c !== 'doc');
  const tables = rows(db, "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'text_fts_%' ORDER BY name").map((r) => r[0]);
  const nd = await needs(store, env);
  const m = store.manifest;
  const text = [
    `fshy: a read-only catalogue of free and cheap capability: storage, compute, GPU time, inference, crawling,`,
    `egress, email, databases, DNS, CI runners, proxies, developer services, data APIs. Built from commit ${String(m.commit || '').slice(0, 12)} (as of ${m.as_of}).`,
    ``,
    `Records by topic: ${topics.join(', ')}.`,
    `rid = topic/slug (stable). grp: ${(vocab.grp || []).join(' | ')}. verdict in order (vorder 0..7, lower is better):`,
    `  ${(vocab.verdict || []).join(', ')}.`,
    `Unknown is NULL, never "no": card ? means not stated. No card = needs_card=0 AND identity_basis='stated'.`,
    `identity shows identity_kind, with ? when the requirement was defaulted or inferred rather than read.`,
    `usd_month and usd_per_tb_month are headline prices, NULL when nothing parsed; a filter or sort on them`,
    `excludes NULL rows and reports how many. stale_on <= today means the record is due for a re-check.`,
    `self_hosted = 1 is software or a node that the user installs and runs. Self-hosted options are listed last, because`,
    `the site is for users with no hardware: every list sorts on self_hosted first.`,
    ``,
    `Operations (HTTP /api/v1/... and MCP tools take the same names):`,
    `  search q [topic grp limit]          names first (exact, prefix, substring, fuzzy), then BM25 full text`,
    `  filter topic verdict grp confidence no_card no_phone anonymous iface binding crypto`,
    `         max_usd_month max_usd_tb include_duplicates sort order limit offset`,
    `  get ids [detail=card|full fields]   full = the record JSON with claims, unknown, history, drift`,
    `  entity id|name [include_duplicates] a vendor and its records; a duplicate is left out unless asked`,
    `  need [id]                           curated best-per-need lists`,
    `  sql q [limit]                       one read-only SELECT/WITH/VALUES/EXPLAIN; LIMIT added if absent; a costly plan is refused`,
    `  worklist stale|drift|changes|unparsed [topic as_of forecast_days]`,
    ``,
    `Tables: ${tables.join(', ')}.`,
    `record columns: ${cols.join(', ')}.`,
    `text_fts is FTS4 (docid = record.rno; columns name offer limits egress identity access notes evidence extras):`,
    `  SELECT r.rid FROM text_fts JOIN record r ON r.rno = text_fts.docid WHERE text_fts MATCH 'webdav*'`,
    `Vocabularies: ${Object.entries(vocab).filter(([d]) => !['grp', 'verdict'].includes(d)).map(([d, t]) => `${d}: ${t.join(' ')}`).join('; ')}.`,
    ``,
    `Needs: ${nd.needs.map((n) => n.id).join(', ')}.`,
    `Full record pages: /r/<topic>/<slug> on this host; JSON: /api/v1/record/<topic>/<slug>.`,
  ].join('\n');
  store.cache.help = text;
  return text;
}

// ------------------------------------------------------------------ rendering

function cell(v) {
  if (v == null) return '';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(+v.toFixed(4));
  const s = String(v).replace(/[\t\r\n]+/g, ' ');
  return clip(s, 200);
}

export function footer(t) {
  const lines = [];
  const shown = t.rows.length + (t.nullRows ? t.nullRows.length : 0) + (t.unstatedRows ? t.unstatedRows.length : 0) +
    (t.selfRows ? t.selfRows.length : 0) + (t.selfUnstatedRows ? t.selfUnstatedRows.length : 0);
  // a capped result (sql) says the cap in its own note, so the first line counts the rows only
  if (t.open) lines.push(`# ${shown} rows`);
  else if (t.truncated) lines.push(`# ${shown} of ${t.total} rows; offset=${t.offset + shown} for more`);
  else lines.push(`# ${shown} of ${t.total} rows`);
  for (const [col, n] of Object.entries(t.excluded || {})) lines.push(`# excluded for NULL ${col}: ${n}`);
  for (const n of t.notes || []) lines.push('# ' + String(n).replace(/[\r\n]+/g, ' '));
  return lines;
}

export function toTsv(t) {
  const lines = [t.columns.join('\t')];
  for (const r of t.rows) lines.push(r.map(cell).join('\t'));
  if (t.nullRows && t.nullRows.length) {
    lines.push(`# no parsed ${t.nullKey}: ${t.nullRows.length} rows below, unranked`);
    for (const r of t.nullRows) lines.push(r.map(cell).join('\t'));
  }
  if (t.unstatedRows && t.unstatedRows.length) {
    lines.push(`# ${UNSTATED_HEADING.toLowerCase()}: ${t.unstatedRows.length} rows below, not counted as no`);
    for (const r of t.unstatedRows) lines.push(r.map(cell).join('\t'));
  }
  if (t.selfRows && t.selfRows.length) {
    lines.push(`# self-hosted, the last resort: ${t.selfRows.length} rows below, after every hosted row`);
    for (const r of t.selfRows) lines.push(r.map(cell).join('\t'));
  }
  if (t.selfUnstatedRows && t.selfUnstatedRows.length) {
    lines.push(`# self-hosted, ${UNSTATED_HEADING.toLowerCase()}: ${t.selfUnstatedRows.length} rows below, not counted as no`);
    for (const r of t.selfUnstatedRows) lines.push(r.map(cell).join('\t'));
  }
  return { lines, footer: footer(t) };
}

export function toJson(t) {
  const o = { columns: t.columns, rows: t.rows, truncated: !!t.truncated, total: t.total, notes: t.notes || [] };
  if (t.offset) o.offset = t.offset;
  if (t.excluded && Object.keys(t.excluded).length) o.excluded_null = t.excluded;
  if (t.nullRows) o.null_rows = t.nullRows;
  if (t.unstatedRows && t.unstatedRows.length) o.unstated_rows = t.unstatedRows;
  if (t.selfRows) o.self_hosted_rows = t.selfRows;
  if (t.selfUnstatedRows && t.selfUnstatedRows.length) o.self_hosted_unstated_rows = t.selfUnstatedRows;
  if (t.entity) o.entity = t.entity;
  if (t.need) o.need = t.need;
  return o;
}
