// fshy Worker: routes the read-only HTTP API, the MCP endpoint, the /r/ permalinks and the download of the public store.
// Everything else is a static asset (wrangler.jsonc run_worker_first lists the Worker routes).
//
// The rate limit runs before the store loads, so a request that gets 429 never pays for a cold load of the store.
// workerd reads each named export of this module as an entrypoint, so the module exports the handler only.

import wasmModule from 'sql.js/dist/sql-wasm-browser.wasm';
import { asset, getStore, HttpError, loadNames } from './db.js';
import { baseHeaders, CORS, errorResponse, jsonResponse, rateLimited } from './http.js';
import * as api from './api.js';
import { handleMcp } from './mcp.js';

const DOWNLOAD = '/data/fshy-public.sqlite.gz';

// GET /api/v1/: the routes, for a caller that guesses the root of the API
const ROUTES = [
  ['GET /api/v1/search?q=WORDS', 'provider names first, then full text; also topic, grp, limit, offset'],
  ['GET /api/v1/records?topic=storage&no_card=1&sort=usd_per_tb_month', 'record cards that meet conditions: topic, verdict, grp, confidence, no_card, no_phone, anonymous, iface, binding, crypto, max_usd_month, max_usd_tb, sort, order, limit, offset'],
  ['GET /api/v1/sql?q=SELECT+rid+FROM+record+LIMIT+5', 'one read-only SQL statement; also POST {q, limit}; 30 a minute'],
  ['GET /api/v1/need/', 'the best-per-need lists; /api/v1/need/ID gives one ranked list'],
  ['GET /api/v1/worklist/KIND', 'KIND is stale, drift, changes or unparsed'],
  ['GET /api/v1/record/TOPIC/SLUG', 'one record as JSON'],
  ['GET /api/v1/entity-search?q=NAME', 'providers by name'],
  ['GET /api/v1/entity/ID.json', 'one provider and all its records (a static file)'],
  ['POST /mcp', 'the MCP endpoint: JSON-RPC 2.0, Streamable HTTP, read-only'],
];
const INDEX = {
  routes: ROUTES.map(([route, what]) => ({ route, what })),
  formats: 'JSON by default; TSV with the suffix .tsv or format=tsv',
  help: '/api/v1/help.txt',
  schema: '/api/v1/schema.sql',
  vocab: '/api/v1/vocab.json',
  llms: '/llms.txt',
  download: DOWNLOAD,
};

function params(url) {
  const p = {};
  for (const [k, v] of url.searchParams) {
    if (k in p) p[k] = [].concat(p[k], v);
    else p[k] = v;
  }
  return p;
}

/** decodeURIComponent, with a 400 for malformed percent-encoding instead of a URIError (a 500). */
function decode(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    throw new HttpError(400, 'malformed percent-encoding in the path');
  }
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

const notAllowed = (allow) => Object.assign(new HttpError(405, 'use ' + allow.replace(', OPTIONS', '').replace(', HEAD', '')), { allow });

/** -> {result, format} for the router to render, or {response} that is complete. */
async function handleApi(request, env, url, open) {
  const path = url.pathname;
  const method = request.method;
  let p = params(url);
  let format = p.format || 'json';
  const m = path.match(/\.(json|tsv)$/);
  const bare = (m ? path.slice(0, -m[0].length) : path).replace(/\/+$/, '') || '/';
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
      throw notAllowed('GET, HEAD, POST, OPTIONS');
    }
    if (await rateLimited(env, 'RL_SQL', request)) throw new HttpError(429, 'rate limited: 30 SQL requests a minute');
    return { result: api.sql(await open(), p), format };
  }
  if (method !== 'GET' && method !== 'HEAD') throw notAllowed('GET, HEAD, OPTIONS');
  if (await rateLimited(env, 'RL_API', request)) throw new HttpError(429, 'rate limited: 120 requests a minute');

  if (bare === '/api/v1') return { result: { json: INDEX }, format: 'json' };
  if (bare === '/api/v1/search') {
    const store = await open();
    await loadNames(store, env);
    return { result: api.search(store, p), format };
  }
  if (bare === '/api/v1/records') return { result: api.filter(await open(), p), format };
  if (bare === '/api/v1/entity-search') {
    const store = await open();
    await loadNames(store, env);
    return { result: api.entitySearch(store, p), format };
  }
  let r;
  if ((r = bare.match(/^\/api\/v1\/need(?:\/([^/]*))?$/))) {
    return { result: await api.need(await open(), env, { ...p, id: decode(r[1] || '') || p.id }), format };
  }
  if ((r = bare.match(/^\/api\/v1\/worklist\/([^/]+)$/))) {
    return { result: api.worklist(await open(), { ...p, kind: decode(r[1]) }), format };
  }
  if ((r = path.match(/^\/api\/v1\/record\/([^/]+)\/([^/]+?)(?:\.json)?\/?$/))) {
    const rid = decode(r[1]) + '/' + decode(r[2]);
    const full = await api.fullRecord(await open(), env, rid);
    if (!full) throw new HttpError(404, 'unknown record ' + rid);
    return { result: { json: full }, format: 'json' };
  }
  // a static file of /api/v1/ that wrangler.jsonc does not list as an exception: serve it as the assets would
  const res = await env.ASSETS.fetch(new Request(url.href, { method: 'GET' }));
  if (res.status === 200) {
    const h = new Headers(res.headers);
    h.set('access-control-allow-origin', '*');
    return { response: new Response(method === 'HEAD' ? null : res.body, { status: 200, headers: h }) };
  }
  if (res.body) await res.body.cancel();
  throw new HttpError(404, 'no such route; the route list is at /api/v1/ and the parameters are in /api/v1/help.txt');
}

