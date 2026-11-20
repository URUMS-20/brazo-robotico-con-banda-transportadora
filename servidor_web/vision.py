"""
==================================================================
 VISIÓN ARTIFICIAL — Logitech Brio 100 (o cualquier webcam USB)
==================================================================
 - Captura con OpenCV en un hilo propio (no frena el control del brazo).
 - Detecta cubos por COLOR (espacio HSV) y mide su TAMAÑO:
       lado_cm = lado_px / px_por_cm
   px_por_cm se calibra con un cubo de medida conocida (botón en la página).
 - Clasifica el tamaño contra la lista "tamanos_cm" (5 y 7 cm).
 - Entrega el video con las detecciones dibujadas (MJPEG) para la página.
 - Configuración en vision.json (esta carpeta).
 - "Imagen de prueba": fuente sintética para probar sin cámara.
==================================================================
"""
import json
import os
import platform
import threading
import time
from urllib.parse import urlsplit, urlunsplit

try:
    import cv2
    import numpy as np
    HAY_CV2 = True
except ImportError:              # la página avisa cómo instalarlo
    cv2 = np = None
    HAY_CV2 = False

ES_WINDOWS = platform.system() == "Windows"
ANCHO_DETECCION = 640            # se detecta en una copia reducida (más rápido)
ANCHO_VIDEO = 960                # tamaño del video que se manda a la página
FPS_VIDEO = 20

CONFIG_DEFECTO = {
    "url_telefono": "",          # URL local de IP Webcam (Android)
    "camara": None,              # índice de la cámara (None = aún no elegida) o "sintetica"
    "activa": False,
    "ancho": 1280,
    "alto": 720,
    "exposicion_auto": True,
    "exposicion": -6,            # solo en modo manual (DirectShow: -11 oscuro ... -1 claro)
    "px_por_cm": None,           # sin calibrar hasta medir un cubo conocido
    "tamanos_cm": [5, 7],
    "tolerancia": 0.2,           # ±20 % para decidir el tamaño
    "area_min_px": 600,
    "colores": {
        # Rangos HSV de OpenCV (H 0–179, S 0–255, V 0–255)
        "rojo":     {"activo": True, "bgr": [50, 50, 235],
                     "rangos": [[[0, 120, 70], [10, 255, 255]], [[170, 120, 70], [179, 255, 255]]]},
        "verde":    {"activo": True, "bgr": [70, 200, 70],   "rangos": [[[40, 70, 60], [85, 255, 255]]]},
        "azul":     {"activo": True, "bgr": [235, 140, 40],  "rangos": [[[95, 120, 60], [130, 255, 255]]]},
        "amarillo": {"activo": True, "bgr": [40, 220, 240],  "rangos": [[[20, 120, 90], [35, 255, 255]]]},
    },
}


def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def url_telefono_validada(valor):
    """Dirección de la app o URL HTTP(S) de video, sin credenciales."""
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 500:
        raise ValueError("Escribe la dirección que muestra la app del teléfono.")
    texto = valor.strip()
    if "://" not in texto:
        texto = "http://" + texto
    try:
        u = urlsplit(texto)
        puerto = u.port
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            raise ValueError
        if any(c.isspace() for c in u.netloc) or puerto == 0 or u.fragment:
            raise ValueError
    except ValueError:
        raise ValueError("Usa una dirección HTTP o HTTPS del teléfono, sin usuario ni contraseña.") from None
    return urlunsplit((u.scheme, u.netloc, "/video" if u.path in ("", "/") else u.path, u.query, ""))


