// Smoke test of the Worker on workerd: starts `wrangler dev` on the built site, asks the API, the SQL route, the
// MCP endpoint, the route patterns of wrangler.jsonc and the download of the public store, and stops wrangler by the
// PID it started. The node tests (run.mjs) fake the bindings; this test runs the real assets binding and the real
// rate limiting binding together, from an empty local state directory, as on a fresh clone.
//
// When `npx wrangler dev` starts from a console with an empty state, the local rate limiter can throw "internal
// error". A process that node starts did not show it, so this test can pass where that bug is. run.mjs tests a
// limiter that throws.
//
//   node site/worker/test/smoke.mjs            port 8791, or FSHY_SMOKE_PORT
//
// Needs site/dist (python publish/build.py --site site/dist) and `npm ci` in site/. No Cloudflare account:
// wrangler dev runs locally. Exit 0 when every answer is right, 1 when one is wrong, 2 when wrangler does not start.

import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PORT = Number(process.env.FSHY_SMOKE_PORT || 8791);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const WRANGLER = join(SITE, 'node_modules', 'wrangler', 'bin', 'wrangler.js');

if (!existsSync(join(SITE, 'dist', 'data', 'manifest.json'))) {
  console.error('no site/dist; build it with python publish/build.py --site site/dist');
  process.exit(2);
}
if (!existsSync(WRANGLER)) {
  console.error('no wrangler; run npm ci in site/');
  process.exit(2);
}

const STATE = mkdtempSync(join(tmpdir(), 'fshy-smoke-'));
// the command of site/README.md; only the port and the state directory differ
const child = spawn(process.execPath, [WRANGLER, 'dev', '--port', String(PORT), '--persist-to', STATE], {
  cwd: SITE,
  env: { ...process.env, WRANGLER_SEND_METRICS: 'false', NO_COLOR: '1' },
  stdio: ['ignore', 'pipe', 'pipe'],
  detached: process.platform !== 'win32',
});
let log = '';
child.stdout.on('data', (b) => { log += b; });
child.stderr.on('data', (b) => { log += b; });
console.log(`# wrangler dev started, PID ${child.pid}, ${ORIGIN}`);

let stopped = false;
function stop() {
  if (stopped || child.exitCode !== null) return;
  stopped = true;
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already gone */ }
  console.log(`# stopped PID ${child.pid}`);
}
process.on('exit', stop);

