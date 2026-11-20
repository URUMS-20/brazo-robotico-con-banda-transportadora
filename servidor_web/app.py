"""
==================================================================
 SERVIDOR WEB — BRAZO ROBÓTICO "THE GENESIS"     (v2, en la laptop)
==================================================================
 - Interfaz en  http://localhost:5000  y  http://<IP>:5000 (celular)
 - Manda los movimientos al ESP32 por USB-Serial (50 Hz)
 - Recibe la posición real del perfil (telemetría "A") y la reenvía
   a la página en tiempo real (gemelo 3D)
 - LÍMITES y HOME: se los pide al ESP32 (viven en su memoria)
 - Poses y secuencias: se guardan en  poses.json   (esta carpeta)
 - Calibración del gemelo 3D:        gemelo.json  (esta carpeta)
 - Visión artificial (cámara USB):   vision.json  (esta carpeta)
   video en  /video  y detecciones dentro del estado ("vision")
 - Sin ESP32 -> usa un ESP32 SIMULADO y lo sigue buscando cada 2 s
==================================================================
"""
import json
import logging
import os
import socket
import threading
import time
import uuid

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.serving import WSGIRequestHandler

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise SystemExit("Falta pyserial ->  python -m pip install -r requirements.txt")

from simulador import ESP32Simulado
from vision import Vision

# ========================= CONFIGURACIÓN ==========================
PUERTO_SERIAL = "AUTO"      # "AUTO" = lo busca solo  |  o fíjalo, ej. "COM3"
BAUDIOS = 115200
PUERTO_WEB = 5000
PERIODO_ENVIO_S = 0.02      # 50 Hz hacia el ESP32
REINTENTO_S = 2.0           # cada cuánto se busca el ESP32 real en simulación
BANDA_LATIDO_S = 0.4        # renueva el permiso de marcha en el ESP32
BANDA_CLIENTE_S = 1.5       # sin navegador, la banda se apaga

CARPETA = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_POSES = os.path.join(CARPETA, "poses.json")
ARCHIVO_GEMELO = os.path.join(CARPETA, "gemelo.json")
ARCHIVO_VISION = os.path.join(CARPETA, "vision.json")

# Solo NOMBRES y canales (iguales a servos[] de main.cpp). Los límites y el HOME los manda el ESP32.
ARTICULACIONES = [
    {"id": 0, "motores": "Motor 1",       "nombre": "Base (giro)",   "canales": [0]},
    {"id": 1, "motores": "Motores 2 + 3", "nombre": "Hombro",        "canales": [1, 2]},
    {"id": 2, "motores": "Motor 4",       "nombre": "Codo",          "canales": [3]},
    {"id": 3, "motores": "Motor 5",       "nombre": "Muñeca",        "canales": [4]},
    {"id": 4, "motores": "Motor 6",       "nombre": "Giro de pinza", "canales": [5]},
    {"id": 5, "motores": "Motor 7",       "nombre": "Pinza",         "canales": [6]},
]
N = len(ARTICULACIONES)
LIM_RESPALDO = (9.0, 171.0)   # solo si el ESP32 tiene el firmware viejo (v1)

# Calibración del gemelo 3D (modelo brazo_articulado.glb).
#  cero    = ángulo del servo cuando esa articulación está igual que en el modelo (CAD)
#  sentido = +1 si al SUBIR el ángulo del servo se mueve como el modelo, -1 si al revés
#  pinza   = ángulo del servo con la pinza abierta (85 mm) y hacia dónde cierra
# Todo empieza en None: NO se inventan valores; se capturan desde la página.
JUNTAS_GEMELO = ("base", "hombro", "codo", "muneca", "giro")
GEMELO_DEFECTO = {
    "version": 2,
    **{k: {"cero": None, "sentido": None} for k in JUNTAS_GEMELO},
    "pinza": {"abierta": None, "sentido_cierre": None},
}

# Cómo describe Windows los adaptadores USB-Serial del ESP32
CHIPS_USB = ("CP210", "CH340", "CH341", "CH910", "CH9102", "SILICON LABS",
             "USB-SERIAL", "USB SERIAL", "WCH", "UART")


