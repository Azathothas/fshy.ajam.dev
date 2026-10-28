/* fshy wiki: freshness, filter chips, name search (MiniSearch), full-text search page, compare page. No framework. */
(function () {
  'use strict';
  var today = new Date().toISOString().slice(0, 10);
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  // verdict terms in vorder and their short labels (publish/pages.py VERDICT_LABEL)
  var VT = ['qualifies', 'qualifies-with-caveat', 'trial-only', 'paid-only', 'fails-identity', 'fails-egress', 'fails-quota', 'dead'];
  var VL = ['★ qualifies', 'caveat', 'trial', 'paid', 'fails: identity', 'fails: egress', 'fails: quota', 'dead'];
  // topic names, from the topic bar of the page (publish/rules/topics.json), so this file holds no copy of the list
  var TN = {};
  $$('.topics a').forEach(function (a) { var m = /^\/t\/([^/]+)\/$/.exec(a.getAttribute('href')); if (m) TN[m[1]] = a.textContent; });
  function pill(v) { var i = typeof v === 'number' ? v : VT.indexOf(v); return '<span class="v v-' + esc(VT[i] || v) + '">' + esc(VL[i] || v) + '</span>'; }
  function usd(v, sfx) { return v == null ? '' : 'USD ' + (v < 1000 ? String(+(+v).toFixed(2)) : (+v).toFixed(0)) + sfx; }
  function topics(ts) { return (ts || []).map(function (t) { return TN[t] || t; }).join(', '); }
  function lane(vs) { // list class from the longest verdict label, as pages.py lane()
    var w = Math.max.apply(null, vs.map(function (v) { var i = VT.indexOf(v); return (VL[i] || v || '').length; }).concat([0]));
    return 'list' + (w > 11 ? '' : w > 6 ? ' lm' : ' ls');
  }

  // ---------------------------------------------------------------- keep the current topic visible in the scrolling topic bar
  var tn = $('.topics'), tc = tn && $('[aria-current]', tn);
  if (tc && tn.scrollWidth > tn.clientWidth) {
    tn.scrollLeft += tc.getBoundingClientRect().left - tn.getBoundingClientRect().left - (tn.clientWidth - tc.offsetWidth) / 2;
  }

  // ---------------------------------------------------------------- freshness, computed against today
  function fresh(root) {
    $$('.fr', root).forEach(function (b) {
      var h = b.closest('[data-stale-on]'), so = b.getAttribute('data-stale-on') || (h && h.getAttribute('data-stale-on'));
      if (!so || so === 'None') { return; }
      var stale = so <= today, inh = b.getAttribute('data-basis') === 'inherited';
      b.className = 'fr ' + (stale ? 'stale' : 'fresh');
      b.textContent = (stale ? 'stale' : 'fresh') + (inh ? ', inherited' : '');
      b.title = 'checked ' + (b.getAttribute('data-checked') || '?') + (inh ? ' (upper bound)' : '') + '; stale on ' + so;
    });
  }
  fresh();
  $$('[data-f]').forEach(function (r) {
    var so = r.getAttribute('data-stale-on');
    if (so && so !== 'None' && so > today) { r.setAttribute('data-f', (r.getAttribute('data-f') + ' fresh').trim()); }
  });

  // ---------------------------------------------------------------- filter chips (class toggles on <html>)
  function recount() {
    var c = $('.chips .count'); if (!c) { return; }
    var rows = $$('.e[data-f]');
    var vis = rows.filter(function (r) { return r.offsetParent !== null; }).length;
    c.textContent = vis === rows.length ? rows.length + ' shown' : vis + ' of ' + rows.length + ' shown';
  }
  $$('.chips button[data-chip]').forEach(function (b) {
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', function () {
      var on = document.documentElement.classList.toggle('f-' + b.getAttribute('data-chip'));
      b.setAttribute('aria-pressed', on ? 'true' : 'false'); recount();
    });
  });
  $$('.chips .ifilter').forEach(function (inp) {
    inp.addEventListener('input', function () {
      var q = inp.value.trim().toLowerCase();
      $$('[data-f]').forEach(function (r) {
        var i = (r.getAttribute('data-i') || '').toLowerCase();
        r.classList.toggle('ihide', !!q && i.indexOf(q) < 0);
      });
      recount();
    });
  });
  recount();

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
      ms = new window.MiniSearch({ fields: ['name', 'aliases', 'domain'], storeFields: ['i'], tokenize: tokenize,
        processTerm: function (t) { return t; },
        searchOptions: { boost: { name: 4, aliases: 2, domain: 2 }, fuzzy: 0.2, prefix: true, tokenize: tokenize, processTerm: function (t) { return t; } } });
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
    var hits = nameHits(q, 10);
    drop.innerHTML = hits.map(function (r, i) {
      return '<a id="qo' + i + '" role="option" href="/p/' + esc(r[0]) + '/">' + esc(r[1]) + pill(r[5]) + '<small>' + esc(topics(r[4])) +
        ' &middot; ' + r[6] + ' record' + (r[6] === 1 ? '' : 's') + '</small></a>';
    }).join('') + '<a id="qo' + hits.length + '" role="option" class="all" href="/search/?q=' + encodeURIComponent(q) + '">Search all text for “' + esc(q) + '”</a>';
    sel = -1; box.removeAttribute('aria-activedescendant'); setOpen(true);
  }
  if (box && drop) {
    // the combobox exists only with this script, so its roles and states are set here rather than in every page
    box.setAttribute('role', 'combobox'); box.setAttribute('aria-autocomplete', 'list');
    box.setAttribute('aria-expanded', 'false'); box.setAttribute('aria-controls', 'qr');
    drop.setAttribute('role', 'listbox'); drop.setAttribute('aria-label', 'Matching providers');
    box.addEventListener('focus', function () { loadNames().then(renderDrop).catch(function () {}); });
    box.addEventListener('input', function () { if (ms) { renderDrop(); } else { loadNames().then(renderDrop).catch(function () {}); } });
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
  var sr = $('#sr');
  if (sr) {
    var q = new URLSearchParams(location.search).get('q') || '';
    if (box) { box.value = q; }
    if (q) {
      document.title = q + ' - Search - fshy';
      sr.innerHTML = '<p class="lede">Searching…</p>';
      loadNames().then(function () {
        var nh = nameHits(q, 8);
        sr.innerHTML = (nh.length ? '<h2>Providers <small>' + nh.length + '</small></h2><ul class="plain">' + nh.map(function (r) {
          return '<li><a href="/p/' + esc(r[0]) + '/"><b>' + esc(r[1]) + '</b></a> ' + pill(r[5]) + ' <small>' + esc(topics(r[4])) +
            ' &middot; ' + r[6] + ' record' + (r[6] === 1 ? '' : 's') + '</small></li>';
        }).join('') + '</ul>' : '') + '<h2>Full text</h2><div id="ft" aria-live="polite"><p>Loading…</p></div>';
        return fetch('/api/v1/search?limit=50&q=' + encodeURIComponent(q));
      }).then(function (r) { return r.json(); }).then(function (d) {
        var ix = {}; (d.columns || []).forEach(function (c, i) { ix[c] = i; });
        var rows = d.rows || [], ft = $('#ft');
        ft.innerHTML = rows.length ? '<ul class="' + lane(rows.map(function (r) { return r[ix.verdict]; })) + '">' + rows.map(function (r) {
          var rid = r[ix.rid], t = rid.split('/')[0], id = r[ix.identity] || '', def = id.slice(-1) === '?';
          var price = usd(r[ix.usd_per_tb_month], '/TB-mo') || usd(r[ix.usd_month], '/mo');
          var card = r[ix.card] === 'no' && !def ? '<span class="ok">no card</span>' : r[ix.card] === 'yes' ? '<span class="w">card</span>' : '<span class="u">card?</span>';
          var m = ix.matched != null && r[ix.matched] ? '<span class="mt">matched in ' + esc(r[ix.matched]) + '</span>' : '';
          return '<li class="e" data-stale-on="' + esc(r[ix.stale_on]) + '">' + pill(r[ix.verdict]) + '<a class="n" href="/r/' + esc(rid) + '">' +
            esc(r[ix.provider]) + '</a>' + (price ? '<span class="pr">' + esc(price) + '</span>' : '') +
            (r[ix.summary] ? '<p class="s">' + esc(r[ix.summary]) + '</p>' : '') + '<p class="f"><span class="tp">' + esc(TN[t] || t) +
            '</span><span class="id">' + esc(id) + '</span>' + card + (r[ix.phone] === 'yes' ? '<span class="w">phone</span>' : '') +
            '<span class="rg">' + esc(r[ix.confidence]) + '</span><span class="fr"></span>' + m + '</p></li>';
        }).join('') + '</ul>' + (d.total > rows.length ? '<p class="needs">Showing ' + rows.length + ' of ' + d.total + ' matches.</p>' : '')
          : '<p>No full-text match.</p>';
        fresh(ft);
      }).catch(function () { var ft = $('#ft'); if (ft) { ft.innerHTML = '<p>Full-text search is unavailable right now; name matches are above.</p>'; } });
    }
  }

  // ---------------------------------------------------------------- compare page
  var cmp = $('#cmp');
  if (cmp) {
    var ids = (new URLSearchParams(location.search).get('r') || '').split(',').filter(Boolean).slice(0, 5);
    if (ids.length) {
      Promise.all(ids.map(function (id) { return fetch('/api/v1/record/' + id + '.json').then(function (r) { return r.ok ? r.json() : null; }); })).then(function (recs) {
        recs = recs.filter(Boolean);
        if (!recs.length) { cmp.innerHTML = '<p>None of those records exist.</p>'; return; }
        var h = function (s) { return esc(s).replace(/\n/g, '<br>'); };
        var f = [['provider', function (x) { return '<a href="/r/' + esc(x.rid) + '"><b>' + esc(x.card.provider) + '</b></a>'; }],
          ['verdict', function (x) { return pill(x.card.verdict); }],
          ['evidence rung', function (x) { return h(x.card.confidence); }],
          ['identity', function (x) { return h(x.card.identity_kind + (x.card.identity_basis === 'defaulted' ? '?' : '')); }],
          ['card', function (x) { return x.card.needs_card === 1 ? 'yes' : x.card.needs_card === 0 ? 'no' : '?'; }],
          ['free tier', function (x) { return h((x.record.free_tier || {}).stated); }], ['price', function (x) { return h(x.record.price_per_tb_month); }],
          ['USD/month', function (x) { return h(x.card.usd_month); }], ['USD/TB-month', function (x) { return h(x.card.usd_per_tb_month); }],
          ['per-object cap', function (x) { return h((x.record.per_object_cap || {}).stated); }], ['retention', function (x) { return h((x.record.retention || {}).stated); }],
          ['egress', function (x) { return h((x.record.egress || {}).terms); }], ['binding', function (x) { return h(x.record.binding); }],
          ['limits', function (x) { return h((x.record.limits || []).map(function (l) { return l.kind + ': ' + l.value; }).join('\n')); }],
          ['interface', function (x) { return h((x.record.interface || []).join(', ')); }], ['reliability', function (x) { return h(x.record.reliability_note); }],
          ['checked', function (x) { return h(x.card.checked_on + ' (' + x.card.verified_basis + '), stale on ' + x.card.stale_on); }]];
        cmp.innerHTML = '<div class="tw"><table class="cmp"><tbody>' + f.map(function (row) {
          return '<tr><th scope="row">' + esc(row[0]) + '</th>' + recs.map(function (x) { return '<td>' + row[1](x) + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
      });
    }
  }
})();
