// Read-only SQL guard (contract: "Read-only SQL guard").
// Strip string literals, quoted identifiers and comments; require exactly one statement whose
// first keyword is SELECT, WITH, VALUES or EXPLAIN; reject any write or session keyword outside
// literals; append LIMIT n when the statement has none. The Worker also opens the database with
// PRAGMA query_only=ON, stops stepping at the row cap and checks total_changes() afterwards.

export const BANNED = [
  'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'UPSERT', 'CREATE', 'DROP', 'ALTER', 'ATTACH', 'DETACH',
  'PRAGMA', 'VACUUM', 'REINDEX', 'ANALYZE', 'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE',
  'TEMP', 'TEMPORARY',
];
const BANNED_RE = new RegExp('\\b(' + BANNED.join('|') + ')\\b', 'i');
const FIRST = new Set(['SELECT', 'WITH', 'VALUES', 'EXPLAIN']);
export const MAX_SQL_CHARS = 10000;

export class GuardError extends Error {}

/**
 * Blank out every literal, quoted identifier and comment (same length, so offsets in the result
 * match the original), scanning left to right so a quote inside a comment, or a comment marker
 * inside a string, is handled correctly. Throws on an unterminated literal or comment.
 * With keepIdents, a quoted identifier ("x", `x` or [x]) keeps its name and loses only its quotes.
 */
export function strip(sql, keepIdents = false) {
  const out = sql.split('');
  const blank = (a, b) => {
    for (let k = a; k < b; k++) if (out[k] !== '\n') out[k] = ' ';
  };
  const n = sql.length;
  let i = 0;
  while (i < n) {
    const c = sql[i];
    const d = sql[i + 1];
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1;
      for (;;) {
        if (j >= n) throw new GuardError('unterminated quoted string');
        if (sql[j] === c) {
          if (sql[j + 1] === c) { j += 2; continue; }
          break;
        }
        j++;
      }
      if (keepIdents && c !== "'") out[i] = out[j] = ' ';
      else blank(i, j + 1);
      i = j + 1;
    } else if (c === '[') {
      const j = sql.indexOf(']', i + 1);
      if (j < 0) throw new GuardError('unterminated [identifier]');
      if (keepIdents) out[i] = out[j] = ' ';
      else blank(i, j + 1);
      i = j + 1;
    } else if (c === '-' && d === '-') {
      const j = sql.indexOf('\n', i + 2);
      const e = j < 0 ? n : j;
      blank(i, e);
      i = e;
    } else if (c === '/' && d === '*') {
      const j = sql.indexOf('*/', i + 2);
      if (j < 0) throw new GuardError('unterminated /* comment');
      blank(i, j + 2);
      i = j + 2;
    } else {
      i++;
    }
  }
  return out.join('');
}

/**
 * Check one read-only statement and return the SQL to run (with LIMIT appended if absent).
 * Throws GuardError with a message meant for the caller.
 */
export function guard(sql, limit) {
  if (typeof sql !== 'string' || !sql.trim()) throw new GuardError('empty query');
  if (sql.length > MAX_SQL_CHARS) throw new GuardError('query longer than ' + MAX_SQL_CHARS + ' characters');
  if (sql.includes('\u0000')) throw new GuardError('NUL byte in query');
  const bare = strip(sql);
  // JavaScript takes U+FEFF as white space and SQLite does not, so the guard and SQLite would read two statements
  if (bare.includes('\ufeff')) throw new GuardError('U+FEFF (a byte order mark) outside a literal; SQLite does not read it as white space');
  // one statement: a single trailing semicolon is tolerated and removed
  const semi = bare.search(/;\s*$/);
  const body = semi >= 0 ? bare.slice(0, semi) : bare;
  if (body.includes(';')) throw new GuardError('one statement only');
  const first = (body.match(/^\s*([A-Za-z]+)/) || [])[1];
  if (!first || !FIRST.has(first.toUpperCase())) {
    throw new GuardError('the statement must start with SELECT, WITH, VALUES or EXPLAIN');
  }
  const bad = body.match(BANNED_RE);
  if (bad) throw new GuardError('keyword not allowed in a read-only query: ' + bad[1].toUpperCase());
  // offsets in `bare` match `sql`, so the trailing semicolon is cut from the original text
  let run = semi >= 0 ? sql.slice(0, semi) + sql.slice(semi + 1) : sql;
  const limited = /\blimit\b/i.test(body);
  if (!limited) run = run.replace(/\s+$/, '') + '\nLIMIT ' + (limit | 0);
  return { sql: run, appendedLimit: !limited };
}