# ==================================================================
#  Archivos JSON (escritura segura: primero .tmp y luego se renombra)
# ==================================================================
def leer_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribir_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def numero(valor, minimo, maximo, defecto):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return defecto
    if v != v:                                   # NaN
        return defecto
    return min(max(v, minimo), maximo)


# ==================================================================
#  Enlace con el ESP32 (real o simulado) — hilo propio
# ==================================================================
class Enlace:
    def __init__(self):
        self.lock = threading.RLock()
        self.obj = [90.0] * N            # objetivos (a dónde va)
        self.act = [90.0] * N            # posición del perfil (telemetría)
        self.mov = False
        self.lim = [list(LIM_RESPALDO) for _ in range(N)]
        self.home = [90.0] * N
        self.vel_pct = 100
        self.calib = False
        self.version = 0                 # sube con cada cambio importante
        self.disp = None                 # serial.Serial o ESP32Simulado
        self.modo = "buscando"           # "esp32" | "simulacion"
        self.puerto = None
        self.firmware = "?"
        self.pendientes = set()          # articulaciones con J por mandar
        self.cola = []                   # otros comandos por mandar
        self.aviso = None
        self._id_aviso = 0
        self._rx = ""
        self._vio_c = self._vio_p = False
        self._saludo_hecho = False
        self._t_busqueda = 0.0
        self.banda_disponible = False
        self.banda_pct = 0
        self.banda_obj = 0
        self._banda_revision = 0
        self._banda_sesion = None
        self._banda_vence = 0.0
        self._banda_envio = False
        self._banda_ultimo_envio = 0.0
        threading.Thread(target=self._hilo, daemon=True).start()

    # ------------------------ API para Flask ------------------------
    def _cambio(self):
        self.version += 1

    def avisar(self, texto, tipo="info"):
        with self.lock:
            self._id_aviso += 1
            self.aviso = {"id": self._id_aviso, "texto": texto, "tipo": tipo}
            self._cambio()
        print(f"[AVISO] {texto}")

    def _rango(self, j):
        return (0.0, 180.0) if self.calib else tuple(self.lim[j])

    def mover(self, j, grados):
        with self.lock:
            mn, mx = self._rango(j)
            g = round(min(max(float(grados), mn), mx), 1)
            if g != self.obj[j]:
                self.obj[j] = g
                self.pendientes.add(j)
                if self.firmware == "v1":        # el v1 no manda telemetría
                    self.act[j] = g
                self._cambio()
            return g

    def mover_todo(self, angulos):
        for j, g in enumerate(angulos[:N]):
            self.mover(j, g)

    def ir_home(self):
        with self.lock:
            self.mover_todo(list(self.home))

    def stop(self):
        with self.lock:
            self.pendientes.clear()
            self.cola.append("S")
            self._parar_banda()

    def _parar_banda(self):
        """Con self.lock tomado. Invalida también peticiones que estén en vuelo."""
        self.banda_obj = 0
        self._banda_revision += 1
        self._banda_sesion = None
        self._banda_vence = 0.0
        self._banda_envio = True
        self._cambio()

    def controlar_banda(self, accion, pct=0, sentido=1, sesion=None, revision=None):
        with self.lock:
            if accion == "detener":
                self._parar_banda()
                return None, None
            if not self.banda_disponible:
                return "Sube el firmware con control de banda al ESP32.", None
            if accion == "iniciar":
                if type(revision) is not int or revision != self._banda_revision:
                    return "El estado de la banda cambió. Vuelve a pulsar Encender.", None
                if self.banda_obj or self.banda_pct:
                    return "Detén la banda antes de volver a iniciarla.", None
                self._banda_sesion = uuid.uuid4().hex
                self.banda_obj = pct * sentido
            elif accion in ("ajustar", "latido"):
                if not sesion or sesion != self._banda_sesion:
                    return "El permiso de marcha terminó. Vuelve a encender la banda.", None
                if time.monotonic() >= self._banda_vence:
                    self._parar_banda()
                    return "Se perdió la comunicación. Vuelve a encender la banda.", None
                if accion == "ajustar":
                    if pct == 0:
                        self._parar_banda()
                        return None, None
                    self.banda_obj = pct * (1 if self.banda_obj > 0 else -1)
            else:
                return "Acción de banda no válida.", None
            self._banda_vence = time.monotonic() + BANDA_CLIENTE_S
            if accion != "latido":
                self._banda_envio = True
                self._cambio()
            return None, self._banda_sesion

    def _comando_banda(self, ahora):
        """Se ejecuta con self.lock en el hilo serie; nunca reanuda tras una pérdida."""
        if self.banda_obj and ahora >= self._banda_vence:
            self._parar_banda()
        if self._banda_envio or (self.banda_obj and ahora - self._banda_ultimo_envio >= BANDA_LATIDO_S):
            self._banda_envio = False
            self._banda_ultimo_envio = ahora
            return f"B {self.banda_obj}"
        return None

    def velocidad(self, pct):
        pct = int(min(max(int(pct), 10), 100))
        with self.lock:
            self.vel_pct = pct
            self.cola.append(f"V {pct}")
            self._cambio()

    def calibracion(self, activo):
        with self.lock:
            self.cola.append(f"X {1 if activo else 0}")

    def fijar_limite(self, j, tipo):
        with self.lock:
            mn, mx = self.lim[j]
            if tipo == "min":
                mn = self.obj[j]
            else:
                mx = self.obj[j]
            if mx - mn < 10:
                return "El mínimo debe quedar al menos 10° por debajo del máximo."
            self.cola.append(f"L{j} {mn:.1f} {mx:.1f}")
        return None

    def guardar_home(self):
        with self.lock:
            self.cola.append("HG")

    def restaurar_fabrica(self):
        with self.lock:
            self.cola.append("R")

    def estado(self):
        with self.lock:
            return {
                "obj": list(self.obj), "act": list(self.act), "mov": self.mov,
                "lim": [list(l) for l in self.lim], "home": list(self.home),
                "vel": self.vel_pct, "calib": self.calib, "ver": self.version,
                "modo": self.modo, "esp32": self.modo == "esp32",
                "puerto": self.puerto, "firmware": self.firmware, "aviso": self.aviso,
                "banda": {"disponible": self.banda_disponible, "pct": self.banda_pct,
                          "revision": self._banda_revision,
                          "objetivo": self.banda_obj, "activa": self.banda_pct != 0},
            }

    def llego(self, tolerancia=0.6):
        with self.lock:
            return (not self.mov and not self.pendientes and
                    all(abs(a - o) <= tolerancia for a, o in zip(self.act, self.obj)))

    # ------------------------ Conexión ------------------------------
    def _buscar_puerto(self):
        if PUERTO_SERIAL.upper() != "AUTO":
            return PUERTO_SERIAL if any(p.device == PUERTO_SERIAL
                                        for p in serial.tools.list_ports.comports()) else None
        for p in serial.tools.list_ports.comports():
            texto = f"{p.description} {p.manufacturer or ''}".upper()
            if any(chip in texto for chip in CHIPS_USB):
                return p.device
        return None

    def _conectar(self):
        puerto = self._buscar_puerto()
        disp = None
        if puerto:
            try:
                disp = serial.Serial(puerto, BAUDIOS, timeout=0, write_timeout=0.5)
                print(f"[ESP32] Puerto {puerto} abierto, esperando al ESP32...")
                time.sleep(2.0)                  # al abrir el puerto el ESP32 se reinicia
                disp.reset_input_buffer()
            except (serial.SerialException, OSError) as e:
                print(f"[ESP32] No pude abrir {puerto}: {e}")
                disp = None
        modo = "esp32" if disp else "simulacion"
        if disp is None:
            disp, puerto = ESP32Simulado(), None

        with self.lock:
            self.disp, self.modo, self.puerto = disp, modo, puerto
            self.firmware, self._rx = "?", ""
            self.pendientes.clear()
            self.cola = []
            self._vio_c = self._vio_p = False
            self._saludo_hecho = False
            self.calib = False
            self.banda_disponible = False
            self.banda_pct = 0
            self._parar_banda()

        # Saludo: pedir configuración y posición
        disp.write(b"B 0\nC\n?\nB?\n")
        limite = time.monotonic() + 1.5
        while time.monotonic() < limite and not (self._vio_c and self._vio_p):
            if disp.in_waiting:
                self._leer()
            time.sleep(0.02)

        with self.lock:
            if self._vio_c:
                self.firmware = "v2"
                self.cola.append(f"V {self.vel_pct}")       # mantener la velocidad elegida
            elif self._vio_p:
                self.firmware = "v1"
                self.lim = [list(LIM_RESPALDO) for _ in range(N)]
                self.home = list(self.obj)
                self.act = list(self.obj)
            self._saludo_hecho = True
            self._t_busqueda = time.monotonic()
            self._cambio()

        if modo == "esp32":
            print(f"[ESP32] Conectado en {puerto}  firmware {self.firmware}  posiciones {self.obj}")
            if self.firmware == "v1":
                self.avisar("El ESP32 tiene el firmware viejo: sube el main.cpp nuevo para "
                            "usar límites, STOP, velocidad y telemetría.", "error")
            elif self.firmware == "?":
                self.avisar("El ESP32 no responde. Revisa el cable o cierra el Monitor Serie.", "error")
        else:
            print("[ESP32] No encontrado -> modo SIMULACIÓN (se sigue buscando cada 2 s)")

    def _cerrar(self):
        try:
            if self.disp:
                self.disp.close()
        except Exception:
            pass
        with self.lock:
            self.disp, self.puerto, self.modo = None, None, "buscando"
            self.banda_disponible = False
            self.banda_pct = 0
            self._parar_banda()
            self._cambio()

    # ------------------------ Hilo de envío -------------------------
    def _hilo(self):
        while True:
            if self.disp is None:
                self._conectar()
                continue
            t0 = time.monotonic()
            try:
                # En simulación: ¿ya conectaron el ESP32 real?
                if self.modo == "simulacion" and t0 - self._t_busqueda > REINTENTO_S:
                    self._t_busqueda = t0
                    if self._buscar_puerto():
                        print("[ESP32] Se detectó el ESP32 real, conectando...")
                        self._cerrar()
                        continue
                with self.lock:
                    lineas = [f"J{j} {self.obj[j]:.1f}" for j in sorted(self.pendientes)] + self.cola
                    banda = self._comando_banda(t0)
                    if banda:
                        lineas.append(banda)
                    self.pendientes.clear()
                    self.cola = []
                if lineas:
                    self.disp.write(("\n".join(lineas) + "\n").encode())
                if self.disp.in_waiting:
                    self._leer()
            except (serial.SerialException, OSError) as e:
                print(f"[ESP32] Desconectado: {e}")
                self._cerrar()
                self.avisar("Se perdió la conexión con el ESP32. Revisa el cable USB.", "error")
                continue
            time.sleep(max(0.0, PERIODO_ENVIO_S - (time.monotonic() - t0)))

    def _leer(self):
        self._rx += self.disp.read(self.disp.in_waiting).decode(errors="ignore")
        *lineas, self._rx = self._rx.replace("\r", "").split("\n")
        for linea in lineas:
            if linea.strip():
                self._procesar_linea(linea.strip())

    def _procesar_linea(self, linea):
        partes = linea.split()
        tipo = partes[0]
        try:
            if tipo == "B" and len(partes) == 2:
                with self.lock:
                    if partes[1] == "NA":
                        self.banda_disponible = False
                        self.banda_pct = 0
                        self._parar_banda()
                        self._banda_envio = False
                    else:
                        pct = int(partes[1])
                        if not -100 <= pct <= 100:
                            return
                        self.banda_disponible = True
                        self.banda_pct = pct
                        if pct == 0 and self.banda_obj and not self._banda_envio:
                            self._parar_banda()  # watchdog del ESP32: requiere un nuevo inicio
                        elif pct and not self.banda_obj:
                            self._banda_envio = True
                        self._cambio()
            elif tipo == "P" and len(partes) == N + 1:
                valores = [float(x) for x in partes[1:]]
                with self.lock:
                    self.obj = valores
                    if self.firmware == "v1":
                        self.act = list(valores)
                    self._vio_p = True
                    self._cambio()
            elif tipo == "A" and len(partes) == N + 2:
                valores = [float(x) for x in partes[1:N + 1]]
                with self.lock:
                    self.act = valores
                    self.mov = partes[-1] == "1"
            elif tipo == "C" and len(partes) == 3 * N + 1:
                v = [float(x) for x in partes[1:]]
                with self.lock:
                    self.lim = [[v[3 * i], v[3 * i + 1]] for i in range(N)]
                    self.home = [v[3 * i + 2] for i in range(N)]
                    self._vio_c = True
                    self._cambio()
            elif tipo == "V" and len(partes) == 2:
                with self.lock:
                    self.vel_pct = int(float(partes[1]))
                    self._cambio()
            elif tipo == "X" and len(partes) == 2:
                with self.lock:
                    self.calib = partes[1] == "1"
                    self._cambio()
            elif tipo == "E":
                self.avisar("ESP32: " + linea[2:], "error")
            elif tipo == "LISTO":
                print(f"[ESP32] {linea}")
                if self._saludo_hecho:           # se reinició solo
                    with self.lock:
                        self.calib = False
                        self.banda_pct = 0
                        self._parar_banda()
                        self.cola += ["B 0", "B?", "C", "?", f"V {self.vel_pct}"]
                    self.avisar("El ESP32 se reinició solo. Casi siempre es una caída de "
                                "voltaje: revisa la fuente y que la tierra esté unida.", "error")
            else:
                print(f"[ESP32] {linea}")
        except ValueError:
            print(f"[ESP32] (línea no válida) {linea}")


