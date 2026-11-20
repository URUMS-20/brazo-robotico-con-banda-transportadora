/*
 * ==================================================================
 *  BRAZO ROBÓTICO "THE GENESIS" — Firmware ESP32 + PCA9685    (v2)
 *  7 servos, 6 articulaciones (M2 y M3 acoplados en el hombro)
 * ==================================================================
 *  Protocolo USB-Serial (115200 baud), una orden por línea:
 *
 *   PC -> ESP32
 *     J<i> <g>          mover la articulación i (0..5) a g grados
 *     H                 ir a HOME
 *     HG                guardar la posición actual como HOME (memoria)
 *     S                 STOP: congela todo donde está (NO suelta los servos)
 *     V <p>             velocidad general en % (10..100)
 *     X <0|1>           modo calibración (permite 0..180°, velocidad <= 25 %)
 *     L<i> <min> <max>  nuevos límites de la articulación i (memoria)
 *     R                 restaurar límites y HOME de fábrica (memoria)
 *     ?                 pedir objetivos y posición   -> "P ..." y "A ..."
 *     C                 pedir configuración          -> "C ..."
 *
 *   ESP32 -> PC
 *     LISTO v2 cfg=...  arranque (cfg=memoria o cfg=fabrica)
 *     P o0 .. o5        objetivos (a dónde va cada articulación)
 *     A a0 .. a5 m      posición actual del perfil; m=1 moviéndose
 *                       (20 veces por segundo mientras hay movimiento)
 *     C n0 x0 h0 .. n5 x5 h5   mínimo, máximo y HOME de cada articulación
 *     V p | X c         confirmaciones
 *     E texto           error
 *
 *  Articulaciones:
 *     J0 = Motor 1        Base (giro)              25 kg
 *     J1 = Motores 2 + 3  Hombro (ACOPLADOS)       2 x 25 kg
 *     J2 = Motor 4        Codo                     15 kg
 *     J3 = Motor 5        Muñeca                   2.2 kg
 *     J4 = Motor 6        Giro de pinza            2.2 kg
 *     J5 = Motor 7        Pinza                    2.2 kg
 *
 *  Seguridad:
 *   - Los LÍMITES y el HOME viven SOLO aquí (memoria flash del ESP32).
 *     El servidor los pide al conectarse, así nunca quedan distintos.
 *   - Aunque la web mande otra cosa, aquí se recorta al límite.
 *   - Perfil trapezoidal: velocidad y aceleración limitadas.
 *   - M2 y M3 SIEMPRE reciben el mismo ángulo (M3 en espejo).
 *   - STOP congela en el lugar (si se cortara el PWM, el brazo caería).
 * ==================================================================
 */
#include <Arduino.h>
#include <Wire.h>
#include <Preferences.h>
#include <Adafruit_PWMServoDriver.h>
#include <esp_arduino_version.h>

// ------------------------- HARDWARE -------------------------------
constexpr uint8_t  PCA_ADDR      = 0x40;     // dirección I2C del PCA9685
constexpr int      PIN_SDA       = 21;       // ESP32 DevKit
constexpr int      PIN_SCL       = 22;
constexpr uint32_t BAUDIOS       = 115200;
constexpr float    SERVO_FREQ_HZ = 50.0f;    // servos estándar
constexpr uint32_t PERIODO_MS    = 20;       // lazo de control a 50 Hz
constexpr uint32_t TELEMETRIA_MS = 50;       // reporte de posición a 20 Hz

// Motor DC de la banda: TC1508A, primer puente (INA/INB, OUTA/OUTB).
// Dos salidas PWM independientes del PCA9685 y de la velocidad del brazo.
constexpr int BANDA_INA = 25;
constexpr int BANDA_INB = 26;
constexpr uint8_t BANDA_CANAL_A = 0;
constexpr uint8_t BANDA_CANAL_B = 1;
constexpr uint32_t BANDA_PWM_HZ = 1000;
constexpr uint32_t BANDA_TIMEOUT_MS = 2000;
int bandaPct = 0;                          // -100..100; 0 = sin potencia (rueda libre)
uint32_t tBanda = 0;
bool bandaLista = false;

