// Remote MCP endpoint: stateless Streamable HTTP, JSON responses only, JSON-RPC 2.0 by hand.
// POST /mcp carries one message (or a batch); GET and DELETE are 405 because there is no
// server-initiated stream and no session. Tool results are text: TSV by default, capped near
// 20,000 tokens with a footer that says what was cut.

import { HttpError } from './db.js';
import { baseHeaders, jsonResponse, rateLimited } from './http.js';
import * as api from './api.js';

export const PROTOCOL_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];
const MAX_TOKENS = 20000;
const ALLOWED_HOSTS = new Set(['fshy.ajam.dev', 'localhost', '127.0.0.1']);

const s = (description, extra = {}) => ({ type: 'string', description, ...extra });
const n = (description, extra = {}) => ({ type: 'integer', description, ...extra });
const b = (description) => ({ type: 'boolean', description });
const obj = (properties, required) => ({ type: 'object', properties, ...(required ? { required } : {}) });
const FORMAT = s('tsv (default) or json', { enum: ['tsv', 'json'] });
const TOPIC = s('topic, e.g. storage, compute, inference, egress, email');

export const TOOLS = [
  {
    name: 'help',
    description: 'Primer: what the store holds, its tables, vocabularies and conventions (NULL = unknown). Read once first.',
    inputSchema: obj({}),
  },
  {
    name: 'search',
    description: 'Find records by provider name, then BM25 full text. Rows are cards plus the fields that matched.',
    inputSchema: obj({ q: s('words or a name; CJK works'), topic: TOPIC, grp: s('usable|trial|paid|rejected|dead, comma list'), limit: n('<= 50, default 20'), offset: n('skip rows'), format: FORMAT }, ['q']),
  },
  {
    name: 'filter',
    description: 'List records by structured conditions. A NULL price is never treated as a match; the footer counts rows excluded for it.',
    inputSchema: obj({
      topic: TOPIC,
      verdict: s('comma list, e.g. qualifies,qualifies-with-caveat'),
      grp: s('comma list: usable,trial,paid,rejected,dead'),
      confidence: s('comma list'),
      no_card: b('a card is stated as not required'),
      no_phone: b('a phone is stated as not required'),
      anonymous: b('no account at all'),
      iface: s('interface substring: s3, webdav, sftp, api ...'),
      binding: s('binding constraint, comma list'),
      crypto: b('a crypto payment rail is named'),
      max_usd_month: { type: 'number', description: 'headline USD a month' },
      max_usd_tb: { type: 'number', description: 'USD per TB-month' },
      include_duplicates: b('keep records marked duplicate_of'),
      sort: s('default vorder', { enum: ['vorder', 'usd_month', 'usd_per_tb_month', 'stale_on', 'provider', 'verified_at'] }),
      order: s('asc or desc', { enum: ['asc', 'desc'] }),
      limit: n('<= 200, default 50'),
      offset: n('skip rows'),
      format: FORMAT,
    }),
  },
  {
    name: 'get',
    description: 'Records by rid (topic/slug). detail=card (<= 50 ids) or full (<= 5 ids: record JSON with claims, unknown, history, drift).',
    inputSchema: obj({
      ids: { type: 'array', items: { type: 'string' }, description: 'rids, e.g. storage/hetzner-storage-box' },
      detail: s('card (default) or full', { enum: ['card', 'full'] }),
      fields: { type: 'array', items: { type: 'string' }, description: 'card: record columns; full: dotted paths such as record.free_tier' },
    }, ['ids']),
  },
  {
    name: 'entity',
    description: 'A vendor and all its records. Give id (entity id) or name (resolved by name search).',
    inputSchema: obj({ id: s('entity id, e.g. hetzner'), name: s('vendor name') }),
  },
  {
    name: 'need',
    description: 'Curated best-per-need lists. No id: list them. With id: ranked records, rows with no parsed number listed separately.',
    inputSchema: obj({ id: s('need id, e.g. s3-storage-no-card'), limit: n('<= 200, default 50'), offset: n('skip rows'), format: FORMAT }),
  },
  {
    name: 'sql',
    description: 'One read-only SELECT, WITH, VALUES or EXPLAIN over the SQLite store (FTS4 table text_fts). Writes and PRAGMA are refused; LIMIT is added if absent.',
    inputSchema: obj({ query: s('the SQL'), limit: n('<= 200, default 100'), format: FORMAT }, ['query']),
  },
  {
    name: 'worklist',
    description: 'Maintenance lists: stale (stale_on <= as_of + forecast_days), drift, changes (newest first), unparsed claims.',
    inputSchema: obj({
      kind: s('stale, drift, changes or unparsed', { enum: ['stale', 'drift', 'changes', 'unparsed'] }),
      topic: TOPIC,
      as_of: s('YYYY-MM-DD, default today (UTC)'),
      forecast_days: n('look ahead this many days'),
      limit: n('<= 200, default 50'),
      offset: n('skip rows'),
      format: FORMAT,
    }, ['kind']),
  },
];

