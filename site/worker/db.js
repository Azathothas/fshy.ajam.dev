// The Worker's SQLite: sql.js over the read-only Worker DB that the build ships as static assets.
// One load per isolate, shared by concurrent cold requests through a module-level promise.
// The chunks named in data/manifest.json are streamed into one preallocated buffer, checked
// against the manifest's length and SHA-256, then opened with PRAGMA query_only=ON and a hard heap limit.

import initSqlJs from 'sql.js/dist/sql-wasm-browser.js';
import { buildNameIndex, indexFromNormalized } from './rank.js';

// The browser build reads self.location.href when it runs inside a worker global scope.
if (!globalThis.location) globalThis.location = { href: 'https://fshy.invalid/' };

const ORIGIN = 'https://assets.invalid/';
// The memory that SQLite may allocate (PRAGMA hard_heap_limit). A statement that needs more fails with "out of memory",
// which the SQL route returns as a refusal (400); the handle stays usable. It bounds the size of any value that a
// statement builds, whatever the functions, and keeps the isolate under its 128 MB.
export const HEAP_LIMIT_MIB = 32;
// The characters that one SQL result may carry, summed over its values. A larger result is refused (400).
export const MAX_RESULT_CHARS = 2000000;
let sqlPromise = null;
let storePromise = null;

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function sqlJs(wasmModule) {
  if (!sqlPromise) {
    sqlPromise = initSqlJs({
      instantiateWasm(imports, ok) {
        WebAssembly.instantiate(wasmModule, imports).then((inst) => ok(inst, wasmModule));
        return {};
      },
    }).catch((e) => {
      sqlPromise = null;
      throw e;
    });
  }
  return sqlPromise;
}

/** Fetch a static file from the assets binding; throws HttpError on a non-200. */
export async function asset(env, path, kind = 'text') {
  const res = await env.ASSETS.fetch(new Request(ORIGIN + path.replace(/^\/+/, '')));
  if (res.status !== 200) {
    if (res.body) await res.body.cancel();
    throw new HttpError(res.status === 404 ? 404 : 500, 'asset ' + path + ': HTTP ' + res.status);
  }
  if (kind === 'json') return res.json();
  if (kind === 'response') return res;
  return res.text();
}

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function load(env, wasmModule) {
  const t0 = performance.now();
  const manifest = await asset(env, 'data/manifest.json', 'json');
  const w = manifest && manifest.worker_db;
  if (!w || !Array.isArray(w.chunks) || !(w.bytes > 0)) throw new Error('manifest has no worker_db');
  const SQLp = sqlJs(wasmModule);
  const buf = new Uint8Array(w.bytes);
  let off = 0;
  for (const p of w.chunks) {
    const res = await asset(env, p, 'response');
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (off + value.byteLength > buf.length) throw new Error('worker DB chunks exceed manifest bytes');
      buf.set(value, off);
      off += value.byteLength;
    }
  }
  if (off !== buf.length) throw new Error('worker DB is ' + off + ' bytes, manifest says ' + buf.length);
  const t1 = performance.now();
  if (w.sha256) {
    const got = hex(await crypto.subtle.digest('SHA-256', buf));
    if (got !== w.sha256) throw new Error('worker DB sha256 mismatch');
  }
  const t2 = performance.now();
  const SQL = await SQLp;
  const t3 = performance.now();
  const db = new SQL.Database(buf);
  db.exec('PRAGMA query_only=ON');
  // temporary tables and sorts stay in SQLite's memory, so the heap limit bounds them too (a temporary file would
  // grow in the isolate's memory, outside the limit)
  db.exec('PRAGMA temp_store=MEMORY');
  db.exec('PRAGMA hard_heap_limit=' + HEAP_LIMIT_MIB * 1024 * 1024);
  const t4 = performance.now();
  const r = (x) => Math.round(x * 10) / 10;
  return {
    db,
    manifest,
    commit: manifest.commit || '',
    asOf: manifest.as_of || null,
    cache: {},
    stats: { fetch_ms: r(t1 - t0), hash_ms: r(t2 - t1), wasm_wait_ms: r(t3 - t2), open_ms: r(t4 - t3), total_ms: r(t4 - t0), bytes: off },
  };
}

/**
 * The store for this isolate: {db, manifest, commit, stats, cache}. `cold` is true for the
 * request(s) that waited on the load.
 */
export async function getStore(env, wasmModule) {
  let cold = false;
  if (!storePromise) {
    cold = true;
    storePromise = load(env, wasmModule).catch((e) => {
      storePromise = null;
      throw e;
    });
  }
  const store = await storePromise;
  return { store, cold };
}

