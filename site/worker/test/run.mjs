// Node tests for the fshy Worker, without wrangler: the guard, the text and ranking rules, and the
// whole Worker fetch handler (API, permalinks, MCP) over the store's Worker copy.
//
//   node site/worker/test/run.mjs
//
// Inputs: FSHY_DB (default .tmp/fshy/worker.db) is served as the Worker DB through a fake ASSETS
// binding, split into two chunks with a manifest made here. Other assets come from FSHY_DIST
// (default site/dist) when present; record and entity-file tests are skipped without it.

import { registerHooks } from 'node:module';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';

const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = resolve(HERE, '..', '..');
const REPO = resolve(SITE, '..');
const DB = process.env.FSHY_DB || join(REPO, '.tmp', 'fshy', 'worker.db');
const DIST = process.env.FSHY_DIST || join(SITE, 'dist');
const HAVE_DIST = existsSync(join(DIST, 'api', 'v1', 'entity'));

// workerd imports *.wasm as a compiled WebAssembly.Module (wrangler rule CompiledWasm); do the same
registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.wasm')) return { format: 'module', source: 'export default globalThis.__fshyWasm;', shortCircuit: true };
    return nextLoad(url, context);
  },
});
globalThis.__fshyWasm = await WebAssembly.compile(readFileSync(join(SITE, 'node_modules', 'sql.js', 'dist', 'sql-wasm-browser.wasm')));

if (!existsSync(DB)) {
  console.error('no worker DB at ' + DB + '; build it with python publish/build.py --site site/dist, or set FSHY_DB');
  process.exit(2);
}
const dbBytes = readFileSync(DB);
const half = Math.ceil(dbBytes.length / 2);
const CHUNKS = { 'data/w/test.000': dbBytes.subarray(0, half), 'data/w/test.001': dbBytes.subarray(half) };
// the built manifest, when there is one, gives the files that the Worker reads besides its DB: the name index, the
// parts of the public store, the topic order
const BUILT = existsSync(join(DIST, 'data', 'manifest.json')) ? JSON.parse(readFileSync(join(DIST, 'data', 'manifest.json'), 'utf8')) : {};
const MANIFEST = {
  schema_version: '1', commit: 'testcommit0123456789', as_of: '2026-10-27',
  worker_db: { chunks: Object.keys(CHUNKS), bytes: dbBytes.length, sha256: createHash('sha256').update(dbBytes).digest('hex') },
  ...(BUILT.name_index ? { name_index: BUILT.name_index } : {}),
  ...(BUILT.public_db ? { public_db: BUILT.public_db } : {}),
  ...(BUILT.topics ? { topics: BUILT.topics } : {}),
};

function assetResponse(path) {
  if (path === 'data/manifest.json') return new Response(JSON.stringify(MANIFEST), { headers: { 'content-type': 'application/json' } });
  if (CHUNKS[path]) return new Response(CHUNKS[path]);
  const f = join(DIST, ...path.split('/'));
  if (existsSync(f) && statSync(f).isFile()) return new Response(readFileSync(f));
  if (path === 'api/v1/needs.json') return new Response(readFileSync(join(REPO, 'publish', 'rules', 'needs.json')));
  return new Response('<!doctype html><title>404</title>', { status: 404, headers: { 'content-type': 'text/html' } });
}

const assetLog = [];
const ASSETS = {
  async fetch(req) {
    const path = decodeURIComponent(new URL(req.url).pathname.replace(/^\/+/, ''));
    assetLog.push(path);
    return assetResponse(path);
  },
};
const denyAll = { limit: async () => ({ success: false }) };
const allowAll = { limit: async () => ({ success: true }) };
const throws = { limit: async () => { throw new Error('binding unavailable'); } };
const env = { ASSETS, RL_API: allowAll, RL_SQL: allowAll };

const { guard, strip, GuardError } = await import('../guard.js');
const text = await import('../text.js');
const rank = await import('../rank.js');
const worker = (await import('../index.js')).default;

const ORIGIN = 'http://127.0.0.1:8790';
async function call(path, init = {}, e = env) {
  const t0 = performance.now();
  const res = await worker.fetch(new Request(ORIGIN + path, init), e);
  const ms = performance.now() - t0;
  const body = res.status === 204 || res.status === 202 || res.status === 301 ? '' : await res.text();
  let json = null;
  try { json = JSON.parse(body); } catch { /* TSV or empty */ }
  return { res, body, json, ms };
}
let rpcId = 0;
async function rpc(method, params, headers = {}) {
  const msg = { jsonrpc: '2.0', id: ++rpcId, method, ...(params ? { params } : {}) };
  return call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream', ...headers }, body: JSON.stringify(msg) });
}
const timings = {};

// ------------------------------------------------------------------ guard

test('guard accepts read-only statements and appends LIMIT', () => {
  assert.equal(guard('SELECT 1', 10).sql, 'SELECT 1\nLIMIT 10');
  assert.equal(guard('select rid from record;', 5).sql, 'select rid from record\nLIMIT 5');
  assert.equal(guard('SELECT 1 LIMIT 3', 10).sql, 'SELECT 1 LIMIT 3');
  assert.equal(guard('WITH t AS (SELECT 1 AS x) SELECT x FROM t', 7).appendedLimit, true);
  assert.ok(guard('VALUES (1), (2)', 2));
  assert.ok(guard('EXPLAIN QUERY PLAN SELECT * FROM record', 2));
  assert.ok(guard("SELECT 'delete from record; drop table x' AS s", 2), 'keywords inside literals are fine');
  assert.ok(guard('SELECT 1 -- update; drop\n', 2), 'keywords inside comments are fine');
  assert.ok(guard('SELECT "update" FROM (SELECT 1 AS "update")', 2), 'quoted identifiers are stripped');
  assert.ok(guard('SELECT * FROM pragma_table_info(\'record\')', 2), 'pragma_ functions are not the PRAGMA keyword');
  assert.equal(guard('SELECT 1 -- note', 4).sql, 'SELECT 1 -- note\nLIMIT 4', 'LIMIT lands after a line comment');
  assert.equal(guard("SELECT ';' -- a;b", 4).sql, "SELECT ';' -- a;b\nLIMIT 4");
  assert.equal(strip("a 'b' \"c\" [d] -- e\n/* f */ g").length, "a 'b' \"c\" [d] -- e\n/* f */ g".length);
});

test('guard refuses writes, sessions and stacked statements', () => {
  const refuse = [
    'DELETE FROM record', 'delete from record', 'UPDATE record SET verdict = 1', 'INSERT INTO meta VALUES (1, 2)',
    'DROP TABLE record', 'PRAGMA query_only=OFF', 'ATTACH DATABASE \'x\' AS y', 'VACUUM', 'BEGIN', 'COMMIT',
    'SELECT 1; DELETE FROM record', 'SELECT 1; SELECT 2', 'WITH x AS (SELECT 1) DELETE FROM record',
    'SELECT replace(rid, \'a\', \'b\') FROM record', 'CREATE TEMP TABLE t (x)', 'SELECT * FROM temp.sqlite_master',
    'REINDEX', 'ANALYZE', 'SAVEPOINT a', 'RELEASE a', 'ROLLBACK', 'DETACH y', 'ALTER TABLE record ADD x',
    'SELECT 1 /* unterminated', "SELECT 'unterminated", '', '   ', 'record', '(SELECT 1)',
    'INSERT INTO text_fts(text_fts) VALUES (\'optimize\')',
  ];
  for (const q of refuse) assert.throws(() => guard(q, 10), GuardError, q);
});

// ------------------------------------------------------------------ text and ranking

test('ftsText is the twin of build.py fts_text', () => {
  // expected values printed by build.py's fts_text
  const cases = [
    ['\u767E\u5EA6\u7F51\u76D8 free 2TB', '\u767E\u5EA6\u7F51\u76D8 \u767E\u5EA6 \u5EA6\u7F51 \u7F51\u76D8 free 2TB'],
    ['115\u7F51\u76D8vip', '115\u7F51\u76D8 \u7F51\u76D8vip'],
    ['\uD55C\uAD6D\uC5B4 \uD14D\uC2A4\uD2B8', '\uD55C\uAD6D\uC5B4 \uD55C\uAD6D \uAD6D\uC5B4 \uD14D\uC2A4\uD2B8 \uD14D\uC2A4 \uC2A4\uD2B8'],
    ['\u3072\u3089\u304C\u306A\u30AB\u30BF\u30AB\u30CA', '\u3072\u3089\u304C\u306A\u30AB\u30BF\u30AB\u30CA \u3072\u3089 \u3089\u304C \u304C\u306A \u306A\u30AB \u30AB\u30BF \u30BF\u30AB \u30AB\u30CA'],
    ['a\u4E2Db', 'a\u4E2D \u4E2Db'],
    ['plain ascii', 'plain ascii'],
    ['\u963F\u91CC\u4E91\u76D8/\u5938\u514B', '\u963F\u91CC\u4E91\u76D8 \u963F\u91CC \u91CC\u4E91 \u4E91\u76D8/\u5938\u514B \u5938\u514B'],
  ];
  for (const [i, o] of cases) assert.equal(text.ftsText(i), o);
});

test('normalize and the MATCH builder', () => {
  assert.equal(text.normalize('  H\u00E9tzner   STRASSE \u00DF '), 'hetzner strasse ss');
  assert.equal(text.normalize('\uFF28\uFF45\uFF54\uFF5A\uFF4E\uFF45\uFF52'), 'hetzner');
  assert.equal(text.ftsMatch('Hetzner storage box'), 'hetzner* storage* box*');
  assert.equal(text.ftsMatch('s3 no-card'), 's3 "no-card"');
  assert.equal(text.ftsMatch('\u767E\u5EA6\u7F51\u76D8'), '\u767E\u5EA6 \u5EA6\u7F51 \u7F51\u76D8');
  assert.equal(text.ftsMatch('offer:gpu OR "x"'), '"offer:gpu" or x');
  assert.equal(text.ftsMatch('*** ---'), '');
});

test('bm25 from a matchinfo blob, and edit distance', () => {
  // p=1 phrase, c=2 columns, n=10 rows; a = [10, 20]; l = [5, 40]; x = col0 (2 hits, 3 all, 2 docs), col1 (0, 4, 3)
  const u = new Uint32Array([1, 2, 10, 10, 20, 5, 40, 2, 3, 2, 0, 4, 3]);
  const r = rank.bm25(new Uint8Array(u.buffer), [4, 2]);
  const idf = Math.log(1 + (10 - 2 + 0.5) / (2 + 0.5));
  const want = (4 * idf * 2 * 2.2) / (2 + 1.2 * (1 - 0.75 + (0.75 * 5) / 10));
  assert.ok(Math.abs(r.score - want) < 1e-9);
  assert.deepEqual(r.matched, ['name']);
  assert.equal(rank.editDistance('hetzer', 'hetzner', 1), 1);
  assert.equal(rank.editDistance('hetzner', 'hertz', 1), 2);
  assert.equal(rank.fuzzBudget('abc'), 0);
  assert.equal(rank.fuzzBudget('abcd'), 1);
  assert.equal(rank.fuzzBudget('abcdefgh'), 2);
});

