/* =====================================================================
   GEMELO DIGITAL 3D — modelo real del brazo (brazo_articulado.glb)
   ---------------------------------------------------------------------
   - Three.js local (static/vendor/three), funciona SIN internet.
   - El modelo se mueve con el adaptador del paquete (modelo/arm-controller.js)
     usando ángulos RELATIVOS a la postura del modelo (CAD).
   - Conversión servo -> modelo (por articulación):
         ángulo_modelo = sentido · (ángulo_servo − cero)
     Pinza (piñón de 18 dientes, radio primitivo 9 mm):
         apertura_mm = 85 − 2 · 9 · rad( sentido_cierre · (ángulo_servo − abierta) )
   - Una articulación SIN calibrar se queda en la postura del modelo:
     no se inventan ceros ni sentidos.
   - Solo dibuja: nunca manda órdenes al robot.
   ===================================================================== */
import * as THREE from './vendor/three/three-urumagod.module.js';
import { createArmController, REST_POSE } from './modelo/arm-controller.js';

const URL_MODELO = '/static/modelo/brazo_articulado.glb';
const RADIO_PINON_MM = 9;

// índice de articulación en el firmware -> clave del modelo
export const ARTICULACIONES_MODELO = [
  { j: 0, clave: 'base',   pose: 'base_deg' },
  { j: 1, clave: 'hombro', pose: 'shoulder_deg' },
  { j: 2, clave: 'codo',   pose: 'elbow_deg' },
  { j: 3, clave: 'muneca', pose: 'wrist_pitch_deg' },
  { j: 4, clave: 'giro',   pose: 'wrist_roll_deg' },
];
const PIEZAS_PINZA = ['g2', 'g4', 'g6', 'g8', 'g10', 'g12', 'g14'];

const sentidoValido = (s) => s === 1 || s === -1;
const numero = (v) => typeof v === 'number' && Number.isFinite(v);

/** Ángulos de servo (6 valores del firmware) -> pose del modelo + lista de lo que falta calibrar */
export function poseDesdeServos(ang, cal) {
  const pose = { ...REST_POSE };
  const pendientes = [];
  for (const a of ARTICULACIONES_MODELO) {
    const c = cal && cal[a.clave];
    if (c && numero(c.cero) && sentidoValido(c.sentido)) pose[a.pose] = c.sentido * (ang[a.j] - c.cero);
    else pendientes.push(a.clave);
  }
  const p = cal && cal.pinza;
  if (p && numero(p.abierta) && sentidoValido(p.sentido_cierre)) {
    const cierreRad = (p.sentido_cierre * (ang[5] - p.abierta)) * Math.PI / 180;
    pose.gripper_opening_mm = Math.min(85, Math.max(45, 85 - 2 * RADIO_PINON_MM * cierreRad));
  } else {
    pendientes.push('pinza');
  }
  return { pose, pendientes };
}