/** Throw away the handle (after an unexpected change) so the next request reopens a clean copy. */
export function discard(store) {
  if (storePromise) {
    storePromise = null;
    try { store.db.close(); } catch { /* already closed */ }
  }
}

/** Throw away the handle and the sql.js module (after the engine itself failed) so the next request starts both again. */
export function reset(store) {
  discard(store);
  sqlPromise = null;
}

/** True for an error of the WebAssembly engine itself, after which sql.js cannot be used again. */
export function engineFailed(e) {
  return (typeof WebAssembly !== 'undefined' && e instanceof WebAssembly.RuntimeError) ||
    /^(?:Aborted|RuntimeError)\b|memory access out of bounds|unreachable executed/.test(String((e && e.message) || e));
}

/** Rows as objects. Parameters are bound, never interpolated. */
export function all(db, sql, params = []) {
  const st = db.prepare(sql);
  try {
    if (params.length) st.bind(params);
    const out = [];
    while (st.step()) out.push(st.getAsObject());
    return out;
  } finally {
    st.free();
  }
}

/** First row as an object, or null. */
export function one(db, sql, params = []) {
  const st = db.prepare(sql);
  try {
    if (params.length) st.bind(params);
    return st.step() ? st.getAsObject() : null;
  } finally {
    st.free();
  }
}

/**
 * Run caller SQL with a row cap: {columns, rows (arrays), truncated}. A result over MAX_RESULT_CHARS is refused with
 * HttpError 400. Checks total_changes() afterwards and discards the handle if anything changed.
 */
export function capped(store, sql, cap) {
  const db = store.db;
  let st;
  try {
    st = db.prepare(sql);
    const columns = st.getColumnNames();
    const rows = [];
    let truncated = false;
    let chars = 0;
    while (st.step()) {
      if (rows.length >= cap) { truncated = true; break; }
      const row = st.get();
      for (const v of row) chars += v == null ? 0 : typeof v === 'string' || v instanceof Uint8Array ? v.length : 8;
      if (chars > MAX_RESULT_CHARS) {
        throw new HttpError(400, 'refused: the result is over ' + MAX_RESULT_CHARS.toLocaleString('en-US') +
          ' characters; select fewer rows or shorter values');
      }
      rows.push(row);
    }
    return { columns, rows, truncated };
  } finally {
    if (st) st.free();
    let changed = 0;
    try { changed = db.exec('SELECT total_changes()')[0].values[0][0]; } catch { changed = 1; }
    if (changed) discard(store);
  }
}

const ENTITY_COLUMNS = ['eid', 'name', 'domain', 'topics', 'n_records', 'best_vorder'];

/**
 * Name index built once per isolate from the alias table, in the order eid, alias, kind. loadNames() fills it from the
 * file that the build writes; this is the path when that file is absent.
 */
export function nameIndex(store) {
  if (!store.cache.names) {
    // one row per entity: far fewer sql.js round trips than one per alias
    const res = store.db.exec('SELECT eid, group_concat(alias, char(31)) FROM (SELECT eid, alias FROM alias ' +
      'ORDER BY eid, alias, kind) GROUP BY eid ORDER BY eid');
    const rows = [];
    for (const [eid, joined] of res.length ? res[0].values : []) {
      for (const alias of String(joined).split(String.fromCharCode(31))) rows.push({ eid, alias });
    }
    store.cache.names = buildNameIndex(rows);
    store.cache.entities = new Map(all(store.db, `SELECT ${ENTITY_COLUMNS.join(', ')} FROM entity`).map((e) => [e.eid, e]));
  }
  return store.cache.names;
}

/**
 * The name index from the file that the manifest names (name_index): the aliases normalised by the build, their
 * entities, and the entity rows. Parsing it costs a few milliseconds; normalising 14,000 aliases on the first search of
 * an isolate cost about 80 ms. Without the file, or when it fails, the index is built from the store.
 */
export async function loadNames(store, env) {
  if (store.cache.names) return store.cache.names;
  const p = store.manifest && store.manifest.name_index;
  if (p) {
    if (!store.cache.namesPromise) {
      store.cache.namesPromise = asset(env, p, 'json').then((j) => {
        if (store.cache.names) return;
        store.cache.entities = new Map(j.entities.map((r) => [r[0], Object.fromEntries(ENTITY_COLUMNS.map((c, i) => [c, r[i]]))]));
        store.cache.names = indexFromNormalized(j.aliases, j.eids);
      }).catch((e) => {
        console.error('fshy name index file failed, built from the store:', e && e.stack ? e.stack : String(e));
      });
    }
    await store.cache.namesPromise;
  }
  return nameIndex(store);
}