void pwmBanda(int pin, uint8_t canal, uint32_t duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(canal, duty);
#endif
}

void reportarBanda() {
  if (!bandaLista) { Serial.println("B NA"); return; }
  Serial.print("B "); Serial.println(bandaPct);
}

void fijarBanda(int pct) {
  if (!bandaLista) { reportarBanda(); return; }
  pct = constrain(pct, -100, 100);
  if (pct && bandaPct && ((pct > 0) != (bandaPct > 0))) {
    Serial.println("E deten la banda antes de invertir el giro");
    return;
  }
  // Primero quitar ambas señales: nunca activar ambos sentidos a la vez.
  pwmBanda(BANDA_INA, BANDA_CANAL_A, 0);
  pwmBanda(BANDA_INB, BANDA_CANAL_B, 0);
  const uint32_t duty = (abs(pct) * 255U + 50U) / 100U;
  if (pct > 0) pwmBanda(BANDA_INA, BANDA_CANAL_A, duty);
  if (pct < 0) pwmBanda(BANDA_INB, BANDA_CANAL_B, duty);
  bandaPct = pct;
  tBanda = millis();
  reportarBanda();
}

void iniciarBanda() {
  digitalWrite(BANDA_INA, LOW);
  digitalWrite(BANDA_INB, LOW);
  pinMode(BANDA_INA, OUTPUT);
  pinMode(BANDA_INB, OUTPUT);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  const bool a = ledcAttachChannel(BANDA_INA, BANDA_PWM_HZ, 8, BANDA_CANAL_A);
  const bool b = ledcAttachChannel(BANDA_INB, BANDA_PWM_HZ, 8, BANDA_CANAL_B);
  bandaLista = a && b;
#else
  const double a = ledcSetup(BANDA_CANAL_A, BANDA_PWM_HZ, 8);
  const double b = ledcSetup(BANDA_CANAL_B, BANDA_PWM_HZ, 8);
  ledcAttachPin(BANDA_INA, BANDA_CANAL_A);
  ledcAttachPin(BANDA_INB, BANDA_CANAL_B);
  bandaLista = a > 0 && b > 0;
#endif
  pwmBanda(BANDA_INA, BANDA_CANAL_A, 0);
  pwmBanda(BANDA_INB, BANDA_CANAL_B, 0);
  bandaPct = 0;
}

// ------------------------- LÍMITES ABSOLUTOS -----------------------
constexpr float ANG_ABS_MIN       = 0.0f;    // nada sale de [0°, 180°]
constexpr float ANG_ABS_MAX       = 180.0f;
constexpr float RECORRIDO_MINIMO  = 10.0f;   // un límite deja al menos 10°
constexpr float ESCALA_CALIBRACION = 0.25f;  // en calibración, máx. 25 % de velocidad

constexpr uint8_t N_ARTS = 6;

// ------------------------- VALORES DE FÁBRICA ----------------------
// Límites seguros (90 % del recorrido) y el HOME elegido con el brazo
// armado. Se usan la primera vez o al mandar "R". Los límites reales
// de cada articulación se calibran desde la página y se guardan en
// la memoria del ESP32 (no hace falta volver a subir el firmware).
const float FAB_MIN[N_ARTS]  = {   9.0f,   9.0f,   9.0f,   9.0f,   9.0f,   9.0f };
const float FAB_MAX[N_ARTS]  = { 171.0f, 171.0f, 171.0f, 171.0f, 171.0f, 171.0f };
const float FAB_HOME[N_ARTS] = {  95.0f,  38.0f, 155.0f,  95.0f, 113.0f,  90.0f };

// ------------------------- SERVOS FÍSICOS --------------------------
struct ServoFisico {
  const char* nombre;
  uint8_t  canal;      // salida del PCA9685 (0..15)
  uint16_t usMin;      // ancho de pulso en 0°   (calibrable)
  uint16_t usMax;      // ancho de pulso en 180° (calibrable)
  bool     invertido;  // true = montaje espejo (gira al revés)
  float    offset;     // ajuste fino en grados (alinear M2 con M3)
};

