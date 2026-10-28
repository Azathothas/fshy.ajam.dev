// HTTP helpers shared by the router (index.js) and the MCP endpoint (mcp.js).

import { HttpError } from './db.js';

export const CORS = {
  'access-control-allow-origin': '*',
  'access-control-expose-headers': 'x-fshy-commit, server-timing, mcp-protocol-version',
};

export function baseHeaders(store, extra = {}) {
  const h = new Headers({ ...CORS, ...extra });
  if (store && store.commit) h.set('x-fshy-commit', store.commit);
  return h;
}

export function jsonResponse(obj, status, headers) {
  headers.set('content-type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify(obj), { status, headers });
}

export function errorResponse(e, store) {
  const status = e instanceof HttpError ? e.status : 500;
  if (status >= 500) console.error('fshy error:', e && e.stack ? e.stack : String(e));
  const msg = status >= 500 && !(e instanceof HttpError) ? 'internal error' : e.message;
  const h = baseHeaders(store, { 'cache-control': 'no-store' });
  if (status === 429) h.set('retry-after', '60');
  return jsonResponse({ error: msg }, status, h);
}

/** Workers rate limiting binding; absent outside Cloudflare (tests), where nothing is limited. */
export async function rateLimited(env, binding, request) {
  const rl = env[binding];
  if (!rl || typeof rl.limit !== 'function') return false;
  const key = request.headers.get('cf-connecting-ip') || 'unknown';
  const { success } = await rl.limit({ key });
  return !success;
}