# ==================================================================
#  Poses y secuencias (poses.json)
# ==================================================================
class Almacen:
    def __init__(self, ruta):
        self.ruta = ruta
        self.lock = threading.Lock()
        datos = leer_json(ruta, {})
        self.poses = [p for p in datos.get("poses", [])
                      if isinstance(p, dict) and len(p.get("angulos", [])) == N]
        ids = {p["id"] for p in self.poses}
        self.secuencias = []
        for s in datos.get("secuencias", []):
            if isinstance(s, dict) and "id" in s:
                s["pasos"] = [p for p in s.get("pasos", []) if p.get("pose") in ids]
                self.secuencias.append(s)

    def _guardar(self):
        escribir_json(self.ruta, {"poses": self.poses, "secuencias": self.secuencias})

    def datos(self):
        with self.lock:
            return json.loads(json.dumps({"poses": self.poses, "secuencias": self.secuencias}))

    def pose(self, pid):
        with self.lock:
            return next((dict(p) for p in self.poses if p["id"] == pid), None)

    def crear_pose(self, nombre, angulos):
        with self.lock:
            nombre = (nombre or "").strip()[:40]
            if not nombre:
                k = len(self.poses) + 1
                existentes = {p["nombre"] for p in self.poses}
                while f"Pose {k}" in existentes:
                    k += 1
                nombre = f"Pose {k}"
            pose = {"id": uuid.uuid4().hex[:8], "nombre": nombre,
                    "angulos": [round(a, 1) for a in angulos]}
            self.poses.append(pose)
            self._guardar()
            return pose

    def actualizar_pose(self, pid, angulos):
        with self.lock:
            for p in self.poses:
                if p["id"] == pid:
                    p["angulos"] = [round(a, 1) for a in angulos]
                    self._guardar()
                    return True
            return False

    def borrar_pose(self, pid):
        with self.lock:
            antes = len(self.poses)
            self.poses = [p for p in self.poses if p["id"] != pid]
            for s in self.secuencias:
                s["pasos"] = [p for p in s["pasos"] if p["pose"] != pid]
            self._guardar()
            return len(self.poses) != antes

    def secuencia(self, sid):
        with self.lock:
            s = next((s for s in self.secuencias if s["id"] == sid), None)
            return json.loads(json.dumps(s)) if s else None

    def guardar_secuencia(self, sid, nombre, pasos):
        with self.lock:
            ids = {p["id"] for p in self.poses}
            limpios = []
            for paso in pasos or []:
                if isinstance(paso, dict) and paso.get("pose") in ids:
                    limpios.append({"pose": paso["pose"],
                                    "pausa": round(numero(paso.get("pausa"), 0, 60, 1.0), 1)})
            nombre = (nombre or "").strip()[:40] or f"Secuencia {len(self.secuencias) + 1}"
            for s in self.secuencias:
                if s["id"] == sid:
                    s["nombre"], s["pasos"] = nombre, limpios
                    self._guardar()
                    return dict(s)
            s = {"id": uuid.uuid4().hex[:8], "nombre": nombre, "pasos": limpios}
            self.secuencias.append(s)
            self._guardar()
            return dict(s)

    def borrar_secuencia(self, sid):
        with self.lock:
            self.secuencias = [s for s in self.secuencias if s["id"] != sid]
            self._guardar()


