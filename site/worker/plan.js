// Statement budget (issue #5). sql.js has no progress handler, so the Worker cannot stop a statement after a
// number of steps. Before a statement runs, the Worker reads its EXPLAIN QUERY PLAN and refuses it when the plan
// runs a full scan of a table over BIG_ROWS rows once for each row of another full scan of a table over BIG_ROWS
// rows: a nested loop of two large scans, for example a cross join, or a join on <>.
//
// A full scan is a plan line "SCAN x", or "SCAN x USING [COVERING] INDEX i" (every row, in index order). A "SEARCH"
// line reads only the rows that an index finds, so it is not a full scan. Two full scans are in one nested loop when
// they have the same parent in the plan, or when the second is inside a CORRELATED subquery that has the first as an
// earlier sibling: the inner one runs once for each row of the outer one. A name in the plan is a table, an alias of
// a table in a FROM or JOIN clause, or something the Worker cannot size (a view, a materialized subquery), which
// counts as large.

import { GuardError, strip } from './guard.js';

export const BIG_ROWS = 1000;
const SCAN_RE = /^SCAN (\S+)(?: USING (?:COVERING )?INDEX \S+)?$/;
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

/** The two full scans of a nested loop that makes the plan too costly, or null. plan: [[id, parent, _, detail]]. */
export function nestedScans(plan, rows, alias) {
  const node = new Map();
  plan.forEach(([id, parent, , detail], k) => node.set(id, { id, parent, detail: String(detail), k }));
  const big = [];
  for (const n of node.values()) {
    const m = SCAN_RE.exec(n.detail);
    if (!m) continue;
    const name = m[1].toLowerCase();
    const table = alias[name] || (name in rows ? name : null);
    const count = table ? rows[table] : Infinity;
    if (count > BIG_ROWS) big.push({ ...n, table: table || m[1], rows: count });
  }
  for (const inner of big) {
    for (let cur = inner; cur; ) {
      const outer = big.find((o) => o !== inner && o.parent === cur.parent && o.k < cur.k);
      if (outer) return [outer, inner];
      const up = node.get(cur.parent);
      cur = up && /^CORRELATED /.test(up.detail) ? up : null;
    }
  }
  return null;
}

function size(s) {
  return Number.isFinite(s.rows) ? s.table + ' (' + s.rows + ' rows)' : s.table + ' (a source the Worker cannot size)';
}

/** Throw GuardError when the plan of `sql` has a nested loop of two large full scans. EXPLAIN statements pass. */
export function checkPlan(store, sql) {
  if (/^\s*explain\b/i.test(strip(sql))) return;
  const res = store.db.exec('EXPLAIN QUERY PLAN ' + sql);
  const rows = tableRows(store);
  const hit = nestedScans(res.length ? res[0].values : [], rows, aliases(sql, rows));
  if (hit) {
    throw new GuardError('the plan scans ' + size(hit[1]) + ' once for each row of ' + size(hit[0]) +
      '. Join the two on an indexed column with =, or filter one of them first');
  }
}
