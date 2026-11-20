/* Control de un motor DC. Los latidos no pueden volver a iniciar una banda detenida. */
export function crearControlBanda({ api, avisar }) {
  const $ = (id) => document.getElementById(id);
  const rango = $('velBanda'), valor = $('valorBanda'), sentido = $('sentidoBanda');
  const inicio = $('btnBandaIniciar'), paro = $('btnBandaDetener');
  let estado = { disponible: false, pct: 0, objetivo: 0 };
  let sesion = null, generacion = 0, pendiente = null, enviando = false, latidoEnVuelo = false;
  let ultimaVersion = -1;

  function pintarValor() {
    valor.textContent = `${rango.value} %`;
    rango.style.setProperty('--p', `${rango.value}%`);
  }

  function detenerLocal() {
    sesion = null;
    pendiente = null;
    generacion++;
  }

  function aplicar(e) {
    if (!e.banda || e.ver < ultimaVersion) return;
    ultimaVersion = e.ver;
    estado = e.banda;
    if (!estado.objetivo && sesion) detenerLocal();
    const marcha = !!(estado.objetivo || estado.pct);
    const propio = !!sesion;
    inicio.disabled = !estado.disponible || marcha || enviando;
    paro.disabled = !estado.disponible;
    sentido.disabled = !estado.disponible || marcha;
    rango.disabled = !estado.disponible || (marcha && !propio);
    if (marcha && document.activeElement !== rango && pendiente === null && !enviando) {
      rango.value = Math.abs(estado.objetivo || estado.pct);
    }
    if (marcha) sentido.value = (estado.objetivo || estado.pct) < 0 ? '-1' : '1';
    const chip = $('estadoBanda');
    chip.className = `chip ${!estado.disponible ? 'warn' : marcha ? 'ok' : ''}`;
    chip.textContent = !estado.disponible ? 'Actualizar ESP32' : marcha
      ? `${e.modo === 'simulacion' ? 'Simulación · ' : ''}${Math.abs(estado.pct)} % aplicado`
      : 'Apagada';
    $('notaBanda').textContent = !estado.disponible
      ? 'Carga el firmware actualizado en el ESP32 para habilitar la banda.'
      : marcha && !propio ? 'Control desde otra pestaña. Puedes detener la banda aquí.'
      : 'Ajusta la velocidad y pulsa Encender. Detén la banda antes de invertir el giro.';
    pintarValor();
  }

  async function bombear() {
    if (enviando || pendiente === null || !sesion) return;
    enviando = true;
    const pct = pendiente, token = sesion, version = generacion;
    pendiente = null;
    try {
      const d = await api('/api/banda', 'POST', { accion: 'ajustar', pct, sesion: token });
      if (version === generacion) aplicar(d);
    } catch (err) {
      if (version === generacion) { detenerLocal(); avisar(err.message, 'error'); }
    } finally {
      enviando = false;
      inicio.disabled = !estado.disponible || !!(estado.objetivo || estado.pct);
      if (version === generacion) bombear();
    }
  }

  rango.addEventListener('input', () => {
    pintarValor();
    if (sesion) { pendiente = Number(rango.value); bombear(); }
  });
  inicio.addEventListener('click', async () => {
    if (enviando) return;
    const pct = Number(rango.value);
    if (!pct) { avisar('Elige una velocidad mayor que 0 %.', 'error'); return; }
    const version = generacion;
    enviando = true;
    inicio.disabled = true;
    try {
      const d = await api('/api/banda', 'POST', { accion: 'iniciar', pct, sentido: Number(sentido.value), revision: estado.revision });
      if (version !== generacion) return;
      sesion = d.sesion_banda;
      aplicar(d);
    } catch (err) { avisar(err.message, 'error'); }
    finally { enviando = false; inicio.disabled = !estado.disponible || !!(estado.objetivo || estado.pct); }
  });
  paro.addEventListener('click', async () => {
    detenerLocal();
    try { aplicar(await api('/api/banda', 'POST', { accion: 'detener' })); }
    catch (err) { avisar(err.message, 'error'); }
  });

  setInterval(async () => {
    if (!sesion || latidoEnVuelo) return;
    const token = sesion, version = generacion;
    latidoEnVuelo = true;
    try {
      await api('/api/banda', 'POST', { accion: 'latido', sesion: token });
    } catch (err) {
      if (version === generacion) { detenerLocal(); avisar('Se perdió el control de la banda. Vuelve a encenderla.', 'error'); }
    } finally { latidoEnVuelo = false; }
  }, 400);
  window.addEventListener('pagehide', () => {
    if (sesion) navigator.sendBeacon('/api/banda', new Blob([JSON.stringify({ accion: 'detener' })], { type: 'application/json' }));
    detenerLocal();
  });
  pintarValor();
  return { aplicar, detenerLocal };
}
