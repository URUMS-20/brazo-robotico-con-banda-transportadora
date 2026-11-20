/* =====================================================================
   BRAZO ROBÓTICO (The Genesis) — lógica de la interfaz
   ---------------------------------------------------------------------
   - Barras en TIEMPO REAL: evento "input" + una sola petición en vuelo
     con el valor MÁS RECIENTE (nunca se acumula retraso).
   - Estado en vivo por Server-Sent Events (/api/eventos): posición
     solicitada, límites, velocidad, calibración, secuencia y visión.
   - Gemelo 3D: modelo real (brazo_articulado.glb) — solo dibuja.
   - Cámara: video MJPEG (/video) con los cubos detectados.
   ===================================================================== */
const INTERVALO_MIN_MS = 20;      // máximo ~50 envíos por segundo
import { crearControlBanda } from './banda.js';
let controlBanda = null;

let ARTS = [];                    // nombres que manda app.py
let est = null;                   // último estado recibido
const ui = [];                    // elementos de cada tarjeta
const pendientes = new Map();     // id -> último ángulo sin enviar
let enVuelo = false;
let versionLocal = -1;
let arrastrando = null;           // id de la barra que se está arrastrando
let ultimoAviso = 0;

let gemelo = null;                // visor 3D (si cargó)
let cfgGemelo = null;             // calibración guardada del gemelo (ceros y sentidos)
let textoPendientes = null;

let camaras = [];                 // resultado de "Buscar cámaras"
let videoActivo = false;
let ultimoDetTxt = '';
const COLOR_CSS = { rojo: '#e5484d', verde: '#46c46a', azul: '#3b82f6', amarillo: '#f2c94c' };

let biblio = { poses: [], secuencias: [] };
let secEditada = { id: null, nombre: '', pasos: [] };
let secSucia = false;             // hay cambios sin guardar en la secuencia

const $ = (s) => document.querySelector(s);

/* =========================== Utilidades ============================ */
async function api(url, metodo = 'GET', datos = undefined) {
  const r = await fetch(url, {
    method: metodo,
    headers: datos !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: datos !== undefined ? JSON.stringify(datos) : undefined,
    cache: 'no-store',
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.error || `Error ${r.status}`);
  return d;
}

function avisar(texto, tipo = 'info') {
  const div = document.createElement('div');
  div.className = 'aviso ' + tipo;
  div.textContent = texto;
  $('#avisos').appendChild(div);
  setTimeout(() => div.remove(), tipo === 'error' ? 8000 : 4000);
}

// Botón que pide un segundo toque para confirmar (evita borrar por accidente)
function confirmarDoble(btn, accion) {
  let timer = null;
  const texto = btn.textContent;
  btn.addEventListener('click', () => {
    if (btn.classList.contains('confirmar')) {
      clearTimeout(timer);
      btn.classList.remove('confirmar');
      btn.textContent = texto;
      accion();
      return;
    }
    btn.classList.add('confirmar');
    btn.textContent = '¿Seguro? toca otra vez';
    timer = setTimeout(() => { btn.classList.remove('confirmar'); btn.textContent = texto; }, 3000);
  });
}

function chip(id, clase, texto) {
  const el = $(id);
  el.className = 'chip ' + clase;
  el.querySelector('b').textContent = texto;
}
const marcarServidor = (ok) => chip('#chipServidor', ok ? 'ok' : 'bad', ok ? 'Servidor' : 'Sin servidor');
const marcarLatencia = (ms) => chip('#chipLatencia', ms < 60 ? 'ok' : 'warn', `${Math.round(ms)} ms`);
const fmt = (v) => (Math.round(v * 10) / 10).toString();

/* ====================== Tarjetas de articulación ===================== */
function construirTablero() {
  const tablero = $('#tablero');
  tablero.innerHTML = '';
  ARTS.forEach((a) => {
    const card = document.createElement('section');
    card.className = 'card' + (a.id === 1 ? ' acoplado' : '');
    card.innerHTML = `
      <div class="card-top">
        <span class="tag">${a.motores}</span>
        <span class="nombre">${a.nombre}</span>
        <span class="rango"></span>
        <span class="valor"><b>--</b><span>°</span></span>
      </div>
      <div class="fila">
        <button data-d="-5" aria-label="menos 5 grados">−5</button>
        <button data-d="-1" aria-label="menos 1 grado">−1</button>
        <input type="range" step="1" aria-label="${a.motores} ${a.nombre}">
        <button data-d="1" aria-label="más 1 grado">+1</button>
        <button data-d="5" aria-label="más 5 grados">+5</button>
      </div>
      <div class="fila-calib">
        <button data-lim="min">Fijar mín</button>
        <span class="lim"></span>
        <button data-lim="max">Fijar máx</button>
      </div>`;
    tablero.appendChild(card);

    const slider = card.querySelector('input');
    ui[a.id] = {
      slider,
      valor: card.querySelector('.valor b'),
      rango: card.querySelector('.rango'),
      lim: card.querySelector('.lim'),
      min: 0, max: 180,
    };

    // "input" se dispara MIENTRAS arrastras -> movimiento en tiempo real
    slider.addEventListener('input', () => {
      const v = Number(slider.value);
      pintar(a.id, v);
      encolar(a.id, v);
    });
    slider.addEventListener('pointerdown', () => { arrastrando = a.id; });

    card.querySelectorAll('button[data-d]').forEach((b) =>
      repetirMientrasPresionas(b, () => ajustar(a.id, Number(b.dataset.d))));
    card.querySelectorAll('button[data-lim]').forEach((b) =>
      b.addEventListener('click', () => fijarLimite(a.id, b.dataset.lim)));
  });
  const fin = () => { arrastrando = null; };
  window.addEventListener('pointerup', fin);
  window.addEventListener('pointercancel', fin);
}

function pintar(id, v) {
  const u = ui[id];
  u.valor.textContent = Math.round(v);
  u.slider.style.setProperty('--p', ((v - u.min) / (u.max - u.min)) * 100 + '%');
}

function ajustar(id, delta) {
  const u = ui[id];
  const v = Math.min(u.max, Math.max(u.min, Number(u.slider.value) + delta));
  u.slider.value = v;
  pintar(id, v);
  encolar(id, v);
}

// Mantener presionado +1/-1 repite el paso (ajuste fino cómodo en el celular)
function repetirMientrasPresionas(btn, accion) {
  let t1 = null, t2 = null;
  const parar = () => { clearTimeout(t1); clearInterval(t2); t1 = t2 = null; };
  btn.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    accion();
    t1 = setTimeout(() => { t2 = setInterval(accion, 70); }, 350);
  });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => btn.addEventListener(ev, parar));
  btn.addEventListener('click', (e) => { if (e.detail === 0) accion(); });   // teclado
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
}

