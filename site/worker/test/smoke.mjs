// Smoke test of the Worker on workerd: starts `wrangler dev` on the built site, asks the API, the SQL route
// and the MCP endpoint once each, and stops wrangler by the PID it started. The node tests (run.mjs) fake the
// bindings; this test runs the real assets binding and the real rate limiting binding together, from an empty
// local state directory, as on a fresh clone.
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
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
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
  try { rmSync(STATE, { recursive: true, force: true }); } catch { /* workerd can hold a file for a moment */ }
}
process.on('exit', stop);

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
  stop();
  process.exit(2);
}
const page = await fetch(ORIGIN + '/');
check('GET / is a static page', page.status === 200);
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

stop();
if (/rate limiter \S+ failed/.test(log)) console.log('# note: the local rate limiter threw, and the Worker allowed the request');
console.log(`${fails.length ? 'FAIL' : 'PASS'}: ${fails.length} failed`);
process.exit(fails.length ? 1 : 0);