test('name scoring tiers', () => {
  const idx = rank.buildNameIndex([
    { eid: 'hetzner', alias: 'Hetzner', kind: 'name' },
    { eid: 'hetzner', alias: 'Hetzner Storage Box', kind: 'provider' },
    { eid: 'other', alias: 'Not Hetzner', kind: 'name' },
    { eid: 'box', alias: 'Box', kind: 'name' },
  ]);
  const by = (q) => Object.fromEntries(rank.scoreNames(idx, q).map((h) => [h.eid, h.score]));
  assert.deepEqual(by('hetzner'), { hetzner: 100, other: 40 });
  assert.deepEqual(by('hetzner sto'), { hetzner: 60 });
  assert.deepEqual(by('hetzer'), { hetzner: 30, other: 30 });
  assert.deepEqual(by('storage hetzner'), { hetzner: 30 });
});

// ------------------------------------------------------------------ Worker over the real store

test('cold and warm search; headers', async () => {
  const cold = await call('/api/v1/search?q=hetzner');
  timings.cold_search_ms = cold.ms;
  assert.equal(cold.res.status, 200, cold.body);
  assert.equal(cold.res.headers.get('x-fshy-commit'), MANIFEST.commit);
  assert.equal(cold.res.headers.get('cache-control'), 'public, max-age=300');
  assert.equal(cold.res.headers.get('access-control-allow-origin'), '*');
  assert.match(cold.res.headers.get('server-timing'), /db;desc="cold load";dur=/);
  timings.server_timing_cold = cold.res.headers.get('server-timing');
  assert.ok(assetLog.includes('data/w/test.000') && assetLog.includes('data/w/test.001'), 'both chunks fetched');
  const j = cold.json;
  assert.deepEqual(j.columns.slice(0, 3), ['rid', 'provider', 'verdict']);
  assert.ok(j.rows.length > 0 && j.rows.length <= 20);
  assert.match(j.rows[0][0], /hetzner/);
  assert.match(j.rows[0].at(-1), /^name\(/);
  const warm = await call('/api/v1/search?q=hetzner');
  timings.warm_search_ms = warm.ms;
  assert.doesNotMatch(warm.res.headers.get('server-timing'), /cold/);
  const n = assetLog.filter((p) => p === 'data/manifest.json').length;
  assert.equal(n, 1, 'the DB is loaded once per isolate');
});

test('search: text hits, filters, TSV, CJK, limits', async () => {
  const r = await call('/api/v1/search?q=webdav%20unlimited&topic=storage&grp=usable&limit=5');
  assert.equal(r.res.status, 200, r.body);
  assert.ok(r.json.rows.length <= 5);
  for (const row of r.json.rows) assert.match(row[0], /^storage\//);
  const t = await call('/api/v1/search?q=hetzner&format=tsv&limit=3');
  assert.match(t.res.headers.get('content-type'), /tab-separated/);
  const lines = t.body.trim().split('\n');
  assert.equal(lines[0].split('\t')[0], 'rid');
  assert.match(lines.find((l) => l.startsWith('# ')), /^# 3 of \d+ rows; offset=3 for more/);
  const t0 = performance.now();
  const c = await call('/api/v1/search?q=' + encodeURIComponent('\u767E\u5EA6'));
  timings.cjk_search_ms = performance.now() - t0;
  assert.equal(c.res.status, 200, c.body);
  assert.ok(c.json.rows.length > 0, 'CJK query finds records');
  timings.cjk_top = c.json.rows.slice(0, 3).map((x) => x[0]);
  const fuzzy = await call('/api/v1/search?q=hetzer');
  assert.ok(fuzzy.json.rows.some((x) => /hetzner/.test(x[0])), 'one typo still finds the name');
  assert.equal((await call('/api/v1/search')).res.status, 400);
  assert.equal((await call('/api/v1/search?q=x&limit=51')).res.status, 400);
  assert.equal((await call('/api/v1/search?q=x&format=xml')).res.status, 400);
});

test('records: filter, price sort, NULL exclusion footer', async () => {
  const r = await call('/api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month&limit=5');
  assert.equal(r.res.status, 200, r.body);
  const j = r.json;
  const ci = j.columns.indexOf('usd_per_tb_month');
  const prices = j.rows.map((x) => x[ci]);
  assert.ok(prices.every((v) => v != null), 'NULL prices are excluded');
  assert.deepEqual([...prices].sort((a, b) => a - b), prices, 'ascending');
  assert.ok(j.excluded_null && j.excluded_null.usd_per_tb_month > 0, 'NULL exclusion reported');
  for (const x of j.rows) assert.equal(x[j.columns.indexOf('card')], 'no');
  const t = await call('/api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month&limit=5&format=tsv');
  assert.match(t.body, /# excluded for NULL usd_per_tb_month: \d+/);
  const m = await call('/api/v1/records?topic=compute&max_usd_month=5&iface=api&order=desc&sort=usd_month');
  assert.equal(m.res.status, 200, m.body);
  const mi = m.json.columns.indexOf('usd_month');
  assert.ok(m.json.rows.every((x) => x[mi] <= 5));
  const u = await call('/api/v1/records?topic=storage&bogus=1&limit=1');
  assert.ok(u.json.notes.some((n) => /ignored parameter: bogus/.test(n)));
  assert.equal((await call('/api/v1/records?sort=rno')).res.status, 400);
  assert.equal((await call('/api/v1/records?limit=201')).res.status, 400);
});

test('sql: guarded, capped, GET and POST', async () => {
  const bad = await call('/api/v1/sql?q=' + encodeURIComponent('DELETE FROM record'));
  assert.equal(bad.res.status, 400);
  assert.match(bad.json.error, /refused/);
  const ok = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT topic, count(*) AS n FROM record GROUP BY topic ORDER BY n DESC'));
  assert.equal(ok.res.status, 200, ok.body);
  assert.deepEqual(ok.json.columns, ['topic', 'n']);
  assert.ok(ok.json.rows.length > 5);
  const post = await call('/api/v1/sql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q: 'SELECT rid FROM record', limit: 3 }) });
  assert.equal(post.res.status, 200, post.body);
  assert.equal(post.json.rows.length, 3);
  assert.equal(post.json.truncated, true);
  assert.equal(post.res.headers.get('cache-control'), 'no-store');
  const err = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT nope FROM record'));
  assert.equal(err.res.status, 400);
  assert.match(err.json.error, /SQL error/);
  assert.doesNotMatch(err.body, /at \w+ \(/, 'no stack trace');
  const fts = await call('/api/v1/sql?q=' + encodeURIComponent("SELECT r.rid FROM text_fts JOIN record r ON r.rno = text_fts.docid WHERE text_fts MATCH 'webdav*' LIMIT 3"));
  assert.equal(fts.res.status, 200, fts.body);
  const limited = await call('/api/v1/sql?q=SELECT%201', {}, { ...env, RL_SQL: denyAll });
  assert.equal(limited.res.status, 429);
  assert.equal(limited.res.headers.get('retry-after'), '60');
  assert.equal((await call('/api/v1/sql', { method: 'PUT' })).res.status, 405);
});

test('query_only holds even past the guard', async () => {
  const { getStore } = await import('../db.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  assert.throws(() => store.db.exec('DELETE FROM record'), /readonly|read-only|query_only/i);
  assert.equal(store.db.exec('SELECT total_changes()')[0].values[0][0], 0);
});

test('need, worklist, entity-search', async () => {
  const list = await call('/api/v1/need/');
  assert.equal(list.res.status, 200, list.body);
  assert.ok(list.json.rows.some((x) => x[0] === 's3-storage-no-card'));
  const n = await call('/api/v1/need/s3-storage-no-card');
  assert.equal(n.res.status, 200, n.body);
  const pi = n.json.columns.indexOf('usd_per_tb_month');
  const vals = n.json.rows.map((x) => x[pi]);
  assert.ok(vals.every((v) => v != null));
  assert.deepEqual([...vals].sort((a, b) => a - b), vals);
  assert.ok(Array.isArray(n.json.null_rows));
  timings.need_rows = `${n.json.rows.length} ranked + ${n.json.null_rows.length} unranked of ${n.json.total}`;
  assert.equal((await call('/api/v1/need/nope')).res.status, 404);
  const gpu = await call('/api/v1/need/free-gpu');
  assert.equal(gpu.res.status, 200, gpu.body);
  for (const kind of ['stale', 'drift', 'changes', 'unparsed']) {
    const w = await call(`/api/v1/worklist/${kind}?limit=3`);
    assert.equal(w.res.status, 200, kind + ': ' + w.body);
    assert.ok(w.json.rows.length <= 3);
  }
  const st = await call('/api/v1/worklist/stale?topic=storage&as_of=2027-06-01&forecast_days=30&limit=2');
  assert.ok(st.json.notes.some((x) => /stale_on <= 2027-07-01/.test(x)));
  assert.equal((await call('/api/v1/worklist/held')).res.status, 400);
  assert.equal((await call('/api/v1/worklist/stale?as_of=yesterday')).res.status, 400);
  const es = await call('/api/v1/entity-search?q=hetzner');
  assert.equal(es.res.status, 200, es.body);
  assert.equal(es.json.rows[0][0], 'hetzner');
  assert.equal(es.json.rows[0][6], 100);
});

test('permalinks and record JSON', async () => {
  const r = await call('/r/storage/hetzner-storage-box');
  assert.equal(r.res.status, 301);
  assert.equal(r.res.headers.get('location'), ORIGIN + '/p/hetzner/#storage--hetzner-storage-box');
  assert.ok(r.res.headers.get('x-fshy-commit'));
  assert.equal((await call('/r/storage/no-such-record')).res.status, 404);
  assert.equal((await call('/api/v1/record/storage/no-such-record')).res.status, 404);
  if (!HAVE_DIST) { console.log('# skipped record JSON: no ' + DIST); return; }
  const j = await call('/api/v1/record/storage/hetzner-storage-box.json');
  assert.equal(j.res.status, 200, j.body);
  assert.equal(j.json.rid, 'storage/hetzner-storage-box');
  for (const k of ['card', 'record', 'claims', 'unknown', 'history', 'drift']) assert.ok(k in j.json, k);
});

test('MCP: initialize, list, call, errors', async () => {
  const init = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '0' } });
  assert.equal(init.res.status, 200, init.body);
  assert.equal(init.json.result.protocolVersion, '2025-06-18');
  assert.deepEqual(init.json.result.capabilities, { tools: { listChanged: false } });
  assert.equal(init.json.result.serverInfo.name, 'fshy');
  const future = await rpc('initialize', { protocolVersion: '2099-01-01' });
  assert.equal(future.json.result.protocolVersion, '2025-11-25');
  const note = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) });
  assert.equal(note.res.status, 202);
  assert.equal((await rpc('ping')).json.result && true, true);
  const tl = await rpc('tools/list');
  const names = tl.json.result.tools.map((t) => t.name);
  assert.deepEqual(names, ['help', 'search', 'filter', 'get', 'entity', 'need', 'sql', 'worklist']);
  const toolJson = JSON.stringify(tl.json.result.tools);
  timings.tools_list_chars = toolJson.length;
  const { estimateTokens } = await import('../mcp.js');
  timings.tools_list_tokens_est = estimateTokens(toolJson);
  const s = await rpc('tools/call', { name: 'search', arguments: { q: 'hetzner', limit: 5 } });
  assert.equal(s.json.result.isError, false);
  const txt = s.json.result.content[0].text;
  assert.match(txt.split('\n')[0], /^rid\tprovider\tverdict/);
  assert.match(txt, /hetzner/);
  const q = await rpc('tools/call', { name: 'sql', arguments: { query: 'DELETE FROM record' } });
  assert.equal(q.json.result.isError, true);
  assert.match(q.json.result.content[0].text, /refused/);
  const g = await rpc('tools/call', { name: 'get', arguments: { ids: ['storage/hetzner-storage-box'], detail: 'card' } });
  assert.match(g.json.result.content[0].text, /storage\/hetzner-storage-box/);
  if (HAVE_DIST) {
    const gf = await rpc('tools/call', { name: 'get', arguments: { ids: ['storage/hetzner-storage-box'], detail: 'full', fields: ['record.free_tier', 'card.verdict'] } });
    assert.equal(gf.json.result.isError, false, gf.body);
    assert.ok(JSON.parse(gf.json.result.content[0].text).records[0]['card.verdict']);
  }
  const e = await rpc('tools/call', { name: 'entity', arguments: { name: 'hetzner' } });
  assert.match(e.json.result.content[0].text, /# entity hetzner/);
  const nd = await rpc('tools/call', { name: 'need', arguments: {} });
  assert.match(nd.json.result.content[0].text, /s3-storage-no-card/);
  const wl = await rpc('tools/call', { name: 'worklist', arguments: { kind: 'drift', limit: 2 } });
  assert.equal(wl.json.result.isError, false);
  const h = await rpc('tools/call', { name: 'help', arguments: {} });
  assert.match(h.json.result.content[0].text, /fshy|record/);
  const big = await rpc('tools/call', { name: 'sql', arguments: { query: "SELECT rid, summary, summary || summary || summary AS s FROM record", limit: 200 } });
  assert.ok(estimateTokens(big.json.result.content[0].text) <= 20100);
  const unk = await rpc('tools/call', { name: 'nope', arguments: {} });
  assert.equal(unk.json.error.code, -32602);
  assert.equal((await rpc('resources/list')).json.error.code, -32601);
  assert.equal((await call('/mcp')).res.status, 405);
  assert.equal((await call('/mcp', { method: 'DELETE' })).res.status, 405);
  const host = await call('/mcp', { method: 'POST', headers: { host: 'evil.example', 'content-type': 'application/json' }, body: '{}' });
  assert.equal(host.res.status, 403);
  const ping = JSON.stringify({ jsonrpc: '2.0', id: 9, method: 'ping' });
  const own = await call('/mcp', { method: 'POST', headers: { host: 'fshy.example', 'content-type': 'application/json' }, body: ping }, { ...env, FSHY_HOST: 'fshy.example' });
  assert.equal(own.res.status, 200, 'the host named by FSHY_HOST is allowed');
  const v6 = await call('/mcp', { method: 'POST', headers: { host: '[::1]:8787', 'content-type': 'application/json' }, body: ping });
  assert.equal(v6.res.status, 200, 'the IPv6 loopback of wrangler dev is allowed');
  const parse = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{nope' });
  assert.equal(parse.json.error.code, -32700);
  const pv = await rpc('ping', null, { 'mcp-protocol-version': '1999-01-01' });
  assert.equal(pv.res.status, 400);
  const lim = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'ping' }) }, { ...env, RL_API: denyAll });
  assert.equal(lim.res.status, 429);
  const pre = await call('/mcp', { method: 'OPTIONS' });
  assert.equal(pre.res.status, 204);
});

