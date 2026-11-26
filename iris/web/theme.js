/* Appliqué avant le premier affichage pour éviter un flash de mauvais thème. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('iris-theme'); } catch (e) { /* stockage indisponible */ }
  if (saved !== 'light' && saved !== 'dark') {
    saved = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', saved);
})();
