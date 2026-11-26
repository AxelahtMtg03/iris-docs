(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;
  var calm = matchMedia('(prefers-reduced-motion: reduce)');
  var texts = window.IRIS_I18N;
  var lang = 'fr';

  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* stockage indisponible */ } }
  function saved(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  /* ---------- Langue (français par défaut) ---------- */
  function setLang(next) {
    lang = texts[next] ? next : 'fr';
    var t = texts[lang];
    root.lang = lang;
    document.title = t.pageTitle;
    document.querySelector('meta[name=description]').content = t.pageDescription;
    document.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = t[el.dataset.i18n]; });
    document.querySelectorAll('[data-i18n-label]').forEach(function (el) { el.setAttribute('aria-label', t[el.dataset.i18nLabel]); });
    document.querySelectorAll('[data-i18n-alt]').forEach(function (el) { el.alt = t[el.dataset.i18nAlt]; });
    $('lang').value = lang;
    $('copied').textContent = '';
  }
  $('lang').addEventListener('change', function () { store('iris-lang', this.value); setLang(this.value); });
  setLang(new URLSearchParams(location.search).get('lang') || saved('iris-lang') || 'fr');

  /* ---------- Liens du dépôt ---------- */
  var repo = window.IRIS_CONFIG.repo.replace(/\/+$/, '');
  var folder = repo.split('/').pop();
  $('commands').textContent = ['git clone ' + repo, 'cd ' + folder, 'pip install -r requirements.txt', 'python run.py'].join('\n');
  $('repo').href = repo;
  $('bug').href = repo + '/issues/new';
  $('license').href = repo + '/blob/main/LICENSE';
  $('zip').href = repo + '/archive/refs/heads/main.zip';

  $('copy').addEventListener('click', function () {
    var text = $('commands').textContent;
    var done = function () { $('copied').textContent = texts[lang].copied; };
    var fallback = function () {
      var range = document.createRange();
      range.selectNodeContents($('commands'));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      if (document.execCommand('copy')) done(); else $('copied').textContent = texts[lang].copyFailed;
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  });

  /* ---------- Thème ---------- */
  $('themeBtn').addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    store('iris-theme', next);
  });

  /* ---------- Menu compact ---------- */
  function menu(open) {
    $('menu').classList.toggle('open', open);
    $('burger').setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  $('burger').addEventListener('click', function () { menu(!$('menu').classList.contains('open')); });
  document.addEventListener('click', function (e) {
    if (!e.target.closest('#burger')) menu(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && $('menu').classList.contains('open')) { menu(false); $('burger').focus(); }
  });

  /* ---------- Scène 3D ---------- */
  var zone = $('tiltZone'), stage = $('stage');
  function fit() {
    var width = zone.clientWidth;
    var narrow = matchMedia('(max-width: 599px)').matches;
    // Sur téléphone seule la fenêtre centrale (560 px) est affichée.
    zone.style.setProperty('--k', Math.min(1, width / (narrow ? 600 : 840)).toFixed(3));
  }
  addEventListener('resize', fit);
  fit();
  zone.addEventListener('pointermove', function (e) {
    if (calm.matches || e.pointerType === 'touch') return;
    var r = zone.getBoundingClientRect();
    var x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
    stage.style.transform = 'rotateX(' + (8 - y * 14).toFixed(2) + 'deg) rotateY(' + (-6 + x * 22).toFixed(2) + 'deg)';
  });
  zone.addEventListener('pointerleave', function () { stage.style.transform = ''; });

  /* ---------- Parallaxe des grands mots ---------- */
  var words = document.querySelectorAll('[data-parallax]');
  var waiting = false;
  function drift() {
    waiting = false;
    words.forEach(function (word) {
      var r = word.parentNode.getBoundingClientRect();
      var progress = Math.max(-1, Math.min(1, (r.top + r.height / 2) / innerHeight * 2 - 1));
      // Le mot ne glisse que dans la place libre à sa droite : jamais hors de l'écran.
      var room = Math.max(0, Math.min(80, word.parentNode.clientWidth - word.offsetWidth));
      var side = Number(word.dataset.parallax) > 0 ? Math.abs(progress) : 1 - Math.abs(progress);
      word.style.setProperty('--shift', calm.matches ? '0px' : (side * room).toFixed(1) + 'px');
    });
  }
  addEventListener('scroll', function () { if (!waiting) { waiting = true; requestAnimationFrame(drift); } }, { passive: true });
  addEventListener('resize', drift);
  drift();
})();
