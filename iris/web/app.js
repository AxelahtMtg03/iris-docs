/* Interface d'Iris : état local, appels à l'API et affichage. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var root = document.documentElement;
  var LANGS = ['fr', 'en', 'es'];

  var token = new URLSearchParams(location.hash.slice(1)).get('t');
  if (token) {
    sessionStorage.setItem('iris-token', token);
    history.replaceState(null, '', location.pathname);
  } else {
    token = sessionStorage.getItem('iris-token') || '';
  }

  var S = {
    view: 'document', app: null,
    file: null, reading: false, dialog: false,
    fmt: 'other', trad: false, srcChoice: 'auto', dst: 'en',
    stage: 'idle', job: null, result: null, notice: null,
    history: [], downloads: {}, customOut: false
  };
  var pollTimer = null;

  /* ---------- Textes ---------- */
  function lang() { return S.app ? S.app.settings.lang : 'fr'; }
  function t(key, values) {
    var text = window.IRIS_I18N[lang()][key] || window.IRIS_I18N.fr[key] || key;
    return text.replace(/\{(\w+)\}/g, function (_, name) {
      return values && name in values ? values[name] : '';
    });
  }
  function translatePage() {
    root.lang = lang();
    document.title = t('docTitle');
    document.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-label]').forEach(function (el) {
      el.setAttribute('aria-label', t(el.dataset.i18nLabel));
    });
  }

  /* ---------- API ---------- */
  function fatal(key) {
    clearTimeout(pollTimer);
    $('fatalText').textContent = t(key);
    $('fatal').hidden = false;
  }
  function api(method, path, body, raw) {
    var headers = { 'X-Iris-Token': token };
    if (S.app) headers['X-Iris-Lang'] = lang();
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    return fetch(path, { method: method, headers: headers, body: body }).then(function (response) {
      if (response.status === 401) { fatal('sessionExpired'); throw { silent: true }; }
      if (raw && response.ok) return response.blob();
      return response.json().then(function (data) {
        if (!response.ok) throw data.error;
        return data;
      });
    }, function () { throw { message: t('serverGone') }; });
  }
  function showError(error) {
    if (!error || error.silent) return;
    S.notice = { message: error.message || String(error), detail: error.detail || '' };
    render();
    $('notice').scrollIntoView({ block: 'nearest' });
  }
  function announce(text) { $('announce').textContent = text; }

  /* ---------- Petits outils d'affichage ---------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'text') node.textContent = attrs[key];
      else if (key === 'onclick') node.addEventListener('click', attrs[key]);
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }
  /* Les boutons sont mis à jour sur place : le focus clavier est conservé. */
  function pills(container, items, disabled) {
    var keys = items.map(function (i) { return i.key; }).join('|');
    if (container.dataset.keys !== keys) {
      container.textContent = '';
      items.forEach(function (item) {
        var button = el('button', { type: 'button', 'class': 'pill' });
        button.addEventListener('click', function () { button.pick(); });
        container.appendChild(button);
      });
      container.dataset.keys = keys;
    }
    items.forEach(function (item, index) {
      var button = container.children[index];
      button.pick = item.pick;
      button.textContent = item.label;
      button.setAttribute('aria-pressed', item.on ? 'true' : 'false');
      button.disabled = !!disabled;
    });
  }
  function size(bytes) {
    var mega = bytes / 1048576;
    var units = lang() === 'fr' ? ['Ko', 'Mo'] : ['KB', 'MB'];
    return mega >= 1
      ? mega.toLocaleString(lang(), { maximumFractionDigits: 1 }) + ' ' + units[1]
      : Math.max(1, Math.round(bytes / 1024)) + ' ' + units[0];
  }

  /* ---------- Thème ---------- */
  var lightQuery = matchMedia('(prefers-color-scheme: light)');
  function applyTheme() {
    var wanted = S.app ? S.app.settings.theme : 'system';
    try {
      if (wanted === 'system') localStorage.removeItem('iris-theme');
      else localStorage.setItem('iris-theme', wanted);
    } catch (e) { /* stockage indisponible */ }
    if (wanted === 'system') wanted = lightQuery.matches ? 'light' : 'dark';
    root.setAttribute('data-theme', wanted);
  }
  lightQuery.addEventListener('change', function () { if (S.app) applyTheme(); });

  function saveSettings(changes) {
    Object.assign(S.app.settings, changes);
    applyTheme();
    if (changes.lang) translatePage();
    render();
    return api('PUT', '/api/settings', changes).then(function (settings) {
      S.app.settings = settings;
      render();
      if (changes.lang && S.view === 'history') loadHistory();
    }).catch(showError);
  }

  /* ---------- Fichier ---------- */
  function idle() {
    clearTimeout(pollTimer);
    S.stage = 'idle'; S.job = null; S.result = null; S.notice = null;
  }
  function busy() { return S.stage === 'running'; }
  function useFile(file) {
    if (S.file) api('DELETE', '/api/files/' + S.file.id).catch(function () {});
    idle();
    S.file = file;
    S.srcChoice = 'auto';
    if (file.detected && file.detected === S.dst) S.dst = file.detected === 'en' ? 'fr' : 'en';
    S.fmt = 'other';
    render();
    announce(file.name);
  }
  function dropFile() {
    if (S.file) api('DELETE', '/api/files/' + S.file.id).catch(function () {});
    S.file = null;
    idle();
    render();
    document.querySelector('[data-pick]').focus();
  }
  function upload(file) {
    if (S.reading || busy()) return;
    var data = new FormData();
    data.append('file', file);
    S.reading = true; S.notice = null; render();
    var limit = S.app.settings.max_mb;
    var request = file.size > limit * 1048576
      ? Promise.reject({ message: t('maxSize') + ' : ' + limit })
      : api('POST', '/api/files', data);
    request.then(function (described) {
      S.reading = false; useFile(described);
    }).catch(function (error) { S.reading = false; showError(error); });
  }
  function pick(kind) {
    if (S.reading || S.dialog || busy()) return;
    S.dialog = true; S.notice = null; render();
    api('POST', '/api/pick', { kind: kind }).then(function (answer) {
      S.dialog = false;
      if (answer.unavailable) {
        $('fileInput').setAttribute('accept', kind === 'any' ? '.docx,.pdf' : '.' + kind);
        $('fileInput').click();
        render();
      } else if (answer.file) useFile(answer.file);
      else render();
    }).catch(function (error) { S.dialog = false; showError(error); });
  }

  /* ---------- Conversion ---------- */
  function sourceLang() { return S.srcChoice === 'auto' ? (S.file && S.file.detected) || 'fr' : S.srcChoice; }
  function choices() {
    var ext = S.file ? S.file.ext : 'docx';
    var conv = S.fmt === 'other';
    var out = conv ? (ext === 'docx' ? 'pdf' : 'docx') : ext;
    return { ext: ext, conv: conv, out: out, trad: S.trad, src: sourceLang(), dst: S.dst };
  }
  function installed(a, b) {
    return S.app.models.some(function (pair) {
      return pair.directions.some(function (d) { return d.from === a && d.to === b && d.installed; });
    });
  }
  function missingPairs(c) {
    if (!c.trad || c.src === c.dst) return [];
    var steps = c.src === 'en' || c.dst === 'en' || installed(c.src, c.dst)
      ? [[c.src, c.dst]] : [[c.src, 'en'], ['en', c.dst]];
    return steps.filter(function (s) { return !installed(s[0], s[1]); })
      .map(function (s) { return s[0].toUpperCase() + ' → ' + s[1].toUpperCase(); });
  }
  function blocker(c) {
    if (!S.file || (!c.conv && !c.trad)) return null;
    if (c.out === 'pdf' && !S.app.tools.libreoffice) return { text: t('needOffice') };
    if (c.ext === 'pdf' && S.file.scan && !S.app.tools.tesseract) return { text: t('needOcr') };
    var missing = missingPairs(c);
    if (missing.length) return { text: t('needModel', { pairs: missing.join(', ') }), languages: true };
    return null;
  }
  function start() {
    var c = choices();
    S.stage = 'running'; S.notice = null; S.result = null;
    S.job = { progress: 0, stage: '', status: 'queued' };
    render();
    $('cancel').focus();
    api('POST', '/api/jobs', {
      file_id: S.file.id, target_format: c.out, translate: c.trad, source_lang: c.src, target_lang: c.dst
    }).then(function (job) { S.job = job; poll(job.id); })
      .catch(function (error) { S.stage = 'idle'; showError(error); });
  }
  function poll(id) {
    pollTimer = setTimeout(function () {
      api('GET', '/api/jobs/' + id).then(function (job) {
        if (!S.job || S.job.id !== id) return;
        job.cancelling = S.job.cancelling;
        S.job = job;
        if (job.status === 'done') {
          S.stage = 'done'; S.result = job.result;
          render();
          announce(t('done', { name: job.result.name }));
          $('openDir').focus({ preventScroll: true });
        } else if (job.status === 'error') {
          S.stage = 'idle';
          showError(job.error);
        } else if (job.status === 'cancelled') {
          S.stage = 'idle'; S.job = null;
          render();
          $('outHint').textContent = t('cancelled');
          announce(t('cancelled'));
        } else {
          renderProgress();
          poll(id);
        }
      }).catch(function (error) { S.stage = 'idle'; showError(error); });
    }, 300);
  }
  function renderProgress() {
    var c = choices();
    var label = c.conv && c.trad ? t('runBoth') : c.conv ? t('runConvert') : t('runTranslate');
    var percent = Math.round((S.job.progress || 0) * 100);
    var stage = S.job.cancelling ? t('cancelling')
      : S.job.status === 'queued' ? t('queued')
      : S.job.stage ? t('stage_' + S.job.stage) : label;
    $('runText').textContent = stage;
    $('runBtn').textContent = label + '…';
    $('progressFill').style.width = percent + '%';
    $('progress').setAttribute('aria-valuenow', percent);
    $('percent').textContent = percent + ' %';
    $('cancel').disabled = !!S.job.cancelling || !S.job.id;
  }

  /* ---------- Vue Document ---------- */
  function renderDocument() {
    var file = S.file, c = choices(), running = busy(), done = S.stage === 'done';
    var label = function (f) { return f === 'pdf' ? 'PDF' : 'Word (.docx)'; };

    $('noFile').hidden = !!file;
    $('hasFile').hidden = !file;
    $('noFile').classList.toggle('busy', S.reading || S.dialog);
    $('dzTitle').textContent = S.reading ? t('reading') : S.dialog ? t('dialogOpen') : t('dropTitle');
    document.querySelectorAll('[data-pick]').forEach(function (b) { b.disabled = S.reading || S.dialog; });
    if (!file) return;

    $('srcExt').textContent = c.ext.toUpperCase();
    $('fileName').textContent = file.name;
    $('fileSize').textContent = size(file.size);
    $('removeFile').disabled = running;
    $('srcLabel').textContent = c.ext.toUpperCase() + (c.trad ? ' · ' + c.src.toUpperCase() : '');
    $('srcT').textContent = file.preview.title || file.name;
    $('srcB').textContent = file.preview.body || (file.scan ? t('scanPreview') : '');
    var destination = c.out.toUpperCase() + (c.trad ? ' · ' + c.dst.toUpperCase() : '');
    $('dstLabel').textContent = destination;
    $('dstLabel2').textContent = destination;
    if (done) {
      $('dstT').textContent = S.result.preview.title || S.result.name;
      $('dstB').textContent = S.result.preview.body || t('noPreview');
    }

    pills($('fmtPills'), [
      { key: 'other', label: t('convertTo', { fmt: label(c.ext === 'docx' ? 'pdf' : 'docx') }), on: c.conv,
        pick: function () { idle(); S.fmt = 'other'; render(); } },
      { key: 'same', label: t('keep', { fmt: label(c.ext) }), on: !c.conv,
        pick: function () { idle(); S.fmt = 'same'; render(); } }
    ], running);

    var autoLabel = file.detected ? t('auto', { lang: t('lang_' + file.detected) }) : t('autoUnknown');
    pills($('srcPills'), ['auto'].concat(LANGS).map(function (id) {
      return {
        key: id, label: id === 'auto' ? autoLabel : t('lang_' + id), on: S.srcChoice === id,
        pick: function () {
          idle(); S.srcChoice = id;
          if (S.dst === sourceLang()) S.dst = LANGS.filter(function (l) { return l !== sourceLang(); })[0];
          render();
        }
      };
    }), running);
    pills($('dstPills'), LANGS.map(function (id) {
      return {
        key: id, label: t('lang_' + id), on: S.dst === id,
        pick: function () {
          idle();
          if (sourceLang() === id) S.srcChoice = S.dst;
          S.dst = id; render();
        }
      };
    }), running);

    $('tradBox').classList.toggle('on', c.trad);
    $('sw').setAttribute('aria-checked', c.trad ? 'true' : 'false');
    $('sw').disabled = running;
    $('swap').disabled = running;
    $('tradOpts').hidden = !c.trad;
    $('notTrad').hidden = c.trad;

    var possible = c.conv || c.trad;
    var block = S.stage === 'idle' ? blocker(c) : null;
    $('blocker').hidden = !block;
    if (block) {
      $('blockerText').textContent = block.text;
      $('blockerBtn').hidden = !block.languages;
    }
    var waiting = S.stage === 'idle';
    $('start').textContent = c.conv && c.trad ? t('actBoth') : c.conv ? t('actConvert') : t('actTranslate');
    $('start').hidden = !(waiting && possible);
    $('start').disabled = !!block;
    $('cant').hidden = !(waiting && !possible);
    $('runBtn').hidden = !running;
    $('cancel').hidden = !running;
    $('doneBox').hidden = !done;
    if (done) $('outName').textContent = t('done', { name: S.result.name });
    $('idleBox').hidden = running;
    $('runBox').hidden = !running;
    $('flip').classList.toggle('done', done);
    if (running) renderProgress();

    $('outHint').textContent = done ? t('savedIn', { folder: S.result.path })
      : waiting && possible ? t('willSave', { folder: S.app.settings.out_dir || file.source_dir }) +
        (file.uploaded && !S.app.settings.out_dir ? t('unknownFolder') : '')
      : '';

    $('report').hidden = !done;
    if (done) {
      var report = S.result.report;
      $('counts').textContent = '';
      Object.keys(report.counts).forEach(function (key) {
        if (!report.counts[key] && key !== 'paragraphs') return;
        $('counts').appendChild(el('li', {}, [
          el('b', { text: String(report.counts[key]) }),
          el('span', { text: t((report.counts[key] === 1 ? 'c1_' : 'c_') + key) })
        ]));
      });
      $('counts').hidden = !$('counts').children.length;
      $('warnings').textContent = '';
      report.warnings.forEach(function (w) { $('warnings').appendChild(el('li', { text: w.message })); });
      $('warnings').hidden = !report.warnings.length;
      $('noWarning').hidden = !!report.warnings.length;
    }
  }

  function renderFooter() {
    var c = choices(), engines = [];
    if (S.file && c.ext === 'pdf' && (c.conv || c.trad)) engines.push(S.file.scan ? 'Tesseract OCR' : 'pdf2docx');
    if (S.file && c.out === 'pdf' && (c.conv || c.trad)) engines.push('LibreOffice');
    if (!S.file) engines.push('LibreOffice');
    if (c.trad || !S.file) engines.push('Argos Translate');
    $('engine').textContent = engines.length ? t('engine', { list: engines.join(' + ') }) : t('engineNone');
    var route = '';
    if (S.file) {
      route = c.conv ? c.ext.toUpperCase() + ' → ' + c.out.toUpperCase() : c.ext.toUpperCase();
      if (c.trad) route += ' · ' + c.src.toUpperCase() + ' → ' + c.dst.toUpperCase();
    }
    $('footR').textContent = route;
  }

  /* ---------- Historique ---------- */
  function loadHistory() {
    return api('GET', '/api/history').then(function (items) { S.history = items; renderHistory(); }).catch(showError);
  }
  function renderHistory() {
    var list = $('historyList');
    list.textContent = '';
    $('historyEmpty').hidden = !!S.history.length;
    $('clearHistory').hidden = !S.history.length;
    S.history.forEach(function (entry) {
      var formats = entry.from.toUpperCase() + (entry.from !== entry.to ? ' → ' + entry.to.toUpperCase() : '');
      var langs = entry.source_lang ? ' · ' + entry.source_lang.toUpperCase() + ' → ' + entry.target_lang.toUpperCase() : '';
      var when = new Date(entry.date).toLocaleString(lang(), { dateStyle: 'medium', timeStyle: 'short' });
      var meta = when + ' · ' + formats + langs + ' · ' + t('seconds', { n: entry.duration.toLocaleString(lang()) });
      if (!entry.exists) meta += ' · ' + t('missingFile');
      list.appendChild(el('li', { 'class': 'card item' }, [
        el('div', { 'class': 'stack' }, [
          el('strong', { text: entry.name }), el('span', { 'class': 'meta', text: meta }),
          el('span', { 'class': 'meta', text: entry.path })
        ]),
        el('div', { 'class': 'item-actions' }, [
          el('button', { type: 'button', 'class': 'btn', text: t('openFolder'), 'aria-label': t('openFolder') + ' : ' + entry.name,
            onclick: function () { api('POST', '/api/history/' + entry.id + '/reveal').catch(showError); } }),
          el('button', { type: 'button', 'class': 'link', text: t('remove'), 'aria-label': t('remove') + ' : ' + entry.name,
            onclick: function () { api('DELETE', '/api/history/' + entry.id).then(loadHistory).catch(showError); } })
        ])
      ]));
    });
  }

  /* ---------- Langues ---------- */
  function watchDownload(job) {
    S.downloads[job.label] = job;
    renderModels();
    if (job.status === 'done' || job.status === 'cancelled') {
      delete S.downloads[job.label];
      refreshModels();
    } else if (job.status !== 'error') {
      setTimeout(function () {
        api('GET', '/api/jobs/' + job.id).then(watchDownload).catch(function (error) {
          delete S.downloads[job.label]; showError(error); renderModels();
        });
      }, 500);
    }
  }
  function refreshModels() {
    return api('GET', '/api/models').then(function (models) { S.app.models = models; render(); }).catch(showError);
  }
  function renderModels() {
    var list = $('modelList');
    var focused = document.activeElement && document.activeElement.dataset.key;
    list.textContent = '';
    var name = function (id) { return t('lang_' + id); };
    S.app.models.forEach(function (pair) {
      var ids = pair.id.split('-');
      var title = name(ids[0]) + ' ↔ ' + name(ids[1]);
      var job = S.downloads[pair.id];
      var active = job && (job.status === 'queued' || job.status === 'running');
      var statuses = el('div', { 'class': 'statuses' }, pair.directions.map(function (d) {
        return el('span', { 'class': 'status' + (d.installed ? ' ok' : ''),
          text: d.from.toUpperCase() + ' → ' + d.to.toUpperCase() + ' · ' + t(d.installed ? 'installedState' : 'missingState') });
      }));
      var info = [el('strong', { text: title }), statuses];
      if (job && job.status === 'error') info.push(el('span', { 'class': 'meta', role: 'alert', text: job.error.message }));
      else if (active) info.push(el('span', { 'class': 'meta', text: t('installing', { n: Math.round(job.progress * 100) }) }));
      else if (!pair.installed) info.push(el('span', { 'class': 'meta', text: t('needsInternet') }));
      var button = function (key, label, cls, action) {
        return el('button', { type: 'button', 'class': cls, text: label, 'data-key': key + pair.id,
          'aria-label': label + ' : ' + title, onclick: action });
      };
      var actions = [];
      if (active) {
        actions.push(button('c', t('cancel'), 'btn', function () {
          api('POST', '/api/jobs/' + job.id + '/cancel').catch(showError);
        }));
      } else {
        if (!pair.installed) actions.push(button('i', t('install'), 'btn btn-primary', function () {
          api('POST', '/api/models/' + pair.id).then(watchDownload).catch(showError);
        }));
        if (pair.directions.some(function (d) { return d.installed; })) {
          actions.push(button('u', t('uninstall'), 'btn', function () {
            api('DELETE', '/api/models/' + pair.id).then(function (models) { S.app.models = models; render(); }).catch(showError);
          }));
        }
      }
      var children = [el('div', { 'class': 'stack' }, info), el('div', { 'class': 'item-actions' }, actions)];
      if (active) {
        var fill = el('div');
        fill.style.width = Math.round(job.progress * 100) + '%';
        children.push(el('div', { 'class': 'bar', role: 'progressbar', 'aria-label': title, 'aria-valuemin': '0',
          'aria-valuemax': '100', 'aria-valuenow': String(Math.round(job.progress * 100)) }, [fill]));
      }
      list.appendChild(el('li', { 'class': 'card item' }, children));
    });
    var ready = S.app.models.every(function (p) { return p.installed; });
    list.appendChild(el('li', { 'class': 'card item' }, [el('div', { 'class': 'stack' }, [
      el('strong', { text: name('fr') + ' ↔ ' + name('es') }),
      el('span', { 'class': 'meta', text: t(ready ? 'pivotReady' : 'pivotMissing') + ' ' + t('pivotQuality') })
    ])]));
    if (focused) {
      var again = list.querySelector('[data-key="' + focused + '"]');
      if (again) again.focus();
    }
  }

  /* ---------- Réglages ---------- */
  function renderSettings() {
    var settings = S.app.settings;
    var group = function (id, key, values, prefix) {
      pills($(id), values.map(function (value) {
        return { key: value, label: t(prefix + value), on: settings[key] === value,
          pick: function () { var change = {}; change[key] = value; saveSettings(change); } };
      }));
    };
    group('themePills', 'theme', ['light', 'dark', 'system'], 'th_');
    group('langPills', 'lang', LANGS, 'lang_');
    group('ocrPills', 'ocr', ['auto', 'yes', 'no'], 'ocr_');
    var custom = S.customOut || !!settings.out_dir;
    pills($('outPills'), [
      { key: 'source', label: t('outSource'), on: !custom,
        pick: function () { S.customOut = false; saveSettings({ out_dir: '' }); } },
      { key: 'custom', label: t('outCustom'), on: custom,
        pick: function () { S.customOut = true; render(); $('outPath').focus(); } }
    ]);
    $('outRow').hidden = !custom;
    if (document.activeElement !== $('outPath')) $('outPath').value = settings.out_dir;
    $('outHelp').textContent = custom ? t('outHelpCustom') : t('outHelpSource', { folder: S.app.default_out_dir });
    $('openAfter').setAttribute('aria-checked', settings.open_after ? 'true' : 'false');
    if (document.activeElement !== $('maxMb')) $('maxMb').value = settings.max_mb;
    var tools = [['LibreOffice', S.app.tools.libreoffice], ['Tesseract OCR', S.app.tools.tesseract]];
    $('toolList').textContent = '';
    tools.forEach(function (tool) {
      $('toolList').appendChild(el('span', { 'class': 'status' + (tool[1] ? ' ok' : ''),
        text: tool[0] + ' · ' + t(tool[1] ? 'installedState' : 'missingState') }));
    });
    var missing = tools.filter(function (x) { return !x[1]; }).map(function (x) { return x[0]; });
    $('toolHelp').textContent = missing.length ? t('toolHelpMissing', { list: missing.join(', ') }) : t('toolHelpOk');
    $('about').textContent = t('about', { version: S.app.version, log: S.app.log_file });
  }

  function render() {
    if (!S.app) return;
    document.querySelectorAll('[data-view]').forEach(function (b) {
      if (b.dataset.view === S.view) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    ['document', 'history', 'languages', 'settings'].forEach(function (v) { $('view-' + v).hidden = v !== S.view; });
    $('notice').hidden = !S.notice;
    if (S.notice) {
      $('noticeText').textContent = S.notice.message;
      $('noticeDetails').hidden = !S.notice.detail;
      $('noticeDetail').textContent = S.notice.detail;
    }
    renderDocument();
    renderFooter();
    if (S.view === 'history') renderHistory();
    if (S.view === 'languages') renderModels();
    if (S.view === 'settings') renderSettings();
  }

  function show(view) {
    if (view !== S.view) S.notice = null;
    S.view = view;
    render();
    if (view === 'history') loadHistory();
    if (view === 'languages') refreshModels();
    if (view === 'settings') {
      api('GET', '/api/state').then(function (state) { S.app.tools = state.tools; render(); }).catch(showError);
    }
  }

  /* ---------- Événements ---------- */
  document.querySelectorAll('[data-view]').forEach(function (b) {
    b.addEventListener('click', function () { show(b.dataset.view); });
  });
  document.querySelectorAll('[data-pick]').forEach(function (b) {
    b.addEventListener('click', function (event) { event.stopPropagation(); pick(b.dataset.pick); });
  });
  $('noFile').addEventListener('click', function () { pick('any'); });
  $('fileInput').addEventListener('click', function (event) { event.stopPropagation(); });
  $('fileInput').addEventListener('change', function () {
    if (this.files.length) upload(this.files[0]);
    this.value = '';
  });

  var depth = 0;
  function hasFiles(event) { return Array.prototype.indexOf.call(event.dataTransfer.types, 'Files') !== -1; }
  function over(on) {
    $('noFile').classList.toggle('over', on);
    if (!S.reading && !S.dialog) $('dzTitle').textContent = t(on ? 'dropOver' : 'dropTitle');
  }
  addEventListener('dragenter', function (e) { if (hasFiles(e)) { e.preventDefault(); depth++; over(true); } });
  addEventListener('dragover', function (e) { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
  addEventListener('dragleave', function (e) { if (hasFiles(e) && --depth <= 0) { depth = 0; over(false); } });
  addEventListener('drop', function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; over(false);
    if (!S.app || !e.dataTransfer.files.length) return;
    if (S.view !== 'document') show('document');
    var several = e.dataTransfer.files.length > 1;
    upload(e.dataTransfer.files[0]);
    if (several) announce(t('oneAtATime'));
  });

  $('removeFile').addEventListener('click', dropFile);
  $('reset').addEventListener('click', dropFile);
  $('sw').addEventListener('click', function () {
    idle(); S.trad = !S.trad;
    if (S.dst === sourceLang()) S.dst = LANGS.filter(function (l) { return l !== sourceLang(); })[0];
    render();
  });
  $('swap').addEventListener('click', function () {
    idle();
    var src = sourceLang();
    S.srcChoice = S.dst; S.dst = src; render();
  });
  $('start').addEventListener('click', start);
  $('cancel').addEventListener('click', function () {
    if (!S.job || !S.job.id) return;
    S.job.cancelling = true; renderProgress();
    api('POST', '/api/jobs/' + S.job.id + '/cancel').catch(showError);
  });
  $('openDir').addEventListener('click', function () { api('POST', '/api/jobs/' + S.job.id + '/reveal').catch(showError); });
  $('download').addEventListener('click', function () {
    var name = S.result.name;
    api('GET', '/api/jobs/' + S.job.id + '/download', null, true).then(function (blob) {
      var link = el('a', { href: URL.createObjectURL(blob), download: name });
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(function () { URL.revokeObjectURL(link.href); }, 10000);
    }).catch(showError);
  });
  $('blockerBtn').addEventListener('click', function () { show('languages'); $('view-languages').focus(); });
  $('clearHistory').addEventListener('click', function () { api('DELETE', '/api/history').then(loadHistory).catch(showError); });
  $('themeBtn').addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    if (S.app) saveSettings({ theme: next });
  });
  $('openAfter').addEventListener('click', function () { saveSettings({ open_after: !S.app.settings.open_after }); });
  $('maxMb').addEventListener('change', function () {
    var value = Math.round(Number(this.value));
    value = Math.min(2000, Math.max(1, value || S.app.settings.max_mb));
    this.value = value;
    saveSettings({ max_mb: value });
  });
  $('outPath').addEventListener('change', function () {
    var value = this.value.trim();
    var absolute = /^([A-Za-z]:[\\/]|\\\\|\/)/.test(value);
    if (value && !absolute) { $('outHelp').textContent = t('outInvalid'); return; }
    S.customOut = !!value;
    saveSettings({ out_dir: value });
  });
  $('outBrowse').addEventListener('click', function () {
    api('POST', '/api/pick', { kind: 'folder' }).then(function (answer) {
      if (answer.folder) saveSettings({ out_dir: answer.folder });
      else if (answer.unavailable) $('outPath').focus();
    }).catch(showError);
  });

  /* ---------- Démarrage ---------- */
  api('GET', '/api/state').then(function (state) {
    S.app = state;
    applyTheme();
    translatePage();
    render();
    state.downloads.forEach(watchDownload);
    document.body.dataset.ready = '1';
  }).catch(function (error) {
    if (!error.silent) { $('fatalText').textContent = error.message; $('fatal').hidden = false; }
  });
})();