# ==================================================================
#  Reproductor de secuencias ("teach & play")
# ==================================================================
class Reproductor:
    TIEMPO_MAX_PASO_S = 30.0

    def __init__(self, enlace, almacen):
        self.enlace = enlace
        self.almacen = almacen
        self.lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo = None
        self.info = {"activo": False, "sec": None, "nombre": "", "paso": 0,
                     "total": 0, "pose": "", "vuelta": 0, "repetir": False}

    def estado(self):
        with self.lock:
            return dict(self.info)

    def _poner(self, **cambios):
        with self.lock:
            self.info.update(cambios)
        with self.enlace.lock:
            self.enlace._cambio()

    def iniciar(self, sid, repetir):
        sec = self.almacen.secuencia(sid)
        if not sec:
            return "No existe esa secuencia."
        pasos = []
        for p in sec["pasos"]:
            pose = self.almacen.pose(p["pose"])
            if pose:
                pasos.append((pose["nombre"], pose["angulos"], p["pausa"]))
        if not pasos:
            return "La secuencia no tiene pasos."
        self.detener()
        self._parar.clear()
        self._poner(activo=True, sec=sid, nombre=sec["nombre"], paso=0,
                    total=len(pasos), pose="", vuelta=1, repetir=bool(repetir))
        self._hilo = threading.Thread(target=self._correr, args=(pasos, bool(repetir)), daemon=True)
        self._hilo.start()
        return None

    def detener(self):
        self._parar.set()
        hilo = self._hilo
        if hilo and hilo.is_alive() and hilo is not threading.current_thread():
            hilo.join(timeout=1.0)
        if self.estado()["activo"]:
            self._poner(activo=False)

    def _esperar_llegada(self):
        time.sleep(0.1)                           # que el ESP32 reciba y empiece
        limite = time.monotonic() + self.TIEMPO_MAX_PASO_S
        while not self._parar.is_set():
            if self.enlace.llego():
                return True
            if time.monotonic() > limite:
                self.enlace.avisar("Un paso tardó más de 30 s en llegar; secuencia detenida.", "error")
                return False
            time.sleep(0.02)
        return False

    def _correr(self, pasos, repetir):
        vuelta = 1
        try:
            while not self._parar.is_set():
                for k, (nombre, angulos, pausa) in enumerate(pasos, start=1):
                    if self._parar.is_set():
                        return
                    self._poner(paso=k, pose=nombre, vuelta=vuelta)
                    self.enlace.mover_todo(angulos)
                    if not self._esperar_llegada():
                        return
                    if self._parar.wait(pausa):
                        return
                if not repetir:
                    return
                vuelta += 1
        finally:
            self._poner(activo=False)


