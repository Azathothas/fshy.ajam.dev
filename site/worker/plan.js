// Statement budget (issue #5). sql.js has no progress handler, so the Worker cannot stop a statement after a number of
// steps. Before a statement runs, the Worker reads its EXPLAIN QUERY PLAN and accepts it only when the plan is cheap.
// This is the first and friendly refusal; the platform stops what it misses (limits.cpu_ms in wrangler.jsonc, and the
// heap limit of db.js).
//
// Each loop step of the plan reads some rows each time it runs:
//   - a scan reads the whole table, whatever follows the name ("SCAN x", "SCAN x USING COVERING INDEX i LEFT-JOIN",
//     "SCAN x EXISTS", ...); so does a SEARCH that has only a range constraint ("SEARCH x USING INDEX i (a>?)"), or a
//     constraint that the Worker cannot read;
//   - a SEARCH with an = constraint reads the rows of one key, and the Worker takes the largest key of that column: the
//     keystat table of the store holds it (publish/build.py), and a column that keystat lacks is counted once per
//     isolate. A rowid or an INTEGER PRIMARY KEY reads one row;
//   - a full-text step reads every document, except a docid lookup, which reads one;
//   - a MULTI-INDEX OR step reads the rows of all its parts; VALUES and constant rows read their rows;
//   - a materialized result or a co-routine holds at most the rows that its own steps read; a source that the Worker
//     cannot size counts as too large.
//
// The steps of one loop chain run nested: each runs once for each row of the steps before it, so it reads the
// product of the rows of the chain up to it. A chain is the loop steps under one plan node, plus those of a
// CORRELATED subquery under it, which runs once for each outer row. A subquery that is not correlated, a MATERIALIZE
// step and a CO-ROUTINE step run once, so each starts a chain of its own, unless a correlated subquery holds them; so
// does each part of a compound SELECT.
//
// Each row costs the work of the expressions that the statement evaluates on it: the weight of a row is 1, plus 1 for
// each function call, LIKE, GLOB, MATCH, REGEXP, -> and ->>, plus DATE_WEIGHT for each date and time function, plus
// one for each conversion and one for each WIDTH_UNIT characters of width or precision of a printf() or format(), plus
// n * n for n || operators (each copies the value that the ones before it built). The plan is refused when:
//   - a chain has two steps that read more than BIG_ROWS rows each, or
//   - the rows that all the steps of all the chains read, summed over the statement, times the weight of a row, are
//     over MAX_WORK.
// The weight is an estimate: a statement can still build a long value on each row, and the platform stops it.
// A recursive CTE is refused by the guard, and again here if the plan has one.

import { ALLOWED_FUNCTIONS, GuardError, strip } from './guard.js';

