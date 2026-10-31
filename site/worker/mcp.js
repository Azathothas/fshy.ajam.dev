// Remote MCP endpoint: stateless Streamable HTTP, JSON responses only, JSON-RPC 2.0 by hand.
// POST /mcp carries one message, or a batch of at most MAX_BATCH messages, of which at most MAX_BATCH_SQL are sql
// calls; GET and DELETE are 405 because there is no server-initiated stream and no session. Tool results are text:
// TSV by default, capped near 20,000 tokens. A cut keeps whole rows and whole records, so the text stays valid TSV or
// valid JSON, and a note in the text says what the cut left out.
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
// a tool that takes several topics (search, filter) reads a comma list, so its schema is a pattern over the topic ids, which
// a validating client accepts for "storage,compute"; a tool that takes one (worklist) has an enum (toolsFor fills both)
const TOPICS = s('one topic id, or a comma list of them');
const TOPIC = s('one topic id');
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
    inputSchema: obj({ q: s('words or a name; CJK works'), topic: TOPICS, grp: GRP, limit: n('<= 50, default 20'), offset: n('skip rows'), format: FORMAT }, ['q']),
  },
  {
    name: 'filter',
    description: 'Use for questions such as "which X need no card" or "which X cost less than Y": the records that meet structured conditions, hosted first, then best verdict first. Start here for a ranked answer. A NULL price never matches a price condition, and the footer counts the rows that it excluded.',
    inputSchema: obj({
      topic: TOPICS,
      verdict: s('comma list, e.g. qualifies,qualifies-with-caveat'),
      grp: GRP,
      confidence: s('comma list of measured, documented, reported, inferred, unverified'),
      no_card: b('a card is stated as not required'),
      no_phone: b('a phone is stated as not required'),
      anonymous: b('no account at all'),
      free: b('a free allowance is stated (the claim has-free-tier), as the need lists read it'),
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
    description: 'Use after search or filter to read records in full. ids are rids (topic/slug). detail=card takes up to 50 ids; detail=full takes up to 5 and gives the record JSON with claims, unknown, history and drift. Over about 20,000 tokens, full sends whole records only and lists the ids it left out in omitted.',
    inputSchema: obj({
      ids: { type: 'array', items: { type: 'string' }, description: 'rids, e.g. storage/hetzner-storage-box' },
      detail: s('card (default) or full', { enum: ['card', 'full'] }),
      fields: { type: 'array', items: { type: 'string' }, description: 'card: record columns; full: dotted paths such as record.free_tier' },
    }, ['ids']),
  },
  {
    name: 'entity',
    description: 'Use to see every record of one provider. Give id (the entity id) or name (found by name search). A duplicate record (duplicate_of) is left out unless include_duplicates is true; a note names it.',
    inputSchema: obj({ id: s('entity id, e.g. hetzner'), name: s('vendor name'), include_duplicates: b('keep records marked duplicate_of') }),
  },
  {
    name: 'need',
    description: 'Use first when the question matches a curated best-per-need list. With no id: the lists. With id: the ranked records, then the rows with no parsed number, then, in a list that asks for no card or no phone, the rows whose card or phone requirement is not stated, then the self-hosted rows.',
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
    const one = '(?:' + topics.map((x) => x.replace(/[^a-z0-9-]/g, '')).join('|') + ')';
    const topic = props.topic === TOPICS
      ? { ...props.topic, pattern: '^' + one + '(?:,' + one + ')*$', description: props.topic.description + ': ' + topics.join(', ') }
      : { ...props.topic, enum: topics };
    return { ...t, inputSchema: { ...t.inputSchema, properties: { ...props, topic } } };
  });
}

