// The parity fixture: site/worker/test/parity.json holds inputs of the Worker's text, ranking and SQL guard rules,
// and the output of each JavaScript rule. run.mjs checks that the rules still give those outputs (issue #7); the
// research repository runs its Python twins on the same inputs at a pinned commit of this repository.
//
//   node site/worker/test/parity.mjs --write    after a deliberate change of a rule: recompute every output
//
// A change of a rule therefore changes parity.json in the same pull request. Merge it here first; then the research
// repository moves its pin and changes its twin in one pull request (publish/README.md, "Parity").

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), 'parity.json');

export function load() {
  return JSON.parse(readFileSync(FIXTURE, 'utf8'));
}

const byScore = (x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0);

/** The fixture with every output recomputed by the JavaScript rules. */
export function compute(fx, { text, rank, guard }) {
  const idx = rank.buildNameIndex(fx.rank.names.aliases);
  return {
    about: fx.about,
    version: fx.version,
    text: {
      normalize: fx.text.normalize.map(([s]) => [s, text.normalize(s)]),
      tokens: fx.text.tokens.map(([s]) => [s, text.tokens(text.normalize(s))]),
      ftsMatch: fx.text.ftsMatch.map(([s]) => [s, text.ftsMatch(s)]),
      ftsText: fx.text.ftsText.map(([s]) => [s, text.ftsText(s)]),
    },
    rank: {
      editDistance: fx.rank.editDistance.map(([a, b, max]) => [a, b, max, rank.editDistance(a, b, max)]),
      fuzzBudget: fx.rank.fuzzBudget.map(([s]) => [s, rank.fuzzBudget(s)]),
      bm25: fx.rank.bm25.map((c) => {
        const blob = new Uint8Array(new Uint32Array(c.matchinfo).buffer);
        const r = c.weights ? rank.bm25(blob, c.weights) : rank.bm25(blob);
        return { matchinfo: c.matchinfo, weights: c.weights, score: r.score, matched: r.matched };
      }),
      names: {
        aliases: fx.rank.names.aliases,
        cases: fx.rank.names.cases.map(([q]) => [q, rank.scoreNames(idx, q).map((h) => [h.eid, h.score]).sort(byScore)]),
      },
    },
    guard: fx.guard.map((c) => {
      try {
        const r = guard.guard(c.sql, c.limit);
        return { sql: c.sql, limit: c.limit, result: ['ok', r.sql, r.appendedLimit] };
      } catch (e) {
        if (!(e instanceof guard.GuardError)) throw e;
        return { sql: c.sql, limit: c.limit, result: ['err'] };
      }
    }),
  };
}

const INVISIBLE = new RegExp('[' + String.fromCharCode(0x2000) + '-' + String.fromCharCode(0x200f, 0x2028, 0x2029, 0xfeff) + ']', 'g');

/** JSON with one case on each line, so the diff of a rule change shows the cases it moved. Invisible characters
 * (U+2000 to U+200F, U+2028, U+2029, U+FEFF) are written as escapes. */
export function format(fx) {
  const one = (x) => JSON.stringify(x).replace(INVISIBLE, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
  const arr = (a, ind) => '[\n' + a.map((x) => ind + '  ' + one(x)).join(',\n') + '\n' + ind + ']';
  const t = fx.text;
  const r = fx.rank;
  return [
    '{',
    '  "about": ' + one(fx.about) + ',',
    '  "version": ' + one(fx.version) + ',',
    '  "text": {',
    Object.keys(t).map((k) => '    ' + one(k) + ': ' + arr(t[k], '    ')).join(',\n'),
    '  },',
    '  "rank": {',
    ['editDistance', 'fuzzBudget', 'bm25'].map((k) => '    ' + one(k) + ': ' + arr(r[k], '    ')).join(',\n') + ',',
    '    "names": {',
    '      "aliases": ' + arr(r.names.aliases, '      ') + ',',
    '      "cases": ' + arr(r.names.cases, '      '),
    '    }',
    '  },',
    '  "guard": ' + arr(fx.guard, '  '),
    '}',
  ].join('\n') + '\n';
}

if (process.argv.includes('--write')) {
  const text = await import('../text.js');
  const rank = await import('../rank.js');
  const guard = await import('../guard.js');
  const out = compute(load(), { text, rank, guard });
  writeFileSync(FIXTURE, format(out));
  console.log('wrote ' + FIXTURE);
}
