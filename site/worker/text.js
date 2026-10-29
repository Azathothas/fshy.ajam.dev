// Text rules shared with publish/build.py.
// ftsText() is the exact twin of build.py fts_text(): a CJK run is kept and followed by its
// overlapping bigrams. Queries use the bigrams only (ftsMatch), so a query term always meets
// a token the index holds.

// Same ranges as build.py CJK: kana, CJK extension A, unified ideographs, hangul syllables.
const CJK_RUN = /[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF]+/gu;

function bigrams(t) {
  const out = [];
  for (let i = 0; i < t.length - 1; i++) out.push(t.slice(i, i + 2));
  return out;
}

/** Index text: identical to build.py fts_text(). All ranges are BMP, so UTF-16 indexing is safe. */
export function ftsText(s) {
  return String(s).replace(CJK_RUN, (t) => t + ' ' + (t.length > 1 ? bigrams(t).join(' ') : t));
}

/** Query side of the CJK rule: a run longer than one character becomes its bigrams. */
export function cjkQuery(s) {
  return String(s).replace(CJK_RUN, (t) => (t.length > 1 ? ' ' + bigrams(t).join(' ') + ' ' : t));
}

/** Python str.casefold() for the cases toLowerCase() misses in this corpus. */
export function casefold(s) {
  return s.toLowerCase().replace(/\u00DF/g, 'ss').replace(/\u1E9E/g, 'ss').replace(/\u03C2/g, '\u03C3');
}

/** Name normaliser: NFKC, casefold, strip combining marks, recompose, collapse whitespace. */
export function normalize(s) {
  if (s == null) return '';
  s = String(s);
  // printable ASCII needs only lower-casing (NFKC, casefold and mark stripping leave it unchanged)
  if (/^[ -~]*$/.test(s)) return s.toLowerCase().replace(/ +/g, ' ').trim();
  let t = casefold(s.normalize('NFKC'));
  t = t.normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC');
  return t.replace(/\s+/gu, ' ').trim();
}

/** Word tokens of a normalised string (letters and digits). */
export function tokens(s) {
  return s.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

/**
 * FTS4 MATCH string for a free-text query: AND of the words; a word of 3+ characters becomes
 * a prefix term (word*); a word containing punctuation is quoted as a phrase (no prefix).
 * A term that repeats is kept once: the AND of a term with itself matches the same rows, and each
 * copy would cost one more pass over the index. Returns '' when nothing searchable is left.
 */
export function ftsMatch(q) {
  const words = cjkQuery(normalize(q)).split(/\s+/u).filter(Boolean);
  const terms = [];
  for (let w of words) {
    w = w.replace(/"/g, '');
    if (!/[\p{L}\p{N}]/u.test(w)) continue;
    const t = /[^\p{L}\p{N}]/u.test(w) ? '"' + w + '"' : [...w].length >= 3 ? w + '*' : w;
    if (!terms.includes(t)) terms.push(t);
  }
  return terms.join(' ');
}

/** Clip a cell for display. */
export function clip(s, n) {
  if (s == null) return s;
  const t = String(s);
  if (t.length <= n) return t;
  let k = Math.max(0, n - 3);
  const c = t.charCodeAt(k - 1);
  if (c >= 0xd800 && c <= 0xdbff) k--; // never split a surrogate pair
  return t.slice(0, k) + '...';
}