function instructions(store) {
  const v = api.vocabOf(store);
  return 'Read-only catalogue of free and cheap capability: storage, compute, GPU time, inference, crawling, egress, ' +
    'email, databases, DNS, CI, proxies and more. Call help once. Then use need or filter for a ranked answer, and ' +
    'search for a name; get with detail=full reads one record. NULL means unknown, never no. A self-hosted record ' +
    '(self_hosted yes: the user installs and runs it) is the last resort, after every hosted record of a list. Topics: ' +
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

// The row lists of a table result, in list order: a need has its rows in these parts (api.need), any other table has
// rows only. toTsv and toJson print them in this order.
const SECTIONS = ['rows', 'nullRows', 'unstatedRows', 'selfRows', 'selfUnstatedRows'];
const allRows = (t) => SECTIONS.flatMap((k) => t[k] || []);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * A copy of a table result with its first n rows in list order, and a note that says what the cut left out. A paged
 * result (api.js marks it paged) gives the offset that reads on; the footer of toTsv gives it too. A sql result says to
 * select less. Any other result names the rids of the rows that it left out, so that get can read them.
 */
function cutTable(t, n, maxTokens) {
  const out = { ...t };
  let left = n;
  for (const k of SECTIONS) {
    if (!t[k]) continue;
    out[k] = t[k].slice(0, left);
    left -= out[k].length;
  }
  const rest = allRows(t).slice(n);
  out.truncated = true;
  let note = `cut at about ${maxTokens} tokens: ${plural(rest.length, 'more row')} not shown`;
  if (t.open) {
    note += '; select fewer rows or columns';
  } else if (t.paged) {
    note += `; offset=${t.offset + n} reads on`;
  } else if (t.columns[0] === 'rid') {
    note += ': ' + rest.map((r) => r[0]).join(', ');
  }
  out.notes = [...(t.notes || []), note];
  return out;
}

function render(t, format) {
  if (format === 'json') return JSON.stringify(api.toJson(t));
  const { lines, footer } = api.toTsv(t);
  return lines.concat(footer).join('\n');
}

/**
 * The text of a table result, TSV or JSON, at about MAX_TOKENS or less. A cut keeps whole rows in list order, so the
 * text stays valid TSV or valid JSON, and its last note says how many rows it left out and how to read them.
 */
export function tableText(t, format = 'tsv', maxTokens = MAX_TOKENS) {
  const whole = render(t, format);
  if (estimateTokens(whole) <= maxTokens) return whole;
  // the rows that fit after the text with no row, whose note names every row that it leaves out, so it is the longest
  const rows = allRows(t);
  let budget = maxTokens - estimateTokens(render(cutTable(t, 0, maxTokens), format));
  let n = 0;
  for (; n < rows.length; n++) {
    const cost = estimateTokens(format === 'json' ? JSON.stringify(rows[n]) : rows[n].map(api.cell).join('\t')) + 1;
    if (cost > budget) break;
    budget -= cost;
  }
  // a heading line of a part of a need costs a little too: take one more row off until the text fits
  let text = render(cutTable(t, n, maxTokens), format);
  while (n > 0 && estimateTokens(text) > maxTokens) text = render(cutTable(t, --n, maxTokens), format);
  return text;
}

/**
 * The JSON of get with detail=full, at about MAX_TOKENS or less: {records, missing, notes}, plus omitted when it is cut.
 * A cut keeps whole records in the order asked and leaves out the rest: omitted lists their ids and a note says so, so
 * the text always parses. The first record is always sent whole, because no smaller answer holds it.
 */
export function recordsText(o, maxTokens = MAX_TOKENS) {
  const whole = JSON.stringify(o);
  if (estimateTokens(whole) <= maxTokens) return whole;
  const shape = (records, omitted) => ({
    ...o, records, omitted,
    notes: [...(o.notes || []), `cut at about ${maxTokens} tokens: ${plural(omitted.length, 'record')} not sent, ` +
      `listed in omitted; ask for ${omitted.length === 1 ? 'it' : 'them'} in another call, or name fields`],
  });
  let budget = maxTokens - estimateTokens(JSON.stringify(shape([], o.records.map((r) => r.rid))));
  const kept = [];
  const omitted = [];
  for (const r of o.records) {
    const cost = estimateTokens(JSON.stringify(r)) + 1;
    if (omitted.length || (kept.length && cost > budget)) {
      omitted.push(r.rid);
      continue;
    }
    kept.push(r);
    budget -= cost;
  }
  return JSON.stringify(shape(kept, omitted));
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
      return r.json ? recordsText(r.json) : tableText(r, 'tsv');
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
