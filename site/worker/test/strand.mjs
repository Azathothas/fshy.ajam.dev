// Test on workerd of a load whose request ended (issue #26): starts `wrangler dev` with the configuration of
// wrangler.jsonc and the entry point strand.js, ends a request while the store loads, and checks that the next
// requests answer. On the code before the fix, they waited for ever, and so did every later request of the isolate.
//
// wrangler dev does not cancel a request when its client goes away, so the request ends by an early answer instead
// (strand.js). The runtime drops its continuations in the same way.
//
//   node site/worker/test/strand.mjs            port 8792, or FSHY_STRAND_PORT
//
// Needs site/dist and `npm ci` in site/. Exit 0 when every answer is right, 1 when one is wrong, 2 when wrangler does
// not start.

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const PORT = Number(process.env.FSHY_STRAND_PORT || 8792);
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
const { LOAD_WAIT_MS = 10000 } = await import('../db.js');

// wrangler.jsonc with another name and entry point. The file goes in site/.wrangler/, which git ignores, so the paths
// in it start from there.
const config = JSON.parse(readFileSync(join(SITE, 'wrangler.jsonc'), 'utf8').replace(/^\s*\/\/.*$/gm, ''));
delete config.$schema;
config.name = 'fshy-strand-test';
config.main = '../worker/test/strand.js';
config.assets.directory = '../dist';
mkdirSync(join(SITE, '.wrangler'), { recursive: true });
const CONFIG = join(SITE, '.wrangler', 'strand.jsonc');
writeFileSync(CONFIG, JSON.stringify(config, null, 2) + '\n');

const STATE = mkdtempSync(join(tmpdir(), 'fshy-strand-'));
const child = spawn(process.execPath, [WRANGLER, 'dev', '--config', CONFIG, '--port', String(PORT), '--persist-to', STATE], {
  cwd: SITE,
  env: { ...process.env, WRANGLER_SEND_METRICS: 'false', NO_COLOR: '1' },
  stdio: ['ignore', 'pipe', 'pipe'],
  detached: process.platform !== 'win32',
});
let log = '';
child.stdout.on('data', (b) => { log += b; });
child.stderr.on('data', (b) => { log += b; });
console.log(`# wrangler dev started, PID ${child.pid}, ${ORIGIN}, LOAD_WAIT_MS ${LOAD_WAIT_MS}`);

let stopped = false;
function stop() {
  if (stopped || child.exitCode !== null) return;
  stopped = true;
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already gone */ }
  console.log(`# stopped PID ${child.pid}`);
}
process.on('exit', stop);

async function finish(code) {
  stop();
  rmSync(CONFIG, { force: true });
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

/** {status, ms, timing}, or {status: 'no answer', ms} when no answer comes in `timeout` ms. */
async function ask(path, headers = {}, timeout = LOAD_WAIT_MS + 15000) {
  const t0 = performance.now();
  try {
    const res = await fetch(ORIGIN + path, { headers, signal: AbortSignal.timeout(timeout) });
    await res.arrayBuffer();
    return { status: res.status, ms: Math.round(performance.now() - t0), timing: res.headers.get('server-timing') || '' };
  } catch {
    return { status: 'no answer', ms: Math.round(performance.now() - t0), timing: '' };
  }
}

if (!(await ready(120000))) {
  console.error('wrangler dev did not answer on ' + ORIGIN + '\n' + log.slice(-3000));
  await finish(2);
}

// 1. the request that starts the load ends, and the runtime drops the load with it: the requests that wait on it give
// up after LOAD_WAIT_MS and load the store again
const drop = await ask('/api/v1/records?limit=1', { 'x-fshy-strand': 'drop' });
check('a request that starts the load and ends at once answers 202', drop.status === 202, JSON.stringify(drop));
const waiters = await Promise.all(['/api/v1/records?limit=1', '/api/v1/search?q=hetzner&limit=1'].map((p) => ask(p)));
for (const [i, w] of waiters.entries()) {
  check(`waiter ${i + 1} on the dropped load answers 200`, w.status === 200, JSON.stringify(w));
}
check('the waiters waited for LOAD_WAIT_MS, so the dropped load did stop (else this test proves nothing)',
  waiters.every((w) => w.ms >= LOAD_WAIT_MS - 2000), JSON.stringify(waiters));
const after = await ask('/api/v1/records?limit=1', {}, 5000);
check('the next request answers 200 from the open store', after.status === 200 && !/cold load/.test(after.timing), JSON.stringify(after));

// 2. the request that starts the load passes it to ctx.waitUntil(): the load completes after the request ends
const reset = await ask('/api/v1/records?limit=1', { 'x-fshy-strand': 'reset' }, 5000);
check('the open store closes', reset.status === 204, JSON.stringify(reset));
const keep = await ask('/api/v1/records?limit=1', { 'x-fshy-strand': 'keep' });
check('a request that starts the load with its ctx and ends at once answers 202', keep.status === 202, JSON.stringify(keep));
const next = await ask('/api/v1/records?limit=1', {}, 5000);
check('the next request answers 200 in 5 s from the store of that load', next.status === 200 && !/cold load/.test(next.timing),
  JSON.stringify(next));

console.log(`# dropped load: the waiters answered in ${waiters.map((w) => w.ms).join(' and ')} ms, the next request in ${after.ms} ms`);
console.log(`# kept load: the next request answered in ${next.ms} ms`);
if (/had hung/.test(log)) console.log('# note: the runtime reported a request that had hung');
console.log(`${fails.length ? 'FAIL' : 'PASS'}: ${fails.length} failed`);
await finish(fails.length ? 1 : 0);