test('parity fixture: the text, ranking and guard rules give the outputs in parity.json', async () => {
  const { compute, load } = await import('./parity.mjs');
  const guardMod = await import('../guard.js');
  const fx = load();
  const got = compute(fx, { text, rank, guard: guardMod });
  for (const k of ['text', 'rank', 'guard', 'guard_lists']) assert.deepEqual(got[k], fx[k], k + ' differs from parity.json: run node site/worker/test/parity.mjs --write after a deliberate change');
  const g = Object.fromEntries(fx.guard.map((c) => [c.sql, c.result[0]]));
  for (const s of ['\uFEFFselect 1', 'SELECT\u00E9INSERT FROM x', 'select 1 where x=\u00E9drop', 'select \u0645delete from record']) {
    assert.equal(g[s], 'err', 'the stricter side wins: ' + JSON.stringify(s));
  }
});

test('sql: the statement budget refuses a costly plan, whatever its shape (issue #5)', async () => {
  // the shapes of a costly statement: many cheap chains, a skewed = key, a value that doubles
  const like = "(SELECT count(*) FROM evidence e, history h WHERE e.url LIKE '%' || h.title || '%')";
  const verdict = '(SELECT count(*) FROM record a, record b WHERE a.verdict = b.verdict)';
  const date = 'SELECT count(*) FROM evidence a JOIN evidence b ON a.date = b.date';
  const hexed = (k) => 'SELECT length(' + 'hex('.repeat(k) + 'group_concat(summary)' + ')'.repeat(k) + ') FROM record';
  // each line: [statement, the start of the refusal]; the eleven after the merge shapes are more shapes to refuse
  const refuse = [
    ['SELECT ' + Array(40).fill(like).join(' + '), 'the plan reads'],
    ['SELECT ' + Array(60).fill(verdict).join(' + '), 'the plan reads'],
    [date, 'the plan reads'],
    [date + ' UNION ALL ' + date, 'the plan reads'],
    [hexed(7), 'function not allowed: hex()'],
    [hexed(10), 'function not allowed: hex()'],
    [hexed(16), 'function not allowed: hex()'],
    ["SELECT count(*) FROM evidence e WHERE EXISTS (SELECT 1 FROM limit_row l WHERE l.value LIKE '%'||e.proved||'%')", 'the plan reads'],
    ['SELECT count(*) FROM evidence e WHERE NOT EXISTS (SELECT 1 FROM limit_row l WHERE l.value = e.proved)', 'the plan reads'],
    ['SELECT count(*) FROM edge a, edge b, edge c WHERE a.src <> b.src AND b.src <> c.src AND c.dst <> a.dst', 'the plan reads'],
    ['SELECT count(*) FROM record a LEFT JOIN record b ON a.rno <> b.rno', 'the plan reads'],
    ['SELECT count(*) FROM record a LEFT JOIN record b ON a.rno <> b.rno LEFT JOIN record c ON b.rno <> c.rno', 'the plan reads'],
    ['SELECT count(*) FROM record a LEFT JOIN record b ON 1 LEFT JOIN record c ON 1 LEFT JOIN record d ON 1', 'the plan reads'],
    ['WITH x AS (SELECT rno FROM record) SELECT count(*) FROM x a, x b WHERE a.rno < b.rno', 'the plan reads'],
    ['WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c', 'a recursive CTE'],
    ['SELECT length(hex(randomblob(50000000)))', 'function not allowed: hex()'],
    ['SELECT length(zeroblob(100000000))', 'function not allowed: zeroblob()'],
    ["SELECT length(printf('%.*c', 100000000, 'x'))", 'printf() width'],
    ['SELECT count(*) FROM claim a, evidence b WHERE a.rid <> b.rid', 'the plan reads'],
    ['SELECT count(*) FROM record r JOIN claim c ON c.rid <> r.rid', 'the plan reads'],
    ['SELECT count(*) FROM record a CROSS JOIN entity b', 'the plan reads'],
    ['SELECT (SELECT count(*) FROM evidence e WHERE e.url <> r.url) FROM record r', 'the plan reads'],
    ['SELECT count(*) FROM "claim" a, [evidence] b', 'the plan reads'],
    ['WITH t AS MATERIALIZED (SELECT * FROM claim) SELECT count(*) FROM t, evidence WHERE t.rid <> evidence.rid', 'the plan reads'],
    ['SELECT count(*) FROM record WHERE rid IN (SELECT a.rid FROM claim a, evidence b WHERE a.rid <> b.rid)', 'the plan reads'],
    ['SELECT count(*) FROM record a, record b, record c WHERE a.topic = b.topic AND b.eid <> c.eid', 'the plan reads'],
    // an = join on a column with few values reads many rows a key: the largest key counts, not the mean
    ['SELECT count(*) FROM record a, record b, record c WHERE a.topic = b.topic AND b.topic = c.topic', 'the plan reads'],
    ['SELECT count(*) FROM record a, record b WHERE a.topic = b.topic', 'the plan reads'],
    ['SELECT count(*) FROM record a JOIN record b ON a.grp = b.grp', 'the plan reads'],
    ["SELECT count(*) FROM record a WHERE EXISTS (SELECT 1 FROM record b WHERE b.topic = a.topic AND b.summary LIKE '%zzz%')", 'the plan reads'],
    // a full-text match reads every document; a MULTI-INDEX OR reads all its parts; a CTE that shadows a table is sized
    ["SELECT count(*) FROM text_fts f, record a WHERE f.text_fts MATCH 'a*'", 'the plan reads'],
    ["SELECT count(*) FROM record a, evidence e WHERE (a.eid = 'x' OR a.topic = 'storage') AND e.url LIKE a.rid", 'the plan reads'],
    ['WITH history AS MATERIALIZED (SELECT a.rno FROM record a, drift b) SELECT count(*) FROM history x, history y', 'the plan reads'],
    ['SELECT (SELECT count(*) FROM (SELECT DISTINCT e.url FROM evidence e, history h WHERE e.rid = r.rid AND h.hid <> e.url)) FROM record r', 'the plan reads'],
    // the weight of a row: the functions and operators that the statement evaluates on it
    ["SELECT count(printf('%1000s', a.alias)) FROM alias a, drift d", 'the plan reads'],
    ["SELECT max(strftime('%Y-%m-%d %H:%M:%S %J %s', 'now', '+' || d.rowid || ' days')) FROM alias a, drift d", 'the plan reads'],
    ["SELECT count(*) FROM alias a, drift d WHERE a.alias LIKE '%' || d.subject || '%'", 'the plan reads'],
    // the function allowlist of the guard
    ['SELECT quote(summary) FROM record', 'function not allowed: quote()'],
    ['SELECT char(65, 66)', 'function not allowed: char()'],
    ['SELECT json_array(summary) FROM record', 'function not allowed: json_array()'],
    ["SELECT * FROM json_each('[1,2,3]')", 'function not allowed: json_each()'],
    ['SELECT "hex"(summary) FROM record', 'function not allowed: hex()'],
    ['WITH hex(a) AS (SELECT 1) SELECT hex(summary) FROM record', 'function not allowed: hex()'],
    ["SELECT printf('%q', summary) FROM record", 'printf() conversion %q'],
    ["SELECT printf('%' || '2000c', 'x')", 'printf() needs a literal format string'],
  ];
  for (const [q, why] of refuse) {
    const r = await call('/api/v1/sql?q=' + encodeURIComponent(q));
    assert.equal(r.res.status, 400, q + ': ' + r.body);
    assert.ok(r.json.error.startsWith('refused: ' + why), q + ': ' + r.json.error);
  }
  const accept = [
    'SELECT r.rid FROM record r JOIN claim c ON c.rid = r.rid',
    "SELECT CAST(usd_month AS DECIMAL(10,2)) FROM record",
    'SELECT name FROM sqlite_master',
    "SELECT * FROM pragma_table_info('record')",
    'SELECT * FROM (VALUES (1),(2),(3)) v, record r WHERE r.rno = v.column1',
    'SELECT length(group_concat(summary)) FROM record',
    "SELECT json_extract('{\"a\":1}', '$.a')",
    "SELECT count(*) FROM record WHERE eid = 'x' OR topic = 'storage'",
    'SELECT count(*) FROM record r WHERE EXISTS (SELECT 1 FROM claim c WHERE c.rid = r.rid)',
    'SELECT rid, row_number() OVER (PARTITION BY topic ORDER BY vorder) FROM record',
    "SELECT matchinfo(text_fts, 'pcx') FROM text_fts WHERE text_fts MATCH 'gpu'",
    "SELECT format('%5.1f%%', usd_month) FROM record",
    'SELECT * FROM record WHERE rid IN (SELECT rid FROM claim)',
    'SELECT * FROM fx a, vocab b',
    "SELECT r.rid FROM text_fts JOIN record r ON r.rno = text_fts.docid WHERE text_fts MATCH 'webdav*'",
    'SELECT rid FROM record UNION ALL SELECT rid FROM claim',
    'SELECT r.rid, (SELECT count(*) FROM claim c WHERE c.rid = r.rid) FROM record r',
    'SELECT count(*) FROM record a LEFT JOIN entity e ON e.eid = a.eid',
    "SELECT printf('%.2f', usd_month) FROM record",
    'WITH t AS (SELECT eid, count(*) AS n FROM record GROUP BY eid) SELECT * FROM t ORDER BY n DESC',
    'EXPLAIN QUERY PLAN SELECT count(*) FROM claim a, evidence b',
  ];
  for (const q of accept) {
    const r = await call('/api/v1/sql?q=' + encodeURIComponent(q));
    assert.equal(r.res.status, 200, q + ': ' + r.body);
  }
  // the backstops: a result over the cap, and a value over the heap limit, are refused; the store stays usable
  const big = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT s || s || s || s FROM (SELECT group_concat(summary) AS s FROM record)'));
  assert.equal(big.res.status, 400, big.body);
  assert.match(big.json.error, /^refused: the result is over 2,000,000 characters/);
  let doubled = 'SELECT group_concat(summary) AS s FROM record';
  for (let i = 0; i < 7; i++) doubled = 'SELECT s || s AS s FROM (' + doubled + ')';
  const oom = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT length(s) FROM (' + doubled + ')'));
  assert.equal(oom.res.status, 400, oom.body);
  assert.match(oom.json.error, /^refused: the statement needs more than the 32 MiB/);
  const after = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT count(*) FROM record'));
  assert.equal(after.res.status, 200, after.body);
  const m = await rpc('tools/call', { name: 'sql', arguments: { query: refuse[0][0] } });
  assert.equal(m.json.result.isError, true);
  assert.match(m.json.result.content[0].text, /the plan reads/);
  // the needs and the worked queries of the primer pass the budget
  const { getStore } = await import('../db.js');
  const { checkPlan } = await import('../plan.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  const needs = JSON.parse(readFileSync(join(REPO, 'publish', 'rules', 'needs.json'), 'utf8')).needs;
  for (const x of needs) assert.doesNotThrow(() => checkPlan(store, x.sql), x.id);
  const help = join(DIST, 'api', 'v1', 'help.txt');
  if (!existsSync(help)) { console.log('# skipped the primer queries: no ' + help); return; }
  const worked = readFileSync(help, 'utf8').split('EXAMPLES')[1].split('\n').filter((l) => /^ {3}(SELECT|WITH) /.test(l)).map((l) => l.trim());
  assert.ok(worked.length >= 5, 'the primer has its worked queries');
  for (const q of worked) assert.doesNotThrow(() => checkPlan(store, q), q);
});

test('sql: a full-text match with filters is refused as a join, the refusal names the recipe, and the recipe runs (F-09)', async () => {
  const q = (sql) => call('/api/v1/sql?q=' + encodeURIComponent(sql));
  const join = await q("SELECT r.rid FROM text_fts f JOIN record r ON r.rno = f.docid WHERE f.text_fts MATCH 'gpu' AND r.topic IN ('compute') AND r.grp IN ('usable') AND r.duplicate_of IS NULL LIMIT 5");
  assert.equal(join.res.status, 400, join.body);
  assert.match(join.json.error, /For a full-text match with filters, select from record WHERE rno IN \(SELECT docid FROM text_fts/);
  const ok = await q("SELECT r.rid, r.verdict FROM record r WHERE r.rno IN (SELECT docid FROM text_fts WHERE text_fts MATCH 'offer:gpu*') AND r.topic IN ('compute','inference') AND r.grp IN ('usable','trial') AND r.duplicate_of IS NULL ORDER BY r.vorder LIMIT 10");
  assert.equal(ok.res.status, 200, ok.body);
  assert.ok(ok.json.rows.length > 0);
  const other = await q('SELECT count(*) FROM claim a, evidence b WHERE a.rid <> b.rid');
  assert.ok(!/full-text/.test(other.json.error), 'the recipe is named for a full-text statement only');
});

test('sql: a failure of the engine is a 503, and the next request loads the store again', async () => {
  const api = await import('../api.js');
  const { engineFailed, HttpError } = await import('../db.js');
  assert.equal(engineFailed(new WebAssembly.RuntimeError('memory access out of bounds')), true);
  assert.equal(engineFailed(new Error('no such column: x')), false);
  const broken = { db: { exec() { throw new WebAssembly.RuntimeError('unreachable executed'); }, close() {} }, cache: {} };
  assert.throws(() => api.sql(broken, { q: 'SELECT 1' }), (e) => e instanceof HttpError && e.status === 503);
  const after = await call('/api/v1/sql?q=' + encodeURIComponent('SELECT count(*) FROM record'));
  assert.equal(after.res.status, 200, after.body);
});

test('a rate limiter that throws fails open', async () => {
  const broken = { ...env, RL_API: throws, RL_SQL: throws };
  const s = await call('/api/v1/search?q=hetzner&limit=1', {}, broken);
  assert.equal(s.res.status, 200, s.body);
  const q = await call('/api/v1/sql?q=SELECT%201', {}, broken);
  assert.equal(q.res.status, 200, q.body);
  const m = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) }, broken);
  assert.equal(m.res.status, 200, m.body);
});