ServoFisico servos[] = {
  // nombre            canal usMin usMax invertido offset
  { "M1 Base",           0,   500, 2500, false,    0.0f },
  { "M2 Hombro A",       1,   500, 2500, false,    0.0f },
  { "M3 Hombro B",       2,   500, 2500, true,     0.0f },  // espejo de M2
  { "M4 Codo",           3,   500, 2500, false,    0.0f },
  { "M5 Muneca",         4,   500, 2500, false,    0.0f },
  { "M6 Giro pinza",     5,   500, 2500, false,    0.0f },
  { "M7 Pinza",          6,   500, 2500, false,    0.0f },
};

// ------------------------- ARTICULACIONES --------------------------
struct Articulacion {
  const char* nombre;
  int8_t servoA;       // índice en servos[]
  int8_t servoB;       // segundo servo acoplado (-1 = ninguno)
  float  velMax;       // °/s   velocidad máxima (al 100 %)
  float  accMax;       // °/s²  aceleración máxima (al 100 %)
  // --- lo siguiente se llena al arrancar (memoria o fábrica) ---
  float  limMin;       // °
  float  limMax;       // °
  float  home;         // °
  float  actual;       // posición que se está mandando ahora
  float  objetivo;     // posición pedida
  float  vel;          // °/s   velocidad actual del perfil
};

// AJUSTE FINO ("sintonía"):
//  - Si REBOTA o se pasa al frenar          -> BAJA accMax
//  - Si se siente lento al arrancar         -> SUBE accMax
//  - Si va muy rápido o jala mucha corriente -> BAJA velMax
Articulacion arts[N_ARTS] = {
  // nombre     A   B   velMax   accMax
  { "Base",     0, -1,  180.0f,   500.0f },
  { "Hombro",   1,  2,  150.0f,   400.0f },   // M2 + M3
  { "Codo",     3, -1,  180.0f,   500.0f },
  { "Muneca",   4, -1,  300.0f,  1500.0f },
  { "Giro",     5, -1,  300.0f,  1500.0f },
  { "Pinza",    6, -1,  300.0f,  1500.0f },
};

// ------------------------- MEMORIA (NVS) ---------------------------
struct ConfigGuardada {
  uint32_t magic;
  float limMin[N_ARTS];
  float limMax[N_ARTS];
  float home[N_ARTS];
};
constexpr uint32_t CONFIG_MAGIC = 0x47454E32;    // "GEN2"

// ------------------------- OBJETOS GLOBALES ------------------------
Adafruit_PWMServoDriver pwm(PCA_ADDR);
Preferences memoria;
uint32_t tAnterior      = 0;
uint32_t tTelemetria    = 0;
bool     moviendoAntes  = false;
float    escalaVel      = 1.0f;     // 0.10 .. 1.00 (comando V)
bool     modoCalibracion = false;   // comando X
char     bufSerial[48];
uint8_t  lenSerial = 0;

// ==================================================================
//  Utilidades
// ==================================================================
float escalaEfectiva() {
  return modoCalibracion ? fminf(escalaVel, ESCALA_CALIBRACION) : escalaVel;
}

// Rango permitido ahora mismo (en calibración se abre a 0..180)
void rangoActivo(uint8_t i, float& mn, float& mx) {
  if (modoCalibracion) { mn = ANG_ABS_MIN; mx = ANG_ABS_MAX; }
  else                 { mn = arts[i].limMin; mx = arts[i].limMax; }
}

// pulso[µs] = usMin + (ang / 180) * (usMax - usMin)
void escribirServo(uint8_t idx, float anguloArt) {
  const ServoFisico& s = servos[idx];
  float ang = s.invertido ? (180.0f - anguloArt) : anguloArt;
  ang += s.offset;
  ang = constrain(ang, 0.0f, 180.0f);
  const uint16_t us = s.usMin + (uint16_t)lroundf(ang / 180.0f * (s.usMax - s.usMin));
  pwm.writeMicroseconds(s.canal, us);
}

void aplicarArticulacion(const Articulacion& a) {
  escribirServo(a.servoA, a.actual);
  if (a.servoB >= 0) escribirServo(a.servoB, a.actual);  // M3 recibe lo mismo que M2
}

void fijarObjetivo(uint8_t i, float grados) {
  if (i >= N_ARTS) return;
  float mn, mx;
  rangoActivo(i, mn, mx);
  arts[i].objetivo = constrain(grados, mn, mx);
}

