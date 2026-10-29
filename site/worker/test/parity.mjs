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
import { ODD_SPACE_CODES } from '../guard.js';

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
      // self-hosted last: a stable split of a list, and the order of the entities of a name search
      hostedFirst: fx.rank.hostedFirst.map(([items, sh]) => [items, sh, rank.hostedFirst(items, (x) => sh.includes(x))]),
      // the best verdict of an entity: of its hosted records, of all its records only when every one is self-hosted
      bestVorder: fx.rank.bestVorder.map(([members]) => [members, rank.bestVorder(members)]),
      // a case with members ([[vorder, self_hosted]] of each entity's records) derives best_vorder and self_hosted from
      // them, so it shows that a self-hosted record never lifts its vendor; the twin reads best_vorder and self_hosted
      entityOrder: fx.rank.entityOrder.map((c) => {
        const m = c.members;
        const bv = m ? Object.fromEntries(Object.entries(m).map(([e, r]) => [e, rank.bestVorder(r)])) : c.best_vorder;
        const sh = m ? Object.keys(m).filter((e) => m[e].every(([, s]) => s)).sort() : c.self_hosted;
        return {
          ...(m ? { members: m } : {}), hits: c.hits, best_vorder: bv, self_hosted: sh,
          order: rank.sortEntities(c.hits.map(([eid, score]) => ({ eid, score })), (e) => bv[e] ?? 99,
            (e) => sh.includes(e)).map((h) => h.eid),
        };
      }),
      names: {
        aliases: fx.rank.names.aliases,
        cases: fx.rank.names.cases.map(([q]) => [q, rank.scoreNames(idx, q).map((h) => [h.eid, h.score]).sort(byScore)]),
      },
    },
    // the lists that the guard's twin copies: a change of a list shows here, and in the cases below
    guard_lists: {
      banned: guard.BANNED,
      odd_space_codes: guard.ODD_SPACE_CODES,
      max_sql_chars: guard.MAX_SQL_CHARS,
      allowed_functions: guard.ALLOWED_FUNCTIONS,
      not_functions: guard.NOT_FUNCTIONS,
      max_width: guard.MAX_WIDTH,
      printf_refused: guard.PRINTF_REFUSED,
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

// the characters that the guard refuses, and the zero-width ones, are written as escapes
const INVISIBLE = new RegExp('[' + ODD_SPACE_CODES.concat([0x200b, 0x200c, 0x200d, 0x200e, 0x200f])
  .map((c) => String.fromCharCode(c)).join('') + ']', 'g');

/** JSON with one case on each line, so the diff of a rule change shows the cases it moved. */
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
    ['editDistance', 'fuzzBudget', 'bm25', 'hostedFirst', 'bestVorder', 'entityOrder'].map((k) => '    ' + one(k) + ': ' + arr(r[k], '    ')).join(',\n') + ',',
    '    "names": {',
    '      "aliases": ' + arr(r.names.aliases, '      ') + ',',
    '      "cases": ' + arr(r.names.cases, '      '),
    '    }',
    '  },',
    '  "guard_lists": {',
    Object.keys(fx.guard_lists).map((k) => '    ' + one(k) + ': ' + one(fx.guard_lists[k])).join(',\n'),
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