/** Stop wrangler, then remove the state directory. workerd releases its files a moment after it stops. */
async function finish(code) {
  stop();
  for (let i = 0; i < 40; i++) {
    try {
      rmSync(STATE, { recursive: true, force: true });
      break;
    } catch {
      if (i === 39) console.log('# could not remove ' + STATE);
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  process.exit(code);
}

async function ready(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (child.exitCode !== null) return false;
    try {
      if ((await fetch(ORIGIN + '/llms.txt')).ok) return true;
    } catch { /* not listening yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

const fails = [];
function check(name, cond, detail = '') {
  if (!cond) fails.push(name);
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${!cond && detail ? '\n     ' + String(detail).slice(0, 400) : ''}`);
}

if (!(await ready(120000))) {
  console.error('wrangler dev did not answer on ' + ORIGIN + '\n' + log.slice(-3000));
  await finish(2);
}
const page = await fetch(ORIGIN + '/');
check('GET / is a static page', page.status === 200);
check('GET / carries the Content-Security-Policy of _headers', /default-src 'self'/.test(page.headers.get('content-security-policy') || ''),
  page.headers.get('content-security-policy'));
const plan = await fetch(ORIGIN + '/api/v1/sql?q=' + encodeURIComponent('SELECT count(*) FROM record a LEFT JOIN record b ON a.rno <> b.rno'));
check('GET /api/v1/sql refuses a LEFT JOIN of two large scans with 400', plan.status === 400, plan.status);
const hexed = await fetch(ORIGIN + '/api/v1/sql?q=' + encodeURIComponent('SELECT length(hex(hex(group_concat(summary)))) FROM record'));
check('GET /api/v1/sql refuses a function that is not on the list with 400', hexed.status === 400, hexed.status);
// the heap limit of db.js on workerd: a value that doubles past it is refused, and the store answers after it
let doubled = 'SELECT group_concat(summary) AS s FROM record';
for (let i = 0; i < 7; i++) doubled = 'SELECT s || s AS s FROM (' + doubled + ')';
const oom = await fetch(ORIGIN + '/api/v1/sql?q=' + encodeURIComponent('SELECT length(s) FROM (' + doubled + ')'));
const oj = await oom.json().catch(() => null);
check('GET /api/v1/sql refuses a value over the heap limit with 400', oom.status === 400 && oj && /needs more than/.test(oj.error),
  `${oom.status} ${JSON.stringify(oj)}`);
const search = await fetch(ORIGIN + '/api/v1/search?q=hetzner&limit=3');
const sj = await search.json().catch(() => null);
check('GET /api/v1/search answers 200 with rows', search.status === 200 && sj && sj.rows && sj.rows.length > 0, `${search.status} ${JSON.stringify(sj)}`);
const sql = await fetch(ORIGIN + '/api/v1/sql?q=' + encodeURIComponent('SELECT count(*) AS n FROM record'));
const qj = await sql.json().catch(() => null);
check('GET /api/v1/sql answers 200', sql.status === 200 && qj && qj.rows && qj.rows[0][0] > 0, `${sql.status} ${JSON.stringify(qj)}`);
const mcp = await fetch(ORIGIN + '/mcp', {
  method: 'POST',
  headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
  body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
});
const mj = await mcp.json().catch(() => null);
check('POST /mcp tools/list answers 200 with tools', mcp.status === 200 && mj && mj.result && mj.result.tools.length > 0, `${mcp.status} ${JSON.stringify(mj)}`);
const call = await fetch(ORIGIN + '/mcp', {
  method: 'POST',
  headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
  body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'search', arguments: { q: 'hetzner', limit: 2 } } }),
});
const cj = await call.json().catch(() => null);
check('POST /mcp tools/call search answers 200', call.status === 200 && cj && cj.result && cj.result.isError === false, `${call.status} ${JSON.stringify(cj)}`);
const perm = await fetch(ORIGIN + '/r/storage/hetzner-storage-box', { redirect: 'manual' });
check('GET /r/<topic>/<slug> redirects', perm.status === 301, perm.status);

// run_worker_first in wrangler.jsonc: the Worker answers every path of /api/v1/ except the static files of the build
const root = await fetch(ORIGIN + '/api/v1/');
const rj = await root.json().catch(() => null);
check('GET /api/v1/ lists the routes as JSON', root.status === 200 && rj && rj.routes && rj.routes.length > 0, `${root.status} ${JSON.stringify(rj)}`);
const bare = await fetch(ORIGIN + '/api/v1');
check('GET /api/v1 lists the routes as JSON', bare.status === 200 && /json/.test(bare.headers.get('content-type') || ''), bare.status);
const unknown = await fetch(ORIGIN + '/api/v1/foo');
const uj = await unknown.json().catch(() => null);
check('GET /api/v1/foo is a JSON 404 that names the help', unknown.status === 404 && uj && /help\.txt/.test(uj.error), `${unknown.status} ${JSON.stringify(uj)}`);
const tsv = await fetch(ORIGIN + '/api/v1/records.tsv?limit=2');
check('GET /api/v1/records.tsv answers TSV', tsv.status === 200 && /tab-separated/.test(tsv.headers.get('content-type') || ''), tsv.status);
for (const p of ['/api/v1/names.json', '/api/v1/entity/hetzner.json', '/api/v1/help.txt']) {
  const s = await fetch(ORIGIN + p);
  await s.arrayBuffer();
  check('GET ' + p + ' is a static file, served without the Worker', s.status === 200 && !s.headers.get('server-timing'), `${s.status} ${s.headers.get('server-timing')}`);
}
const bad = await fetch(ORIGIN + '/api/v1/need/%E0%A4%A');
check('GET /api/v1/need/%E0%A4%A is a 400, not a 500', bad.status === 400, bad.status);

// the public store: one URL joins the parts that the manifest names
const man = JSON.parse(readFileSync(join(SITE, 'dist', 'data', 'manifest.json'), 'utf8'));
const dl = await fetch(ORIGIN + '/data/fshy-public.sqlite.gz');
const db = Buffer.from(await dl.arrayBuffer());
check('GET /data/fshy-public.sqlite.gz joins the parts into the file of the manifest',
  dl.status === 200 && db.length === man.public_db.gzip_bytes && createHash('sha256').update(db).digest('hex') === man.public_db.gzip_sha256,
  `${dl.status} ${db.length} of ${man.public_db.gzip_bytes}`);
const dh = await fetch(ORIGIN + '/data/fshy-public.sqlite.gz', { method: 'HEAD' });
check('HEAD /data/fshy-public.sqlite.gz gives the length', dh.status === 200 && dh.headers.get('content-length') === String(man.public_db.gzip_bytes),
  `${dh.status} ${dh.headers.get('content-length')}`);
// a matching If-None-Match is 304 with no body; one Range is 206 with that range of the joined file, also across the
// border of two parts; a range past the end is 416
const FILE = ORIGIN + '/data/fshy-public.sqlite.gz';
const total = man.public_db.gzip_bytes;
const part = man.public_db.part_bytes;
const nm = await fetch(FILE, { headers: { 'if-none-match': '"' + man.public_db.gzip_sha256 + '"' } });
check('GET /data/fshy-public.sqlite.gz with a matching If-None-Match is 304 with no body',
  nm.status === 304 && (await nm.arrayBuffer()).byteLength === 0, nm.status);
for (const [header, a, b] of [['bytes=0-99', 0, 99], [`bytes=${part - 10}-${part + 9}`, part - 10, part + 9], ['bytes=-50', total - 50, total - 1]]) {
  const r = await fetch(FILE, { headers: { range: header } });
  const bytes = Buffer.from(await r.arrayBuffer());
  check('GET /data/fshy-public.sqlite.gz with Range ' + header + ' is 206 and the bytes of the file',
    r.status === 206 && r.headers.get('content-range') === `bytes ${a}-${b}/${total}` && bytes.equals(db.subarray(a, b + 1)),
    `${r.status} ${r.headers.get('content-range')} ${bytes.length}`);
}
const past = await fetch(FILE, { headers: { range: `bytes=${total}-` } });
check('GET /data/fshy-public.sqlite.gz with a Range past the end is 416', past.status === 416 && past.headers.get('content-range') === `bytes */${total}`, past.status);
const batch = await fetch(ORIGIN + '/mcp', {
  method: 'POST',
  headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
  body: JSON.stringify([1, 2, 3, 4, 5, 6].map((id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'help', arguments: {} } }))),
});
check('POST /mcp refuses a batch of 6 messages with 400', batch.status === 400, batch.status);
const sqlBatch = await fetch(ORIGIN + '/mcp', {
  method: 'POST',
  headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
  body: JSON.stringify([1, 2].map((id) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'sql', arguments: { query: 'SELECT 1' } } }))),
});
const sqlJson = await sqlBatch.json().catch(() => null);
check('POST /mcp refuses a batch of 2 sql calls with 400 and a JSON-RPC error',
  sqlBatch.status === 400 && sqlJson && sqlJson.error && sqlJson.error.code === -32600 && /at most 1 sql call;/.test(sqlJson.error.message),
  `${sqlBatch.status} ${JSON.stringify(sqlJson)}`);
// _headers: a text file carries its charset, and the immutable data parts get one Cache-Control, not two
for (const [path, type] of [['/llms.txt', 'text/plain; charset=utf-8'], ['/t/storage.md', 'text/markdown; charset=utf-8'],
  ['/api/v1/help.txt', 'text/plain; charset=utf-8'], ['/index.md', 'text/markdown; charset=utf-8']]) {
  const r = await fetch(ORIGIN + path);
  await r.arrayBuffer();
  check('GET ' + path + ' is served as ' + type, (r.headers.get('content-type') || '').toLowerCase() === type, r.headers.get('content-type'));
}
const dataPart = await fetch(ORIGIN + '/' + man.public_db.parts[0]);
await dataPart.arrayBuffer();
check('GET a data part has one Cache-Control of a year', dataPart.headers.get('cache-control') === 'public, max-age=31536000, immutable', dataPart.headers.get('cache-control'));
const hp = await fetch(ORIGIN + '/');
await hp.arrayBuffer();
check('GET / carries Permissions-Policy and Cross-Origin-Opener-Policy', /camera=\(\)/.test(hp.headers.get('permissions-policy') || '') &&
  hp.headers.get('cross-origin-opener-policy') === 'same-origin', hp.headers.get('permissions-policy'));
const tp = await fetch(ORIGIN + '/api/v1/records?topic=nope');
check('GET /api/v1/records with an unknown topic is a 400', tp.status === 400, tp.status);
const icon = await fetch(ORIGIN + '/favicon.ico');
check('GET /favicon.ico is an icon', icon.status === 200 && (await icon.arrayBuffer()).byteLength < 300, icon.status);

if (/rate limiter \S+ failed/.test(log)) console.log('# note: the local rate limiter threw, and the Worker allowed the request');
console.log(`${fails.length ? 'FAIL' : 'PASS'}: ${fails.length} failed`);
await finish(fails.length ? 1 : 0);
