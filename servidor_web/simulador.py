"""
==================================================================
 ESP32 SIMULADO  (para usar la página SIN el brazo conectado)
==================================================================
 Se comporta como el firmware v2 (main.cpp): entiende los mismos
 comandos (J, H, HG, S, V, X, L, R, ?, C), mueve las articulaciones
 con el mismo perfil trapezoidal y responde con las mismas líneas
 (P, A, C, V, X, E). Para app.py es igual que un puerto serie.

 OJO: los valores de fábrica de abajo son una COPIA de los de
 main.cpp, solo para la simulación. Los que mandan en el brazo real
 son los del ESP32.
==================================================================
"""
import math
import threading
import time

N_ARTS = 6
ANG_ABS_MIN, ANG_ABS_MAX = 0.0, 180.0
RECORRIDO_MINIMO = 10.0
ESCALA_CALIBRACION = 0.25
PERIODO_S = 0.02
TELEMETRIA_S = 0.05

# Copia de main.cpp (solo simulación)
FAB_MIN = [9.0] * N_ARTS
FAB_MAX = [171.0] * N_ARTS
FAB_HOME = [95.0, 38.0, 155.0, 95.0, 113.0, 90.0]
VEL_MAX = [180.0, 150.0, 180.0, 300.0, 300.0, 300.0]
ACC_MAX = [500.0, 400.0, 500.0, 1500.0, 1500.0, 1500.0]