async function permalink(request, env, url, open) {
  if (request.method !== 'GET' && request.method !== 'HEAD') throw notAllowed('GET, HEAD, OPTIONS');
  if (await rateLimited(env, 'RL_API', request)) throw new HttpError(429, 'rate limited: 120 requests a minute');
  const m = url.pathname.match(/^\/r\/([^/]+)\/([^/]+?)\/?$/);
  const store = await open();
  if (m) {
    const topic = decode(m[1]);
    const slug = decode(m[2]);
    const st = store.db.prepare('SELECT eid FROM record WHERE rid = ?');
    let eid = null;
    try {
      st.bind([topic + '/' + slug]);
      if (st.step()) eid = st.get()[0];
    } finally {
      st.free();
    }
    if (eid) {
      const loc = new URL(recordPath(store, eid, topic, slug), url);
      return new Response(null, { status: 301, headers: baseHeaders(store, { location: loc.href, 'cache-control': 'public, max-age=300' }) });
    }
  }
  // unknown: the site's 404 page from the assets (not_found_handling = 404-page)
  const res = await env.ASSETS.fetch(new Request(url.href, { method: 'GET' }));
  const h = new Headers(res.headers);
  h.set('x-fshy-commit', store.commit);
  return new Response(res.body, { status: res.status === 200 ? 404 : res.status, headers: h });
}

/**
 * The page of a record. A provider with more than manifest.record_pages_over records has a page for each record
 * (publish/pages.py); the others hold every record on the provider page, under the anchor topic--slug.
 */
function recordPath(store, eid, topic, slug) {
  const over = store.manifest && store.manifest.record_pages_over;
  const e = encodeURIComponent(eid);
  if (over && store.cache) {
    const counts = store.cache.recordCounts || (store.cache.recordCounts = new Map());
    if (!counts.has(eid)) {
      const st = store.db.prepare('SELECT count(*) FROM record WHERE eid = ?');
      try {
        st.bind([eid]);
        counts.set(eid, st.step() ? st.get()[0] : 0);
      } finally {
        st.free();
      }
    }
    if (counts.get(eid) > over) return '/p/' + e + '/' + topic + '--' + slug + '/';
  }
  return '/p/' + e + '/#' + topic + '--' + slug;
}

/**
 * GET /data/fshy-public.sqlite.gz: the parts that the manifest names, streamed in order as one gzip file. One file
 * would pass the 25 MiB limit of a static asset as the corpus grows, so the build writes parts and this route joins
 * them. The store is not loaded.
 */
async function download(request, env, ctx) {
  if (request.method !== 'GET' && request.method !== 'HEAD') throw notAllowed('GET, HEAD, OPTIONS');
  if (await rateLimited(env, 'RL_API', request)) throw new HttpError(429, 'rate limited: 120 requests a minute');
  const man = await asset(env, 'data/manifest.json', 'json');
  const pd = man && man.public_db;
  if (!pd || !Array.isArray(pd.parts) || !pd.parts.length) throw new HttpError(500, 'the manifest names no parts of the public store');
  const h = baseHeaders(null, {
    'content-type': 'application/gzip',
    'content-length': String(pd.gzip_bytes),
    'content-disposition': 'attachment; filename="fshy-public.sqlite.gz"',
    'cache-control': 'public, max-age=300',
    etag: '"' + pd.gzip_sha256 + '"',
  });
  if (man.commit) h.set('x-fshy-commit', man.commit);
  if (request.method === 'HEAD') return new Response(null, { status: 200, headers: h });
  // FixedLengthStream keeps the Content-Length on workerd; node has no such class
  const { readable, writable } = typeof FixedLengthStream === 'function' ? new FixedLengthStream(pd.gzip_bytes) : new TransformStream();
  const pump = (async () => {
    for (const p of pd.parts) {
      const res = await asset(env, p, 'response');
      await res.body.pipeTo(writable, { preventClose: true });
    }
    await writable.close();
  })().catch((e) => {
    console.error('fshy download failed:', e && e.stack ? e.stack : String(e));
    return writable.abort(e).catch(() => {});
  });
  if (ctx && typeof ctx.waitUntil === 'function') ctx.waitUntil(pump);
  return new Response(readable, { status: 200, headers: h });
}

function isWorkerRoute(path) {
  return path === '/api/v1' || path.startsWith('/api/v1/') || path === '/mcp' || path.startsWith('/r/') || path === DOWNLOAD;
}

async function route(request, env, ctx) {
  const t0 = performance.now();
  const url = new URL(request.url);
  const path = url.pathname;
  if (!isWorkerRoute(path)) return env.ASSETS.fetch(request);

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
  // the store loads on the first call, after the route has checked the method and the rate limit
  const open = async () => {
    if (!store) {
      try {
        ({ store, cold } = await getStore(env, wasmModule));
      } catch (e) {
        console.error('fshy store load failed:', e && e.stack ? e.stack : String(e));
        throw Object.assign(new HttpError(500, 'store unavailable'), { logged: true });
      }
    }
    return store;
  };
  try {
    let res;
    if (path === '/mcp') {
      res = await handleMcp(request, env, url, open);
    } else if (path.startsWith('/r/')) {
      res = await permalink(request, env, url, open);
    } else if (path === DOWNLOAD) {
      res = await download(request, env, ctx);
    } else {
      const out = await handleApi(request, env, url, open);
      if (out.response) {
        res = out.response;
      } else {
        const h = baseHeaders(store, {
          'cache-control': request.method === 'POST' ? 'no-store' : 'public, max-age=300',
        });
        res = render(out.result, out.format, h);
        if (request.method === 'HEAD') res = new Response(null, { status: res.status, headers: res.headers });
      }
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
  fetch(request, env, ctx) {
    return route(request, env, ctx);
  },
};