void recortarObjetivos() {
  for (uint8_t i = 0; i < N_ARTS; i++) fijarObjetivo(i, arts[i].objetivo);
}

// ==================================================================
//  Reportes hacia la PC
// ==================================================================
void reportarObjetivos() {
  Serial.print('P');
  for (uint8_t i = 0; i < N_ARTS; i++) { Serial.print(' '); Serial.print(arts[i].objetivo, 1); }
  Serial.println();
}

void reportarTelemetria(bool moviendo) {
  Serial.print('A');
  for (uint8_t i = 0; i < N_ARTS; i++) { Serial.print(' '); Serial.print(arts[i].actual, 1); }
  Serial.print(' ');
  Serial.println(moviendo ? 1 : 0);
}

void reportarConfig() {
  Serial.print('C');
  for (uint8_t i = 0; i < N_ARTS; i++) {
    Serial.print(' '); Serial.print(arts[i].limMin, 1);
    Serial.print(' '); Serial.print(arts[i].limMax, 1);
    Serial.print(' '); Serial.print(arts[i].home, 1);
  }
  Serial.println();
}

// ==================================================================
//  Memoria flash (límites y HOME sobreviven al apagado)
// ==================================================================
bool configValida(const ConfigGuardada& c) {
  if (c.magic != CONFIG_MAGIC) return false;
  for (uint8_t i = 0; i < N_ARTS; i++) {
    // (las comparaciones con NaN dan false, así que un NaN también se rechaza)
    if (!(c.limMin[i] >= ANG_ABS_MIN && c.limMax[i] <= ANG_ABS_MAX)) return false;
    if (!(c.limMax[i] - c.limMin[i] >= RECORRIDO_MINIMO)) return false;
    if (!(c.home[i] >= c.limMin[i] && c.home[i] <= c.limMax[i])) return false;
  }
  return true;
}

void usarFabrica() {
  for (uint8_t i = 0; i < N_ARTS; i++) {
    arts[i].limMin = FAB_MIN[i];
    arts[i].limMax = FAB_MAX[i];
    arts[i].home   = FAB_HOME[i];
  }
}

bool cargarConfig() {
  ConfigGuardada c;
  const bool leida = memoria.getBytesLength("cfg") == sizeof(c) &&
                     memoria.getBytes("cfg", &c, sizeof(c)) == sizeof(c);
  if (!leida || !configValida(c)) { usarFabrica(); return false; }
  for (uint8_t i = 0; i < N_ARTS; i++) {
    arts[i].limMin = c.limMin[i];
    arts[i].limMax = c.limMax[i];
    arts[i].home   = c.home[i];
  }
  return true;
}

void guardarConfig() {
  ConfigGuardada c;
  c.magic = CONFIG_MAGIC;
  for (uint8_t i = 0; i < N_ARTS; i++) {
    c.limMin[i] = arts[i].limMin;
    c.limMax[i] = arts[i].limMax;
    c.home[i]   = arts[i].home;
  }
  memoria.putBytes("cfg", &c, sizeof(c));
}

// ==================================================================
//  Acciones
// ==================================================================
void detenerTodo() {                       // STOP: congelar donde está
  fijarBanda(0);
  for (uint8_t i = 0; i < N_ARTS; i++) {
    arts[i].objetivo = arts[i].actual;
    arts[i].vel = 0.0f;
  }
  reportarObjetivos();
  reportarTelemetria(false);
  moviendoAntes = false;
}

void fijarLimites(uint8_t i, float mn, float mx) {
  if (i >= N_ARTS || !(mn >= ANG_ABS_MIN) || !(mx <= ANG_ABS_MAX) ||
      !(mx - mn >= RECORRIDO_MINIMO)) {
    Serial.println("E limites invalidos: deben estar entre 0 y 180 y dejar al menos 10 grados");
    return;
  }
  arts[i].limMin = mn;
  arts[i].limMax = mx;
  arts[i].home   = constrain(arts[i].home, mn, mx);     // el HOME siempre dentro
  if (!modoCalibracion) fijarObjetivo(i, arts[i].objetivo);
  guardarConfig();
  reportarConfig();
  reportarObjetivos();
}