export async function crearGemelo(contenedor, calibracion, opciones = {}) {
  /* ---------------- Escena ---------------- */
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.9;
  contenedor.prepend(renderer.domElement);

  const escena = new THREE.Scene();
  const camara = new THREE.PerspectiveCamera(36, 1, 0.001, 20);
  const controles = new THREE.OrbitControls(camara, renderer.domElement);
  controles.minDistance = 0.03;
  controles.maxDistance = 2.5;

  escena.add(new THREE.HemisphereLight(0xe4f3ff, 0x424149, 1.3));
  const luz1 = new THREE.DirectionalLight(0xffffff, 2);
  luz1.position.set(0.6, 1, 0.8);
  escena.add(luz1);
  const luz2 = new THREE.DirectionalLight(0xc0d8ff, 1);
  luz2.position.set(-0.5, 0.3, -0.5);
  escena.add(luz2);
  const rejilla = new THREE.GridHelper(0.9, 18, 0x46627d, 0x263a51);   // cuadros de 5 cm
  rejilla.position.y = -0.0005;
  escena.add(rejilla);

  /* ---------------- Dibujo bajo demanda ---------------- */
  let pedido = false;
  let modelo = null, brazo = null;
  let cal = calibracion || {};
  let angDestino = null, angVista = null;
  let soloReposo = false;                       // mostrar la postura del modelo (para calibrar)
  let ultimaPunta = '';

  function dibujar() {
    pedido = false;
    let falta = false;
    if (brazo && soloReposo) {
      brazo.reset();
      informarPunta();
    } else if (brazo && angDestino) {
      if (!angVista) angVista = angDestino.slice();
      for (let k = 0; k < 6; k++) {            // suavizar entre lecturas (20 Hz -> 60 fps)
        const d = angDestino[k] - angVista[k];
        if (Math.abs(d) > 0.05) { angVista[k] += d * 0.35; falta = true; } else angVista[k] = angDestino[k];
      }
      const { pose, pendientes } = poseDesdeServos(angVista, cal);
      brazo.setPose(pose);
      if (opciones.onPendientes) opciones.onPendientes(pendientes);
      informarPunta();
    }
    renderer.render(escena, camara);
    if (falta) solicitar();
  }
  function solicitar() {
    if (!pedido) { pedido = true; requestAnimationFrame(dibujar); }
  }
  controles.addEventListener('change', solicitar);

  // Punta = punto medio entre las almohadillas de goma (mm, ejes del robot:
  // X adelante, Y izquierda, Z arriba; origen en el eje de la base, al nivel del piso)
  const va = new THREE.Vector3(), vb = new THREE.Vector3(), vBase = new THREE.Vector3();
  function informarPunta() {
    if (!opciones.onPunta || !modelo) return;
    modelo.getObjectByName('part_g12').getWorldPosition(va);
    modelo.getObjectByName('part_g14').getWorldPosition(vb);
    modelo.getObjectByName('joint_base').getWorldPosition(vBase);
    const x = ((va.x + vb.x) / 2 - vBase.x) * 1000;
    const y = -((va.z + vb.z) / 2 - vBase.z) * 1000;
    const z = ((va.y + vb.y) / 2) * 1000;
    const txt = `${Math.round(x)},${Math.round(y)},${Math.round(z)}`;
    if (txt !== ultimaPunta) { ultimaPunta = txt; opciones.onPunta(x, y, z); }
  }

  /* ---------------- Encuadre ---------------- */
  function encuadrar(caja) {
    const centro = caja.getCenter(new THREE.Vector3());
    const tam = caja.getSize(new THREE.Vector3());
    const dist = Math.max(tam.x, tam.y, tam.z) / (2 * Math.tan(THREE.MathUtils.degToRad(camara.fov / 2))) * 1.6;
    controles.target.copy(centro);
    camara.position.copy(centro).add(new THREE.Vector3(0.72, 0.38, 1).normalize().multiplyScalar(dist));
    camara.near = Math.max(1e-4, dist / 100);
    camara.far = dist * 100;
    camara.updateProjectionMatrix();
    controles.update();
    solicitar();
  }
  function vista(cual = 'brazo') {
    if (!modelo) return;
    modelo.updateMatrixWorld(true);
    const caja = new THREE.Box3();
    if (cual === 'pinza') {
      for (const id of PIEZAS_PINZA) caja.expandByObject(modelo.getObjectByName('part_' + id));
    } else {
      caja.setFromObject(modelo);
    }
    encuadrar(caja);
  }

  /* ---------------- Tamaño ---------------- */
  function ajustarTamano() {
    const w = Math.max(50, contenedor.clientWidth), h = Math.max(50, contenedor.clientHeight);
    renderer.setSize(w, h, false);
    camara.aspect = w / h;
    camara.updateProjectionMatrix();
    solicitar();
  }
  new ResizeObserver(ajustarTamano).observe(contenedor);
  ajustarTamano();

  /* ---------------- Carga del modelo ---------------- */
  const gltf = await new THREE.GLTFLoader().loadAsync(URL_MODELO, (e) => {
    if (opciones.onProgreso && e.total) opciones.onProgreso(Math.round((e.loaded / e.total) * 100));
  });
  modelo = gltf.scene;
  escena.add(modelo);
  brazo = createArmController(modelo);
  vista('brazo');

  return {
    /** 6 ángulos de servo (posición solicitada que reporta el ESP32) */
    ponerAngulos(ang) {
      if (!ang || ang.length < 6) return;
      angDestino = ang.slice(0, 6).map(Number);
      solicitar();
    },
    ponerCalibracion(nueva) {
      cal = nueva || {};
      solicitar();
    },
    vista,
    /** true = mostrar la postura del modelo (CAD) en lugar de la del robot — solo visual */
    mostrarReposo(activo) {
      soloReposo = !!activo;
      angVista = null;
      solicitar();
    },
    pose: () => brazo.getPose(),
    _depuracion: { THREE, modelo, brazo, camara, renderer },
  };
}