export const BIG_ROWS = 1000;
export const MAX_WORK = 5000000;
export const DATE_WEIGHT = 10;
export const WIDTH_UNIT = 50;
const DATE_FUNCTIONS = new Set(['date', 'datetime', 'julianday', 'strftime', 'time', 'timediff', 'unixepoch']);
const CALLS = new Set(ALLOWED_FUNCTIONS);
// a pragma_* table-valued function reads the schema: a few rows for each table, column or index
export const PRAGMA_ROWS = 100;
const SCAN_RE = /^SCAN (\S+)(?: (.*))?$/;
const SEARCH_RE = /^SEARCH (\S+)(.*)$/;
const ONCE_RE = /^(?:LIST SUBQUERY|SCALAR SUBQUERY|MATERIALIZE|CO-ROUTINE|COMPOUND QUERY|LEFT-MOST SUBQUERY|UNION ALL|UNION USING|INTERSECT USING|EXCEPT USING|MERGE \()/;
const NOT_ALIAS = new Set(['where', 'on', 'using', 'join', 'left', 'right', 'full', 'inner', 'outer', 'cross',
  'natural', 'group', 'order', 'limit', 'having', 'window', 'union', 'except', 'intersect', 'indexed', 'not', 'as']);

/** {table name: row count} of the store, counted once per isolate; sqlite_master and sqlite_schema included. */
export function tableRows(store) {
  if (store.cache.tableRows) return store.cache.tableRows;
  const rows = {};
  const r = store.db.exec("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'text_fts%'");
  for (const [name] of r.length ? r[0].values : []) {
    rows[name.toLowerCase()] = store.db.exec('SELECT count(*) FROM "' + name.replace(/"/g, '""') + '"')[0].values[0][0];
  }
  rows.sqlite_master = rows.sqlite_schema = store.db.exec('SELECT count(*) FROM sqlite_master')[0].values[0][0];
  store.cache.tableRows = rows;
  return rows;
}

/** The names of the CTEs that `sql` defines, lower case. */
export function cteNames(sql) {
  const text = strip(sql, true);
  const out = new Set();
  for (const m of text.matchAll(/(?:\bwith\b|,)\s*([A-Za-z_][\w$]*)\s*(?:\([^()]*\))?\s*as\s*(?:not\s+)?(?:materialized\s*)?\(/gi)) {
    out.add(m[1].toLowerCase());
  }
  return out;
}

/** {name or alias: source} for each table or CTE named after FROM, JOIN or a comma, with its alias when it has one. */
export function aliases(sql, rows) {
  const text = strip(sql, true);
  const known = cteNames(sql);
  const map = {};
  // the alias is read ahead, so that the next keyword (JOIN, a comma) starts the next match
  for (const m of text.matchAll(/(?:\bfrom\b|\bjoin\b|,)\s*([A-Za-z_][\w$]*)(?=(?:\s+as\b)?\s+([A-Za-z_][\w$]*)|)/gi)) {
    const table = m[1].toLowerCase();
    if (!(table in rows) && !known.has(table) && table !== 'text_fts') continue;
    map[table] = table;
    const alias = (m[2] || '').toLowerCase();
    if (alias && !NOT_ALIAS.has(alias)) map[alias] = table;
  }
  return map;
}

/**
 * The rows of the largest key of table.column: from the keystat table of the store, else counted once per isolate.
 * NULL counts as a key, because IS matches it. null for a column that the table lacks.
 */
export function maxKey(store, table, column) {
  const cache = store.cache;
  if (!cache.keystat) {
    cache.keystat = {};
    let r = [];
    try {
      r = store.db.exec('SELECT tbl, col, max_key FROM keystat');
    } catch { /* a store built before keystat: every column is counted when a plan needs it */ }
    for (const [t, c, n] of r.length ? r[0].values : []) cache.keystat[String(t).toLowerCase() + '.' + String(c).toLowerCase()] = n;
  }
  const k = table + '.' + column;
  if (k in cache.keystat) return cache.keystat[k];
  const cols = store.db.exec('SELECT name FROM pragma_table_info(\'' + table.replace(/'/g, "''") + '\')');
  const known = (cols.length ? cols[0].values : []).map((x) => String(x[0]).toLowerCase());
  cache.keystat[k] = known.includes(column) ?
    store.db.exec('SELECT coalesce(max(n), 0) FROM (SELECT count(*) AS n FROM "' + table.replace(/"/g, '""') +
      '" GROUP BY "' + column.replace(/"/g, '""') + '")')[0].values[0][0] : null;
  return cache.keystat[k];
}

/**
 * {table, rows, key} for a loop step: the rows it reads each time it runs; null for a line that is not a loop step.
 * sizes: {name of a materialized result or co-routine: the rows it holds}.
 */
export function stepOf(detail, rows, alias, store, sizes = {}) {
  if (detail === 'SCAN CONSTANT ROW') return { table: 'a constant row', rows: 1, key: false };
  const n = /^SCAN (\d+)(?:-ROW VALUES CLAUSE| CONSTANT ROWS)$/.exec(detail);
  if (n) return { table: 'VALUES', rows: Number(n[1]), key: false };
  let name = null;
  let eq = null;
  const s = SCAN_RE.exec(detail);
  if (s) {
    name = s[1];
    const v = /^VIRTUAL TABLE INDEX (\d+):/.exec(s[2] || '');
    if (v && /^pragma_/i.test(name)) return { table: name, rows: PRAGMA_ROWS, key: false };
    // a docid lookup of the full-text index
    if (v && (alias[name.toLowerCase()] || name.toLowerCase()) === 'text_fts' && (Number(v[1]) & 0xffff) === 1) {
      return { table: name, rows: 1, key: true };
    }
  } else {
    const r = SEARCH_RE.exec(detail);
    if (!r) return null;
    name = r[1];
    if (/\bINTEGER PRIMARY KEY\b/.test(r[2])) return { table: name, rows: 1, key: true };
    const c = /\(([^()]*)\)[^()]*$/.exec(r[2]);
    const m = c && /(?:^|[\s(])([A-Za-z_][\w$]*)=\?/.exec(c[1]);
    if (m) eq = m[1].toLowerCase();
    if (eq === 'rowid') return { table: name, rows: 1, key: true };
  }
  const key = name.toLowerCase();
  const source = alias[key] || key;
  if (source in sizes) return { table: name, rows: sizes[source], key: false };
  const table = source in rows ? source : source === 'text_fts' ? 'record' : null;
  if (!table) return { table: name, rows: Infinity, key: false };
  if (!eq) return { table, rows: rows[table], key: false };
  const most = store ? maxKey(store, table, eq) : null;
  return most == null ? { table, rows: rows[table], key: false } : { table, rows: Math.max(1, most), key: true };
}

/**
 * The cost of a plan: {total, worst, twoBig}. total is the rows that all the steps read, summed; worst is the chain
 * whose last step reads the most; twoBig is the first chain with two steps over BIG_ROWS, or null.
 * plan: [[id, parent, _, detail]].
 */
export function planCost(plan, rows, alias, store) {
  const kids = new Map();
  for (const [id, parent, , detail] of plan) {
    if (!kids.has(parent)) kids.set(parent, []);
    kids.get(parent).push({ id, detail: String(detail) });
  }
  const sizes = {};
  let worst = { cost: 0, chain: [] };
  let twoBig = null;
  const below = (id) => (kids.get(id) || []).flatMap((k) => [k, ...below(k.id)]);
  const walk = (parent, outer, correlated) => {
    const chain = outer.slice();
    let read = 0;
    for (const n of kids.get(parent) || []) {
      let s = stepOf(n.detail, rows, alias, store, sizes);
      let into = kids.has(n.id);
      if (/^MULTI-INDEX OR/.test(n.detail)) {
        // one loop over the union of its parts
        const parts = below(n.id).map((k) => stepOf(k.detail, rows, alias, store, sizes)).filter(Boolean);
        s = { table: parts.length ? parts[0].table : 'MULTI-INDEX OR', rows: parts.reduce((a, p) => a + p.rows, 0), key: false };
        into = false;
      }
      if (s) {
        chain.push(s);
        const cost = chain.reduce((a, c) => a * c.rows, 1);
        read += cost;
        if (cost > worst.cost) worst = { cost, chain: chain.slice() };
        if (!twoBig && chain.filter((c) => c.rows > BIG_ROWS).length >= 2) twoBig = chain.slice();
      }
      if (!into) continue;
      // a step that runs once starts a chain; a correlated subquery, or a part of this loop, continues it
      const once = ONCE_RE.test(n.detail) && !correlated;
      const got = walk(n.id, once ? [] : chain, correlated || /^CORRELATED /.test(n.detail));
      read += got;
      const named = /^(?:MATERIALIZE|CO-ROUTINE) (\S+)$/.exec(n.detail);
      if (named) sizes[named[1].toLowerCase()] = Math.max(1, got);
    }
    return read;
  };
  const total = walk(0, [], false);
  return { total, worst: worst.chain, twoBig };
}

/** The weight of one row of `sql`: the work of the expressions it evaluates, as above. */
export function rowWeight(sql) {
  const named = strip(sql, true);
  const bare = strip(sql);
  let w = 1;
  for (const m of named.matchAll(/([A-Za-z_][\w$]*)\s*\(/g)) {
    const name = m[1].toLowerCase();
    if (!CALLS.has(name)) continue; // a keyword or the name of a CTE
    w += DATE_FUNCTIONS.has(name) ? DATE_WEIGHT : 1;
    if (name !== 'printf' && name !== 'format') continue;
    // the guard has checked that a literal format string follows; `named` blanks it at the same offsets
    let at = m.index + m[0].length;
    while (/\s/.test(sql[at] || '')) at++;
    if (sql[at] !== "'") continue;
    let j = at + 1;
    while (j < sql.length && !(sql[j] === "'" && sql[j + 1] !== "'")) j += sql[j] === "'" ? 2 : 1;
    let width = 0;
    for (const c of sql.slice(at + 1, j).matchAll(/%[-+ #0,!]*(\d*)(?:\.(\d*))?/g)) {
      w += 1;
      width += Number(c[1] || 0) + Number(c[2] || 0);
    }
    w += Math.ceil(width / WIDTH_UNIT);
  }
  w += (bare.match(/\b(?:like|glob|match|regexp)\b(?!\s*\()/gi) || []).length;
  w += (bare.match(/->>?/g) || []).length;
  const concat = (bare.match(/\|\|/g) || []).length;
  return w + concat * concat;
}

function size(s) {
  if (!Number.isFinite(s.rows)) return s.table + ' (a source the Worker cannot size)';
  return s.table + (s.key ? ' (up to ' + s.rows + ' rows a key)' : ' (' + s.rows + ' rows)');
}

function rowsText(n) {
  return Number.isFinite(n) ? String(Math.round(n)).replace(/\B(?=(\d{3})+$)/g, ',') : 'an unknown number of';
}

/** Throw GuardError when `sql` is too costly to run. EXPLAIN statements pass. */
export function checkPlan(store, sql) {
  const bare = strip(sql);
  if (/^\s*explain\b/i.test(bare)) return;
  const res = store.db.exec('EXPLAIN QUERY PLAN ' + sql);
  const plan = res.length ? res[0].values : [];
  if (plan.some((r) => /^(?:RECURSIVE STEP|SETUP)$/.test(String(r[3])))) {
    throw new GuardError('a recursive CTE runs as long as the statement says; it is not accepted');
  }
  const rows = tableRows(store);
  const { total, worst, twoBig } = planCost(plan, rows, aliases(sql, rows), store);
  const hint = '. Join on an indexed column with =, filter one side first, or split the statement';
  if (twoBig) throw new GuardError('the plan reads ' + twoBig.map(size).join(', then for each row ') + hint);
  const weight = rowWeight(sql);
  if (total * weight > MAX_WORK) {
    throw new GuardError('the plan reads ' + rowsText(total) + ' rows in all, at a weight of ' + weight +
      ' a row (its functions and operators): ' + rowsText(total * weight) + ', over the budget of ' + rowsText(MAX_WORK) +
      '; the costliest part reads ' + worst.map(size).join(', then for each row ') + hint + ', or use fewer functions');
  }
}