// Rango de cada barra: límites guardados, o 0..180 en modo calibración
function aplicarRangos(e) {
  e.lim.forEach(([mn, mx], id) => {
    const u = ui[id];
    if (!u) return;
    const nuevoMin = e.calib ? 0 : mn;
    const nuevoMax = e.calib ? 180 : mx;
    if (u.min !== nuevoMin || u.max !== nuevoMax) {
      u.min = nuevoMin; u.max = nuevoMax;
      u.slider.min = nuevoMin; u.slider.max = nuevoMax;
    }
    u.rango.textContent = `${fmt(nuevoMin)}–${fmt(nuevoMax)}°`;
    u.lim.textContent = `Límite: ${fmt(mn)}° – ${fmt(mx)}°`;
    u.slider.style.setProperty('--lmin', (mn / 180) * 100 + '%');
    u.slider.style.setProperty('--lmax', (mx / 180) * 100 + '%');
    pintar(id, Number(u.slider.value));
  });
}

// Pone las barras en la posición del servidor, excepto la que estás moviendo
function aplicarPosiciones(pos) {
  pos.forEach((v, id) => {
    if (id === arrastrando || pendientes.has(id) || !ui[id]) return;
    if (Number(ui[id].slider.value) !== Math.round(v)) ui[id].slider.value = v;
    pintar(id, v);
  });
}

/* ========================= Envío en tiempo real ===================== */
function encolar(id, v) {
  pendientes.set(id, v);
  bombear();
}

async function bombear() {
  if (enVuelo || pendientes.size === 0) return;
  enVuelo = true;
  const lote = Object.fromEntries(pendientes);
  pendientes.clear();
  const t0 = performance.now();
  try {
    const d = await api('/api/mover', 'POST', { cambios: lote });
    marcarServidor(true);
    marcarLatencia(performance.now() - t0);
    versionLocal = Math.max(versionLocal, d.ver);
    aplicarPosiciones(d.obj);
  } catch (err) {
    marcarServidor(false);
    for (const [k, v] of Object.entries(lote)) {           // reintentar solo lo más nuevo
      if (!pendientes.has(Number(k))) pendientes.set(Number(k), v);
    }
    await new Promise((res) => setTimeout(res, 500));
  }
  const espera = Math.max(0, INTERVALO_MIN_MS - (performance.now() - t0));
  setTimeout(() => { enVuelo = false; bombear(); }, espera);
}

