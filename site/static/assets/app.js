/* fshy wiki: freshness badges, filter chips, name search (MiniSearch), full-text search page, compare page. */
(function () {
  'use strict';
  var today = new Date().toISOString().slice(0, 10);
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  // ---------------------------------------------------------------- freshness, computed against today
  $$('.b.fr').forEach(function (b) {
    var so = b.getAttribute('data-stale-on'), basis = b.getAttribute('data-basis'), ck = b.getAttribute('data-checked');
    if (!so || so === 'None') { return; }
    var stale = so <= today;
    b.classList.add(stale ? 'stale' : 'fresh');
    b.textContent = (stale ? 'stale' : 'fresh') + (basis === 'inherited' ? ', inherited' : '');
    b.title = 'checked ' + (ck || '?') + (basis === 'inherited' ? ' (upper bound)' : '') + '; stale on ' + so;
  });
  $$('[data-f]').forEach(function (r) {
    var so = r.getAttribute('data-stale-on');
    if (so && so !== 'None' && so > today) { r.setAttribute('data-f', (r.getAttribute('data-f') + ' fresh').trim()); }
  });

  // ---------------------------------------------------------------- filter chips (fmhy-style class toggles)
  function recount() {
    var c = $('.chips .count'); if (!c) { return; }
    var rows = $$('li.e[data-f], tr[data-f], section.rec[data-f]');
    var vis = rows.filter(function (r) { return r.offsetParent !== null; }).length;
    c.textContent = vis + ' of ' + rows.length + ' shown';
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
    return loading;
  }
  var VORD = ['qualifies', 'caveat', 'trial', 'paid', 'fails: identity', 'fails: egress', 'fails: quota', 'dead'];
  function nameHits(q, n) {
    if (!ms || !q) { return []; }
    return ms.search(q).slice(0, n || 12).map(function (h) { return names[h.i]; });
  }
  var box = $('#q'), drop = $('#qr'), sel = -1;
  function renderDrop() {
    var q = box.value.trim(); if (!q) { drop.hidden = true; return; }
    var hits = nameHits(q, 10);
    drop.innerHTML = hits.map(function (r) {
      return '<a href="/p/' + esc(r[0]) + '/">' + esc(r[1]) + ' <small>' + esc((r[4] || []).join(', ')) + ' &middot; ' + r[6] +
        ' record' + (r[6] === 1 ? '' : 's') + ' &middot; best: ' + esc(VORD[r[5]] || '') + '</small></a>';
    }).join('') + '<a href="/search/?q=' + encodeURIComponent(q) + '"><b>Search all text for "' + esc(q) + '"</b></a>';
    drop.hidden = false; sel = -1;
  }
  if (box) {
    box.addEventListener('focus', function () { loadNames().then(renderDrop).catch(function () {}); });
    box.addEventListener('input', function () { if (ms) { renderDrop(); } else { loadNames().then(renderDrop); } });
    box.addEventListener('keydown', function (ev) {
      var a = $$('a', drop);
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault(); sel = Math.max(-1, Math.min(a.length - 1, sel + (ev.key === 'ArrowDown' ? 1 : -1)));
        a.forEach(function (x, i) { x.classList.toggle('sel', i === sel); });
      } else if (ev.key === 'Enter' && sel >= 0 && a[sel]) { ev.preventDefault(); location.href = a[sel].href; }
      else if (ev.key === 'Escape') { drop.hidden = true; }
    });
    document.addEventListener('click', function (ev) { if (!ev.target.closest('form.q')) { drop.hidden = true; } });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === '/' && document.activeElement !== box && !/input|textarea/i.test(document.activeElement.tagName)) { ev.preventDefault(); box.focus(); }
    });
  }

  // ---------------------------------------------------------------- full-text search page
  var sr = $('#sr');
  if (sr) {
    var q = new URLSearchParams(location.search).get('q') || '';
    if (box) { box.value = q; }
    if (q) {
      sr.innerHTML = '<p>Searching...</p>';
      loadNames().then(function () {
        var nh = nameHits(q, 8);
        var html = nh.length ? '<h2>Providers</h2><ul class="list">' + nh.map(function (r) {
          return '<li class="e hit"><a class="n" href="/p/' + esc(r[0]) + '/">' + esc(r[1]) + '</a> <small>' + esc((r[4] || []).join(', ')) +
            ' &middot; ' + r[6] + ' records</small></li>';
        }).join('') + '</ul>' : '';
        sr.innerHTML = html + '<h2>Full text</h2><div id="ft"><p>Loading...</p></div>';
        return fetch('/api/v1/search?limit=50&q=' + encodeURIComponent(q));
      }).then(function (r) { return r.json(); }).then(function (d) {
        var cols = d.columns || [], ix = {}; cols.forEach(function (c, i) { ix[c] = i; });
        var rows = d.rows || [];
        $('#ft').innerHTML = rows.length ? '<ul class="list">' + rows.map(function (r) {
          var rid = r[ix.rid];
          return '<li class="e hit"><a class="n" href="/r/' + esc(rid) + '">' + esc(r[ix.provider]) + '</a> <span class="b">' + esc(r[ix.verdict]) +
            '</span> <span class="b">' + esc(r[ix.identity]) + '</span> <small>' + esc(rid) + (ix.matched != null && r[ix.matched] ? ' &middot; matched in ' + esc(r[ix.matched]) : '') +
            '</small><div class="s">' + esc(r[ix.summary] || '') + '</div></li>';
        }).join('') + '</ul>' : '<p>No full-text match.</p>';
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
        var f = [['provider', function (x) { return x.card.provider; }], ['verdict', function (x) { return x.card.verdict; }],
          ['evidence rung', function (x) { return x.card.confidence; }], ['identity', function (x) { return x.card.identity_kind + (x.card.identity_basis === 'defaulted' ? '?' : ''); }],
          ['card', function (x) { return x.card.needs_card === 1 ? 'yes' : x.card.needs_card === 0 ? 'no' : '?'; }],
          ['free tier', function (x) { return (x.record.free_tier || {}).stated; }], ['price', function (x) { return x.record.price_per_tb_month; }],
          ['USD/month', function (x) { return x.card.usd_month; }], ['USD/TB-month', function (x) { return x.card.usd_per_tb_month; }],
          ['per-object cap', function (x) { return (x.record.per_object_cap || {}).stated; }], ['retention', function (x) { return (x.record.retention || {}).stated; }],
          ['egress', function (x) { return (x.record.egress || {}).terms; }], ['binding', function (x) { return x.record.binding; }],
          ['limits', function (x) { return (x.record.limits || []).map(function (l) { return l.kind + ': ' + l.value; }).join('\n'); }],
          ['interface', function (x) { return (x.record.interface || []).join(', '); }], ['reliability', function (x) { return x.record.reliability_note; }],
          ['checked', function (x) { return x.card.checked_on + ' (' + x.card.verified_basis + '), stale on ' + x.card.stale_on; }]];
        cmp.innerHTML = '<table class="cmp"><tbody>' + f.map(function (row) {
          return '<tr><th>' + esc(row[0]) + '</th>' + recs.map(function (x) { return '<td>' + esc(row[1](x)).replace(/\n/g, '<br>') + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table>';
      });
    }
  }
})();