class ESP32Simulado:
    """Imita un puerto serie conectado al firmware v2."""

    def __init__(self):
        self._lock = threading.Lock()
        self._salida = bytearray()
        self._entrada = ""
        self.lim_min = list(FAB_MIN)
        self.lim_max = list(FAB_MAX)
        self.home = list(FAB_HOME)
        self.actual = list(FAB_HOME)
        self.objetivo = list(FAB_HOME)
        self.vel = [0.0] * N_ARTS
        self.escala = 1.0
        self.calibracion = False
        self.moviendo_antes = False
        self._t_telem = 0.0
        self._vivo = True
        self.banda_pct = 0
        self._t_banda = 0.0
        self._enviar("LISTO v2 cfg=fabrica (simulado)")
        self._reportar_config()
        self._reportar_objetivos()
        threading.Thread(target=self._hilo, daemon=True).start()

    # ---------------- interfaz tipo pyserial ----------------
    @property
    def in_waiting(self):
        with self._lock:
            return len(self._salida)

    def read(self, n=1):
        with self._lock:
            datos = bytes(self._salida[:n])
            del self._salida[:n]
            return datos

    def write(self, datos):
        texto = datos.decode(errors="ignore")
        with self._lock:
            self._entrada += texto
            *lineas, self._entrada = self._entrada.replace("\r", "\n").split("\n")
            for linea in lineas:
                if linea.strip():
                    self._procesar(linea.strip())
        return len(datos)

    def reset_input_buffer(self):
        with self._lock:
            self._salida.clear()

    def close(self):
        self._vivo = False

    # ---------------- respuestas ----------------
    def _enviar(self, linea):
        self._salida += (linea + "\n").encode()

    def _reportar_objetivos(self):
        self._enviar("P " + " ".join(f"{v:.1f}" for v in self.objetivo))

    def _reportar_telemetria(self, moviendo):
        self._enviar("A " + " ".join(f"{v:.1f}" for v in self.actual) + f" {1 if moviendo else 0}")

    def _reportar_config(self):
        partes = []
        for i in range(N_ARTS):
            partes += [f"{self.lim_min[i]:.1f}", f"{self.lim_max[i]:.1f}", f"{self.home[i]:.1f}"]
        self._enviar("C " + " ".join(partes))

    # ---------------- lógica (igual que main.cpp) ----------------
    def _rango(self, i):
        if self.calibracion:
            return ANG_ABS_MIN, ANG_ABS_MAX
        return self.lim_min[i], self.lim_max[i]

    def _fijar(self, i, g):
        mn, mx = self._rango(i)
        self.objetivo[i] = min(max(g, mn), mx)

    def _procesar(self, cmd):
        try:
            c = cmd[0]
            resto = cmd[1:].split()
            if c == "B":
                if cmd == "B?":
                    self._enviar(f"B {self.banda_pct}")
                elif len(resto) == 1 and -100 <= int(resto[0]) <= 100:
                    pct = int(resto[0])
                    if pct and self.banda_pct and (pct > 0) != (self.banda_pct > 0):
                        self._enviar("E deten la banda antes de invertir el giro")
                    else:
                        self.banda_pct = pct
                        self._t_banda = time.monotonic()
                        self._enviar(f"B {pct}")
                else:
                    self._enviar("E formato: B <-100..100> o B?")
            elif c == "J" and len(resto) == 2:
                i = int(resto[0])
                if 0 <= i < N_ARTS:
                    self._fijar(i, float(resto[1]))
            elif c == "H":
                if cmd.startswith("HG"):
                    for i in range(N_ARTS):
                        self.home[i] = min(max(self.objetivo[i], self.lim_min[i]), self.lim_max[i])
                    self._reportar_config()
                else:
                    for i in range(N_ARTS):
                        self._fijar(i, self.home[i])
            elif c == "S":
                self.banda_pct = 0
                self._enviar("B 0")
                for i in range(N_ARTS):
                    self.objetivo[i] = self.actual[i]
                    self.vel[i] = 0.0
                self._reportar_objetivos()
                self._reportar_telemetria(False)
                self.moviendo_antes = False
            elif c == "V" and resto:
                self.escala = min(max(int(float(resto[0])), 10), 100) / 100
                self._enviar(f"V {round(self.escala * 100)}")
            elif c == "X" and resto:
                self.calibracion = int(float(resto[0])) != 0
                if not self.calibracion:
                    for i in range(N_ARTS):
                        self._fijar(i, self.objetivo[i])
                self._enviar(f"X {1 if self.calibracion else 0}")
                self._reportar_objetivos()
            elif c == "L":
                if len(resto) != 3:
                    self._enviar("E formato: L<i> <min> <max>")
                    return
                i, mn, mx = int(resto[0]), float(resto[1]), float(resto[2])
                if not (0 <= i < N_ARTS and mn >= ANG_ABS_MIN and mx <= ANG_ABS_MAX
                        and mx - mn >= RECORRIDO_MINIMO):
                    self._enviar("E limites invalidos: deben estar entre 0 y 180 y dejar al menos 10 grados")
                    return
                self.lim_min[i], self.lim_max[i] = mn, mx
                self.home[i] = min(max(self.home[i], mn), mx)
                if not self.calibracion:
                    self._fijar(i, self.objetivo[i])
                self._reportar_config()
                self._reportar_objetivos()
            elif c == "R":
                self.lim_min, self.lim_max, self.home = list(FAB_MIN), list(FAB_MAX), list(FAB_HOME)
                if not self.calibracion:
                    for i in range(N_ARTS):
                        self._fijar(i, self.objetivo[i])
                self._reportar_config()
                self._reportar_objetivos()
            elif c == "?":
                self._reportar_objetivos()
                self._reportar_telemetria(self.moviendo_antes)
            elif c == "C":
                self._reportar_config()
        except (ValueError, IndexError):
            pass                                  # el firmware también ignora basura

    def _rampas(self, dt):
        esc = min(self.escala, ESCALA_CALIBRACION) if self.calibracion else self.escala
        hay = False
        for i in range(N_ARTS):
            error = self.objetivo[i] - self.actual[i]
            if error == 0.0 and self.vel[i] == 0.0:
                continue
            v_max, a_max = VEL_MAX[i] * esc, ACC_MAX[i] * esc
            v_fren = a_max * (math.sqrt(0.25 * dt * dt + 2 * abs(error) / a_max) - 0.5 * dt)
            v_des = math.copysign(min(v_max, v_fren), error)
            dv = a_max * dt
            self.vel[i] += min(max(v_des - self.vel[i], -dv), dv)
            paso = self.vel[i] * dt
            cruza = (error > 0 and paso >= error) or (error < 0 and paso <= error)
            llego = abs(error) < 0.05 and abs(self.vel[i]) <= dv
            if cruza or llego:
                self.actual[i] = self.objetivo[i]
                self.vel[i] = 0.0
            else:
                self.actual[i] += paso
                hay = True
        return hay

    def _hilo(self):
        t_ant = time.monotonic()
        while self._vivo:
            time.sleep(PERIODO_S)
            ahora = time.monotonic()
            dt = min(ahora - t_ant, 0.1)
            t_ant = ahora
            with self._lock:
                if self.banda_pct and ahora - self._t_banda >= 2.0:
                    self.banda_pct = 0
                    self._enviar("B 0")
                    self._enviar("E banda detenida por perdida de comunicacion")
                moviendo = self._rampas(dt)
                if moviendo and ahora - self._t_telem >= TELEMETRIA_S:
                    self._reportar_telemetria(True)
                    self._t_telem = ahora
                elif not moviendo and self.moviendo_antes:
                    self._reportar_telemetria(False)
                    self._t_telem = ahora
                self.moviendo_antes = moviendo