// ------------------------------------------------------------------ limits, pages and the API (P-nn and U-nn tag the item that a test covers)

test('MCP: a batch holds at most 5 messages, and each tool call costs one unit of the limit (P-01)', async () => {
  const call1 = (id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'need', arguments: {} } });
  const post = (body, e = env) => call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }, e);
  const six = await post([1, 2, 3, 4, 5, 6].map(call1));
  assert.equal(six.res.status, 400, six.body);
  assert.match(six.json.error.message, /at most 5 messages/);
  let n = 0;
  const counting = { limit: async () => { n++; return { success: true }; } };
  const five = await post([1, 2, 3, 4, 5].map(call1), { ...env, RL_API: counting });
  assert.equal(five.res.status, 200, five.body);
  assert.equal(five.json.length, 5);
  assert.equal(n, 5, 'five tool calls are five units');
  n = 0;
  const two = await post([{ jsonrpc: '2.0', id: 1, method: 'ping' }, { jsonrpc: '2.0', id: 2, method: 'tools/list' }], { ...env, RL_API: counting });
  assert.equal(two.res.status, 200);
  assert.equal(n, 1, 'a request with no tool call is one unit');
  let left = 3;
  const three = { limit: async () => ({ success: left-- > 0 }) };
  const over = await post([1, 2, 3, 4, 5].map(call1), { ...env, RL_API: three });
  assert.equal(over.res.status, 429, 'a batch over the units left is refused whole');
  const { MAX_BATCH } = await import('../mcp.js');
  assert.equal(MAX_BATCH, 5);
});

test('MCP: a batch holds at most 1 sql call, so no accepted batch passes the CPU limit', async () => {
  const { MAX_BATCH, MAX_BATCH_SQL } = await import('../mcp.js');
  const sql = (id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'sql', arguments: { query: 'SELECT 1' } } });
  const need = (id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'need', arguments: {} } });
  const post = (body, e = env) => call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }, e);
  let n = 0;
  const counting = { limit: async () => { n++; return { success: true }; } };
  const counted = { ...env, RL_API: counting, RL_SQL: counting };

  // the bound, with the costs that site/README.md measures (CPU ms of a warm request): the costliest sql statement,
  // and a search of a batch of five. A full batch of the most sql calls that the limit accepts, with searches for
  // the other calls, keeps a margin of 2 under cpu_ms of wrangler.jsonc.
  const SQL_MS = 672;
  const SEARCH_MS = 75;
  const cpuMs = Number(/"cpu_ms":\s*(\d+)/.exec(readFileSync(join(SITE, 'wrangler.jsonc'), 'utf8'))[1]);
  const worst = MAX_BATCH_SQL * SQL_MS + (MAX_BATCH - MAX_BATCH_SQL) * SEARCH_MS;
  assert.ok(worst * 2 <= cpuMs, `a batch of ${MAX_BATCH_SQL} sql and ${MAX_BATCH - MAX_BATCH_SQL} other calls is ${worst} ms; cpu_ms is ${cpuMs}`);
  assert.equal(MAX_BATCH_SQL, 1);

  // over the bound: a clear JSON-RPC error and a 400, before the rate limit and the load of the store
  for (const body of [[1, 2].map(sql), [1, 2, 3].map(sql), [sql(1), need(2), sql(3), need(4), sql(5)], [1, 2, 3, 4, 5].map(sql)]) {
    n = 0;
    const r = await post(body, counted);
    assert.equal(r.res.status, 400, r.body);
    assert.equal(r.json.error.code, -32600);
    assert.equal(r.json.id, null);
    assert.match(r.json.error.message, /a batch holds at most 1 sql call; send the others in more requests/);
    assert.equal(n, 0, 'a refused batch costs no unit of any limit');
  }
  // at the bound: answered, with the other calls of a full batch
  n = 0;
  const ok = await post([sql(1), need(2), need(3), need(4), need(5)], counted);
  assert.equal(ok.res.status, 200, ok.body);
  assert.equal(ok.json.length, 5);
  assert.ok(ok.json.every((x) => x.result && x.result.isError === false), ok.body);
  assert.equal(n, 5 + 1, 'five calls on RL_API and one on RL_SQL');
  // only a call of the tool sql weighs more: a batch of five other calls, a sql call alone, and a notification are fine
  assert.equal((await post([1, 2, 3, 4, 5].map(need))).res.status, 200);
  assert.equal((await post(sql(1))).res.status, 200);
  const named = { jsonrpc: '2.0', id: 9, method: 'tools/call', params: { name: 'SQL', arguments: {} } };
  assert.equal((await post([named, named, named])).res.status, 200, 'a call of an unknown tool is cheap and is not a sql call');
});

