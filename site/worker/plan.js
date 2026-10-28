// Statement budget (issue #5). sql.js has no progress handler, so the Worker cannot stop a statement after a number of
// steps. Before a statement runs, the Worker reads its EXPLAIN QUERY PLAN and accepts it only when the plan is cheap.
//
// Each loop step of the plan reads some rows each time it runs:
//   - a scan reads the whole table, whatever follows the name ("SCAN x", "SCAN x USING COVERING INDEX i LEFT-JOIN",
//     "SCAN x EXISTS", ...); so does a SEARCH that has only a range constraint ("SEARCH x USING INDEX i (a>?)");
//   - a SEARCH with an = constraint reads the rows of one key: the table's rows divided by the number of distinct
//     values of the first = column, counted once per isolate (1 for a unique column);
//   - a full-text lookup reads few rows and is not counted; a full scan of the full-text index is a scan.
//
// The steps of one loop chain run nested: each runs once for each row of the steps before it. A chain is the loop
// steps under one plan node, plus those of a CORRELATED subquery under it, which runs once for each outer row. A
// subquery that is not correlated, a MATERIALIZE step and a CO-ROUTINE step run once, so each starts a chain of its
// own; so does each part of a compound SELECT. In each chain, the plan is refused when:
//   - two steps read more than BIG_ROWS rows each, or
//   - the product of the rows that its steps read is over MAX_PRODUCT.
// A name that the Worker cannot size (a materialized result, a view) counts as large. A recursive CTE is refused,
// because its cost is a number that the statement writes. So are randomblob() and zeroblob(), and a printf() or
// format() width over MAX_WIDTH, which build a large value from a short statement.

import { GuardError, strip } from './guard.js';