/* ============================ Estado en vivo ======================== */
function aplicarEstado(e) {
  if (controlBanda) controlBanda.aplicar(e);
  const calibAntes = est ? est.calib : null;
  est = e;

  // Chips de conexión
  if (e.modo === 'esp32') {
    chip('#chipEsp32', e.firmware === 'v2' ? 'ok' : 'warn',
      `ESP32 · ${e.puerto}` + (e.firmware === 'v1' ? ' · firmware viejo' : ''));
  } else if (e.modo === 'simulacion') {
    chip('#chipEsp32', 'warn', 'Simulación');
  } else {
    chip('#chipEsp32', 'warn', 'Buscando ESP32…');
  }

  // Modo calibración
  document.body.classList.toggle('calibrando', e.calib);
  $('#bandaCalib').hidden = !e.calib;
  $('#btnCalib').textContent = e.calib ? 'Salir del modo calibración' : 'Entrar a modo calibración';
  if (calibAntes !== null && calibAntes !== e.calib) versionLocal = -1;   // re-sincronizar barras

  aplicarRangos(e);
  if (e.ver > versionLocal && !enVuelo && pendientes.size === 0) {
    versionLocal = e.ver;
    aplicarPosiciones(e.obj);
  }

  // Velocidad
  document.querySelectorAll('[data-vel]').forEach((b) =>
    b.classList.toggle('activo', Number(b.dataset.vel) === e.vel));

  // Gemelo 3D: posición solicitada que reporta el ESP32 (no la barra)
  if (gemelo) gemelo.ponerAngulos(e.act);

  // Cámara y visión artificial
  if (e.vision) aplicarVision(e.vision);

  // Secuencia en curso
  pintarReproduccion(e.rep);

  // Avisos del servidor / ESP32
  if (e.aviso && e.aviso.id > ultimoAviso) {
    ultimoAviso = e.aviso.id;
    avisar(e.aviso.texto, e.aviso.tipo);
  }
}

function conectarEventos() {
  const fuente = new EventSource('/api/eventos');
  fuente.onmessage = (ev) => {
    marcarServidor(true);
    aplicarEstado(JSON.parse(ev.data));
  };
  fuente.onerror = () => marcarServidor(false);    // EventSource se reconecta solo
}

/* ========================== Acciones generales ====================== */
async function accion(url, datos, textoOk) {
  try {
    const d = await api(url, 'POST', datos);
    if (textoOk) avisar(textoOk, 'ok');
    return d;
  } catch (err) {
    avisar(err.message, 'error');
    return null;
  }
}

function stop() {
  if (controlBanda) controlBanda.detenerLocal();
  pendientes.clear();
  const b = $('#btnStop');
  b.classList.add('pulso');
  setTimeout(() => b.classList.remove('pulso'), 300);
  accion('/api/stop', {});
}

async function fijarLimite(id, tipo) {
  const d = await accion('/api/limite', { j: id, tipo });
  if (d) avisar(`${ARTS[id].nombre}: límite ${tipo === 'min' ? 'mínimo' : 'máximo'} guardado en ${Math.round(ui[id].slider.value)}°`, 'ok');
}

/* ============================== Poses =============================== */
function pintarPoses() {
  const lista = $('#listaPoses');
  lista.innerHTML = '';
  if (biblio.poses.length === 0) {
    lista.innerHTML = '<li class="vacio">Aún no hay poses. Mueve el brazo y guarda la posición.</li>';
  }
  biblio.poses.forEach((p) => {
    const li = document.createElement('li');
    li.innerHTML = `
      <div class="info">
        <span class="nom"></span>
        <span class="ang">${p.angulos.map((a) => Math.round(a)).join(' · ')}</span>
      </div>
      <button data-a="ir" title="Mover el brazo a esta pose">Ir</button>
      <button data-a="act" title="Reemplazar con la posición actual">⟳</button>
      <button data-a="borrar" class="peligro" title="Borrar">✕</button>`;
    li.querySelector('.nom').textContent = p.nombre;
    li.querySelector('[data-a=ir]').addEventListener('click', () => accion(`/api/poses/${p.id}/ir`, {}));
    li.querySelector('[data-a=act]').addEventListener('click', async () => {
      try { biblio = await api(`/api/poses/${p.id}`, 'PUT', {}); pintarBiblioteca(); avisar(`"${p.nombre}" actualizada`, 'ok'); }
      catch (err) { avisar(err.message, 'error'); }
    });
    confirmarDoble(li.querySelector('[data-a=borrar]'), async () => {
      try {
        biblio = await api(`/api/poses/${p.id}`, 'DELETE');
        secEditada.pasos = secEditada.pasos.filter((s) => s.pose !== p.id);
        pintarBiblioteca();
      } catch (err) { avisar(err.message, 'error'); }
    });
    lista.appendChild(li);
  });
}

/* ============================ Secuencias ============================ */
function pintarSelectorSecuencias() {
  const sel = $('#selSecuencia');
  sel.innerHTML = '';
  if (secEditada.id === null) sel.add(new Option('(nueva secuencia)', ''));
  biblio.secuencias.forEach((s) => sel.add(new Option(s.nombre, s.id)));
  sel.value = secEditada.id || '';
}