void guardarHome() {                        // HOME = posición pedida actual
  for (uint8_t i = 0; i < N_ARTS; i++) {
    arts[i].home = constrain(arts[i].objetivo, arts[i].limMin, arts[i].limMax);
  }
  guardarConfig();
  reportarConfig();
}

void restaurarFabrica() {
  usarFabrica();
  guardarConfig();
  if (!modoCalibracion) recortarObjetivos();
  reportarConfig();
  reportarObjetivos();
}

// ==================================================================
//  Protocolo serie
// ==================================================================
// Lee "<entero> <real> <real>" a partir de p. Devuelve cuántos leyó.
int leerNumeros(const char* p, long* entero, float* r1, float* r2) {
  char* fin = nullptr;
  int n = 0;
  if (entero) {
    *entero = strtol(p, &fin, 10);
    if (fin == p) return n;
    p = fin; n++;
  }
  if (r1) {
    *r1 = strtof(p, &fin);
    if (fin == p) return n;
    p = fin; n++;
  }
  if (r2) {
    *r2 = strtof(p, &fin);
    if (fin == p) return n;
    n++;
  }
  return n;
}

void procesarComando(const char* cmd) {
  long i = 0;
  float a = 0.0f, b = 0.0f;
  switch (cmd[0]) {
    case 'B':                              // B? consulta; B <-100..100> potencia con signo
      if (cmd[1] == '?' && cmd[2] == '\0') reportarBanda();
      else {
        char* fin = nullptr;
        const long pct = strtol(cmd + 1, &fin, 10);
        const bool leido = fin != cmd + 1;
        while (*fin == ' ') ++fin;
        if (leido && *fin == '\0' && pct >= -100 && pct <= 100)
          fijarBanda((int)pct);
        else Serial.println("E formato: B <-100..100> o B?");
      }
      break;
    case 'J':                                     // J<i> <grados>
      if (leerNumeros(cmd + 1, &i, &a, nullptr) == 2 && i >= 0 && i < N_ARTS)
        fijarObjetivo((uint8_t)i, a);
      break;
    case 'H':
      if (cmd[1] == 'G') guardarHome();           // HG
      else for (uint8_t k = 0; k < N_ARTS; k++) fijarObjetivo(k, arts[k].home);
      break;
    case 'S':
      detenerTodo();
      break;
    case 'V':                                     // V <porcentaje>
      if (leerNumeros(cmd + 1, &i, nullptr, nullptr) == 1) {
        escalaVel = constrain(i, 10L, 100L) / 100.0f;
        Serial.print("V "); Serial.println((int)lroundf(escalaVel * 100.0f));
      }
      break;
    case 'X':                                     // X <0|1>
      if (leerNumeros(cmd + 1, &i, nullptr, nullptr) == 1) {
        modoCalibracion = (i != 0);
        if (!modoCalibracion) recortarObjetivos(); // regresar dentro de límites
        Serial.print("X "); Serial.println(modoCalibracion ? 1 : 0);
        reportarObjetivos();
      }
      break;
    case 'L':                                     // L<i> <min> <max>
      if (leerNumeros(cmd + 1, &i, &a, &b) == 3 && i >= 0 && i < N_ARTS)
        fijarLimites((uint8_t)i, a, b);
      else
        Serial.println("E formato: L<i> <min> <max>");
      break;
    case 'R':
      restaurarFabrica();
      break;
    case '?':
      reportarObjetivos();
      reportarTelemetria(moviendoAntes);
      break;
    case 'C':
      reportarConfig();
      break;
    default:
      break;                                      // se ignora
  }
}

void leerSerial() {
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (lenSerial > 0) {
        bufSerial[lenSerial] = '\0';
        procesarComando(bufSerial);
        lenSerial = 0;
      }
    } else if (lenSerial < sizeof(bufSerial) - 1) {
      bufSerial[lenSerial++] = c;
    } else {
      lenSerial = 0;                              // línea demasiado larga -> se descarta
    }
  }
}