export const BIG_ROWS = 1000;
export const MAX_PRODUCT = 5000000;
export const MAX_WIDTH = 1000;
const SCAN_RE = /^SCAN (\S+)(?: (.*))?$/;
const SEARCH_RE = /^SEARCH (\S+) USING .*\(([^()]*)\)/;
const ONCE_RE = /^(?:LIST SUBQUERY|SCALAR SUBQUERY|MATERIALIZE|CO-ROUTINE|COMPOUND QUERY|LEFT-MOST SUBQUERY|UNION ALL|UNION USING|INTERSECT USING|EXCEPT USING|MERGE \()/;
const NOT_ALIAS = new Set(['where', 'on', 'using', 'join', 'left', 'right', 'full', 'inner', 'outer', 'cross',
  'natural', 'group', 'order', 'limit', 'having', 'window', 'union', 'except', 'intersect', 'indexed', 'not', 'as']);

/** {table name: row count} of the store, counted once per isolate. */
export function tableRows(store) {
  if (store.cache.tableRows) return store.cache.tableRows;
  const rows = {};
  const r = store.db.exec("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'text_fts%'");
  for (const [name] of r.length ? r[0].values : []) {
    rows[name.toLowerCase()] = store.db.exec('SELECT count(*) FROM "' + name.replace(/"/g, '""') + '"')[0].values[0][0];
  }
  store.cache.tableRows = rows;
  return rows;
}

/** {name or alias: table} for each table named after FROM, JOIN or a comma, with its alias when it has one. */
export function aliases(sql, rows) {
  const text = strip(sql, true);
  const map = {};
  for (const m of text.matchAll(/(?:\bfrom\b|\bjoin\b|,)\s*([A-Za-z_][\w$]*)(?:\s+as\b)?(?:\s+([A-Za-z_][\w$]*))?/gi)) {
    const table = m[1].toLowerCase();
    if (!(table in rows)) continue;
    map[table] = table;
    const alias = (m[2] || '').toLowerCase();
    if (alias && !NOT_ALIAS.has(alias)) map[alias] = table;
  }
  return map;
}

/** The number of distinct values of a column, counted once per isolate; null for a column the table lacks. */
export function distinct(store, table, column) {
  const cache = (store.cache.distinct ||= {});
  const k = table + '.' + column;
  if (k in cache) return cache[k];
  const cols = store.db.exec('SELECT name FROM pragma_table_info(\'' + table.replace(/'/g, "''") + '\')');
  const known = (cols.length ? cols[0].values : []).map((r) => String(r[0]).toLowerCase());
  cache[k] = known.includes(column) ?
    store.db.exec('SELECT count(DISTINCT "' + column + '") FROM "' + table + '"')[0].values[0][0] : null;
  return cache[k];
}

/** {table, rows, key} for a loop step: the rows it reads each time it runs; null for a step that reads none. */
export function stepOf(detail, rows, alias, store) {
  let name = null;
  let eq = null;
  const s = SCAN_RE.exec(detail);
  if (s) {
    if (s[1] === 'CONSTANT') return null;
    const rest = s[2] || '';
    if (/^VIRTUAL TABLE INDEX /.test(rest) && !/^VIRTUAL TABLE INDEX 0:/.test(rest)) return null; // MATCH or docid
    name = s[1];
  } else {
    const r = SEARCH_RE.exec(detail);
    if (!r) return null;
    const m = /([A-Za-z_][\w$]*)=\?/.exec(r[2]);
    if (m) eq = m[1].toLowerCase();
    else if (!/[<>]/.test(r[2])) return null;
    name = r[1];
  }
  const key = name.toLowerCase();
  const table = alias[key] || (key in rows ? key : key === 'text_fts' ? 'record' : null);
  if (!table) return { table: name, rows: Infinity, key: false };
  if (!eq) return { table, rows: rows[table], key: false };
  const n = store ? distinct(store, table, eq) : null;
  return { table, rows: n ? Math.ceil(rows[table] / n) : rows[table], key: true };
}

/** The scans of the chain that makes the plan too costly, or null. plan: [[id, parent, _, detail]]. */
export function costlyChain(plan, rows, alias, store) {
  const kids = new Map();
  for (const [id, parent, , detail] of plan) {
    if (!kids.has(parent)) kids.set(parent, []);
    kids.get(parent).push({ id, detail: String(detail) });
  }
  const verdict = (chain) => {
    if (chain.length < 2) return false;
    const big = chain.filter((c) => c.rows > BIG_ROWS).length;
    const product = chain.reduce((p, c) => p * c.rows, 1);
    return big >= 2 || product > MAX_PRODUCT;
  };
  const walk = (parent, outer) => {
    const chain = outer.slice();
    for (const n of kids.get(parent) || []) {
      const s = stepOf(n.detail, rows, alias, store);
      if (s) {
        chain.push(s);
        if (verdict(chain)) return chain;
      }
      if (!kids.has(n.id)) continue;
      // a step that runs once starts a chain; a correlated subquery or a part of this loop continues the chain
      const hit = walk(n.id, ONCE_RE.test(n.detail) ? [] : chain);
      if (hit) return hit;
    }
    return null;
  };
  return walk(0, []);
}

function size(s) {
  if (!Number.isFinite(s.rows)) return s.table + ' (a source the Worker cannot size)';
  return s.table + (s.key ? ' (about ' + s.rows + ' rows a key)' : ' (' + s.rows + ' rows)');
}

/** Throw GuardError when `sql` is too costly to run. EXPLAIN statements pass. */
export function checkPlan(store, sql) {
  const bare = strip(sql);
  if (/^\s*explain\b/i.test(bare)) return;
  if (/\brecursive\b/i.test(bare)) throw new GuardError('a recursive CTE runs as long as the statement says; it is not accepted');
  const gen = /\b(randomblob|zeroblob)\s*\(/i.exec(bare);
  if (gen) throw new GuardError(gen[1].toLowerCase() + '() builds a value of any size; it is not accepted');
  checkWidths(sql, bare);
  const res = store.db.exec('EXPLAIN QUERY PLAN ' + sql);
  const plan = res.length ? res[0].values : [];
  if (plan.some((r) => /^(?:RECURSIVE STEP|SETUP)$/.test(String(r[3])))) {
    throw new GuardError('a recursive CTE runs as long as the statement says; it is not accepted');
  }
  const rows = tableRows(store);
  const chain = costlyChain(plan, rows, aliases(sql, rows), store);
  if (chain) {
    throw new GuardError('the plan reads ' + chain.map(size).join(', then for each row ') +
      '. Join on an indexed column with =, or filter one side first');
  }
}

/** printf() and format() with a width or a precision over MAX_WIDTH, or one that the arguments set (*). */
function checkWidths(sql, bare) {
  // `bare` blanks literals with spaces at the same offsets, so the format string is read from `sql`
  for (const m of bare.matchAll(/\b(printf|format)\s*\(/gi)) {
    let at = m.index + m[0].length;
    while (/\s/.test(sql[at] || '')) at++;
    if (sql[at] !== "'") throw new GuardError(m[1].toLowerCase() + '() needs a literal format string');
    let j = at + 1;
    while (j < sql.length && !(sql[j] === "'" && sql[j + 1] !== "'")) j += sql[j] === "'" ? 2 : 1;
    for (const w of sql.slice(at + 1, j).matchAll(/%[-+ #0,!]*(\*|\d+)?(?:\.(\*|\d+))?/g)) {
      for (const v of [w[1], w[2]]) {
        if (v === '*' || (v && Number(v) > MAX_WIDTH)) {
          throw new GuardError(m[1].toLowerCase() + '() width or precision over ' + MAX_WIDTH + '; it is not accepted');
        }
      }
    }
  }
}