/** Rough token estimate: ASCII at 4 characters a token, anything else at 1. */
export function estimateTokens(text) {
  let ascii = 0;
  let other = 0;
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) < 128) ascii++;
    else other++;
  }
  return Math.ceil(ascii / 4) + other;
}

/** TSV text for a table result, cut at about MAX_TOKENS with a footer that says so. */
export function tableText(t, format = 'tsv', maxTokens = MAX_TOKENS) {
  if (format === 'json') {
    const text = JSON.stringify(api.toJson(t));
    if (estimateTokens(text) <= maxTokens) return text;
    // too large as JSON: fall back to TSV, which is cut by rows
  }
  const { lines, footer } = api.toTsv(t);
  let budget = maxTokens - estimateTokens(footer.join('\n')) - 60;
  const kept = [];
  let cut = 0;
  for (let i = 0; i < lines.length; i++) {
    const cost = estimateTokens(lines[i]) + 1;
    if (cost > budget) { cut = lines.length - i; break; }
    budget -= cost;
    kept.push(lines[i]);
  }
  const out = kept.concat(footer);
  if (cut) {
    const shown = Math.max(0, kept.length - 1);
    out.push(`# truncated at about ${maxTokens} tokens: ${cut} more lines not shown after row ${shown}; narrow the query or page with limit/offset`);
  }
  return out.join('\n');
}

function jsonText(o, maxTokens = MAX_TOKENS) {
  const text = JSON.stringify(o);
  if (estimateTokens(text) <= maxTokens) return text;
  let cut = text.slice(0, maxTokens * 3);
  while (estimateTokens(cut) > maxTokens && cut.length > 100) cut = cut.slice(0, Math.floor(cut.length * 0.9));
  return cut + `\n# truncated at about ${maxTokens} tokens; ask for fewer ids or use fields`;
}

function args(a) {
  if (a == null) return {};
  if (typeof a !== 'object' || Array.isArray(a)) throw new HttpError(400, 'arguments must be an object');
  return a;
}

async function callTool(name, a, store, env, request) {
  const fmt = (x) => {
    const f = x.format || 'tsv';
    if (f !== 'tsv' && f !== 'json') throw new HttpError(400, 'format must be tsv or json');
    return f;
  };
  switch (name) {
    case 'help':
      return await api.help(store, env);
    case 'search':
      return tableText(api.search(store, a), fmt(a));
    case 'filter':
      return tableText(api.filter(store, a), fmt(a));
    case 'get': {
      const r = await api.get(store, env, a);
      return r.json ? jsonText(r.json) : tableText(r, 'tsv');
    }
    case 'entity':
      return tableText(api.entity(store, a), 'tsv');
    case 'need':
      return tableText(await api.need(store, env, a), fmt(a));
    case 'sql': {
      if (await rateLimited(env, 'RL_SQL', request)) throw new HttpError(429, 'rate limited: 30 SQL calls a minute');
      return tableText(api.sql(store, { q: a.query ?? a.q, limit: a.limit }), fmt(a));
    }
    case 'worklist':
      return tableText(api.worklist(store, a), fmt(a));
    default:
      return null;
  }
}

const rpcError = (id, code, message) => ({ jsonrpc: '2.0', id: id ?? null, error: { code, message } });
const rpcResult = (id, result) => ({ jsonrpc: '2.0', id, result });