test('the rate limit runs before the store loads (P-04), and /r/ is limited', async () => {
  const { getStore, discard } = await import('../db.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  discard(store);
  const before = assetLog.length;
  for (const p of ['/api/v1/search?q=x', '/api/v1/records', '/r/storage/hetzner-storage-box', '/api/v1/need/free-gpu']) {
    const r = await call(p, {}, { ...env, RL_API: denyAll });
    assert.equal(r.res.status, 429, p + ': ' + r.body);
  }
  const m = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) }, { ...env, RL_API: denyAll });
  assert.equal(m.res.status, 429);
  const s = await call('/api/v1/sql?q=SELECT%201', {}, { ...env, RL_SQL: denyAll });
  assert.equal(s.res.status, 429);
  assert.ok(!assetLog.slice(before).includes('data/manifest.json'), 'a refused request loads no store');
  const ok = await call('/api/v1/records?limit=1');
  assert.equal(ok.res.status, 200, ok.body);
  assert.ok(assetLog.slice(before).includes('data/manifest.json'), 'the next request loads the store again');
});

// ------------------------------------------------------------------ a load whose request ended (issue #26)

// The Workers runtime drops the continuations of a request that has ended. A client that goes away cancels its
// request, and an asset read of that request then never settles. These tests make the same read with an ASSETS binding
// that does not answer until release(). Each test imports a new copy of db.js, so it starts with no store. The timeout
// turns the old fault, a request that waits for ever, into a failure. smoke.mjs and strand.mjs test the same on workerd.
function stalled() {
  const waiting = [];
  let open = false;
  return {
    ASSETS: {
      fetch(req) {
        const path = decodeURIComponent(new URL(req.url).pathname.replace(/^\/+/, ''));
        if (open) return Promise.resolve(assetResponse(path));
        return new Promise((resolve) => waiting.push(() => resolve(assetResponse(path))));
      },
    },
    get waiting() { return waiting.length; },
    release() {
      open = true;
      for (const f of waiting.splice(0)) f();
    },
  };
}
let dbCopies = 0;
const freshDb = () => import('../db.js?copy=' + ++dbCopies);
const manifestReads = (from) => assetLog.slice(from).filter((p) => p === 'data/manifest.json').length;

test('a request does not wait for ever on a load that an ended request started (issue #26)', { timeout: 20000 }, async () => {
  const db = await freshDb();
  const s = stalled();
  // the request that starts the load ends: it passes no ctx.waitUntil(), its read never settles, and it never runs
  // again, which a wait of 1e9 ms stands for
  const ended = db.getStore({ ...env, ASSETS: s.ASSETS }, globalThis.__fshyWasm, undefined, 1e9);
  assert.equal(s.waiting, 1, 'the load started with the read of the manifest');
  const before = assetLog.length;
  const t0 = performance.now();
  const [a, b] = await Promise.all([1, 2].map(() => db.getStore(env, globalThis.__fshyWasm, undefined, 300)));
  const ms = performance.now() - t0;
  assert.ok(ms >= 250 && ms < 10000, 'the waiters gave up on the old load after 300 ms, then loaded the store: ' + ms);
  assert.equal(a.store, b.store, 'two waiters share one new load');
  assert.equal(manifestReads(before), 1, 'one new load, not one for each waiter');
  assert.ok(a.store.db.exec('SELECT count(*) FROM record')[0].values[0][0] > 0);
  // the old read answers after all: the old load completes, and the store in use stays
  s.release();
  assert.equal((await ended).store, a.store);
  assert.equal((await db.getStore(env, globalThis.__fshyWasm)).store, a.store);
  db.discard(a.store);
});

test('the request that starts a load passes it to ctx.waitUntil(), so the load completes after the request ends', { timeout: 20000 }, async () => {
  const db = await freshDb();
  const s = stalled();
  const kept = [];
  const ctx = { waitUntil: (p) => kept.push(p) };
  const ended = db.getStore({ ...env, ASSETS: s.ASSETS }, globalThis.__fshyWasm, ctx, 1e9);
  assert.equal(kept.length, 1, 'the load is passed to ctx.waitUntil()');
  s.release();
  await kept[0];
  const before = assetLog.length;
  const next = await db.getStore(env, globalThis.__fshyWasm, undefined, 300);
  assert.equal(next.cold, false, 'the next request uses the store of that load');
  assert.equal(manifestReads(before), 0);
  assert.equal((await ended).store, next.store);
  db.discard(next.store);
});

test('a request whose own load is late too gets a 503, and the next request loads the store', { timeout: 20000 }, async () => {
  const db = await freshDb();
  const { HttpError } = db;
  const s = stalled();
  const t0 = performance.now();
  await assert.rejects(db.getStore({ ...env, ASSETS: s.ASSETS }, globalThis.__fshyWasm, undefined, 200),
    (e) => e instanceof HttpError && e.status === 503 && e.late === true && /did not load/.test(e.message));
  const ms = performance.now() - t0;
  assert.ok(ms >= 350 && ms < 10000, 'two waits of 200 ms: ' + ms);
  s.release();
  const { store } = await db.getStore(env, globalThis.__fshyWasm, undefined, 300);
  assert.ok(store.db.exec('SELECT count(*) FROM record')[0].values[0][0] > 0);
  db.discard(store);
});

test('a name index read that never settles does not stall the name index of another request (issue #26)', { timeout: 20000 }, async (t) => {
  if (!MANIFEST.name_index) { t.skip('no name index in ' + DIST); return; }
  const db = await freshDb();
  const { store } = await db.getStore(env, globalThis.__fshyWasm);
  const s = stalled();
  const ended = db.loadNames(store, { ...env, ASSETS: s.ASSETS });
  const names = await db.loadNames(store, env);
  assert.equal(store.cache.names, names);
  s.release();
  await ended;
  assert.equal(store.cache.names, names, 'a late read keeps the index in use');
  db.discard(store);
});

test('malformed percent-encoding in a path is a 400, not a 500 (P-12)', async () => {
  for (const p of ['/api/v1/need/%E0%A4%A', '/api/v1/worklist/%E0%A4%A', '/api/v1/record/%E0%A4%A/x', '/r/%E0%A4%A/x', '/r/storage/%E0%A4%A']) {
    const r = await call(p);
    assert.equal(r.res.status, 400, p + ': ' + r.body);
    assert.match(r.json.error, /percent-encoding/);
  }
});

test('a repeated query word costs one word, and a long query has no fuzzy pass (P-05)', () => {
  const idx = rank.buildNameIndex([{ eid: 'hetzner', alias: 'Hetzner Storage Box' }, { eid: 'box', alias: 'Box' }]);
  const by = (q) => rank.scoreNames(idx, q).map((h) => [h.eid, h.score]).sort();
  assert.deepEqual(by(Array(40).fill('hetzer').join(' ')), by('hetzer'));
  assert.deepEqual(by('hetzer storag'), [['hetzner', 30]]);
  const nine = 'hetzer storag boxx one two three four five six';
  assert.equal(new Set(text.tokens(text.normalize(nine))).size, rank.MAX_FUZZY_TOKENS + 1);
  assert.deepEqual(by(nine), [], 'over MAX_FUZZY_TOKENS distinct words, the fuzzy tier does not run');
});

