// Read-only SQL guard (contract: "Read-only SQL guard").
// Strip string literals, quoted identifiers and comments; require exactly one statement whose
// first keyword is SELECT, WITH, VALUES or EXPLAIN; reject any write or session keyword outside
// literals, a recursive CTE, and a function that is not on ALLOWED_FUNCTIONS; cap the width of
// printf() and format(); append LIMIT n when the statement has none. The Worker also opens the
// database with PRAGMA query_only=ON and a hard heap limit, stops stepping at the row cap and
// checks total_changes() afterwards. The twin of this file in the research repository follows
// site/worker/test/parity.json, which holds the lists below.

export const BANNED = [
  'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'UPSERT', 'CREATE', 'DROP', 'ALTER', 'ATTACH', 'DETACH',
  'PRAGMA', 'VACUUM', 'REINDEX', 'ANALYZE', 'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE',
  'TEMP', 'TEMPORARY',
];
const BANNED_RE = new RegExp('\\b(' + BANNED.join('|') + ')\\b', 'i');
const FIRST = new Set(['SELECT', 'WITH', 'VALUES', 'EXPLAIN']);
export const MAX_SQL_CHARS = 10000;
// SQLite's white space is space, tab, LF, VT, FF and CR. These are white space to JavaScript (\s) or to Python
// (str.isspace) and not to SQLite.
export const ODD_SPACE_CODES = [0x1c, 0x1d, 0x1e, 0x1f, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004,
  0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff];
const ODD_SPACE = new RegExp('[' + ODD_SPACE_CODES.map((c) => String.fromCharCode(c)).join('') + ']');

// The functions a statement may call; any other is refused. Left out on purpose: the functions that build a value
// larger than their input from one reference to it (hex, unhex, quote, char, json_quote, zeroblob, randomblob, the
// JSON builders such as json_array, json_object and json_set, and printf() conversions %q, %Q and %w), the row
// generators that the statement budget cannot size (json_each, json_tree), and the functions that need the text of
// the full-text index, which the store does not hold (snippet, offsets). printf() and format() need a literal format
// string, and their widths and precisions are at most MAX_WIDTH. replace() is refused already: REPLACE is a write
// keyword. A value that grows through || or concat() stops at the heap limit of the Worker (db.js).
export const ALLOWED_FUNCTIONS = [
  // scalar
  'abs', 'changes', 'coalesce', 'concat', 'concat_ws', 'format', 'glob', 'if', 'ifnull', 'iif', 'instr',
  'last_insert_rowid', 'length', 'like', 'likelihood', 'likely', 'lower', 'ltrim', 'max', 'min', 'nullif',
  'octet_length', 'printf', 'random', 'round', 'rtrim', 'sign', 'sqlite_version', 'substr', 'substring',
  'total_changes', 'trim', 'typeof', 'unicode', 'unlikely', 'upper',
  // aggregate and window
  'avg', 'count', 'group_concat', 'string_agg', 'sum', 'total',
  'cume_dist', 'dense_rank', 'first_value', 'lag', 'last_value', 'lead', 'nth_value', 'ntile', 'percent_rank',
  'rank', 'row_number',
  // date and time
  'date', 'datetime', 'julianday', 'strftime', 'time', 'timediff', 'unixepoch',
  // math
  'acos', 'acosh', 'asin', 'asinh', 'atan', 'atan2', 'atanh', 'ceil', 'ceiling', 'cos', 'cosh', 'degrees', 'exp',
  'floor', 'ln', 'log', 'log10', 'log2', 'mod', 'pi', 'pow', 'power', 'radians', 'sin', 'sinh', 'sqrt', 'tan',
  'tanh', 'trunc',
  // JSON, read only
  'json', 'json_array_length', 'json_error_position', 'json_extract', 'json_type', 'json_valid',
  // full text, and the schema as a table
  'matchinfo',
  'pragma_table_info', 'pragma_table_xinfo', 'pragma_index_list', 'pragma_index_info', 'pragma_index_xinfo',
  'pragma_foreign_key_list',
];
// the words that can come before "(" and do not call a function. A name after AS is a type name or an alias, and
// the name of a CTE with a column list is not a call either.
export const NOT_FUNCTIONS = [
  'all', 'and', 'any', 'as', 'asc', 'between', 'by', 'case', 'cast', 'collate', 'current', 'desc', 'distinct',
  'else', 'end', 'escape', 'except', 'exclude', 'exists', 'filter', 'first', 'following', 'from', 'groups',
  'having', 'in', 'intersect', 'is', 'join', 'last', 'limit', 'match', 'materialized', 'not', 'null', 'nulls',
  'offset', 'on', 'or', 'over', 'partition', 'preceding', 'range', 'rows', 'select', 'then', 'unbounded', 'union',
  'using', 'values', 'when', 'where', 'window', 'with',
];
export const MAX_WIDTH = 1000;
// printf() conversions that double a quote character: nested, they grow a value without bound
export const PRINTF_REFUSED = ['q', 'Q', 'w'];
const ALLOWED = new Set(ALLOWED_FUNCTIONS);
const NOT_FN = new Set(NOT_FUNCTIONS);

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
  // a character that JavaScript or Python takes as white space and SQLite does not: the guard and SQLite would
  // read different statements, and the guard's twin in the research repository would read a third
  const odd = ODD_SPACE.exec(bare);
  if (odd) {
    throw new GuardError('U+' + odd[0].charCodeAt(0).toString(16).toUpperCase().padStart(4, '0') +
      ' outside a literal: SQLite does not read it as white space');
  }
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
  if (/\brecursive\b/i.test(body)) throw new GuardError('a recursive CTE runs as long as the statement says; it is not accepted');
  checkFunctions(sql, semi >= 0 ? strip(sql, true).slice(0, semi) : strip(sql, true));
  // offsets in `bare` match `sql`, so the trailing semicolon is cut from the original text
  let run = semi >= 0 ? sql.slice(0, semi) + sql.slice(semi + 1) : sql;
  const limited = /\blimit\b/i.test(body);
  if (!limited) run = run.replace(/\s+$/, '') + '\nLIMIT ' + (limit | 0);
  return { sql: run, appendedLimit: !limited };
}