function pintarPasos() {
  const lista = $('#listaPasos');
  lista.innerHTML = '';
  $('#nombreSec').value = secEditada.nombre;
  if (secEditada.pasos.length === 0) {
    lista.innerHTML = `<li class="vacio">${biblio.poses.length
      ? 'Sin pasos. Toca “Añadir paso”.' : 'Primero guarda algunas poses.'}</li>`;
  }
  secEditada.pasos.forEach((paso, k) => {
    const li = document.createElement('li');
    const sel = document.createElement('select');
    biblio.poses.forEach((p) => sel.add(new Option(p.nombre, p.id)));
    sel.value = paso.pose;
    sel.addEventListener('change', () => { paso.pose = sel.value; marcarSucia(); });
    li.appendChild(sel);
    const pausa = document.createElement('label');
    pausa.className = 'pausa';
    pausa.innerHTML = 'pausa <input type="number" min="0" max="60" step="0.5"> s';
    const inp = pausa.querySelector('input');
    inp.value = paso.pausa;
    inp.addEventListener('input', () => { paso.pausa = Number(inp.value) || 0; marcarSucia(); });
    li.appendChild(pausa);
    const mk = (txt, titulo, fn) => {
      const b = document.createElement('button');
      b.textContent = txt; b.title = titulo; b.type = 'button';
      b.addEventListener('click', fn);
      li.appendChild(b);
      return b;
    };
    mk('↑', 'Subir', () => mover(k, -1)).disabled = k === 0;
    mk('↓', 'Bajar', () => mover(k, 1)).disabled = k === secEditada.pasos.length - 1;
    mk('✕', 'Quitar paso', () => { secEditada.pasos.splice(k, 1); marcarSucia(); pintarPasos(); })
      .classList.add('peligro');
    lista.appendChild(li);
  });
  marcarPasoActual();
}

function mover(k, d) {
  const p = secEditada.pasos;
  [p[k], p[k + d]] = [p[k + d], p[k]];
  marcarSucia();
  pintarPasos();
}

function marcarSucia() {
  secSucia = true;
  $('#btnGuardarSec').textContent = 'Guardar *';
}

function cargarSecuencia(id) {
  const s = biblio.secuencias.find((x) => x.id === id);
  secEditada = s ? JSON.parse(JSON.stringify(s)) : { id: null, nombre: '', pasos: [] };
  secSucia = false;
  $('#btnGuardarSec').textContent = 'Guardar';
  pintarSelectorSecuencias();
  pintarPasos();
}

function pintarBiblioteca() {
  pintarPoses();
  if (secEditada.id && !biblio.secuencias.some((s) => s.id === secEditada.id)) {
    secEditada = { id: null, nombre: '', pasos: [] };
  }
  pintarSelectorSecuencias();
  pintarPasos();
}

async function guardarSecuencia(silencioso = false) {
  secEditada.nombre = $('#nombreSec').value.trim();
  try {
    const d = await api('/api/secuencias', 'POST', secEditada);
    biblio = { poses: d.poses, secuencias: d.secuencias };
    cargarSecuencia(d.guardada);
    if (!silencioso) avisar('Secuencia guardada', 'ok');
    return true;
  } catch (err) {
    avisar(err.message, 'error');
    return false;
  }
}

async function reproducirODetener() {
  if (est && est.rep.activo) {
    accion('/api/secuencias/detener', {});
    return;
  }
  if (secEditada.pasos.length === 0) {
    avisar('La secuencia no tiene pasos.', 'error');
    return;
  }
  if (secSucia || !secEditada.id) {
    if (!(await guardarSecuencia(true))) return;
  }
  accion(`/api/secuencias/${secEditada.id}/reproducir`, { repetir: $('#chkRepetir').checked });
}

function pintarReproduccion(rep) {
  const btn = $('#btnReproducir');
  btn.textContent = rep.activo ? '■ Detener secuencia' : '▶ Reproducir';
  $('#estadoRep').textContent = rep.activo
    ? `${rep.nombre} · paso ${rep.paso} de ${rep.total}` + (rep.repetir ? ` · vuelta ${rep.vuelta}` : '')
    : '';
  marcarPasoActual();
}

function marcarPasoActual() {
  const activo = est && est.rep.activo && est.rep.sec === secEditada.id && !secSucia;
  document.querySelectorAll('#listaPasos li').forEach((li, k) =>
    li.classList.toggle('actual', !!activo && k === est.rep.paso - 1));
}

