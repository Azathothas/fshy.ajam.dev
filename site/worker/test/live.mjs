// Live check of the store routes, for the job deploy: no request may wait for an answer longer than the Worker allows.
//
//   node site/worker/test/live.mjs https://fshy.ajam.dev
//
// 1. 2 bursts of 8 requests to the store routes that the client abandons after 150 ms, as a client that times out
//    does. After a deploy, they start loads of the store in new isolates. Before the fix of issue #26, such a request left its isolate
//    with a load that never settled, and every later request of that isolate got no answer.
// 2. 3 bursts of 8 requests at the same time, then 16 requests one after another. Each request opens a new connection,
//    so the requests reach more isolates.
//
// A request of step 2 fails the check when no status arrives in LOAD_WAIT_MS (worker/db.js) plus 5 s, or when its
// status is not 200. A 429 is the rate limit of the Worker, not a fault, and is only counted. The two steps send 56
// requests, under the limit of 120 a minute. Exit 0 when every request answers, 1 when one does not, 2 on bad usage.

import http from 'node:http';
import https from 'node:https';

const origin = (process.argv[2] || '').replace(/\/+$/, '');
if (!/^https?:\/\/[^/]+$/.test(origin)) {
  console.error('usage: node site/worker/test/live.mjs ORIGIN');
  process.exit(2);
}
const { LOAD_WAIT_MS } = await import('../db.js');
const TIMEOUT_MS = LOAD_WAIT_MS + 5000;
const ABANDON_MS = 150;

const MCP = { 'content-type': 'application/json', accept: 'application/json, text/event-stream' };
const rpc = (method, params) => JSON.stringify({ jsonrpc: '2.0', id: 1, method, ...(params ? { params } : {}) });
// every route here opens the store; the query string differs on each request, so no cache answers it
const ROUTES = [
  (n) => ({ path: `/api/v1/search?q=storage&limit=1&n=${n}` }),
  (n) => ({ path: `/api/v1/records?limit=1&n=${n}` }),
  (n) => ({ path: `/api/v1/need/?n=${n}` }),
  (n) => ({ path: `/api/v1/entity-search?q=cloud&limit=1&n=${n}` }),
  (n) => ({ path: `/api/v1/worklist/stale?limit=1&n=${n}` }),
  (n) => ({ path: '/api/v1/sql?q=' + encodeURIComponent(`SELECT count(*) FROM record WHERE ${n} = ${n}`) }),
  () => ({ path: '/mcp', method: 'POST', headers: MCP, body: rpc('tools/list') }),
  (n) => ({ path: '/mcp', method: 'POST', headers: MCP, body: rpc('tools/call', { name: 'filter', arguments: { limit: 1, offset: n % 3 } }) }),
];

let sent = 0;
/** One request on a new connection: {status, ttfb, total, ray}. status is 'no answer' when none came in `ms`. */
function ask(ms) {
  const n = sent++;
  const spec = ROUTES[n % ROUTES.length](n);
  const url = new URL(origin + spec.path);
  const lib = url.protocol === 'https:' ? https : http;
  const t0 = performance.now();
  return new Promise((done) => {
    const out = { path: spec.method === 'POST' ? 'POST ' + spec.path + ' ' + JSON.parse(spec.body).method : spec.path };
    let finished = false;
    const end = (extra) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      done({ ...out, total: Math.round(performance.now() - t0), ...extra });
    };
    const req = lib.request(url, { method: spec.method || 'GET', headers: spec.headers, agent: false }, (res) => {
      out.status = res.statusCode;
      out.ttfb = Math.round(performance.now() - t0);
      out.ray = res.headers['cf-ray'] || '';
      res.on('data', () => {});
      res.on('end', () => end({}));
      res.on('error', () => end({ status: out.status, error: 'body cut' }));
    });
    const timer = setTimeout(() => {
      req.destroy();
      end(out.status ? { error: 'body cut' } : { status: 'no answer' });
    }, ms);
    req.on('error', (e) => end(out.status ? { error: 'body cut' } : { status: 'error', error: String(e.code || e.message) }));
    if (spec.body) req.write(spec.body);
    req.end();
  });
}

console.log(`# ${origin}: abandon 16 requests after ${ABANDON_MS} ms, then send 40; a request fails after ${TIMEOUT_MS} ms`);
const abandoned = [];
for (let b = 0; b < 2; b++) {
  abandoned.push(...await Promise.all(Array.from({ length: 8 }, () => ask(ABANDON_MS))));
  await new Promise((r) => setTimeout(r, 1000));
}
console.log(`# step 1: ${abandoned.filter((r) => r.status === 'no answer').length} of 16 abandoned before an answer`);

const results = [];
for (let b = 0; b < 3; b++) results.push(...await Promise.all(Array.from({ length: 8 }, () => ask(TIMEOUT_MS))));
for (let i = 0; i < 16; i++) results.push(await ask(TIMEOUT_MS));

let bad = 0;
let limited = 0;
for (const r of results) {
  const ok = r.status === 200 && !r.error;
  if (r.status === 429) limited++;
  else if (!ok) bad++;
  console.log(`${ok ? 'ok  ' : r.status === 429 ? '429 ' : 'FAIL'} ${String(r.status).padEnd(9)} ttfb ${String(r.ttfb ?? '-').padStart(5)} ms  total ${String(r.total).padStart(5)} ms  ${r.ray || '-'}  ${r.path}${r.error ? '  (' + r.error + ')' : ''}`);
}
const slow = results.filter((r) => r.status === 200 && r.ttfb > 5000).length;
console.log(`# ${results.length} requests: ${results.length - bad - limited} answered 200, ${limited} rate limited, ${bad} failed; ${slow} took over 5 s`);
if (bad) console.error(`${bad} requests to the store routes got no answer in ${TIMEOUT_MS} ms or a status that is not 200`);
process.exit(bad ? 1 : 0);
