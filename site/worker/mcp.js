// Remote MCP endpoint: stateless Streamable HTTP, JSON responses only, JSON-RPC 2.0 by hand.
// POST /mcp carries one message, or a batch of at most MAX_BATCH messages, of which at most MAX_BATCH_SQL are sql
// calls; GET and DELETE are 405 because there is no server-initiated stream and no session. Tool results are text:
// TSV by default, capped near 20,000 tokens with a footer that says what was cut.
//
// Cost: each tools/call message counts one unit of the rate limit RL_API, so a batch costs what its calls cost. A
// sql call can take 0.6 s of CPU where any other call takes 0.1 s or less, so the batch limit weighs it: with the
// costliest sql call that site/README.md measures, MAX_BATCH_SQL of them and the other calls of a full batch stay
// under cpu_ms of wrangler.jsonc. The protocol revision 2025-06-18 removed batches; only the two oldest versions
// that this endpoint accepts use them.

import { HttpError, loadNames } from './db.js';
import { baseHeaders, jsonResponse, rateLimited } from './http.js';
import * as api from './api.js';

export const PROTOCOL_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];
export const MAX_BATCH = 5;
// the sql calls that one batch may hold: 1 x 672 ms (the costliest warm statement) + 4 x 75 ms (searches) = 972 ms,
// under the cpu_ms of 2,500 with a margin of 2.6; 2 sql calls would be 1,569 ms and leave 1.6
export const MAX_BATCH_SQL = 1;
const MAX_TOKENS = 20000;
// the site's own host (wrangler.jsonc vars.FSHY_HOST), the local hosts of `wrangler dev`, and *.workers.dev previews
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]'];
const DEFAULT_HOST = 'fshy.ajam.dev';

const s = (description, extra = {}) => ({ type: 'string', description, ...extra });
const n = (description, extra = {}) => ({ type: 'integer', description, ...extra });
const b = (description) => ({ type: 'boolean', description });
const obj = (properties, required) => ({ type: 'object', properties, ...(required ? { required } : {}) });
const FORMAT = s('tsv (default) or json', { enum: ['tsv', 'json'] });
const TOPIC = s('a topic id from the enum; a comma list where the tool takes several');
const GRP = s('comma list of usable, trial, paid, rejected, dead');
// every tool reads the store and changes nothing; the same arguments give the same answer until the next publish
const ANNOTATIONS = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

