// Search ranking (contract: "Search ranking"). The local CLI implements the same arithmetic.
//
// Full text: BM25 over matchinfo(text_fts, 'pcnalx'), summed over phrases and columns:
//   score = sum_i sum_j  w_j * idf_ij * tf_ij * (k1 + 1) / (tf_ij + k1 * (1 - b + b * dl_j / avgdl_j))
//   idf_ij = ln(1 + (N - df_ij + 0.5) / (df_ij + 0.5))     (always positive)
// where tf_ij = hits of phrase i in column j of this row, df_ij = rows with a hit in column j,
// N = rows in the table, dl_j = tokens in column j of this row, avgdl_j = mean tokens in column j.
// k1 = 1.2, b = 0.75. `matched` lists the columns where any phrase has a hit in this row.
//
// Names: an entity scores the best of its aliases: exact 100, alias prefix 60, alias substring 40,
// else 30 when every query token meets a token of that alias within edit distance 1 (query token
// length 4-7) or 2 (length >= 8); a query token under 4 characters must equal an alias token.
// The fuzzy tier counts each distinct query token once, and it runs only for a query of at most
// MAX_FUZZY_TOKENS distinct tokens: each token is compared with every token of the index, so a long
// query would cost one full pass for each word (the twin in the research repository follows this).
//
// Self-hosted last: a self-hosted offer is software or a node that the user installs and runs (record.self_hosted = 1).
// The site is for users with no hardware, so it is the last resort. self_hosted ascending is the first sort key of every
// list of records: every hosted item in its order, then every self-hosted item in its order (hostedFirst). In a name
// search, an entity whose every record is self-hosted comes after every other entity (sortEntities). The twins in the
// research repository are hosted_first() and name_scores() of fr.py.

import { normalize, tokens } from './text.js';

export const FTS_COLUMNS = ['name', 'offer', 'limits', 'egress', 'identity', 'access', 'notes', 'evidence', 'extras'];
export const WEIGHTS = [4, 2, 1.5, 1.5, 1.5, 1, 1, 0.7, 0.5];
export const K1 = 1.2;
export const B = 0.75;

/** BM25 from a matchinfo('pcnalx') blob (Uint8Array of little-endian uint32). */
export function bm25(blob, weights = WEIGHTS) {
  const u = new Uint32Array(blob.buffer, blob.byteOffset, blob.byteLength >>> 2);
  const p = u[0];
  const c = u[1];
  const n = u[2];
  const a = 3; // c averages
  const l = 3 + c; // c lengths
  const x = 3 + 2 * c; // 3 * p * c
  let score = 0;
  const hit = new Array(c).fill(false);
  for (let i = 0; i < p; i++) {
    for (let j = 0; j < c; j++) {
      const k = x + 3 * (i * c + j);
      const tf = u[k];
      if (!tf) continue;
      hit[j] = true;
      const df = u[k + 2];
      const idf = Math.log(1 + (n - df + 0.5) / (df + 0.5));
      const avg = u[a + j] || 1;
      const dl = u[l + j];
      const w = weights[j] ?? 1;
      score += (w * idf * tf * (K1 + 1)) / (tf + K1 * (1 - B + (B * dl) / avg));
    }
  }
  const matched = [];
  for (let j = 0; j < c; j++) if (hit[j]) matched.push(FTS_COLUMNS[j] || 'c' + j);
  return { score, matched };
}

