/* Appliqué avant le premier affichage pour éviter un flash de mauvais thème. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('iris-theme'); } catch (e) { /* stockage indisponible */ }
  if (saved !== 'light' && saved !== 'dark') {
    saved = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', saved);
  // Dans la fenêtre de l'application, la page remplit tout, sans le décor du navigateur.
  // « winframe » : fenêtre sans barre de titre, la page dessine les boutons.
  [['d', 'desktop'], ['w', 'winframe']].forEach(function (flag) {
    var on = new RegExp('[#&]' + flag[0] + '=1').test(location.hash);
    try {
      if (on) sessionStorage.setItem('iris-' + flag[1], '1');
      else on = sessionStorage.getItem('iris-' + flag[1]) === '1';
    } catch (e) { /* stockage indisponible */ }
    if (on) document.documentElement.classList.add(flag[1]);
  });
})();
