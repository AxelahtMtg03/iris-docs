/* Appliqué avant le premier affichage pour éviter un flash de mauvais thème. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('iris-theme'); } catch (e) { /* stockage indisponible */ }
  if (saved !== 'light' && saved !== 'dark') {
    saved = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', saved);
  // Dans la fenêtre de l'application, la page remplit tout, sans le décor du navigateur.
  var desktop = /[#&]d=1/.test(location.hash);
  try {
    if (desktop) sessionStorage.setItem('iris-desktop', '1');
    else desktop = sessionStorage.getItem('iris-desktop') === '1';
  } catch (e) { /* stockage indisponible */ }
  if (desktop) document.documentElement.classList.add('desktop');
})();