// ==================================================================
//  Perfil TRAPEZOIDAL: limita velocidad Y aceleración
//   - Arranca suave, viaja a velMax y frena justo a tiempo para llegar
//     al objetivo sin pasarse. Velocidad máxima para poder frenar:
//        v_frenado = sqrt(2 · accMax · |error|)
//   - La velocidad general (comando V) escala velMax y accMax.
// ==================================================================
bool actualizarRampas(float dt) {
  const float esc = escalaEfectiva();
  bool hayMovimiento = false;
  for (uint8_t i = 0; i < N_ARTS; i++) {
    Articulacion& a = arts[i];
    const float error = a.objetivo - a.actual;
    if (error == 0.0f && a.vel == 0.0f) continue;          // quieto y en su lugar

    const float vMax = a.velMax * esc;
    const float aMax = a.accMax * esc;

    // 1) Velocidad deseada: la mayor que todavía permite frenar a tiempo.
    //    Versión discreta de v = sqrt(2·a·|e|), exacta para pasos de dt:
    //    v²/(2a) + v·dt/2 = |e|  ->  v = a·( sqrt(dt²/4 + 2|e|/a) - dt/2 )
    const float vFrenado = aMax * (sqrtf(0.25f * dt * dt + 2.0f * fabsf(error) / aMax) - 0.5f * dt);
    const float vDeseada = copysignf(fminf(vMax, vFrenado), error);

    // 2) La velocidad solo cambia aMax·dt por ciclo (aceleración limitada)
    const float dvMax = aMax * dt;
    a.vel += constrain(vDeseada - a.vel, -dvMax, dvMax);

    // 3) Avanzar; si este paso cruzaría el objetivo, aterrizar exacto en él
    const float paso  = a.vel * dt;
    const bool  cruza = (error > 0.0f && paso >= error) || (error < 0.0f && paso <= error);
    const bool  llego = fabsf(error) < 0.05f && fabsf(a.vel) <= dvMax;
    if (cruza || llego) {
      a.actual = a.objetivo;
      a.vel = 0.0f;
    } else {
      a.actual += paso;
      hayMovimiento = true;
    }
    aplicarArticulacion(a);
  }
  return hayMovimiento;
}

// ==================================================================
void setup() {
  iniciarBanda();                           // motor apagado desde el inicio
  Serial.begin(BAUDIOS);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);                         // I2C rápido: 7 servos en < 2 ms

  if (!pwm.begin()) {
    Serial.println("E no se encontro el PCA9685 (revisa SDA/SCL/VCC/GND)");
  }
  pwm.setOscillatorFrequency(27000000);          // valor típico de los módulos PCA9685
  pwm.setPWMFreq(SERVO_FREQ_HZ);
  delay(10);

  memoria.begin("brazo", false);
  const bool deMemoria = cargarConfig();

  // Posición inicial: HOME en todas las articulaciones
  for (uint8_t i = 0; i < N_ARTS; i++) {
    arts[i].actual = arts[i].objetivo = arts[i].home;
    arts[i].vel = 0.0f;
    aplicarArticulacion(arts[i]);
  }

  tAnterior = tTelemetria = millis();
  Serial.print("LISTO v2 cfg=");
  Serial.println(deMemoria ? "memoria" : "fabrica");
  reportarConfig();
  reportarObjetivos();
  reportarBanda();
}

void loop() {
  if (bandaPct && millis() - tBanda >= BANDA_TIMEOUT_MS) {
    fijarBanda(0);                            // sin latidos USB, no seguir moviendo la banda
    Serial.println("E banda detenida por perdida de comunicacion");
  }
  leerSerial();

  const uint32_t ahora = millis();
  if (ahora - tAnterior >= PERIODO_MS) {
    float dt = (ahora - tAnterior) / 1000.0f;
    if (dt > 0.1f) dt = 0.1f;                     // si algo se trabó, no dar un salto
    tAnterior = ahora;

    const bool moviendo = actualizarRampas(dt);
    if (moviendo && ahora - tTelemetria >= TELEMETRIA_MS) {
      reportarTelemetria(true);
      tTelemetria = ahora;
    } else if (!moviendo && moviendoAntes) {
      reportarTelemetria(false);                  // aviso de "ya llegó"
      tTelemetria = ahora;
    }
    moviendoAntes = moviendo;
  }
}
