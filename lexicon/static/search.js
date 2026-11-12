// Client-side search over data/search-index.json.
(function () {
  var form = document.getElementById('search-form');
  var input = document.getElementById('q');
  var langSel = document.getElementById('lang');
  var status = document.getElementById('search-status');
  var results = document.getElementById('results');
  var MAX = 100;
  var data = null;
  var POS = { n: 'noun', adj: 'adjective', vb: 'verb', root: 'root', adv: 'adverb', pron: 'pronoun',
    prep: 'preposition', conj: 'conjunction', interj: 'interjection', suf: 'suffix', pref: 'prefix',
    'masc-name': 'masculine name', 'fem-name': 'feminine name', 'place-name': 'place name',
    'proper-name': 'proper name', 'collective-name': 'collective name', cardinal: 'number', ordinal: 'ordinal' };

  function norm(s) {
    return s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9 ]/g, '');
  }
  function mode() { var m = form.querySelector('input[name=mode]:checked'); return m ? m.value : 'all'; }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function render(q) {
    results.innerHTML = '';
    var nq = norm(q).trim();
    if (!nq) { status.textContent = 'Type a word to search ' + data.entries.length.toLocaleString() + ' entries.'; return; }
    var lang = langSel.value, m = mode();
    var scored = [];
    var wordRe = new RegExp('(^|[^a-z])' + nq.replace(/ /g, ' '));
    data.entries.forEach(function (x) {
      if (lang && x[3] !== lang) return;
      var score = 0, key = x[2], gloss = norm(x[4]);
      if (m !== 'gloss') {
        if (key === nq.replace(/ /g, '')) score = 100;
        else if (key.indexOf(nq.replace(/ /g, '')) === 0) score = 60;
        else if (nq.length > 2 && key.indexOf(nq.replace(/ /g, '')) > 0) score = 20;
      }
      if (m !== 'form' && gloss) {
        if (gloss === nq) score = Math.max(score, 90);
        else if (wordRe.test(gloss)) score = Math.max(score, 50);
        else if (nq.length > 3 && gloss.indexOf(nq) >= 0) score = Math.max(score, 10);
      }
      if (score) scored.push([score, x]);
    });
    scored.sort(function (a, b) { return b[0] - a[0] || a[1][2].localeCompare(b[1][2]); });
    var shown = scored.slice(0, MAX);
    shown.forEach(function (s) {
      var x = s[1], L = data.langs[x[3]];
      var li = el('li');
      var a = el('a', { href: x[6] });
      if (x[5] === 'root') { a.appendChild(el('span', { class: 'sym', 'aria-hidden': 'true' }, '√')); a.appendChild(el('span', { class: 'visually-hidden' }, 'root ')); }
      else if (x[3] === 'p') { a.appendChild(el('span', { class: 'sym', 'aria-hidden': 'true' }, '✶')); a.appendChild(el('span', { class: 'visually-hidden' }, 'primitive form ')); }
      a.appendChild(el('span', { lang: L[1], class: 'elv' }, x[1]));
      li.appendChild(a);
      li.appendChild(document.createTextNode(' '));
      li.appendChild(el('span', { class: 'lang-name' }, L[0] + (POS[x[5]] ? ', ' + POS[x[5]] : '')));
      if (x[4]) { li.appendChild(document.createTextNode(' ')); li.appendChild(el('span', { class: 'gloss' }, '“' + x[4] + '”')); }
      results.appendChild(li);
    });
    var n = scored.length;
    status.textContent = n === 0 ? 'No entries found for “' + q + '”.' :
      n + (n === 1 ? ' entry' : ' entries') + ' found for “' + q + '”' + (n > MAX ? '. Showing the best ' + MAX + '.' : '.');
  }

  var timer;
  function schedule() { clearTimeout(timer); timer = setTimeout(function () { if (data) render(input.value); }, 250); }

  form.addEventListener('submit', function (ev) { ev.preventDefault(); if (data) render(input.value); });
  input.addEventListener('input', schedule);
  langSel.addEventListener('change', schedule);
  form.querySelectorAll('input[name=mode]').forEach(function (r) { r.addEventListener('change', schedule); });

  var params = new URLSearchParams(location.search);
  if (params.get('q')) input.value = params.get('q');
  if (params.get('lang')) langSel.value = params.get('lang');
  status.textContent = 'Loading the word index…';
  fetch('data/search-index.json').then(function (r) { return r.json(); }).then(function (d) {
    data = d; render(input.value);
  }).catch(function () {
    status.textContent = 'The search index could not be loaded. Please use Browse instead.';
  });
})();
