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