test('the name index file of the build equals the index the Worker builds from the store (P-16)', async (t) => {
  if (!MANIFEST.name_index) { t.skip('no name index in ' + DIST); return; }
  const { getStore, loadNames } = await import('../db.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  const fromFile = JSON.parse(readFileSync(join(DIST, ...MANIFEST.name_index.split('/')), 'utf8'));
  const res = store.db.exec('SELECT eid, alias FROM alias ORDER BY eid, alias, kind');
  const built = rank.buildNameIndex(res[0].values.map(([eid, alias]) => ({ eid, alias })));
  assert.deepEqual(fromFile.aliases, built.aliases, 'the normalisation of site_gen.py is the one of text.js');
  assert.deepEqual(fromFile.eids, built.eids);
  store.cache.names = null;
  const t0 = performance.now();
  await loadNames(store, env);
  timings.name_index_from_file_ms = performance.now() - t0;
  assert.ok(assetLog.includes(MANIFEST.name_index), 'the Worker reads the file');
  assert.deepEqual(store.cache.names.aliases, built.aliases);
  const s = await call('/api/v1/search?q=hetzner&limit=1');
  assert.match(s.json.rows[0][0], /hetzner/);
});

test('a need ranks a tie by evidence, and the API, the page and the Markdown agree (U-13)', async (t) => {
  const n = await call('/api/v1/need/free-gpu?limit=200');
  assert.equal(n.res.status, 200, n.body);
  const ci = n.json.columns.indexOf('confidence');
  const RUNG = { measured: 0, documented: 1, reported: 2, inferred: 3, unverified: 4 };
  const vi = n.json.columns.indexOf('verdict');
  const VO = ['qualifies', 'qualifies-with-caveat', 'trial-only', 'paid-only', 'fails-identity', 'fails-egress', 'fails-quota', 'dead'];
  const key = (r) => [VO.indexOf(r[vi]), RUNG[r[ci]] ?? 5];
  for (let i = 1; i < n.json.rows.length; i++) {
    const [a, b] = [key(n.json.rows[i - 1]), key(n.json.rows[i])];
    assert.ok(a[0] < b[0] || (a[0] === b[0] && a[1] <= b[1]), 'row ' + i + ' is out of order: ' + n.json.rows[i][0]);
  }
  const md = join(DIST, 'need', 'free-gpu.md');
  if (!existsSync(md)) { t.skip('no ' + md); return; }
  const page = [...readFileSync(md, 'utf8').matchAll(/^\d+\. .*?`([^`]+)`/gm)].map((m) => m[1]);
  // the page splits the list into sections (llms.NEED_SPLITS: 4 for this need) and keeps the order of the API inside each, so
  // the page holds the same rows, and it goes back in the order of the API at most once between two sections
  const api = n.json.rows.map((r) => r[0]);
  assert.deepEqual([...page].sort(), [...api].sort());
  let back = 0;
  for (let i = 1; i < page.length; i++) if (api.indexOf(page[i]) < api.indexOf(page[i - 1])) back++;
  assert.ok(back <= 3, 'the Markdown goes back in the order of the API ' + back + ' times');
});

test('the API answers its root, an unknown route, a .tsv suffix and the static files (U-21)', async () => {
  for (const p of ['/api/v1/', '/api/v1']) {
    const r = await call(p);
    assert.equal(r.res.status, 200, p + ': ' + r.body);
    assert.ok(r.json.routes.length >= 8 && r.json.help === '/api/v1/help.txt');
  }
  const u = await call('/api/v1/foo');
  assert.equal(u.res.status, 404);
  assert.match(u.json.error, /help\.txt/);
  const t = await call('/api/v1/records.tsv?limit=2');
  assert.equal(t.res.status, 200, t.body);
  assert.match(t.res.headers.get('content-type'), /tab-separated/);
  if (HAVE_DIST) {
    const nm = await call('/api/v1/names.json');
    assert.equal(nm.res.status, 200, 'a static file of /api/v1/ still answers when the Worker sees it');
    assert.ok(Array.isArray(nm.json));
  }
});

test('an unknown term in a filter is a 400, never a silent empty list; a topic with no records is valid (U-22, W-20)', async () => {
  const t = await call('/api/v1/records?topic=stroage');
  assert.equal(t.res.status, 400, t.body);
  assert.match(t.json.error, /unknown topic "stroage"; topic is one of storage, compute/);
  // the topics of the manifest are valid when they have no record yet, and the 400 lists them
  const empty = (MANIFEST.topics || []).filter((x) => !/^(storage|compute)$/.test(x));
  assert.ok(empty.length, 'the manifest lists topics');
  for (const topic of ['dev-services', 'data-apis'].filter((x) => (MANIFEST.topics || []).includes(x))) {
    const r = await call('/api/v1/records?topic=' + topic + '&limit=1');
    assert.equal(r.res.status, 200, topic + ': ' + r.body);
    assert.ok(!(r.json.notes || []).some((n) => /unknown topic/.test(n)), r.body);
    assert.ok(t.json.error.includes(topic), 'the 400 lists ' + topic);
  }
  for (const p of ['verdict=bogus', 'grp=bogus', 'confidence=bogus', 'binding=bogus', 'no_card=maybe']) {
    const r = await call('/api/v1/records?' + p);
    assert.equal(r.res.status, 400, p + ': ' + r.body);
  }
  assert.equal((await call('/api/v1/records?no_card=yes&limit=1')).res.status, 200);
  assert.equal((await call('/api/v1/search?q=gpu&grp=bogus')).res.status, 400);
  const s = await call('/api/v1/search?q=gpu&topic=nonexistent');
  assert.equal(s.res.status, 400, s.body);
  assert.equal((await call('/api/v1/worklist/stale?topic=nonexistent')).res.status, 400);
  const m = await rpc('tools/call', { name: 'filter', arguments: { topic: 'zzz' } });
  assert.equal(m.json.result.isError, true);
  assert.match(m.json.result.content[0].text, /error: unknown topic "zzz"; topic is one of storage/);
});

test('the MCP tools say when to use each, carry read-only annotations and the topic list (U-23)', async () => {
  const tl = await rpc('tools/list');
  for (const tool of tl.json.result.tools) {
    assert.match(tool.description, /^Use /, tool.name);
    assert.equal(tool.annotations.readOnlyHint, true, tool.name);
    assert.equal(tool.annotations.destructiveHint, false, tool.name);
    if (tool.inputSchema.properties.topic) assert.ok(tool.inputSchema.properties.topic.enum.includes('storage'), tool.name);
  }
  const init = await rpc('initialize', { protocolVersion: '2025-06-18' });
  assert.match(init.json.result.instructions, /Topics: storage, compute/);
  assert.match(init.json.result.instructions, /Verdicts, best first: qualifies/);
  const unk = await rpc('tools/call', { name: 'nothing' });
  assert.match(unk.json.error.message, /the tools are help, search, filter/);
});

test('MCP: a call with no tool name, a request with a null id, and the batch limit get clear answers (W-25)', async () => {
  const post = (body) => call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const noName = await post({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: {} });
  assert.equal(noName.json.error.code, -32602);
  assert.match(noName.json.error.message, /^tools\/call needs the name of a tool in params\.name; the tools are help, search/);
  assert.ok(!/undefined/.test(noName.body), 'no JavaScript value leaks into the text');
  const named = await post({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'nope' } });
  assert.match(named.json.error.message, /^unknown tool: nope; the tools are/);
  const noQuery = await post({ jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'sql', arguments: {} } });
  assert.equal(noQuery.json.result.isError, true);
  assert.equal(noQuery.json.result.content[0].text, 'error: query (the SQL text) is required');
  const nullId = await post({ jsonrpc: '2.0', id: null, method: 'ping' });
  assert.equal(nullId.json.error.code, -32600);
  assert.match(nullId.json.error.message, /id must be a string or a number/);
  assert.deepEqual((await post({ jsonrpc: '2.0', id: 'a', method: 'ping' })).json.result, {});
  const init = await rpc('initialize', { protocolVersion: '2025-06-18' });
  assert.match(init.json.result.instructions, /A batch holds at most 5 messages, and at most 1 of them calls sql\./);
  const cors = await call('/mcp', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 3, method: 'ping' }) });
  assert.ok(!/mcp-protocol-version/i.test(cors.res.headers.get('access-control-expose-headers')), 'the Worker sends no such header, so it does not expose one');
});

test('a need that asks for no card or no phone lists the rows whose requirement is not stated in a section of their own', async (t) => {
  const NEED = 'inference-no-card-no-phone';
  const n = await call('/api/v1/need/' + NEED + '?limit=200');
  assert.equal(n.res.status, 200, n.body);
  const ids = (rows) => rows.map((r) => r[0]);
  const confirmed = [...ids(n.json.rows), ...ids(n.json.null_rows || [])];
  const unstated = ids(n.json.unstated_rows || []);
  const last = ids(n.json.self_hosted_rows || []);
  assert.ok(unstated.length > 0, 'the list has rows whose card or phone requirement is not stated');
  assert.ok(confirmed.length > 0 && !unstated.some((r) => confirmed.includes(r)), 'no row is in both sections');
  assert.equal(n.json.total, confirmed.length + unstated.length + last.length, 'the total counts every part');
  // an independent count with plain SQL: the rows of the need without its conditions that need no known card or phone,
  // and that are not confirmed
  const sql = "SELECT count(*) FROM record WHERE (topic='inference' OR category LIKE '%inference%') AND grp='usable' AND duplicate_of IS NULL " +
    "AND coalesce(summary,'') NOT LIKE 'no free %' AND coalesce(summary,'') NOT LIKE 'no published free %' AND coalesce(summary,'') NOT LIKE 'no perpetual free %' " +
    "AND coalesce(needs_card,0) <> 1 AND coalesce(needs_phone,0) <> 1 AND NOT (coalesce(needs_card,9)=0 AND coalesce(needs_phone,9)=0 AND identity_basis='stated') " +
    'AND self_hosted = 0'; // a self-hosted row is in self_hosted_rows, after every hosted row
  const c = await call('/api/v1/sql?q=' + encodeURIComponent(sql));
  assert.equal(c.json.rows[0][0], unstated.length, 'the section holds every row of the need that is not confirmed and not known to need a card or a phone');
  // the rows of the section have NULL somewhere: a card or a phone that is not stated, or an identity that is a placeholder
  const cols = n.json.columns;
  for (const r of n.json.unstated_rows) {
    const card = r[cols.indexOf('card')];
    const phone = r[cols.indexOf('phone')];
    assert.ok(card !== 'yes' && phone !== 'yes', r[0] + ' needs a card or a phone');
  }
  const tsv = await call('/api/v1/need/' + NEED + '.tsv?limit=200');
  assert.match(tsv.body, /# card or phone requirement not stated: \d+ rows below, not counted as no/);
  assert.ok(n.json.notes.some((x) => /rows with the card or phone requirement not stated follow the others/.test(x)));
  // a need that asks for neither has no such section
  const free = await call('/api/v1/need/free-gpu?limit=200');
  assert.equal(free.json.unstated_rows, undefined);
  const mcp = await rpc('tools/call', { name: 'need', arguments: { id: NEED, limit: 200 } });
  assert.match(mcp.json.result.content[0].text, /# card or phone requirement not stated: \d+ rows below/);
  // the page and the Markdown list the same rows
  const md = join(DIST, 'need', NEED + '.md');
  if (!existsSync(md)) { t.skip('no ' + md); return; }
  const text = readFileSync(md, 'utf8');
  const part = (text.split('## Card or phone requirement not stated')[1] || '').split('\n## Self-hosted, the last resort')[0];
  const listed = [...part.matchAll(/^- \[[^\]]*\]\([^)]*\) \[`([^`]+)`\]/gm)].map((m) => m[1]);
  assert.deepEqual([...listed].sort(), [...unstated].sort(), 'the Markdown page and the API hold the same rows');
});

test('the changes worklist says which field of which record was amended and never prints an empty old -> new (W-13)', async () => {
  const w = await call('/api/v1/worklist/changes?limit=200');
  assert.equal(w.res.status, 200, w.body);
  const ledger = w.json.rows.filter((r) => r[1] === 'ledger');
  assert.ok(ledger.length > 0, 'the newest rows are ledger rows');
  for (const r of ledger) {
    assert.ok(!/^ -> $/.test(r[4]), r.join(' | '));
    assert.match(r[4], /^amended; the old and the new value are not published$| -> /);
    assert.ok(r[5].includes('/'), 'the record id is the last column');
  }
});