/** Levenshtein distance, or max + 1 as soon as it is known to exceed max. */
export function editDistance(a, b, max) {
  const A = [...a];
  const Bv = [...b];
  if (Math.abs(A.length - Bv.length) > max) return max + 1;
  let prev = new Array(Bv.length + 1);
  let cur = new Array(Bv.length + 1);
  for (let j = 0; j <= Bv.length; j++) prev[j] = j;
  for (let i = 1; i <= A.length; i++) {
    cur[0] = i;
    let rowMin = cur[0];
    for (let j = 1; j <= Bv.length; j++) {
      const cost = A[i - 1] === Bv[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (cur[j] < rowMin) rowMin = cur[j];
    }
    if (rowMin > max) return max + 1;
    [prev, cur] = [cur, prev];
  }
  return prev[Bv.length];
}

/** Allowed edit distance for a query token, by its length in characters (0 = no fuzzy match). */
export function fuzzBudget(tok) {
  const n = [...tok].length;
  if (n >= 8) return 2;
  if (n >= 4) return 1;
  return 0;
}

export const MAX_FUZZY_TOKENS = 8;

/**
 * Build the name index from rows of the alias table: [{eid, alias, kind}].
 * Keeps each distinct normalised alias once with its entities, and a token -> aliases map.
 */
export function buildNameIndex(aliasRows) {
  const byNorm = new Map(); // norm alias -> Set(eid)
  for (const r of aliasRows) {
    const k = normalize(r.alias);
    if (!k) continue;
    let s = byNorm.get(k);
    if (!s) byNorm.set(k, (s = new Set()));
    s.add(r.eid);
  }
  const aliases = [...byNorm.keys()];
  return indexFromNormalized(aliases, aliases.map((k) => [...byNorm.get(k)]));
}

/**
 * The name index from aliases that are normalised already, each with its entities. The build writes them (site_gen.py
 * name_index), so the Worker skips the normalisation of every alias on the first search of an isolate.
 */
export function indexFromNormalized(aliases, eids) {
  const tokenMap = new Map(); // token -> alias indexes
  aliases.forEach((k, idx) => {
    for (const t of tokens(k)) {
      let s = tokenMap.get(t);
      if (!s) tokenMap.set(t, (s = []));
      if (s[s.length - 1] !== idx) s.push(idx);
    }
  });
  return { aliases, eids, tokenMap, tokenList: [...tokenMap.keys()] };
}

const KIND = { 100: 'exact', 60: 'prefix', 40: 'substring', 30: 'fuzzy' };

/**
 * Score entities against a query. Returns [{eid, score, how, alias}] (unsorted), best per entity.
 */
export function scoreNames(index, query) {
  const q = normalize(query);
  const best = new Map();
  if (!q) return [];
  const put = (idx, score) => {
    for (const eid of index.eids[idx]) {
      const cur = best.get(eid);
      if (!cur || cur.score < score) best.set(eid, { eid, score, how: KIND[score], alias: index.aliases[idx] });
    }
  };
  index.aliases.forEach((k, idx) => {
    if (k === q) put(idx, 100);
    else if (k.startsWith(q)) put(idx, 60);
    else if (k.includes(q)) put(idx, 40);
  });
  // fuzzy tier: every query token meets a token of the same alias within its budget
  // (budget 0 for tokens under 4 characters, so those must match a token exactly)
  let hits = null;
  const qts = [...new Set(tokens(q))];
  for (const qt of qts.length <= MAX_FUZZY_TOKENS ? qts : []) {
    const max = fuzzBudget(qt);
    const set = new Set();
    if (!max) {
      for (const idx of index.tokenMap.get(qt) || []) set.add(idx);
    } else {
      for (const t of index.tokenList) {
        if (editDistance(qt, t, max) <= max) for (const idx of index.tokenMap.get(t)) set.add(idx);
      }
    }
    hits = hits ? new Set([...hits].filter((i) => set.has(i))) : set;
    if (!hits.size) break;
  }
  if (hits) for (const idx of hits) put(idx, 30);
  return [...best.values()];
}

/** Every hosted item, then every self-hosted one; each part keeps the order it had (a stable partition). */
export function hostedFirst(items, isSelfHosted) {
  const hosted = [];
  const last = [];
  for (const x of items) (isSelfHosted(x) ? last : hosted).push(x);
  return hosted.concat(last);
}

/**
 * The entities of a name search, best first: score, then best verdict (bestVorder(eid), lower is better), then eid; then
 * every entity whose every record is self-hosted (allSelfHosted(eid)) after every other entity. hits: [{eid, score}].
 */
export function sortEntities(hits, bestVorder, allSelfHosted) {
  const ranked = [...hits].sort((a, b) => b.score - a.score || bestVorder(a.eid) - bestVorder(b.eid) ||
    (a.eid < b.eid ? -1 : a.eid > b.eid ? 1 : 0));
  return hostedFirst(ranked, (h) => allSelfHosted(h.eid));
}
