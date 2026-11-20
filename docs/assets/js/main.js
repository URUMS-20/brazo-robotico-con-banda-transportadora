/* Documentación del brazo robótico — navegación, enlaces al repo y botones de copiar */
(function () {
  'use strict';

  // >>> CAMBIA ESTO cuando crees el repositorio en GitHub <<<
  var SITIO = {
    nombre: 'Brazo Robótico · The Genesis',
    repo: 'https://github.com/URUMS-20/brazo-robotico-con-banda-transportadora'
  };

  var PAGINAS = [
    { href: 'index.html',           texto: 'Inicio',                icono: 'bi-house' },
    { href: 'funcionamiento.html',  texto: 'Cómo funciona',         icono: 'bi-gear-wide-connected' },
    { href: 'ensamblaje.html',      texto: 'Ensamblaje',            icono: 'bi-wrench-adjustable' },
    { href: 'banda.html',           texto: 'Banda',                 icono: 'bi-arrow-left-right' },
    { href: 'control.html',         texto: 'Control',               icono: 'bi-sliders' },
    { href: 'conexiones.html',      texto: 'Conexiones',            icono: 'bi-diagram-3' },
    { href: 'codigo.html',          texto: 'Códigos',               icono: 'bi-code-slash' },
    { href: 'cad.html',             texto: 'Diseño CAD',            icono: 'bi-box' },
    { href: 'celula.html',          texto: 'Célula (video)',        icono: 'bi-play-circle' },
    { href: 'origen.html',          texto: 'Origen',                icono: 'bi-people' }
  ];

  var actual = (location.pathname.split('/').pop() || 'index.html');

  function crearCabecera() {
    var host = document.getElementById('cabecera');
    if (!host) return;
    var items = PAGINAS.map(function (p) {
      var cur = p.href === actual ? ' aria-current="page"' : '';
      return '<li><a href="' + p.href + '"' + cur + '><i class="bi ' + p.icono + '" aria-hidden="true"></i>' + p.texto + '</a></li>';
    }).join('');
    host.innerHTML =
      '<header class="cab"><div class="wrap">' +
      '<a class="marca" href="index.html"><i class="bi bi-robot" aria-hidden="true"></i><span>' + SITIO.nombre + '</span></a>' +
      '<button class="menu-btn" id="menuBtn" aria-label="Abrir menú" aria-expanded="false" aria-controls="menuNav"><i class="bi bi-list" aria-hidden="true"></i> Menú</button>' +
      '<nav id="menuNav" aria-label="Principal"><ul>' + items + '</ul></nav>' +
      '</div></header>';
    var btn = document.getElementById('menuBtn'), nav = document.getElementById('menuNav');
    btn.addEventListener('click', function () {
      var abierto = nav.classList.toggle('abierto');
      btn.setAttribute('aria-expanded', abierto ? 'true' : 'false');
    });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) nav.classList.remove('abierto'); });
  }

  function crearPie() {
    var host = document.getElementById('pie');
    if (!host) return;
    host.innerHTML =
      '<footer><div class="wrap">' +
      '<span>' + SITIO.nombre + ' · documentación técnica</span>' +
      '<span><a href="' + SITIO.repo + '" target="_blank" rel="noopener"><i class="bi bi-github" aria-hidden="true"></i> Código en GitHub</a></span>' +
      '</div></footer>';
  }

  // <a data-repo="ruta/dentro/del/repo"> -> enlace completo al archivo en GitHub
  function enlazarRepo() {
    document.querySelectorAll('[data-repo]').forEach(function (a) {
      var ruta = a.getAttribute('data-repo');
      var esCarpeta = ruta === '' || ruta.slice(-1) === '/';
      a.href = SITIO.repo + (ruta ? (esCarpeta ? '/tree/main/' : '/blob/main/') + ruta : '');
      a.target = '_blank'; a.rel = 'noopener';
    });
  }

  function botonesCopiar() {
    document.querySelectorAll('.bloque').forEach(function (b) {
      var pre = b.querySelector('pre');
      if (!pre || b.querySelector('.copiar')) return;
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'copiar'; btn.textContent = 'Copiar';
      btn.addEventListener('click', function () {
        var t = pre.innerText;
        var ok = function () { btn.textContent = '¡Copiado!'; setTimeout(function () { btn.textContent = 'Copiar'; }, 1500); };
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(ok);
        else { var r = document.createRange(); r.selectNodeContents(pre); var s = getSelection(); s.removeAllRanges(); s.addRange(r); document.execCommand('copy'); s.removeAllRanges(); ok(); }
      });
      b.appendChild(btn);
    });
  }

  // <button data-seek="42"> salta a ese segundo del <video id="video">
  function saltosDeVideo() {
    var v = document.getElementById('video');
    if (!v) return;
    document.querySelectorAll('[data-seek]').forEach(function (b) {
      b.addEventListener('click', function () {
        v.currentTime = Number(b.getAttribute('data-seek')) || 0;
        v.play(); v.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    crearCabecera(); crearPie(); enlazarRepo(); botonesCopiar(); saltosDeVideo();
  });
})();