test('the public store downloads from one URL that joins its parts (P-08)', async (t) => {
  if (!MANIFEST.public_db || !MANIFEST.public_db.parts) { t.skip('no parts of the public store in ' + DIST); return; }
  const pd = MANIFEST.public_db;
  const res = await worker.fetch(new Request(ORIGIN + '/data/fshy-public.sqlite.gz'), env, { waitUntil() {} });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'application/gzip');
  assert.equal(res.headers.get('content-length'), String(pd.gzip_bytes));
  const b = Buffer.from(await res.arrayBuffer());
  assert.equal(b.length, pd.gzip_bytes);
  assert.equal(createHash('sha256').update(b).digest('hex'), pd.gzip_sha256);
  const { gunzipSync } = await import('node:zlib');
  assert.equal(createHash('sha256').update(gunzipSync(b)).digest('hex'), pd.sha256, 'the joined file is the store');
  const head = await worker.fetch(new Request(ORIGIN + '/data/fshy-public.sqlite.gz', { method: 'HEAD' }), env);
  assert.equal(head.status, 200);
  assert.equal(head.headers.get('content-length'), String(pd.gzip_bytes));
  for (const p of pd.parts) assert.ok(statSync(join(DIST, ...p.split('/'))).size <= 25 * 1024 * 1024 * 0.7, p + ' is under 70 percent of the asset limit');
  const limited = await call('/data/fshy-public.sqlite.gz', {}, { ...env, RL_API: denyAll });
  assert.equal(limited.res.status, 429);
});

test('the download answers If-None-Match with 304 and one Range with 206, and sends the whole file otherwise', async (t) => {
  if (!MANIFEST.public_db || !MANIFEST.public_db.parts) { t.skip('no parts of the public store in ' + DIST); return; }
  const pd = MANIFEST.public_db;
  assert.ok(pd.part_bytes > 0, 'the build writes the size of a part into the manifest');
  const whole = Buffer.concat(pd.parts.map((p) => readFileSync(join(DIST, ...p.split('/')))));
  assert.equal(whole.length, pd.gzip_bytes);
  assert.ok(pd.parts.length > 1, 'the range tests cross a part');
  const URL_ = ORIGIN + '/data/fshy-public.sqlite.gz';
  const etag = '"' + pd.gzip_sha256 + '"';
  const get = (headers, method = 'GET') => worker.fetch(new Request(URL_, { method, headers }), env, { waitUntil() {} });

  // If-None-Match: a match is 304 with no body and no length of the file
  for (const inm of [etag, 'W/' + etag, '"other", ' + etag, '*']) {
    const r = await get({ 'if-none-match': inm });
    assert.equal(r.status, 304, inm);
    assert.equal((await r.arrayBuffer()).byteLength, 0);
    assert.equal(r.headers.get('etag'), etag);
    assert.equal(r.headers.get('content-length'), null, 'a 304 names no length of the body');
    assert.equal(r.headers.get('cache-control'), 'public, max-age=300');
    assert.equal(r.headers.get('access-control-allow-origin'), '*');
    assert.equal(r.headers.get('x-fshy-commit'), MANIFEST.commit);
  }
  const head304 = await get({ 'if-none-match': etag }, 'HEAD');
  assert.equal(head304.status, 304);
  const stale = await get({ 'if-none-match': '"0000"' });
  assert.equal(stale.status, 200, 'a tag that does not match gets the file');
  assert.equal(stale.headers.get('accept-ranges'), 'bytes');
  await stale.body.cancel();
  // the 304 costs a limit unit, and a refused request is 429 before it
  assert.equal((await worker.fetch(new Request(URL_, { headers: { 'if-none-match': etag } }), { ...env, RL_API: denyAll })).status, 429);

  // Range: [header, start, end] of the expected bytes
  const P = pd.part_bytes;
  const T = pd.gzip_bytes;
  const cases = [
    ['bytes=0-99', 0, 99], ['bytes=5-5', 5, 5], ['bytes=100-', 100, T - 1], ['bytes=-50', T - 50, T - 1], ['bytes=-' + (T + 10), 0, T - 1],
    [`bytes=${P - 10}-${P + 9}`, P - 10, P + 9], [`bytes=${P}-${P + 4}`, P, P + 4], [`bytes=${P - 1}-${P - 1}`, P - 1, P - 1],
    [`bytes=0-${T + 1000}`, 0, T - 1], [`bytes=${T - 1}-`, T - 1, T - 1],
  ];
  for (const [header, a, b] of cases) {
    const r = await get({ range: header });
    assert.equal(r.status, 206, header);
    assert.equal(r.headers.get('content-range'), `bytes ${a}-${b}/${T}`, header);
    assert.equal(r.headers.get('content-length'), String(b - a + 1), header);
    assert.equal(r.headers.get('etag'), etag);
    const body = Buffer.from(await r.arrayBuffer());
    assert.ok(body.equals(whole.subarray(a, b + 1)), header + ': the bytes are the bytes of the file');
  }
  // past the end, and a suffix of nothing: 416 with the length
  for (const header of [`bytes=${T}-`, `bytes=${T + 5}-${T + 9}`, 'bytes=-0']) {
    const r = await get({ range: header });
    assert.equal(r.status, 416, header);
    assert.equal(r.headers.get('content-range'), `bytes */${T}`);
    assert.equal((await r.arrayBuffer()).byteLength, 0);
  }
  // a list of ranges, another unit, and a range that is not valid are ignored: 200 and the whole length
  for (const header of ['bytes=0-1,5-9', 'items=0-1', 'bytes=9-1', 'bytes=-', 'bytes=a-b', 'nonsense']) {
    const r = await get({ range: header });
    assert.equal(r.status, 200, header);
    assert.equal(r.headers.get('content-length'), String(T));
    await r.body.cancel();
  }
  // If-Range: the tag of this version keeps the range, any other value gives the whole file
  const keep = await get({ range: 'bytes=0-9', 'if-range': etag });
  assert.equal(keep.status, 206);
  await keep.arrayBuffer();
  const drop = await get({ range: 'bytes=0-9', 'if-range': '"0000"' });
  assert.equal(drop.status, 200);
  await drop.body.cancel();
  // HEAD names the length and the ranges that it accepts, whatever Range says
  const head = await get({ range: 'bytes=0-9' }, 'HEAD');
  assert.equal(head.status, 200);
  assert.equal(head.headers.get('content-length'), String(T));
  assert.equal(head.headers.get('accept-ranges'), 'bytes');
  // a manifest without part_bytes, as an older build wrote it, still sends the whole file
  const was = pd.part_bytes;
  delete pd.part_bytes;
  try {
    const r = await get({ range: 'bytes=0-9' });
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('accept-ranges'), null);
    await r.body.cancel();
  } finally {
    pd.part_bytes = was;
  }
  const http = await import('../http.js');
  assert.deepEqual(http.parseRange('bytes=2-4', 10), { start: 2, end: 4 });
  assert.deepEqual(http.parseRange('bytes=8-', 10), { start: 8, end: 9 });
  assert.deepEqual(http.parseRange('bytes=-3', 10), { start: 7, end: 9 });
  assert.equal(http.parseRange('bytes=10-', 10), 'unsatisfiable');
  assert.equal(http.parseRange('bytes=1-2,4-5', 10), null);
  assert.equal(http.etagMatches('"a", W/"b"', '"b"'), true);
  assert.equal(http.etagMatches('"a"', '"b"'), false);
});