# ==================================================================
#  Gemelo 3D (gemelo.json)
# ==================================================================
def _angulo_o_nada(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 1) if 0 <= v <= 180 else None


def _sentido_o_nada(v):
    return v if v in (1, -1) else None


def gemelo_validado(d):
    d = d if isinstance(d, dict) else {}
    if d.get("version") != 2:     # formato del gemelo anterior: no sirve para el modelo nuevo
        d = {}
    g = {"version": 2}
    for k in JUNTAS_GEMELO:
        x = d.get(k) if isinstance(d.get(k), dict) else {}
        g[k] = {"cero": _angulo_o_nada(x.get("cero")), "sentido": _sentido_o_nada(x.get("sentido"))}
    x = d.get("pinza") if isinstance(d.get("pinza"), dict) else {}
    g["pinza"] = {"abierta": _angulo_o_nada(x.get("abierta")),
                  "sentido_cierre": _sentido_o_nada(x.get("sentido_cierre"))}
    return g


# ==================================================================
#  Servidor web
# ==================================================================
app = Flask(__name__)
enlace = Enlace()
almacen = Almacen(ARCHIVO_POSES)
reproductor = Reproductor(enlace, almacen)
vision = Vision(ARCHIVO_VISION)
logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no llenar la consola


def estado_completo():
    est = enlace.estado()
    est["rep"] = reproductor.estado()
    est["vision"] = vision.estado()
    return est


