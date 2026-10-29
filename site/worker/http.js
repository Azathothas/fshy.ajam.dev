// HTTP helpers shared by the router (index.js) and the MCP endpoint (mcp.js).

import { HttpError } from './db.js';

export const CORS = {
  'access-control-allow-origin': '*',
  'access-control-expose-headers': 'x-fshy-commit, server-timing, mcp-protocol-version',
};
// the static files get these from static/_headers; a response of the Worker gets them here
const SAFE = { 'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer' };

export function baseHeaders(store, extra = {}) {
  const h = new Headers({ ...CORS, ...SAFE, ...extra });
  if (store && store.commit) h.set('x-fshy-commit', store.commit);
  return h;
}

export function jsonResponse(obj, status, headers) {
  headers.set('content-type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify(obj), { status, headers });
}

export function errorResponse(e, store) {
  const status = e instanceof HttpError ? e.status : 500;
  if (status >= 500 && !(e && e.logged)) console.error('fshy error:', e && e.stack ? e.stack : String(e));
  const msg = status >= 500 && !(e instanceof HttpError) ? 'internal error' : e.message;
  const h = baseHeaders(store, { 'cache-control': 'no-store' });
  if (status === 429) h.set('retry-after', '60');
  return jsonResponse({ error: msg }, status, h);
}

/** True when the value of an If-None-Match header holds the entity tag: a list of tags, `*`, or a weak copy of the tag. */
export function etagMatches(header, etag) {
  return header.split(',').some((t) => {
    const tag = t.trim();
    return tag === '*' || tag.replace(/^W\//, '') === etag;
  });
}

/**
 * The byte range that a Range header asks of a file of `total` bytes: {start, end}, both inclusive; the string
 * 'unsatisfiable' when it lies past the end; null when the header is to be ignored, so the whole file is sent. That is
 * a unit other than bytes, a list of ranges, and a range that is not valid.
 */
export function parseRange(header, total) {
  const m = /^bytes=(\d*)-(\d*)$/i.exec(header.trim());
  if (!m || (m[1] === '' && m[2] === '')) return null;
  if (m[1] === '') {
    const last = Number(m[2]);
    return last === 0 ? 'unsatisfiable' : { start: Math.max(0, total - last), end: total - 1 };
  }
  const start = Number(m[1]);
  if (m[2] !== '' && Number(m[2]) < start) return null;
  if (start >= total) return 'unsatisfiable';
  return { start, end: m[2] === '' ? total - 1 : Math.min(Number(m[2]), total - 1) };
}

/**
 * Workers rate limiting binding. Absent in the node tests, and `limit()` throws in some local `wrangler dev`
 * runs: both fail open, because the store is read-only and the Worker has a CPU limit. A thrown error is
 * logged once per isolate, so a binding that breaks in production is visible in the logs.
 */
let limiterFailed = false;
export async function rateLimited(env, binding, request, units = 1) {
  const rl = env[binding];
  if (!rl || typeof rl.limit !== 'function') return false;
  const key = request.headers.get('cf-connecting-ip') || 'unknown';
  try {
    // one call of limit() counts one unit; a request that carries several tool calls counts each of them
    for (let i = 0; i < units; i++) {
      const r = await rl.limit({ key });
      if (!(r && r.success)) return true;
    }
    return false;
  } catch (e) {
    if (!limiterFailed) console.error('fshy rate limiter ' + binding + ' failed, request allowed:', e && e.stack ? e.stack : String(e));
    limiterFailed = true;
    return false;
  }
}