class FuenteSintetica:
    """Imita una cámara: cubos de colores moviéndose sobre una banda gris."""

    def __init__(self, ancho=1280, alto=720):
        self.ancho, self.alto, self.t0 = ancho, alto, time.monotonic()

    def isOpened(self):
        return True

    def read(self):
        t = time.monotonic() - self.t0
        img = np.full((self.alto, self.ancho, 3), 70, np.uint8)
        cv2.rectangle(img, (0, self.alto // 2 - 160), (self.ancho, self.alto // 2 + 160), (45, 45, 45), -1)
        # (color BGR, lado en px, carril y, velocidad px/s, desfase)
        for bgr, lado, y, vel, fase in (((30, 30, 200), 150, -60, 90, 0), ((40, 170, 40), 210, 70, 90, 520),
                                         ((200, 110, 20), 150, 70, 90, 260), ((30, 200, 230), 210, -60, 90, 800)):
            x = int((t * vel + fase) % (self.ancho + lado)) - lado // 2
            cy = self.alto // 2 + y
            cv2.rectangle(img, (x - lado // 2, cy - lado // 2), (x + lado // 2, cy + lado // 2), bgr, -1)
        time.sleep(1 / 30)
        return True, img

    def set(self, *_):
        return True

    def release(self):
        pass


class Vision:
    def __init__(self, ruta_config):
        self.ruta = ruta_config
        self.lock = threading.Lock()
        self.cfg = self._cargar()
        self.cap = None
        self._hilo = None
        self._parar = threading.Event()
        self._reaplicar = False
        self._jpeg = None
        self._dets = []
        self._fps = 0.0
        self._error = None if HAY_CV2 else "Falta OpenCV: python -m pip install opencv-python"
        self._tam_frame = None
        if HAY_CV2 and self.cfg["activa"] and self.cfg["camara"] is not None:
            self.iniciar()

    # ------------------------ configuración ------------------------
    def _cargar(self):
        cfg = json.loads(json.dumps(CONFIG_DEFECTO))
        guardada = _leer_json(self.ruta)
        for k, v in guardada.items():
            if k == "colores" and isinstance(v, dict):
                for nombre, datos in v.items():
                    if nombre in cfg["colores"] and isinstance(datos, dict):
                        cfg["colores"][nombre].update(datos)
            elif k in cfg:
                cfg[k] = v
        if cfg["url_telefono"]:
            try:
                cfg["url_telefono"] = url_telefono_validada(cfg["url_telefono"])
            except ValueError:
                cfg["url_telefono"] = ""
                if cfg["camara"] == "telefono":
                    cfg["activa"] = False
        return cfg

    def _guardar(self):
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.ruta)

    def configurar(self, datos):
        """Cambios desde la página: cámara, encendido, exposición, colores y tamaños."""
        reiniciar = False
        nueva_url = url_telefono_validada(datos["url_telefono"]) if "url_telefono" in datos else None
        with self.lock:
            if nueva_url is not None and nueva_url != self.cfg["url_telefono"]:
                self.cfg["url_telefono"] = nueva_url
                reiniciar = self.cfg["camara"] == "telefono"
                if reiniciar:
                    self.cfg["px_por_cm"] = None
            if "camara" in datos and datos["camara"] != self.cfg["camara"]:
                cam = datos["camara"]
                if cam in ("sintetica", "telefono") or (type(cam) is int and 0 <= cam <= 9):
                    self.cfg["camara"] = cam
                    self.cfg["px_por_cm"] = None  # Cada cámara tiene su escala y encuadre.
                    reiniciar = True
            if "exposicion_auto" in datos:
                self.cfg["exposicion_auto"] = bool(datos["exposicion_auto"])
                self._reaplicar = True
            if "exposicion" in datos:
                try:
                    self.cfg["exposicion"] = max(-13, min(0, int(datos["exposicion"])))
                    self._reaplicar = True
                except (TypeError, ValueError):
                    pass
            if isinstance(datos.get("colores"), dict):
                for nombre, activo in datos["colores"].items():
                    if nombre in self.cfg["colores"]:
                        self.cfg["colores"][nombre]["activo"] = bool(activo)
            if isinstance(datos.get("tamanos_cm"), list):
                tam = [float(t) for t in datos["tamanos_cm"] if isinstance(t, (int, float)) and 0.5 <= t <= 50]
                if tam:
                    self.cfg["tamanos_cm"] = tam
            if "activa" in datos:
                self.cfg["activa"] = bool(datos["activa"])
            self._guardar()
            activa = self.cfg["activa"]
        if not HAY_CV2:
            return
        if activa and (reiniciar or not self.corriendo()):
            if self.detener(guardar=False):
                self.iniciar()
        elif not activa and self.corriendo():
            self.detener(guardar=False)

    def calibrar(self, lado_cm):
        """px_por_cm = lado medido en px / lado real en cm (usa el cubo más grande a la vista)."""
        with self.lock:
            if not self._dets:
                return "No veo ningún cubo. Pon uno solo, bien iluminado, debajo de la cámara."
            d = max(self._dets, key=lambda x: x["area_px"])
            if d["relacion"] < 0.8:
                return "El objeto no se ve cuadrado. Ponlo derecho, con la cámara viendo desde arriba."
            self.cfg["px_por_cm"] = round(d["lado_px"] / float(lado_cm), 2)
            self._guardar()
            return None

    # ------------------------ cámaras ------------------------------
    def listar_camaras(self, maximo=5):
        lista = []
        if HAY_CV2:
            en_uso = self.cfg["camara"] if self.corriendo() else None
            for i in range(maximo):
                if i == en_uso:
                    lista.append({"indice": i, "texto": f"Cámara {i} (en uso)"})
                    continue
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if ES_WINDOWS else cv2.VideoCapture(i)
                if cap is not None and cap.isOpened():
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        h, w = frame.shape[:2]
                        lista.append({"indice": i, "texto": f"Cámara {i} ({w}×{h})"})
                if cap is not None:
                    cap.release()
            lista.append({"indice": "sintetica", "texto": "Imagen de prueba (sin cámara)"})
            lista.append({"indice": "telefono", "texto": "Mi teléfono (WiFi / IP Webcam)"})
        return lista

    def corriendo(self):
        return self._hilo is not None and self._hilo.is_alive()

    def iniciar(self):
        if not HAY_CV2 or self.corriendo() or self.cfg["camara"] is None:
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._capturar, daemon=True)
        self._hilo.start()

    def detener(self, guardar=True):
        self._parar.set()
        if self._hilo and self._hilo is not threading.current_thread():
            self._hilo.join(timeout=4.0)
            if self._hilo.is_alive():
                with self.lock:
                    self._error = "La cámara está terminando de cerrar. Espera y vuelve a encenderla."
                return False
        self._hilo = None
        with self.lock:
            self._jpeg, self._dets, self._fps = None, [], 0.0
            if guardar:
                self.cfg["activa"] = False
                self._guardar()
        return True

    def _abrir(self):
        cam = self.cfg["camara"]
        if cam == "sintetica":
            return FuenteSintetica(self.cfg["ancho"], self.cfg["alto"])
        if cam == "telefono":
            if not self.cfg["url_telefono"]:
                with self.lock:
                    self._error = "Escribe la dirección del teléfono en Conectar teléfono por WiFi."
                return None
            try:
                cap = cv2.VideoCapture(self.cfg["url_telefono"], cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1000,
                ])
            except cv2.error:
                return None
            if not cap.isOpened():
                cap.release()
                return None
            return cap
        cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW) if ES_WINDOWS else cv2.VideoCapture(cam)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg["ancho"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg["alto"])
        cap.set(cv2.CAP_PROP_FPS, 30)
        return cap

    def _aplicar_exposicion(self):
        if self.cfg["camara"] == "telefono":
            return  # La exposición del teléfono se ajusta en su app.
        # DirectShow (Windows): 0.75 = automática, 0.25 = manual.  V4L2 (Linux): 3 = auto, 1 = manual.
        auto = (0.75 if ES_WINDOWS else 3) if self.cfg["exposicion_auto"] else (0.25 if ES_WINDOWS else 1)
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, auto)
        if not self.cfg["exposicion_auto"]:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, self.cfg["exposicion"])

    # ------------------------ hilo de captura -----------------------
    def _capturar(self):
        fallos, t_ant = 0, time.monotonic()
        while not self._parar.is_set():
            if self.cap is None:
                self.cap = self._abrir()
                if self.cap is None:
                    with self.lock:
                        if self.cfg["camara"] == "telefono":
                            if self.cfg["url_telefono"]:
                                self._error = "No se pudo conectar al teléfono. Abre IP Webcam, inicia el servidor y comprueba la dirección y la misma red WiFi."
                        else:
                            self._error = f"No se pudo abrir la cámara {self.cfg['camara']}. ¿Está conectada o la usa otro programa?"
                    self._parar.wait(2.0)
                    continue
                self._aplicar_exposicion()
                with self.lock:
                    self._error = None
            if self._reaplicar:
                self._reaplicar = False
                self._aplicar_exposicion()
            ok, frame = self.cap.read()
            if not ok or frame is None:
                fallos += 1
                if fallos > 30:                       # se desconectó: reabrir
                    self.cap.release()
                    self.cap = None
                    fallos = 0
                time.sleep(0.02)
                continue
            fallos = 0
            dets = self.detectar(frame)
            jpeg = self._codificar(self.dibujar(frame, dets))
            ahora = time.monotonic()
            with self.lock:
                self._dets, self._jpeg = dets, jpeg
                self._tam_frame = frame.shape[1], frame.shape[0]
                dt = ahora - t_ant
                self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt) if dt > 0 else self._fps
            t_ant = ahora
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    # ------------------------ detección -----------------------------
    def _clasificar(self, lado_cm):
        mejor = min(self.cfg["tamanos_cm"], key=lambda t: abs(t - lado_cm))
        return f"{mejor:g} cm" if abs(mejor - lado_cm) <= self.cfg["tolerancia"] * mejor else "?"

    def detectar(self, frame):
        h, w = frame.shape[:2]
        esc = min(1.0, ANCHO_DETECCION / w)
        peq = cv2.resize(frame, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA) if esc < 1 else frame
        hsv = cv2.cvtColor(cv2.GaussianBlur(peq, (5, 5), 0), cv2.COLOR_BGR2HSV)
        nucleo = np.ones((5, 5), np.uint8)
        ppc = self.cfg["px_por_cm"]
        dets = []
        for nombre, c in self.cfg["colores"].items():
            if not c.get("activo"):
                continue
            mascara = np.zeros(hsv.shape[:2], np.uint8)
            for bajo, alto in c["rangos"]:
                mascara |= cv2.inRange(hsv, np.array(bajo, np.uint8), np.array(alto, np.uint8))
            mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, nucleo)
            mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, nucleo)
            contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contornos:
                area = cv2.contourArea(cnt) / (esc * esc)
                if area < self.cfg["area_min_px"]:
                    continue
                (cx, cy), (rw, rh), ang = cv2.minAreaRect(cnt)
                cx, cy, rw, rh = cx / esc, cy / esc, rw / esc, rh / esc
                lado = (rw + rh) / 2
                d = {"color": nombre, "centro_px": [round(cx), round(cy)], "lado_px": round(lado, 1),
                     "angulo": round(ang, 1), "relacion": round(min(rw, rh) / max(rw, rh), 2),
                     "area_px": round(area), "caja": [round(cx), round(cy), round(rw), round(rh), round(ang, 1)]}
                if ppc:
                    lado_cm = lado / ppc
                    d["lado_cm"] = round(lado_cm, 1)
                    d["clase"] = self._clasificar(lado_cm)
                    # posición respecto al centro de la imagen: X a la derecha, Y hacia arriba
                    d["pos_cm"] = [round((cx - w / 2) / ppc, 1), round((h / 2 - cy) / ppc, 1)]
                dets.append(d)
        dets.sort(key=lambda d: -d["area_px"])
        return dets[:10]

    def dibujar(self, frame, dets):
        img = frame.copy()
        h, w = img.shape[:2]
        cv2.drawMarker(img, (w // 2, h // 2), (200, 200, 200), cv2.MARKER_CROSS, 24, 1)
        for d in dets:
            cx, cy, rw, rh, ang = d["caja"]
            bgr = tuple(int(x) for x in self.cfg["colores"][d["color"]]["bgr"])
            puntos = cv2.boxPoints(((cx, cy), (rw, rh), ang)).astype(np.int32)
            cv2.polylines(img, [puntos], True, (255, 255, 255), 4)
            cv2.polylines(img, [puntos], True, bgr, 2)
            cv2.circle(img, (cx, cy), 4, (255, 255, 255), -1)
            texto = f"{d['color']} {d.get('clase', str(round(d['lado_px'])) + ' px')}"
            (tw, th), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            x0, y0 = int(cx - tw / 2), int(cy - rh / 2 - 12)
            cv2.rectangle(img, (x0 - 6, y0 - th - 6), (x0 + tw + 6, y0 + 6), (20, 20, 20), -1)
            cv2.putText(img, texto, (x0, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        if not self.cfg["px_por_cm"]:
            cv2.putText(img, "Sin calibrar px/cm: tamanos en pixeles", (16, h - 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 200, 255), 2, cv2.LINE_AA)
        return img

    def _codificar(self, img):
        h, w = img.shape[:2]
        if w > ANCHO_VIDEO:
            img = cv2.resize(img, (ANCHO_VIDEO, int(h * ANCHO_VIDEO / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    # ------------------------ para la página ------------------------
    def estado(self):
        with self.lock:
            return {
                "disponible": HAY_CV2, "activa": self.corriendo() and self._jpeg is not None,
                "encendida": bool(self.cfg["activa"]), "camara": self.cfg["camara"],
                "url_telefono": self.cfg["url_telefono"],
                "fps": round(self._fps), "error": self._error, "px_por_cm": self.cfg["px_por_cm"],
                "tamanos_cm": self.cfg["tamanos_cm"], "exposicion_auto": self.cfg["exposicion_auto"],
                "exposicion": self.cfg["exposicion"],
                "colores": {k: bool(v.get("activo")) for k, v in self.cfg["colores"].items()},
                "detecciones": [{k: v for k, v in d.items() if k != "caja"} for d in self._dets],
            }

    def flujo_mjpeg(self):
        """Video para <img src="/video">: un JPEG tras otro (multipart/x-mixed-replace)."""
        ultimo = None
        while self.corriendo():
            with self.lock:
                jpeg = self._jpeg
            if jpeg is not None and jpeg is not ultimo:
                ultimo = jpeg
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                       str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            time.sleep(1 / FPS_VIDEO)