/** True when the word AS (not part of a longer name) and white space only come before offset i of text. */
function afterAs(text, i) {
  let k = i;
  while (k > 0 && /\s/.test(text[k - 1])) k--;
  return k >= 2 && text.slice(k - 2, k).toLowerCase() === 'as' && !/[\w$]/.test(text[k - 3] || '');
}

/**
 * Every name before "(" in `named` (the statement with literals and comments blanked and quoted names kept) must be
 * a word of NOT_FUNCTIONS, a name after AS, the name of a CTE where the CTE is defined with a column list, or a
 * function of ALLOWED_FUNCTIONS. printf() and format() need a literal format string, then "," or ")"; its widths and
 * precisions are at most MAX_WIDTH, with no "*", and it has no conversion of PRINTF_REFUSED.
 */
export function checkFunctions(sql, named) {
  const defs = new Set();
  for (const m of named.matchAll(/(?:\bwith\b|,)\s*([A-Za-z_][\w$]*)\s*\([^()]*\)\s*as\s*(?:not\s+)?(?:materialized\s*)?\(/dgi)) {
    defs.add(m.indices[1][0]);
  }
  for (const m of named.matchAll(/([A-Za-z_][\w$]*)\s*\(/g)) {
    const name = m[1].toLowerCase();
    if (NOT_FN.has(name) || defs.has(m.index) || afterAs(named, m.index)) continue;
    if (!ALLOWED.has(name)) throw new GuardError('function not allowed: ' + name + '()');
    if (name !== 'printf' && name !== 'format') continue;
    // the format string is read from `sql`: `named` blanks literals at the same offsets
    let at = m.index + m[0].length;
    while (/\s/.test(sql[at] || '')) at++;
    if (sql[at] !== "'") throw new GuardError(name + '() needs a literal format string');
    let j = at + 1;
    while (j < sql.length && !(sql[j] === "'" && sql[j + 1] !== "'")) j += sql[j] === "'" ? 2 : 1;
    let k = j + 1;
    while (/\s/.test(sql[k] || '')) k++;
    if (sql[k] !== ',' && sql[k] !== ')') throw new GuardError(name + '() needs a literal format string');
    for (const w of sql.slice(at + 1, j).matchAll(/%[-+ #0,!]*(\*|\d+)?(?:\.(\*|\d+))?(?:ll?)?(.?)/g)) {
      for (const v of [w[1], w[2]]) {
        if (v === '*' || (v && Number(v) > MAX_WIDTH)) {
          throw new GuardError(name + '() width or precision over ' + MAX_WIDTH + '; it is not accepted');
        }
      }
      if (PRINTF_REFUSED.includes(w[3])) throw new GuardError(name + '() conversion %' + w[3] + ' is not accepted');
    }
  }
}
