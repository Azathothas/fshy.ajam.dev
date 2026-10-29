/* fshy wiki: freshness, filter chips, name search (MiniSearch), full-text search page, compare page. No framework. */
(function () {
  'use strict';
  var today = new Date().toISOString().slice(0, 10);
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  // lang on a run of a non-Latin script (pages.py lang_wrap)
  var RUN = /[぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿가-힯ᄀ-ᇿ㄰-㆏][　-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿가-힯ᄀ-ᇿ㄰-㆏＀-￯]*|[Ѐ-ӿ]+(?:[ -][Ѐ-ӿ]+)*|[؀-ۿ]+(?: [؀-ۿ]+)*|[֐-׿]+(?: [֐-׿]+)*|[฀-๿]+/g;
  function lng(r) { var c = r.charCodeAt(0); return c < 1280 ? 'ru' : c < 1536 ? 'he' : c < 2048 ? 'ar' : c < 3712 ? 'th' : /[぀-ヿㇰ-ㇿ]/.test(r) ? 'ja' : /[가-힯ᄀ-ᇿ㄰-㆏]/.test(r) ? 'ko' : 'zh'; }
  function txt(s) { return esc(s).replace(RUN, function (r) { return '<span lang="' + lng(r) + '">' + r + '</span>'; }); }
  // verdict terms in vorder and their short labels (publish/pages.py VERDICT_LABEL)
  var VT = ['qualifies', 'qualifies-with-caveat', 'trial-only', 'paid-only', 'fails-identity', 'fails-egress', 'fails-quota', 'dead'];
  var VL = ['★ qualifies', 'caveat', 'trial', 'paid', 'fails: identity', 'fails: egress', 'fails: quota', 'dead'];
  // topic names from the topic bar, so this file holds no copy of the list
  var TN = {};
  $$('.topics a').forEach(function (a) { var m = /^\/t\/([^/]+)\/$/.exec(a.getAttribute('href')); if (m) TN[m[1]] = a.textContent; });
  function pill(v) { var i = typeof v === 'number' ? v : VT.indexOf(v); return '<span class="v v-' + esc(VT[i] || v) + '">' + esc(VL[i] || v) + '</span>'; }
  function usd(v, sfx) { return v == null ? '' : 'USD ' + (v < 1000 ? String(+(+v).toFixed(2)) : (+v).toFixed(0)) + sfx; }
  function topics(ts) { return (Array.isArray(ts) ? ts : String(ts || '').split(',')).filter(Boolean).map(function (t) { return TN[t] || t; }).join(', '); }
  function lane(vs) { // list class from the longest verdict label, as pages.py lane()
    var w = Math.max.apply(null, vs.map(function (v) { var i = VT.indexOf(v); return (VL[i] || v || '').length; }).concat([0]));
    return 'list' + (w > 11 ? '' : w > 6 ? ' lm' : ' ls');
  }
  // the line of a row, as llms.py headline()
  function line(s) {
    s = String(s || '').trim().replace(/^(?:quoted|verbatim|quote):\s*/i, '');
    if (/(\.\.\.|…)$/.test(s)) { var t = s.replace(/\s*\S*(\.\.\.|…)$/, '').replace(/[ ,;:(-]+$/, ''); if (t.length >= 20) { s = t + '...'; } }
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ---------------------------------------------------------------- keep the current topic visible in the scrolling topic bar
  var tn = $('.topics'), tc = tn && $('[aria-current]', tn);
  if (tc && tn.scrollWidth > tn.clientWidth) {
    tn.scrollLeft += tc.getBoundingClientRect().left - tn.getBoundingClientRect().left - (tn.clientWidth - tc.offsetWidth) / 2;
  }

  // ---------------------------------------------------------------- freshness, computed against today
  function fresh(root) {
    $$('.fr:not(.done)', root).forEach(function (b) {
      var h = b.closest('[data-stale-on]'), so = b.getAttribute('data-stale-on') || (h && h.getAttribute('data-stale-on'));
      if (!so || so === 'None') { return; }
      var stale = so <= today, inh = b.getAttribute('data-basis') === 'inherited';
      b.className = 'fr ' + (stale ? 'stale' : 'fresh');
      b.textContent = (stale ? 'stale since ' : 'fresh until ') + so + (inh ? ', inherited' : '');
    });
  }
  fresh();
  $$('[data-f]').forEach(function (r) {
    var so = r.getAttribute('data-stale-on');
    if (so && so !== 'None' && so > today) { r.setAttribute('data-f', (r.getAttribute('data-f') + ' fresh').trim()); }
  });

  // ---------------------------------------------------------------- filter chips (class toggles on <html>), kept in ?f= and ?i=
  var chips = $('.chips'), ifl = $('.chips .ifilter'), clear = $('.chips .clear');
  // shown rows come from the attributes, so the count reads no layout; the writes follow the reads
  function recount() {
    var c = $('.chips .count'); if (!c) { return; }
    var on = $$('.chips [aria-pressed=true]').map(function (b) { return b.getAttribute('data-chip'); });
    var rows = $$('.e[data-f]'), seen = new Set(), vis = 0;
    rows.forEach(function (r) {
      var f = ' ' + r.getAttribute('data-f') + ' ';
      if (!r.classList.contains('ihide') && on.every(function (k) { return f.indexOf(' ' + k + ' ') >= 0; })) { seen.add(r); vis++; }
    });
    var count = function (el) { var all = $$('.e[data-f]', el); return [all.filter(function (r) { return seen.has(r); }).length, all.length]; };
    c.textContent = vis === rows.length ? rows.length + ' shown' : vis + ' of ' + rows.length + ' shown';
    var lists = $$('main ul.list, main ol.list').map(function (ul) { return [ul, count(ul)]; });
    var grps = $$('section.grp').map(function (g) { return [g, count(g)]; });
    lists.forEach(function (x) {
      var ul = x[0], h = ul.previousElementSibling;
      ul.hidden = !x[1][0] && x[1][1] > 0;
      if (h && h.tagName === 'H3') { h.hidden = ul.hidden; }
    });
    grps.forEach(function (x) {
      var n = x[1][0], all = x[1][1], sm = $('h2 small', x[0]);
      if (!all) { return; }
      x[0].hidden = !n;
      if (sm) { sm.textContent = n === all ? String(all) : n + ' of ' + all; }
    });
    if (clear) { clear.hidden = !on.length && !(ifl && ifl.value.trim()); }
    if (chips) {
      var u = new URLSearchParams(location.search);
      if (on.length) { u.set('f', on.join(',')); } else { u.delete('f'); }
      if (ifl && ifl.value.trim()) { u.set('i', ifl.value.trim()); } else { u.delete('i'); }
      var qs = u.toString();
      if ((qs ? '?' + qs : '') !== location.search) { history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash); }
    }
  }
  function press(b, on) {
    document.documentElement.classList.toggle('f-' + b.getAttribute('data-chip'), on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  function ifilter() {
    var q = ifl.value.trim().toLowerCase();
    $$('[data-f]').forEach(function (r) {
      var i = (r.getAttribute('data-i') || '').toLowerCase();
      r.classList.toggle('ihide', !!q && i.indexOf(q) < 0);
    });
  }
  if (chips) {
    chips.hidden = false;
    var start = new URLSearchParams(location.search), want = (start.get('f') || '').split(',');
    $$('.chips button[data-chip]').forEach(function (b) {
      press(b, want.indexOf(b.getAttribute('data-chip')) >= 0);
      b.addEventListener('click', function () { press(b, b.getAttribute('aria-pressed') !== 'true'); recount(); });
    });
    if (ifl) {
      ifl.value = start.get('i') || '';
      ifl.addEventListener('input', function () { ifilter(); recount(); });
      if (ifl.value) { ifilter(); }
    }
    if (clear) {
      clear.addEventListener('click', function () {
        $$('.chips button[data-chip]').forEach(function (b) { press(b, false); });
        if (ifl) { ifl.value = ''; ifilter(); }
        recount();
      });
    }
    recount();
  }

  // ---------------------------------------------------------------- name search (lazy MiniSearch over names.json)
  var ms = null, names = null, loading = null;
  function norm(s) { return String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function tokenize(s) {
    var out = [];
    norm(s).split(/[^\p{L}\p{N}]+/u).forEach(function (t) {
      if (!t) { return; }
      if (/[぀-ヿ㐀-䶿一-鿿가-힯]/.test(t) && t.length > 1) {
        out.push(t); for (var i = 0; i < t.length - 1; i++) { out.push(t.slice(i, i + 2)); }
      } else { out.push(t); }
    });
    return out;
  }
  function loadNames() {
    if (loading) { return loading; }
    loading = new Promise(function (res, rej) {
      var s = document.createElement('script'); s.src = '/assets/minisearch.js'; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    }).then(function () { return fetch('/api/v1/names.json'); }).then(function (r) { return r.json(); }).then(function (rows) {
      names = rows;
      // a typo only in a word of five letters or more
      ms = new window.MiniSearch({ fields: ['name', 'aliases', 'domain'], storeFields: ['i'], tokenize: tokenize,
        processTerm: function (t) { return t; },
        searchOptions: { boost: { name: 4, aliases: 2, domain: 2 }, fuzzy: function (t) { return t.length >= 5 ? 0.2 : false; }, prefix: true, tokenize: tokenize, processTerm: function (t) { return t; } } });
      ms.addAll(rows.map(function (r, i) { return { id: i, i: i, name: r[1], aliases: (r[2] || []).join(' '), domain: r[3] || '' }; }));
    });
    loading.catch(function () { loading = null; });
    return loading;
  }
  function nameHits(q, n) {
    if (!ms || !q) { return []; }
    return ms.search(q).slice(0, n || 12).map(function (h) { return names[h.i]; });
  }
  var box = $('#q'), drop = $('#qr'), sel = -1;
  function setOpen(on) {
    drop.hidden = !on; box.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (!on) { sel = -1; box.removeAttribute('aria-activedescendant'); }
  }
  function renderDrop() {
    var q = box.value.trim(); if (!q) { setOpen(false); return; }
    if (!ms) { // the names are on their way: say so, so a slow phone does not show an empty box
      drop.setAttribute('aria-busy', 'true');
      drop.innerHTML = '<p class="busy">Loading names...</p>'; setOpen(true); return;
    }
    drop.removeAttribute('aria-busy');
    var hits = nameHits(q, 10);
    drop.innerHTML = hits.map(function (r, i) {
      return '<a id="qo' + i + '" role="option" href="/p/' + esc(r[0]) + '/">' + txt(r[1]) + pill(r[5]) + '<small>' + esc(topics(r[4])) +
        ' &middot; ' + r[6] + ' record' + (r[6] === 1 ? '' : 's') + '</small></a>';
    }).join('') + '<a id="qo' + hits.length + '" role="option" class="all" href="/search/?q=' + encodeURIComponent(q) + '">Search all text for "' + txt(q) + '"</a>';
    sel = -1; box.removeAttribute('aria-activedescendant'); setOpen(true);
  }
  function names_then_drop() { renderDrop(); loadNames().then(renderDrop).catch(function () { drop.removeAttribute('aria-busy'); setOpen(false); }); }
  if (box && drop) {
    // the combobox exists only with this script, so its roles are set here
    box.setAttribute('role', 'combobox'); box.setAttribute('aria-autocomplete', 'list');
    box.setAttribute('aria-expanded', 'false'); box.setAttribute('aria-controls', 'qr');
    drop.setAttribute('role', 'listbox'); drop.setAttribute('aria-label', 'Matching providers');
    box.addEventListener('focus', function () { loadNames().then(renderDrop).catch(function () {}); });
    box.addEventListener('input', function () { if (ms) { renderDrop(); } else { names_then_drop(); } });
    box.addEventListener('keydown', function (ev) {
      var a = $$('a', drop);
      if ((ev.key === 'ArrowDown' || ev.key === 'ArrowUp') && !drop.hidden) {
        ev.preventDefault(); sel = Math.max(-1, Math.min(a.length - 1, sel + (ev.key === 'ArrowDown' ? 1 : -1)));
        a.forEach(function (x, i) { x.setAttribute('aria-selected', i === sel ? 'true' : 'false'); });
        if (sel >= 0) { box.setAttribute('aria-activedescendant', a[sel].id); a[sel].scrollIntoView({ block: 'nearest' }); } else { box.removeAttribute('aria-activedescendant'); }
      } else if (ev.key === 'Enter' && sel >= 0 && a[sel] && !drop.hidden) { ev.preventDefault(); location.href = a[sel].href; }
      else if (ev.key === 'Escape') { setOpen(false); }
    });
    document.addEventListener('click', function (ev) { if (!ev.target.closest('form.q')) { setOpen(false); } });
    document.addEventListener('keydown', function (ev) {
      var t = document.activeElement;
      if (ev.key === '/' && t !== box && !/^(input|textarea|select)$/i.test(t.tagName) && !t.isContentEditable) { ev.preventDefault(); box.focus(); }
    });
  }

  // ---------------------------------------------------------------- full-text search page
  // the columns of the full-text index, in words (site/worker/rank.js FTS_COLUMNS)
  var COL = { name: 'name', offer: 'free tier and price', limits: 'limits', egress: 'egress', identity: 'identity', access: 'interface',
    notes: 'notes', evidence: 'evidence', extras: 'other fields' };
  function matched(m) {
    var seen = {};
    return String(m || '').split(',').map(function (c) { return COL[c.replace(/\(.*\)$/, '')] || c.replace(/\(.*\)$/, ''); })
      .filter(function (w) { return w && !seen[w] && (seen[w] = 1); }).join(', ');
  }
  var sr = $('#sr');
  if (sr) {
    var q = new URLSearchParams(location.search).get('q') || '';
    if (box) { box.value = q; }
    if (q) {
      document.title = q + ' | Search | fshy';
      sr.innerHTML = '<p class="lede">Searching...</p>';
      var api = fetch('/api/v1/search?limit=50&q=' + encodeURIComponent(q)).then(function (r) { return r.json(); });
      loadNames().catch(function () {}).then(function () {
        var nh = nameHits(q, 8);
        sr.innerHTML = (nh.length ? '<h2>Providers <small>' + nh.length + '</small></h2><ul class="plain">' + nh.map(function (r) {
          return '<li><a href="/p/' + esc(r[0]) + '/"><b>' + txt(r[1]) + '</b></a> ' + pill(r[5]) + ' <small>' + esc(topics(r[4])) +
            ' &middot; ' + r[6] + ' record' + (r[6] === 1 ? '' : 's') + '</small></li>';
        }).join('') + '</ul>' : '') + '<h2>Full text</h2><div id="ft" aria-live="polite"><p>Loading...</p></div>';
        return api;
      }).then(function (d) {
        var ix = {}; (d.columns || []).forEach(function (c, i) { ix[c] = i; });
        var rows = d.rows || [], ft = $('#ft');
        ft.innerHTML = rows.length ? '<ul class="' + lane(rows.map(function (r) { return r[ix.verdict]; })) + '">' + rows.map(function (r) {
          var rid = r[ix.rid], t = rid.split('/')[0], id = r[ix.identity] || '', def = id.slice(-1) === '?';
          var price = usd(r[ix.usd_per_tb_month], '/TB-month') || usd(r[ix.usd_month], '/month');
          var card = r[ix.card] === 'no' && !def ? '<span class="ok">no card</span>' : r[ix.card] === 'yes' ? '<span class="w">card</span>' : '<span class="u">card?</span>';
          var m = ix.matched != null && r[ix.matched] ? '<span class="mt"><i>matched in</i> ' + esc(matched(r[ix.matched])) + '</span>' : '';
          return '<li class="e" data-stale-on="' + esc(r[ix.stale_on]) + '">' + pill(r[ix.verdict]) + '<a class="n" href="/r/' + esc(rid) + '">' +
            txt(r[ix.provider]) + '</a>' + (price ? '<span class="pr">' + esc(price) + '</span>' : '') +
            (r[ix.summary] ? '<p class="s">' + txt(line(r[ix.summary])) + '</p>' : '') + '<p class="f"><span class="tp">' + esc(TN[t] || t) +
            '</span><span class="id"><i>identity</i> ' + esc(id) + '</span>' + card + (r[ix.phone] === 'yes' ? '<span class="w">phone</span>' : '') +
            '<span class="rg"><i>evidence</i> ' + esc(r[ix.confidence]) + '</span><span class="fr"></span>' + m + '</p></li>';
        }).join('') + '</ul>' + (d.total > rows.length ? '<p class="needs">Showing ' + rows.length + ' of ' + d.total + ' matches.</p>' : '')
          : '<p>No match. Try fewer words, or open a list of <a href="/need/">Best per need</a>.</p>';
        fresh(ft);
      }).catch(function () { var ft = $('#ft'); if (ft) { ft.innerHTML = '<p>Full-text search is not available now. The name matches are above.</p>'; } });
    }
  }

  // ---------------------------------------------------------------- compare page
  var cmp = $('#cmp');
  if (cmp) {
    var ids = (new URLSearchParams(location.search).get('r') || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 5);
    var go = function (list) { location.search = list.length ? '?r=' + list.map(encodeURIComponent).join(',').replace(/%2F/gi, '/') : ''; };
    var add = '<form class="add"><label for="cmp-add">Add a record (topic/slug)</label> <input id="cmp-add" placeholder="compute/oracle-cloud" ' +
      'autocomplete="off"> <button>add</button></form>';
    var bindAdd = function () {
      var f = $('form.add', cmp);
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var v = $('#cmp-add').value.trim().replace(/^\/+|\/+$/g, '');
        if (/^[^/\s]+\/[^/\s]+$/.test(v) && ids.indexOf(v) < 0) { go(ids.concat([v]).slice(0, 5)); }
      });
    };
    if (!ids.length) { cmp.innerHTML = add; bindAdd(); }
    if (ids.length) {
      Promise.all(ids.map(function (id) { return fetch('/api/v1/record/' + id + '.json').then(function (r) { return r.ok ? r.json() : null; }); })).then(function (recs) {
        var missing = ids.filter(function (id, i) { return !recs[i]; });
        recs = recs.filter(Boolean);
        if (!recs.length) { cmp.innerHTML = '<p>None of those records exist.</p>' + add; bindAdd(); return; }
        var h = function (s) { return s == null || s === '' ? '' : txt(s).replace(/\n/g, '<br>'); };
        var f = [['verdict', function (x) { return pill(x.card.verdict); }],
          ['evidence rung', function (x) { return h(x.card.confidence); }],
          ['identity', function (x) { return h(x.card.identity_kind + (x.card.identity_basis === 'defaulted' ? '?' : '')); }],
          ['card', function (x) { return x.card.needs_card === 1 ? 'yes' : x.card.needs_card === 0 ? 'no' : 'unknown'; }],
          ['free tier', function (x) { return h((x.record.free_tier || {}).stated); }], ['price', function (x) { return h(x.record.price_per_tb_month); }],
          ['USD a month', function (x) { return h(x.card.usd_month); }], ['USD per TB-month', function (x) { return h(x.card.usd_per_tb_month); }],
          ['per-object cap', function (x) { return h((x.record.per_object_cap || {}).stated); }], ['retention', function (x) { return h((x.record.retention || {}).stated); }],
          ['egress', function (x) { return h((x.record.egress || {}).terms); }], ['binding', function (x) { return h(x.record.binding); }],
          ['limits', function (x) { return h((x.record.limits || []).map(function (l) { return l.kind + ': ' + l.value; }).join('\n')); }],
          ['interface', function (x) { return h((x.record.interface || []).join(', ')); }], ['reliability', function (x) { return h(x.record.reliability_note); }],
          ['checked', function (x) { return h(x.card.checked_on + ' (' + x.card.verified_basis + '), stale on ' + x.card.stale_on); }]];
        var head = '<thead><tr><td></td>' + recs.map(function (x) {
          return '<th scope="col"><a href="/r/' + esc(x.rid) + '">' + txt(x.card.provider) + '</a> <small><code>' + esc(x.rid) + '</code> ' +
            '<a href="#" data-drop="' + esc(x.rid) + '">remove</a></small></th>';
        }).join('') + '</tr></thead>';
        var body = f.map(function (row) {
          var cells = recs.map(function (x) { return row[1](x); });
          if (cells.every(function (c) { return !c; })) { return ''; } // a row that no record fills says nothing
          return '<tr><th scope="row">' + esc(row[0]) + '</th>' + cells.map(function (c) { return '<td>' + (c || '<span class="na">not stated</span>') + '</td>'; }).join('') + '</tr>';
        }).join('');
        cmp.innerHTML = '<div class="tw"><table class="cmp">' + head + '<tbody>' + body + '</tbody></table></div>' +
          (missing.length ? '<p>Not found: ' + esc(missing.join(', ')) + '</p>' : '') + add;
        $$('[data-drop]', cmp).forEach(function (a) {
          a.addEventListener('click', function (ev) { ev.preventDefault(); var r = a.getAttribute('data-drop'); go(ids.filter(function (x) { return x !== r; })); });
        });
        bindAdd();
      });
    }
  }
})();