def ok(**extra):
    return jsonify({"ok": True, **estado_completo(), **extra})


def error(texto, codigo=400):
    return jsonify({"ok": False, "error": texto}), codigo


def cuerpo():
    return request.get_json(silent=True) or {}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def api_config():
    return jsonify({"articulaciones": ARTICULACIONES,
                    "gemelo": gemelo_validado(leer_json(ARCHIVO_GEMELO, {})),
                    **estado_completo()})


@app.get("/api/estado")
def api_estado():
    return jsonify(estado_completo())


@app.get("/api/eventos")
def api_eventos():
    """Server-Sent Events: manda el estado cada vez que cambia (máx. 20 por s)."""
    def generar():
        ultimo, t_ping = None, time.monotonic()
        while True:
            texto = json.dumps(estado_completo(), separators=(",", ":"))
            ahora = time.monotonic()
            if texto != ultimo:
                yield f"data: {texto}\n\n"
                ultimo, t_ping = texto, ahora
            elif ahora - t_ping > 10:
                yield ": ping\n\n"
                t_ping = ahora
            time.sleep(0.05)
    return Response(generar(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------- Movimiento ---------------------------
@app.post("/api/banda")
def api_banda():
    d = cuerpo()
    if not isinstance(d, dict):
        return error("Datos de banda no válidos.")
    accion = d.get("accion")
    if accion not in ("iniciar", "ajustar", "latido", "detener"):
        return error("Acción de banda no válida.")
    pct, sentido = d.get("pct", 0), d.get("sentido", 1)
    if accion in ("iniciar", "ajustar"):
        if type(pct) is not int or not (1 if accion == "iniciar" else 0) <= pct <= 100:
            return error("La velocidad debe ser un entero entre 0 y 100 % (inicio: 1–100 %).")
    if accion == "iniciar" and (type(sentido) is not int or sentido not in (-1, 1)):
        return error("Sentido de banda no válido.")
    problema, sesion = enlace.controlar_banda(accion, pct, sentido, d.get("sesion"), d.get("revision"))
    return error(problema, 409) if problema else ok(sesion_banda=sesion)


@app.post("/api/mover")
def api_mover():
    """Recibe {"cambios": {"1": 95.0, "2": 80.0}} (solo lo que cambió)."""
    cambios = cuerpo().get("cambios") or {}
    if cambios:
        reproductor.detener()                    # mover a mano detiene la secuencia
    for j, grados in cambios.items():
        try:
            j = int(j)
            if 0 <= j < N:
                enlace.mover(j, grados)
        except (TypeError, ValueError):
            pass
    return ok()


@app.post("/api/home")
def api_home():
    reproductor.detener()
    enlace.ir_home()
    return ok()


@app.post("/api/stop")
def api_stop():
    reproductor.detener()
    enlace.stop()
    return ok()


@app.post("/api/velocidad")
def api_velocidad():
    enlace.velocidad(numero(cuerpo().get("pct"), 10, 100, 100))
    return ok()


# --------------------------- Calibración --------------------------
@app.post("/api/calibracion")
def api_calibracion():
    reproductor.detener()
    enlace.calibracion(bool(cuerpo().get("activo")))
    return ok()


@app.post("/api/limite")
def api_limite():
    d = cuerpo()
    try:
        j = int(d.get("j"))
    except (TypeError, ValueError):
        return error("Articulación no válida.")
    if not 0 <= j < N or d.get("tipo") not in ("min", "max"):
        return error("Datos no válidos.")
    problema = enlace.fijar_limite(j, d["tipo"])
    return error(problema) if problema else ok()


@app.post("/api/home/guardar")
def api_home_guardar():
    enlace.guardar_home()
    return ok()


@app.post("/api/fabrica")
def api_fabrica():
    enlace.restaurar_fabrica()
    return ok()


# ----------------------- Poses y secuencias -----------------------
@app.get("/api/poses")
def api_poses():
    return jsonify(almacen.datos())


@app.post("/api/poses")
def api_pose_nueva():
    almacen.crear_pose(cuerpo().get("nombre"), enlace.estado()["obj"])
    return jsonify(almacen.datos())


@app.put("/api/poses/<pid>")
def api_pose_actualizar(pid):
    if not almacen.actualizar_pose(pid, enlace.estado()["obj"]):
        return error("No existe esa pose.", 404)
    return jsonify(almacen.datos())


@app.delete("/api/poses/<pid>")
def api_pose_borrar(pid):
    almacen.borrar_pose(pid)
    return jsonify(almacen.datos())


@app.post("/api/poses/<pid>/ir")
def api_pose_ir(pid):
    pose = almacen.pose(pid)
    if not pose:
        return error("No existe esa pose.", 404)
    reproductor.detener()
    enlace.mover_todo(pose["angulos"])
    return ok()


@app.post("/api/secuencias")
def api_secuencia_guardar():
    d = cuerpo()
    sec = almacen.guardar_secuencia(d.get("id"), d.get("nombre"), d.get("pasos"))
    return jsonify({**almacen.datos(), "guardada": sec["id"]})


@app.delete("/api/secuencias/<sid>")
def api_secuencia_borrar(sid):
    if reproductor.estado()["sec"] == sid:
        reproductor.detener()
    almacen.borrar_secuencia(sid)
    return jsonify(almacen.datos())


@app.post("/api/secuencias/<sid>/reproducir")
def api_secuencia_reproducir(sid):
    problema = reproductor.iniciar(sid, cuerpo().get("repetir"))
    return error(problema) if problema else ok()


@app.post("/api/secuencias/detener")
def api_secuencia_detener():
    reproductor.detener()
    return ok()


# --------------------------- Gemelo 3D ----------------------------
@app.get("/api/gemelo")
def api_gemelo():
    return jsonify(gemelo_validado(leer_json(ARCHIVO_GEMELO, {})))


@app.post("/api/gemelo")
def api_gemelo_guardar():
    datos = cuerpo()
    g = gemelo_validado(GEMELO_DEFECTO if datos.get("restaurar") else {**datos, "version": 2})
    escribir_json(ARCHIVO_GEMELO, g)
    return jsonify(g)


# ------------------------ Visión artificial -----------------------
@app.get("/video")
def video():
    if not vision.corriendo():
        return Response("Cámara apagada", status=503, mimetype="text/plain")
    return Response(vision.flujo_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/vision/camaras")
def api_vision_camaras():
    return jsonify({"camaras": vision.listar_camaras()})


@app.post("/api/vision")
def api_vision():
    datos = cuerpo()
    if not isinstance(datos, dict):
        return error("Datos de cámara no válidos.")
    try:
        vision.configurar(datos)
    except ValueError as e:
        return error(str(e))
    return ok()


@app.post("/api/vision/calibrar")
def api_vision_calibrar():
    lado = numero(cuerpo().get("lado_cm"), 0.5, 50, None)
    if lado is None:
        return error("Medida no válida.")
    problema = vision.calibrar(lado)
    return error(problema) if problema else ok()


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no envía nada, solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    WSGIRequestHandler.protocol_version = "HTTP/1.1"   # keep-alive = menos latencia
    print("=" * 62)
    print(" BRAZO ROBÓTICO (The Genesis) - servidor listo")
    print(f"   En esta laptop : http://localhost:{PUERTO_WEB}")
    print(f"   En el celular  : http://{ip_local()}:{PUERTO_WEB}  (misma red WiFi)")
    print("   Detener: Ctrl + C")
    print("=" * 62)
    app.run(host="0.0.0.0", port=PUERTO_WEB, threaded=True, debug=False)