/* ============================ Gemelo 3D ============================= */
const JUNTAS_CAL = [
  { clave: 'base', j: 0, nombre: 'Base' }, { clave: 'hombro', j: 1, nombre: 'Hombro' },
  { clave: 'codo', j: 2, nombre: 'Codo' }, { clave: 'muneca', j: 3, nombre: 'Muñeca (flexión)' },
  { clave: 'giro', j: 4, nombre: 'Giro de pinza' },
];
const NOMBRES_CAL = Object.fromEntries([...JUNTAS_CAL.map((x) => [x.clave, x.nombre]), ['pinza', 'Pinza']]);

function construirTablaCalib() {
  const tb = $('#tablaCalib');
  tb.innerHTML = '';
  const fila = (clave, j, nombre, opciones) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${nombre}<span class="pend" data-pend="${clave}"></span></td>
      <td>${ARTS[j].canales.join(' + ')}</td>
      <td><input type="number" min="0" max="180" step="0.5" data-cero="${clave}" aria-label="Cero de ${nombre}"></td>
      <td><select data-sentido="${clave}" aria-label="Sentido de ${nombre}">
        <option value="">— elegir —</option>${opciones}</select></td>`;
    tb.appendChild(tr);
  };
  JUNTAS_CAL.forEach(({ clave, j, nombre }) =>
    fila(clave, j, nombre, '<option value="1">Normal</option><option value="-1">Invertido</option>'));
  fila('pinza', 5, 'Pinza (abierta = 85 mm)',
    '<option value="1">Cierra al subir el ángulo</option><option value="-1">Cierra al bajar el ángulo</option>');
}

function leerCalib() {
  const val = (sel) => { const el = $(sel); return el.value === '' ? null : Number(el.value); };
  const cal = { version: 2 };
  JUNTAS_CAL.forEach(({ clave }) => {
    cal[clave] = { cero: val(`[data-cero=${clave}]`), sentido: val(`[data-sentido=${clave}]`) };
  });
  cal.pinza = { abierta: val('[data-cero=pinza]'), sentido_cierre: val('[data-sentido=pinza]') };
  return cal;
}

function llenarCalib(cal) {
  const poner = (sel, v) => { $(sel).value = v === null || v === undefined ? '' : String(v); };
  JUNTAS_CAL.forEach(({ clave }) => {
    poner(`[data-cero=${clave}]`, cal[clave].cero);
    poner(`[data-sentido=${clave}]`, cal[clave].sentido);
  });
  poner('[data-cero=pinza]', cal.pinza.abierta);
  poner('[data-sentido=pinza]', cal.pinza.sentido_cierre);
}

function mostrarPendientes(lista) {
  const txt = lista.join(',');
  if (txt === textoPendientes) return;
  textoPendientes = txt;
  const av = $('#avisoGemelo');
  av.hidden = lista.length === 0;
  av.textContent = `Sin calibrar: ${lista.map((k) => NOMBRES_CAL[k]).join(', ')} · toca para calibrar`;
  document.querySelectorAll('[data-pend]').forEach((el) => {
    el.textContent = lista.includes(el.dataset.pend) ? ' · pendiente' : '';
  });
}

function cerrarCalibGemelo() {
  $('#formGemelo').hidden = true;
  $('#chkReposo').checked = false;
  if (gemelo) { gemelo.mostrarReposo(false); gemelo.ponerCalibracion(cfgGemelo); }   // descartar lo no guardado
}

async function iniciarGemelo() {
  const cont = $('#lienzoGemelo');
  const carga = $('#cargaGemelo');
  try {
    const { crearGemelo } = await import('./gemelo.js');
    gemelo = await crearGemelo(cont, cfgGemelo, {
      onProgreso: (pct) => { carga.textContent = `Cargando modelo 3D… ${pct} %`; },
      onPunta: (x, y, z) => {
        $('#coordPunta').textContent = `Punta  X ${Math.round(x)} · Y ${Math.round(y)} · Z ${Math.round(z)} mm`;
      },
      onPendientes: mostrarPendientes,
    });
    carga.hidden = true;
    window.gemeloGenesis = gemelo;                         // para revisar desde la consola (F12)
    if (est) gemelo.ponerAngulos(est.act);
  } catch (err) {
    console.error(err);
    carga.textContent = 'No se pudo mostrar el gemelo 3D: ' + err.message +
      '. Revisa que el navegador tenga activada la aceleración gráfica (WebGL).';
  }
}

/* ======================= Cámara y visión artificial ======================= */
function textoCamara(c) {
  if (c === 'telefono') return 'Mi teléfono (WiFi / IP Webcam)';
  if (c === 'sintetica') return 'Imagen de prueba (sin cámara)';
  return c === null || c === undefined ? '— elige una cámara —' : `Cámara ${c}`;
}

function valorCamara(texto) {
  if (texto === '') return null;
  return ['sintetica', 'telefono'].includes(texto) ? texto : Number(texto);
}

function pintarSelectorCamaras(actual) {
  const sel = $('#selCamara');
  const opciones = camaras.length ? camaras.map((c) => [String(c.indice), c.texto]) : [];
  if (!opciones.some(([v]) => v === 'telefono')) opciones.push(['telefono', textoCamara('telefono')]);
  if (!opciones.some(([v]) => v === '')) opciones.unshift(['', '- elige una cámara -']);
  if (actual !== null && actual !== undefined && !opciones.some(([v]) => v === String(actual))) {
    opciones.unshift([String(actual), textoCamara(actual)]);
  }
  if (!opciones.length) opciones.push(['', 'Toca “Buscar cámaras”']);
  const firma = JSON.stringify(opciones);
  if (sel.dataset.firma !== firma) {
    sel.innerHTML = '';
    opciones.forEach(([v, t]) => sel.add(new Option(t, v)));
    sel.dataset.firma = firma;
  }
  if (document.activeElement !== sel) sel.value = actual === null || actual === undefined ? sel.options[0].value : String(actual);
}

function aplicarVision(v) {
  const telefono = $('#urlTelefono');
  if (document.activeElement !== telefono && telefono.dataset.guardada !== (v.url_telefono || '')) {
    telefono.value = v.url_telefono || '';
    telefono.dataset.guardada = v.url_telefono || '';
  }
  $('#btnTelefono').disabled = !v.disponible;
  if (!v.disponible) {
    chip('#chipCamara', 'bad', 'Sin OpenCV');
    $('#estadoCam').textContent = 'Falta instalar OpenCV:  python -m pip install -r requirements.txt';
    $('#sinVideo').textContent = 'Instala OpenCV para usar la cámara.';
    ['#btnCamara', '#btnBuscarCam', '#btnCalibrarCam'].forEach((s) => { $(s).disabled = true; });
    return;
  }
  // Chip y textos
  if (v.activa) chip('#chipCamara', 'ok', `Cámara · ${v.fps} fps`);
  else if (v.encendida) chip('#chipCamara', 'warn', v.error ? 'Cámara con error' : 'Cámara conectando…');
  else chip('#chipCamara', '', 'Cámara apagada');
  $('#estadoCam').textContent = v.error || (v.activa
    ? `${textoCamara(v.camara)} · ${v.detecciones.length} objeto(s) detectado(s)`
    : (v.encendida ? 'Abriendo la cámara…' : 'Apagada'));
  $('#btnCamara').textContent = v.encendida ? '■ Apagar' : '▶ Encender';
  pintarSelectorCamaras(v.camara);

  // Video (MJPEG): solo se pide cuando la cámara ya está entregando imágenes
  const img = $('#video');
  if (v.activa && !videoActivo) {
    videoActivo = true;
    img.src = '/video?t=' + Date.now();
    img.hidden = false;
  } else if (!v.activa && videoActivo) {
    videoActivo = false;
    img.removeAttribute('src');
    img.hidden = true;
  }
  $('#sinVideo').hidden = v.activa;
  $('#sinVideo').textContent = v.error || (v.encendida ? 'Conectando con la cámara…' : 'Cámara apagada');

  // Detecciones
  const txt = JSON.stringify(v.detecciones);
  if (txt !== ultimoDetTxt) {
    ultimoDetTxt = txt;
    const ul = $('#listaDetecciones');
    ul.innerHTML = '';
    if (v.activa && v.detecciones.length === 0) ul.innerHTML = '<li class="vacio">No se detectan cubos.</li>';
    v.detecciones.slice(0, 6).forEach((d) => {
      const li = document.createElement('li');
      const tam = d.lado_cm !== undefined ? `${d.clase} (${d.lado_cm} cm)` : `${Math.round(d.lado_px)} px`;
      const pos = d.pos_cm ? `x ${d.pos_cm[0]} · y ${d.pos_cm[1]} cm` : `(${d.centro_px[0]}, ${d.centro_px[1]}) px`;
      li.innerHTML = `<span class="muestra" style="background:${COLOR_CSS[d.color] || '#888'}"></span>
        <span class="clase"></span><span class="tam"></span><span class="pos"></span>`;
      li.querySelector('.clase').textContent = d.color[0].toUpperCase() + d.color.slice(1);
      li.querySelector('.tam').textContent = tam;
      li.querySelector('.pos').textContent = pos;
      ul.appendChild(li);
    });
  }

  // Ajustes
  $('#valPxCm').textContent = v.px_por_cm ? `${v.px_por_cm} px/cm` : 'sin calibrar';
  const cont = $('#coloresVision');
  if (!cont.children.length) {
    Object.keys(v.colores).forEach((nombre) => {
      const lab = document.createElement('label');
      lab.innerHTML = `<input type="checkbox" data-color="${nombre}"><span class="muestra-chica" style="background:${COLOR_CSS[nombre] || '#888'}"></span>${nombre}`;
      lab.querySelector('input').addEventListener('change', (ev) =>
        accion('/api/vision', { colores: { [nombre]: ev.target.checked } }));
      cont.appendChild(lab);
    });
  }
  cont.querySelectorAll('input[data-color]').forEach((ch) => { ch.checked = !!v.colores[ch.dataset.color]; });
  $('#chkExpAuto').checked = v.exposicion_auto;
  const rng = $('#rngExposicion');
  rng.disabled = v.exposicion_auto;
  if (document.activeElement !== rng) rng.value = v.exposicion;
  pintarExposicion(v.exposicion_auto);
  if (v.camara === 'telefono') {
    $('#chkExpAuto').disabled = true;
    rng.disabled = true;
  } else $('#chkExpAuto').disabled = false;
}

function pintarExposicion(auto) {
  const rng = $('#rngExposicion');
  const p = auto ? 0 : ((Number(rng.value) - Number(rng.min)) / (Number(rng.max) - Number(rng.min))) * 100;
  rng.style.setProperty('--p', p + '%');
  $('#valExposicion').textContent = auto ? 'auto' : rng.value;
}

async function buscarCamaras() {
  const b = $('#btnBuscarCam');
  b.disabled = true;
  b.textContent = 'Buscando…';
  try {
    camaras = (await api('/api/vision/camaras')).camaras;
    $('#selCamara').dataset.firma = '';
    pintarSelectorCamaras(est && est.vision ? est.vision.camara : null);
    if (!camaras.some((c) => c.indice !== 'sintetica')) avisar('No encontré cámaras USB. ¿Está conectada la Brio 100?', 'error');
  } catch (err) { avisar(err.message, 'error'); }
  b.disabled = false;
  b.textContent = 'Buscar cámaras';
}

/* ============================== Inicio ============================== */
function conectarBotones() {
  $('#btnStop').addEventListener('click', stop);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') stop(); });
  $('#btnHome').addEventListener('click', () => { pendientes.clear(); accion('/api/home', {}); });
  document.querySelectorAll('[data-vel]').forEach((b) =>
    b.addEventListener('click', () => accion('/api/velocidad', { pct: Number(b.dataset.vel) })));

  // Calibración
  $('#btnCalib').addEventListener('click', () => accion('/api/calibracion', { activo: !(est && est.calib) }));
  $('#btnGuardarHome').addEventListener('click', () =>
    accion('/api/home/guardar', {}, 'HOME guardado en el ESP32'));
  confirmarDoble($('#btnFabrica'), () => accion('/api/fabrica', {}, 'Límites y HOME de fábrica restaurados'));

  // Poses
  $('#formPose').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      biblio = await api('/api/poses', 'POST', { nombre: $('#nombrePose').value });
      $('#nombrePose').value = '';
      pintarBiblioteca();
    } catch (err) { avisar(err.message, 'error'); }
  });

  // Secuencias
  $('#selSecuencia').addEventListener('change', (e) => cargarSecuencia(e.target.value || null));
  $('#btnNuevaSec').addEventListener('click', () => cargarSecuencia(null));
  $('#nombreSec').addEventListener('input', () => { secEditada.nombre = $('#nombreSec').value; marcarSucia(); });
  $('#btnAgregarPaso').addEventListener('click', () => {
    if (biblio.poses.length === 0) { avisar('Primero guarda al menos una pose.', 'error'); return; }
    const ultima = biblio.poses[biblio.poses.length - 1];
    secEditada.pasos.push({ pose: ultima.id, pausa: 1 });
    marcarSucia();
    pintarPasos();
  });
  $('#btnGuardarSec').addEventListener('click', () => guardarSecuencia());
  confirmarDoble($('#btnBorrarSec'), async () => {
    if (!secEditada.id) { cargarSecuencia(null); return; }
    try {
      biblio = await api(`/api/secuencias/${secEditada.id}`, 'DELETE');
      cargarSecuencia(null);
      pintarBiblioteca();
    } catch (err) { avisar(err.message, 'error'); }
  });
  $('#btnReproducir').addEventListener('click', reproducirODetener);

  // Gemelo 3D: vistas y calibración (ceros y sentidos)
  $('#btnVistaBrazo').addEventListener('click', () => gemelo && gemelo.vista('brazo'));
  $('#btnVistaPinza').addEventListener('click', () => gemelo && gemelo.vista('pinza'));
  const form = $('#formGemelo');
  const abrirCalib = () => {
    if (!form.hidden) { cerrarCalibGemelo(); return; }
    llenarCalib(cfgGemelo);
    form.hidden = false;
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  $('#btnCalibrarGemelo').addEventListener('click', abrirCalib);
  $('#avisoGemelo').addEventListener('click', () => { if (form.hidden) abrirCalib(); });
  form.addEventListener('input', () => { if (gemelo) gemelo.ponerCalibracion(leerCalib()); });
  form.addEventListener('change', () => { if (gemelo) gemelo.ponerCalibracion(leerCalib()); });
  $('#chkReposo').addEventListener('change', (e) => { if (gemelo) gemelo.mostrarReposo(e.target.checked); });
  $('#btnCapturarCero').addEventListener('click', () => {
    if (!est) return;
    JUNTAS_CAL.forEach(({ clave, j }) => { $(`[data-cero=${clave}]`).value = est.obj[j]; });
    $('[data-cero=pinza]').value = est.obj[5];
    if (gemelo) gemelo.ponerCalibracion(leerCalib());
    avisar('Ceros tomados de la posición actual. Ahora elige el sentido de cada articulación.', 'ok');
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      cfgGemelo = await api('/api/gemelo', 'POST', leerCalib());
      llenarCalib(cfgGemelo);
      if (gemelo) gemelo.ponerCalibracion(cfgGemelo);
      avisar('Calibración del gemelo guardada', 'ok');
    } catch (err) { avisar(err.message, 'error'); }
  });
  confirmarDoble($('#btnBorrarCalib'), async () => {
    try {
      cfgGemelo = await api('/api/gemelo', 'POST', { restaurar: true });
      llenarCalib(cfgGemelo);
      if (gemelo) gemelo.ponerCalibracion(cfgGemelo);
    } catch (err) { avisar(err.message, 'error'); }
  });
  $('#btnGemeloCerrar').addEventListener('click', cerrarCalibGemelo);

  // Cámara y visión
  $('#btnTelefono').addEventListener('click', async () => {
    const direccion = $('#urlTelefono').value.trim();
    if (!direccion) { avisar('Escribe la dirección que muestra IP Webcam en el teléfono.', 'error'); return; }
    const d = await accion('/api/vision', { camara: 'telefono', url_telefono: direccion, activa: true });
    if (d) {
      aplicarVision(d.vision);
      avisar('Conectando al teléfono. Su imagen aparecerá en el panel.', 'info');
    }
  });
  $('#btnBuscarCam').addEventListener('click', buscarCamaras);
  $('#selCamara').addEventListener('change', (e) => {
    const cam = valorCamara(e.target.value);
    if (cam !== null) accion('/api/vision', { camara: cam });
  });
  $('#btnCamara').addEventListener('click', () => {
    const encender = !(est && est.vision && est.vision.encendida);
    const cam = valorCamara($('#selCamara').value);
    if (encender && cam === null) { avisar('Elige una cámara o conecta tu teléfono por WiFi.', 'error'); return; }
    if (encender && cam === 'telefono' && !$('#urlTelefono').value.trim()) {
      avisar('Abre Conectar teléfono por WiFi y escribe la dirección de su app.', 'error'); return;
    }
    accion('/api/vision', encender ? { activa: true, camara: cam,
      ...(cam === 'telefono' ? { url_telefono: $('#urlTelefono').value.trim() } : {}) } : { activa: false });
  });
  $('#video').addEventListener('error', () => {           // si se cortó el video, reintentar
    if (videoActivo) setTimeout(() => { if (videoActivo) $('#video').src = '/video?t=' + Date.now(); }, 1000);
  });
  $('#chkExpAuto').addEventListener('change', (e) => accion('/api/vision', { exposicion_auto: e.target.checked }));
  $('#rngExposicion').addEventListener('input', () => pintarExposicion(false));
  $('#rngExposicion').addEventListener('change', (e) => accion('/api/vision', { exposicion: Number(e.target.value) }));
  $('#btnCalibrarCam').addEventListener('click', async () => {
    const lado = Number($('#ladoCalib').value);
    const d = await accion('/api/vision/calibrar', { lado_cm: lado });
    if (d && d.vision) avisar(`Cámara calibrada: ${d.vision.px_por_cm} px por cm`, 'ok');
  });
}

async function iniciar() {
  let d = null;
  while (!d) {                                             // esperar al servidor
    try { d = await api('/api/config'); }
    catch (err) { marcarServidor(false); await new Promise((r) => setTimeout(r, 1500)); }
  }
  ARTS = d.articulaciones;
  cfgGemelo = d.gemelo;
  ultimoAviso = d.aviso ? d.aviso.id : 0;                  // no repetir avisos viejos
  construirTablero();
  construirTablaCalib();
  controlBanda = crearControlBanda({ api, avisar });
  conectarBotones();
  aplicarEstado(d);
  marcarServidor(true);
  try { biblio = await api('/api/poses'); } catch (err) { avisar(err.message, 'error'); }
  pintarBiblioteca();
  conectarEventos();
  iniciarGemelo();
}

iniciar();