export const TOOLS = [
  {
    name: 'help',
    description: 'Use once, first: the primer of the store, with its tables, vocabularies and rules. NULL means unknown, never no.',
    inputSchema: obj({}),
  },
  {
    name: 'search',
    description: 'Use when you have a provider name or words. It matches names first, then ranks the full text (BM25). Rows are cards plus the fields that matched. For conditions such as no card, a price cap or an interface, use filter.',
    inputSchema: obj({ q: s('words or a name; CJK works'), topic: TOPIC, grp: GRP, limit: n('<= 50, default 20'), offset: n('skip rows'), format: FORMAT }, ['q']),
  },
  {
    name: 'filter',
    description: 'Use for questions such as "which X need no card" or "which X cost less than Y": the records that meet structured conditions, best verdict first. Start here for a ranked answer. A NULL price never matches a price condition, and the footer counts the rows that it excluded.',
    inputSchema: obj({
      topic: TOPIC,
      verdict: s('comma list, e.g. qualifies,qualifies-with-caveat'),
      grp: GRP,
      confidence: s('comma list of measured, documented, reported, inferred, unverified'),
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
    description: 'Use after search or filter to read records in full. ids are rids (topic/slug). detail=card takes up to 50 ids; detail=full takes up to 5 and gives the record JSON with claims, unknown, history and drift.',
    inputSchema: obj({
      ids: { type: 'array', items: { type: 'string' }, description: 'rids, e.g. storage/hetzner-storage-box' },
      detail: s('card (default) or full', { enum: ['card', 'full'] }),
      fields: { type: 'array', items: { type: 'string' }, description: 'card: record columns; full: dotted paths such as record.free_tier' },
    }, ['ids']),
  },
  {
    name: 'entity',
    description: 'Use to see every record of one provider. Give id (the entity id) or name (found by name search).',
    inputSchema: obj({ id: s('entity id, e.g. hetzner'), name: s('vendor name') }),
  },
  {
    name: 'need',
    description: 'Use first when the question matches a curated best-per-need list. With no id: the lists. With id: the ranked records, then the rows with no parsed number.',
    inputSchema: obj({ id: s('need id, e.g. s3-storage-no-card'), limit: n('<= 200, default 50'), offset: n('skip rows'), format: FORMAT }),
  },
  {
    name: 'sql',
    description: 'Use only when filter cannot express the question. One read-only SELECT, WITH, VALUES or EXPLAIN over the SQLite store (FTS4 table text_fts). A write, PRAGMA, a function that is not on the list and a costly plan are refused, and the refusal says why. LIMIT is added if absent. 30 calls a minute.',
    inputSchema: obj({ query: s('the SQL'), limit: n('<= 200, default 100'), format: FORMAT }, ['query']),
  },
  {
    name: 'worklist',
    description: 'Use to find records to maintain, not to answer a question about an offer: stale (stale_on <= as_of + forecast_days), drift, changes (newest first), unparsed claims.',
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
].map((t) => ({ ...t, annotations: ANNOTATIONS }));
const TOOL_NAMES = TOOLS.map((t) => t.name).join(', ');

/** The tools, with the topic ids of the store as the enum of each topic argument. */
export function toolsFor(store) {
  const topics = [...api.vocabOf(store).topic];
  return TOOLS.map((t) => {
    const props = t.inputSchema.properties;
    if (!props.topic) return t;
    return { ...t, inputSchema: { ...t.inputSchema, properties: { ...props, topic: { ...props.topic, enum: topics } } } };
  });
}

function instructions(store) {
  const v = api.vocabOf(store);
  return 'Read-only catalogue of free and cheap capability: storage, compute, GPU time, inference, crawling, egress, ' +
    'email, databases, DNS, CI, proxies and more. Call help once. Then use need or filter for a ranked answer, and ' +
    'search for a name; get with detail=full reads one record. NULL means unknown, never no. Topics: ' +
    [...v.topic].join(', ') + '. Verdicts, best first: ' + [...v.verdict].join(', ') + '. A batch holds at most ' +
    MAX_BATCH + ' messages, and at most ' + MAX_BATCH_SQL + (MAX_BATCH_SQL === 1 ? ' of them calls' : ' of them call') + ' sql.';
}

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
      await loadNames(store, env);
      return tableText(api.search(store, a), fmt(a));
    case 'filter':
      return tableText(api.filter(store, a), fmt(a));
    case 'get': {
      const r = await api.get(store, env, a);
      return r.json ? jsonText(r.json) : tableText(r, 'tsv');
    }
    case 'entity':
      await loadNames(store, env);
      return tableText(api.entity(store, a), 'tsv');
    case 'need':
      return tableText(await api.need(store, env, a), fmt(a));
    case 'sql': {
      if (a.query == null && a.q == null) throw new HttpError(400, 'query (the SQL text) is required');
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
  // MCP asks for a string or a number: null is no id, and a reply to it could not be matched to the request
  if (!isNote && (id === null || (typeof id !== 'string' && typeof id !== 'number'))) {
    return rpcError(null, -32600, 'invalid request: id must be a string or a number');
  }
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
        instructions: instructions(store),
      });
    }
    case 'ping':
      return rpcResult(id, {});
    case 'tools/list':
      return rpcResult(id, { tools: toolsFor(store) });
    case 'tools/call': {
      const name = p.name;
      if (typeof name !== 'string' || !TOOLS.some((t) => t.name === name)) {
        const what = typeof name === 'string' ? 'unknown tool: ' + name : 'tools/call needs the name of a tool in params.name';
        return rpcError(id, -32602, what + '; the tools are ' + TOOL_NAMES);
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

function hostAllowed(request, url, env) {
  const raw = request.headers.get('host') || url.host;
  const host = raw.replace(/:\d+$/, '').toLowerCase();
  const own = String((env && env.FSHY_HOST) || DEFAULT_HOST).toLowerCase();
  return host === own || LOCAL_HOSTS.includes(host) || host.endsWith('.workers.dev');
}

/** The units of the rate limit that a body costs: one for each tools/call message, and at least one. */
export function units(body) {
  const msgs = Array.isArray(body) ? body : [body];
  return Math.max(1, msgs.filter((m) => m && typeof m === 'object' && m.method === 'tools/call').length);
}

/** The tools/call messages of a body that call the tool sql. */
export function sqlCalls(body) {
  const msgs = Array.isArray(body) ? body : [body];
  return msgs.filter((m) => m && typeof m === 'object' && m.method === 'tools/call' && m.params && m.params.name === 'sql').length;
}

/** POST /mcp. open() loads the store; it runs after the checks and the rate limit, so a refusal costs no load. */
export async function handleMcp(request, env, url, open) {
  const h = (store) => baseHeaders(store, { 'cache-control': 'no-store' });
  if (!hostAllowed(request, url, env)) return jsonResponse({ error: 'host not allowed' }, 403, h(null));
  if (request.method !== 'POST') {
    const hh = h(null);
    hh.set('allow', 'POST, OPTIONS');
    return jsonResponse(rpcError(null, -32000, 'method not allowed: POST JSON-RPC messages to /mcp'), 405, hh);
  }
  const pv = request.headers.get('mcp-protocol-version');
  if (pv && !PROTOCOL_VERSIONS.includes(pv)) {
    return jsonResponse(rpcError(null, -32600, 'unsupported MCP-Protocol-Version ' + pv), 400, h(null));
  }
  const text = await request.text();
  if (text.length > 1048576) return jsonResponse(rpcError(null, -32600, 'body too large'), 413, h(null));
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = undefined;
  }
  if (Array.isArray(body) && body.length > MAX_BATCH) {
    return jsonResponse(rpcError(null, -32600, `a batch holds at most ${MAX_BATCH} messages; send the others in more requests`), 400, h(null));
  }
  if (Array.isArray(body) && sqlCalls(body) > MAX_BATCH_SQL) {
    return jsonResponse(rpcError(null, -32600, `a batch holds at most ${MAX_BATCH_SQL} sql call${MAX_BATCH_SQL === 1 ? '' : 's'}; send the others in more requests`), 400, h(null));
  }
  if (await rateLimited(env, 'RL_API', request, body === undefined ? 1 : units(body))) {
    const hh = h(null);
    hh.set('retry-after', '60');
    return jsonResponse(rpcError(null, -32000, 'rate limited: 120 tool calls a minute'), 429, hh);
  }
  if (body === undefined) return jsonResponse(rpcError(null, -32700, 'parse error'), 400, h(null));
  if (Array.isArray(body) && !body.length) return jsonResponse(rpcError(null, -32600, 'empty batch'), 400, h(null));
  const store = await open();
  if (Array.isArray(body)) {
    const out = [];
    for (const m of body) {
      const r = await dispatch(m, store, env, request);
      if (r) out.push(r);
    }
    if (!out.length) return new Response(null, { status: 202, headers: h(store) });
    return jsonResponse(out, 200, h(store));
  }
  const r = await dispatch(body, store, env, request);
  if (!r) return new Response(null, { status: 202, headers: h(store) });
  return jsonResponse(r, 200, h(store));
}