test('a provider with many records has a page for each record, and /r/ goes there', async () => {
  const { getStore } = await import('../db.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  const n = store.db.exec("SELECT count(*) FROM record WHERE eid = 'hetzner'")[0].values[0][0];
  store.manifest.record_pages_over = n - 1;
  store.cache.recordCounts = null;
  try {
    const r = await call('/r/storage/hetzner-storage-box');
    assert.equal(r.res.status, 301);
    assert.equal(r.res.headers.get('location'), ORIGIN + '/p/hetzner/storage--hetzner-storage-box/');
  } finally {
    delete store.manifest.record_pages_over;
    store.cache.recordCounts = null;
  }
});

test('self-hosted last: every list of the API, the MCP tools and the static files puts each self-hosted row after every hosted row', async (t) => {
  const { getStore } = await import('../db.js');
  const { store } = await getStore(env, globalThis.__fshyWasm);
  const q = (sql) => (store.db.exec(sql)[0] || { values: [] }).values;
  const sh = new Set(q('SELECT rid FROM record WHERE self_hosted = 1').map((r) => r[0]));
  if (!sh.size) {
    // CI runs this file a second time on a copy of data/ with self-hosted records (publish/fixture_selfhosted.py)
    assert.notEqual(process.env.FSHY_SELF_HOSTED, 'required', 'FSHY_SELF_HOSTED=required, and the store has no self-hosted record');
    t.skip('the store has no self-hosted record (data of schema_version 1)');
    return;
  }
  const after = (rids, what) => {
    let first = null;
    for (const rid of rids) {
      if (sh.has(rid)) first = first || rid;
      else assert.equal(first, null, `${what}: the hosted row ${rid} is below the self-hosted row ${first}`);
    }
    return rids.filter((r) => sh.has(r)).length;
  };
  // search: the whole list splits, name hits and text hits alike; the card says yes or no
  const s = await call('/api/v1/search?q=self-hosted&limit=50');
  assert.equal(s.res.status, 200, s.body);
  const si = s.json.columns.indexOf('self_hosted');
  assert.equal(si, s.json.columns.indexOf('verdict') + 1, 'self_hosted follows verdict in a card');
  for (const r of s.json.rows) assert.equal(r[si], sh.has(r[0]) ? 'yes' : 'no', r[0]);
  const all = [];
  for (let off = 0; off < s.json.total && off < 400; off += 50) {
    all.push(...(await call('/api/v1/search?q=self-hosted&limit=50&offset=' + off)).json.rows.map((r) => r[0]));
  }
  assert.ok(after(all, 'search') > 0 && all.length > after(all, 'search'), 'the query finds hosted and self-hosted records');
  assert.ok(s.json.notes.some((n) => /^self-hosted: \d+ records, listed after every hosted record$/.test(n)), s.json.notes.join('; '));
  // a name hit of a provider whose every record is self-hosted is below every hosted text hit
  const [[eid, name]] = q('SELECT e.eid, e.name FROM entity e WHERE e.eid IN (SELECT eid FROM record GROUP BY eid ' +
    'HAVING min(self_hosted) = 1) ORDER BY e.n_records DESC, e.eid LIMIT 1');
  const byName = await call('/api/v1/search?limit=50&q=' + encodeURIComponent(name));
  after(byName.json.rows.map((r) => r[0]), 'search by the name ' + name);
  const es = await call('/api/v1/entity-search?limit=50&q=' + encodeURIComponent(name));
  const allSelf = new Set(q('SELECT eid FROM record GROUP BY eid HAVING min(self_hosted) = 1').map((r) => r[0]));
  let seen = false;
  for (const r of es.json.rows) {
    if (allSelf.has(r[0])) seen = true;
    else assert.ok(!seen, 'entity-search: the entity ' + r[0] + ' is below an entity whose every record is self-hosted');
  }
  assert.ok(es.json.rows.some((r) => r[0] === eid), 'entity-search finds ' + eid);
  // a vendor ranks by the best verdict of its hosted records: its self-hosted record never lifts it (rank.bestVorder)
  const bestRule = '(SELECT coalesce(min(CASE WHEN r.self_hosted = 0 THEN r.vorder END), min(r.vorder)) FROM record r WHERE r.eid = e.eid)';
  assert.deepEqual(q(`SELECT e.eid FROM entity e WHERE e.best_vorder IS NOT ${bestRule}`), [], 'entity.best_vorder follows the hosted records');
  const lifted = q('SELECT eid, min(CASE WHEN self_hosted = 0 THEN vorder END) AS h FROM record GROUP BY eid HAVING ' +
    'min(self_hosted) = 0 AND min(CASE WHEN self_hosted = 1 THEN vorder END) < min(CASE WHEN self_hosted = 0 THEN vorder END) ORDER BY eid');
  assert.ok(lifted.length > 0, 'the store has a vendor whose self-hosted record has a better verdict than its hosted ones');
  for (const [le, h] of lifted) {
    const [[lname]] = q(`SELECT name FROM entity WHERE eid = '${le}'`);
    const r = await call('/api/v1/entity-search?limit=50&q=' + encodeURIComponent(lname));
    const [bi, sci] = ['best_vorder', 'score'].map((c) => r.json.columns.indexOf(c));
    const row = r.json.rows.find((x) => x[0] === le);
    assert.ok(row, 'entity-search ' + lname + ' finds ' + le);
    assert.equal(row[bi], h, 'entity-search gives ' + le + ' the best verdict of its hosted records');
    for (let i = 1; i < r.json.rows.length; i++) {
      const [a, b] = [r.json.rows[i - 1], r.json.rows[i]];
      if (a[sci] === b[sci] && allSelf.has(a[0]) === allSelf.has(b[0])) {
        assert.ok(a[bi] <= b[bi], `entity-search ${lname}: ${a[0]} (${a[bi]}) is above ${b[0]} (${b[bi]}) with the same score`);
      }
    }
  }
  // the case that showed the defect: the self-hosted OpenList software ranked its vendor above a hosted public instance
  if (q("SELECT count(*) FROM entity WHERE eid IN ('chirmyram', 'github-openlistteam')")[0][0] === 2 &&
    allSelf.has('github-openlistteam') && !allSelf.has('chirmyram')) {
    const ol = (await call('/api/v1/entity-search?limit=50&q=openlist')).json.rows.map((r) => r[0]);
    assert.ok(ol.includes('chirmyram') && ol.indexOf('chirmyram') < ol.indexOf('github-openlistteam'), 'openlist: ' + ol.slice(0, 6).join(', '));
  }
  // a name lookup gives one entity: the exact name of a self-hosted vendor wins over a fuzzy or prefix match of a hosted
  // vendor that the name search lists first (rank.resolveEntity); a hosted entity wins only a tie
  let lookups = 0;
  for (const [se, sname] of q('SELECT e.eid, e.name FROM entity e WHERE e.eid IN (SELECT eid FROM record GROUP BY eid ' +
    'HAVING min(self_hosted) = 1) ORDER BY e.eid LIMIT 400')) {
    const list = (await call('/api/v1/entity-search?limit=50&q=' + encodeURIComponent(sname))).json;
    const [sc, mt] = ['score', 'match'].map((c) => list.columns.indexOf(c));
    const mine = list.rows.find((r) => r[0] === se);
    if (!mine || mine[mt] !== 'exact' || list.rows[0][0] === se) continue;
    // the first entity with the best score, in the order of the list: a hosted entity that ties comes first, and wins
    const top = Math.max(...list.rows.map((r) => r[sc]));
    if (list.rows.find((r) => r[sc] === top)[0] !== se) continue;
    const m = await rpc('tools/call', { name: 'entity', arguments: { name: sname } });
    const lines = m.json.result.content[0].text.split('\n');
    assert.ok(lines.some((l) => l.startsWith('# entity ' + se + ': ')),
      `MCP entity ${JSON.stringify(sname)} resolves to ${se}, not to the first of ${list.rows.slice(0, 3).map((r) => r[0]).join(', ')}`);
    assert.ok(lines.includes('# self-hosted: every record of this entity is self-hosted, so it is the last resort'), lines.join('\n'));
    lookups++;
  }
  assert.ok(lookups > 0, 'a self-hosted vendor whose exact name is listed below a hosted match of the name search');
  if (allSelf.has('coder')) {
    const c = await rpc('tools/call', { name: 'entity', arguments: { name: 'coder' } });
    assert.ok(c.json.result.content[0].text.split('\n').some((l) => l.startsWith('# entity coder: ')), 'MCP entity coder resolves to coder');
  }
  // filter: page by page, a page boundary inside the hosted part included
  const [[topic, grp]] = q('SELECT topic, grp FROM record WHERE duplicate_of IS NULL GROUP BY topic, grp HAVING ' +
    'sum(self_hosted) > 0 AND sum(self_hosted) < count(*) AND count(*) <= 200 ORDER BY sum(self_hosted) DESC, topic, grp LIMIT 1');
  const f = await call(`/api/v1/records?topic=${topic}&grp=${grp}&limit=200`);
  const fr = f.json.rows.map((r) => r[0]);
  assert.ok(after(fr, 'filter') > 0);
  const nh = fr.length - fr.filter((r) => sh.has(r)).length;
  const p2 = await call(`/api/v1/records?topic=${topic}&grp=${grp}&limit=4&offset=${nh - 2}`);
  assert.deepEqual(p2.json.rows.map((r) => r[0]), fr.slice(nh - 2, nh + 2), 'a page that spans the split keeps the order');
  const desc = await call(`/api/v1/records?topic=${topic}&grp=${grp}&limit=200&sort=usd_month&order=desc`);
  after(desc.json.rows.map((r) => r[0]), 'filter by usd_month descending');
  assert.ok(f.json.notes.some((n) => /^self-hosted: \d+ records/.test(n)));
  // need: hosted ranked, hosted with no number, then the self-hosted rows apart
  const needs = JSON.parse(readFileSync(join(REPO, 'publish', 'rules', 'needs.json'), 'utf8')).needs;
  let withSelf = 0;
  for (const x of needs) {
    const n = await call(`/api/v1/need/${x.id}?limit=200`);
    assert.equal(n.res.status, 200, n.body);
    for (const r of [...n.json.rows, ...n.json.null_rows, ...(n.json.unstated_rows || [])]) assert.ok(!sh.has(r[0]), x.id + ': ' + r[0] + ' is self-hosted');
    for (const r of n.json.self_hosted_rows) assert.ok(sh.has(r[0]), x.id + ': ' + r[0] + ' is hosted');
    if (n.json.self_hosted_rows.length) {
      withSelf++;
      const tsv = await call(`/api/v1/need/${x.id}.tsv?limit=200`);
      assert.match(tsv.body, /\n# self-hosted, the last resort: \d+ rows below, after every hosted row\n/);
      const shown = n.json.rows.length + n.json.null_rows.length + (n.json.unstated_rows || []).length + n.json.self_hosted_rows.length;
      assert.match(tsv.body, new RegExp(`# ${shown} of `));
      // the self-hosted rows come after every other part of the TSV
      const body = tsv.body.split('# self-hosted, the last resort:')[0];
      for (const r of n.json.self_hosted_rows) assert.ok(!body.includes('\n' + r[0] + '\t'), x.id + ': ' + r[0] + ' is above the self-hosted part');
    }
  }
  assert.ok(withSelf > 0, 'a need lists self-hosted rows');
  // entity (MCP), worklists, and the static entity file
  const [[mixed]] = q('SELECT eid FROM record GROUP BY eid HAVING min(self_hosted) = 0 AND max(self_hosted) = 1 ORDER BY eid LIMIT 1');
  const e = await rpc('tools/call', { name: 'entity', arguments: { id: mixed } });
  after(e.json.result.content[0].text.split('\n').filter((l) => l && !l.startsWith('#')).slice(1).map((l) => l.split('\t')[0]), 'entity ' + mixed);
  for (const kind of ['stale', 'unparsed']) {
    const base = `/api/v1/worklist/${kind}?topic=${topic}&as_of=2099-01-01`;
    const total = (await call(base + '&limit=1')).json.total;
    const w = await call(base + `&limit=200&offset=${Math.max(0, total - 200)}`);
    assert.ok(after(w.json.rows.map((r) => r[0]), 'worklist ' + kind) > 0, 'worklist ' + kind + ' ends with self-hosted rows');
  }
  // drift: a pair of records, sorted on the self_hosted of its subject first
  const drift = [];
  const dTotal = (await call('/api/v1/worklist/drift?limit=1')).json.total;
  for (let off = 0; off < dTotal; off += 200) drift.push(...(await call('/api/v1/worklist/drift?limit=200&offset=' + off)).json.rows);
  assert.equal(drift.length, dTotal);
  after(drift.map((r) => r[1]), 'worklist drift');
  if (HAVE_DIST) {
    const ef = await call(`/api/v1/entity/${mixed}.json`);
    after(ef.json.records.map((r) => r.rid), 'the entity file of ' + mixed);
    const nm = (await call('/api/v1/names.json')).json;
    const row = nm.find((r) => r[0] === eid);
    assert.equal(row[8], 1, 'names.json marks a provider whose every record is self-hosted');
    const best = q(`SELECT min(vorder) FROM record WHERE eid = '${mixed}' AND self_hosted = 0`)[0][0];
    assert.equal(nm.find((r) => r[0] === mixed)[5], best, 'names.json gives a mixed provider the verdict of its hosted records');
    assert.equal(nm.find((r) => r[0] === mixed).length, 8);
  }
  const ins = await rpc('initialize', { protocolVersion: '2025-06-18' });
  assert.match(ins.json.result.instructions, /self-hosted record .* is the last resort/);
});

test('the vendored MiniSearch is the npm package of package.json (P-18)', () => {
  const pkg = JSON.parse(readFileSync(join(SITE, 'package.json'), 'utf8'));
  const vendored = readFileSync(join(SITE, 'static', 'assets', 'minisearch.js'), 'utf8').split('\n');
  const npm = readFileSync(join(SITE, 'node_modules', 'minisearch', 'dist', 'umd', 'index.js'), 'utf8').replace(/\n\/\/# sourceMappingURL=\S+\n?$/, '\n');
  assert.match(vendored[0], new RegExp('^/\\* MiniSearch ' + pkg.dependencies.minisearch.replace(/\./g, '\\.') + ', MIT licence'),
    'the header names the version of package.json');
  assert.equal(vendored.slice(1).join('\n'), npm, 'site/static/assets/minisearch.js is dist/umd/index.js of that version: copy it after an update');
});

test('the Worker module exports its handler only: workerd reads a named export as an entrypoint', async () => {
  assert.deepEqual(Object.keys(await import('../index.js')), ['default']);
});

test('report', () => {
  for (const [k, v] of Object.entries(timings)) console.log('# ' + k + ': ' + (typeof v === 'number' ? v.toFixed(1) : JSON.stringify(v)));
});
