// fshy Worker: routes the read-only HTTP API, the MCP endpoint and the /r/ permalinks.
// Everything else is a static asset (wrangler.jsonc run_worker_first lists the Worker routes).

import wasmModule from 'sql.js/dist/sql-wasm-browser.wasm';
import { getStore, HttpError } from './db.js';
import { baseHeaders, CORS, errorResponse, jsonResponse, rateLimited } from './http.js';
import * as api from './api.js';
import { handleMcp } from './mcp.js';

function params(url) {
  const p = {};
  for (const [k, v] of url.searchParams) {
    if (k in p) p[k] = [].concat(p[k], v);
    else p[k] = v;
  }
  return p;
}

function timing(cold, store, t0) {
  const parts = [];
  if (cold && store) {
    const s = store.stats;
    parts.push(`db;desc="cold load";dur=${s.total_ms}`, `dbfetch;dur=${s.fetch_ms}`, `dbhash;dur=${s.hash_ms}`, `dbopen;dur=${s.open_ms}`);
  }
  parts.push(`app;dur=${Math.round((performance.now() - t0) * 10) / 10}`);
  return parts.join(', ');
}

/** Render a table result (or a raw JSON result) as JSON or TSV. */
function render(result, format, headers, status = 200) {
  if (result && result.json) return jsonResponse(result.json, status, headers);
  if (format === 'tsv') {
    const { lines, footer } = api.toTsv(result);
    headers.set('content-type', 'text/tab-separated-values; charset=utf-8');
    return new Response(lines.concat(footer).join('\n') + '\n', { status, headers });
  }
  return jsonResponse(api.toJson(result), status, headers);
}

async function readJsonBody(request, max = 65536) {
  const text = await request.text();
  if (text.length > max) throw new HttpError(400, 'body larger than ' + max + ' bytes');
  try {
    return JSON.parse(text);
  } catch {
    throw new HttpError(400, 'body is not JSON');
  }
}

async function handleApi(request, env, url, store) {
  const path = url.pathname;
  const method = request.method;
  let p = params(url);
  let format = p.format || 'json';
  const m = path.match(/\.(json|tsv)$/);
  const bare = m ? path.slice(0, -m[0].length) : path;
  if (m) format = m[1];
  if (format !== 'json' && format !== 'tsv') throw new HttpError(400, 'format must be json or tsv');

  if (bare === '/api/v1/sql') {
    if (method === 'POST') {
      const body = await readJsonBody(request);
      if (!body || typeof body !== 'object' || Array.isArray(body)) throw new HttpError(400, 'body must be a JSON object {q, limit}');
      p = { ...p, ...body };
      if (body.format) format = body.format;
      if (format !== 'json' && format !== 'tsv') throw new HttpError(400, 'format must be json or tsv');
    } else if (method !== 'GET' && method !== 'HEAD') {
      throw Object.assign(new HttpError(405, 'use GET or POST'), { allow: 'GET, HEAD, POST, OPTIONS' });
    }
    if (await rateLimited(env, 'RL_SQL', request)) throw new HttpError(429, 'rate limited: 30 SQL requests a minute');
    return { result: api.sql(store, p), format };
  }
  if (method !== 'GET' && method !== 'HEAD') {
    throw Object.assign(new HttpError(405, 'use GET'), { allow: 'GET, HEAD, OPTIONS' });
  }
  if (await rateLimited(env, 'RL_API', request)) throw new HttpError(429, 'rate limited: 120 requests a minute');

  if (bare === '/api/v1/search') return { result: api.search(store, p), format };
  if (bare === '/api/v1/records') return { result: api.filter(store, p), format };
  if (bare === '/api/v1/entity-search') return { result: api.entitySearch(store, p), format };
  let r;
  if ((r = bare.match(/^\/api\/v1\/need\/?([^/]*)\/?$/))) {
    return { result: await api.need(store, env, { ...p, id: decodeURIComponent(r[1]) || p.id }), format };
  }
  if ((r = bare.match(/^\/api\/v1\/worklist\/([^/]+)\/?$/))) {
    return { result: api.worklist(store, { ...p, kind: decodeURIComponent(r[1]) }), format };
  }
  if ((r = path.match(/^\/api\/v1\/record\/([^/]+)\/([^/]+?)(?:\.json)?\/?$/))) {
    const rid = decodeURIComponent(r[1]) + '/' + decodeURIComponent(r[2]);
    const full = await api.fullRecord(store, env, rid);
    if (!full) throw new HttpError(404, 'unknown record ' + rid);
    return { result: { json: full }, format: 'json' };
  }
  throw new HttpError(404, 'no such API route');
}

async function permalink(request, env, url, store) {
  const m = url.pathname.match(/^\/r\/([^/]+)\/([^/]+?)\/?$/);
  if (m) {
    const topic = decodeURIComponent(m[1]);
    const slug = decodeURIComponent(m[2]);
    const st = store.db.prepare('SELECT eid FROM record WHERE rid = ?');
    let eid = null;
    try {
      st.bind([topic + '/' + slug]);
      if (st.step()) eid = st.get()[0];
    } finally {
      st.free();
    }
    if (eid) {
      const loc = new URL('/p/' + encodeURIComponent(eid) + '/#' + topic + '--' + slug, url);
      return new Response(null, { status: 301, headers: baseHeaders(store, { location: loc.href, 'cache-control': 'public, max-age=300' }) });
    }
  }
  // unknown: the site's 404 page from the assets (not_found_handling = 404-page)
  const res = await env.ASSETS.fetch(new Request(url.href, { method: 'GET' }));
  const h = new Headers(res.headers);
  h.set('x-fshy-commit', store.commit);
  return new Response(res.body, { status: res.status === 200 ? 404 : res.status, headers: h });
}

async function route(request, env) {
  const t0 = performance.now();
  const url = new URL(request.url);
  const path = url.pathname;
  const isWorkerRoute = path.startsWith('/api/v1/') || path === '/mcp' || path.startsWith('/r/');
  if (!isWorkerRoute) return env.ASSETS.fetch(request);

  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        ...CORS,
        'access-control-allow-methods': path === '/mcp' ? 'POST, OPTIONS' : 'GET, HEAD, POST, OPTIONS',
        'access-control-allow-headers': 'content-type, accept, mcp-protocol-version, mcp-session-id, last-event-id',
        'access-control-max-age': '86400',
      },
    });
  }

  let store = null;
  let cold = false;
  try {
    ({ store, cold } = await getStore(env, wasmModule));
  } catch (e) {
    console.error('fshy store load failed:', e && e.stack ? e.stack : String(e));
    return errorResponse(new HttpError(500, 'store unavailable'), null);
  }
  try {
    let res;
    if (path === '/mcp') {
      res = await handleMcp(request, env, url, store);
    } else if (path.startsWith('/r/')) {
      res = await permalink(request, env, url, store);
    } else {
      const { result, format } = await handleApi(request, env, url, store);
      const h = baseHeaders(store, {
        'cache-control': request.method === 'POST' ? 'no-store' : 'public, max-age=300',
      });
      res = render(result, format, h);
      if (request.method === 'HEAD') res = new Response(null, { status: res.status, headers: res.headers });
    }
    res.headers.set('server-timing', timing(cold, store, t0));
    return res;
  } catch (e) {
    const res = errorResponse(e, store);
    if (e && e.allow) res.headers.set('allow', e.allow);
    res.headers.set('server-timing', timing(cold, store, t0));
    return res;
  }
}

export default {
  fetch(request, env) {
    return route(request, env);
  },
};