async function dispatch(msg, store, env, request) {
  if (!msg || typeof msg !== 'object' || Array.isArray(msg) || msg.jsonrpc !== '2.0' || typeof msg.method !== 'string') {
    // a response sent to us by a client (result/error without method) needs no reply
    if (msg && typeof msg === 'object' && msg.jsonrpc === '2.0' && !('method' in msg) && ('result' in msg || 'error' in msg)) return null;
    return rpcError(msg && msg.id, -32600, 'invalid request');
  }
  const isNote = !('id' in msg);
  const id = msg.id;
  const p = msg.params || {};
  if (isNote) return null; // notifications/initialized, notifications/cancelled, ...
  switch (msg.method) {
    case 'initialize': {
      const asked = typeof p.protocolVersion === 'string' ? p.protocolVersion : null;
      const version = PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0];
      return rpcResult(id, {
        protocolVersion: version,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: 'fshy', version: (store.commit || 'unknown').slice(0, 12) },
        instructions: 'Read-only catalogue of free and cheap capability (storage, compute, GPU, inference, crawling, egress, email, databases, DNS, CI, proxies). Call help once, then search or filter; get detail=full for one record. NULL means unknown, never no.',
      });
    }
    case 'ping':
      return rpcResult(id, {});
    case 'tools/list':
      return rpcResult(id, { tools: TOOLS });
    case 'tools/call': {
      const name = p.name;
      if (typeof name !== 'string' || !TOOLS.some((t) => t.name === name)) {
        return rpcError(id, -32602, 'unknown tool: ' + String(name));
      }
      try {
        const text = await callTool(name, args(p.arguments), store, env, request);
        return rpcResult(id, { content: [{ type: 'text', text }], isError: false });
      } catch (e) {
        const known = e instanceof HttpError;
        if (!known) console.error('fshy mcp tool error:', e && e.stack ? e.stack : String(e));
        const message = known ? e.message : 'internal error';
        return rpcResult(id, { content: [{ type: 'text', text: 'error: ' + message }], isError: true });
      }
    }
    default:
      return rpcError(id, -32601, 'method not found: ' + msg.method);
  }
}

function hostAllowed(request, url) {
  const raw = request.headers.get('host') || url.host;
  const host = raw.replace(/:\d+$/, '').toLowerCase();
  return ALLOWED_HOSTS.has(host) || host.endsWith('.workers.dev');
}

export async function handleMcp(request, env, url, store) {
  const h = baseHeaders(store, { 'cache-control': 'no-store' });
  if (!hostAllowed(request, url)) return jsonResponse({ error: 'host not allowed' }, 403, h);
  if (request.method !== 'POST') {
    h.set('allow', 'POST, OPTIONS');
    return jsonResponse(rpcError(null, -32000, 'method not allowed: POST JSON-RPC messages to /mcp'), 405, h);
  }
  const pv = request.headers.get('mcp-protocol-version');
  if (pv && !PROTOCOL_VERSIONS.includes(pv)) {
    return jsonResponse(rpcError(null, -32600, 'unsupported MCP-Protocol-Version ' + pv), 400, h);
  }
  if (await rateLimited(env, 'RL_API', request)) {
    h.set('retry-after', '60');
    return jsonResponse(rpcError(null, -32000, 'rate limited: 120 requests a minute'), 429, h);
  }
  const text = await request.text();
  if (text.length > 1048576) return jsonResponse(rpcError(null, -32600, 'body too large'), 413, h);
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return jsonResponse(rpcError(null, -32700, 'parse error'), 400, h);
  }
  if (Array.isArray(body)) {
    if (!body.length) return jsonResponse(rpcError(null, -32600, 'empty batch'), 400, h);
    const out = [];
    for (const m of body.slice(0, 50)) {
      const r = await dispatch(m, store, env, request);
      if (r) out.push(r);
    }
    if (!out.length) return new Response(null, { status: 202, headers: h });
    return jsonResponse(out, 200, h);
  }
  const r = await dispatch(body, store, env, request);
  if (!r) return new Response(null, { status: 202, headers: h });
  return jsonResponse(r, 200, h);
}
