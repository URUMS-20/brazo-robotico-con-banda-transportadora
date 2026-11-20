==============================================================================
  BRAZO ROBÓTICO (The Genesis)
  Control web + gemelo digital 3D + visión artificial
------------------------------------------------------------------------------
  Firmware ESP32: v2        Servidor web: v2        Actualizado: noviembre 2026
==============================================================================

ÍNDICE
  1.  Qué es este proyecto
  2.  Cómo funciona (vista general)
  3.  Qué hay en esta carpeta
  4.  Hardware: componentes, canales y conexiones
  5.  Mudar el proyecto a otra laptop (paso a paso)
  6.  Uso diario
  7.  La interfaz web
  8.  Calibraciones (límites, HOME, gemelo y cámara)
  9.  Firmware del ESP32
  10. Servidor web (Python)
  11. Visión artificial
  12. Gemelo digital 3D
  13. Solución de problemas
  14. Estado actual y pendientes
  15. Próximos pasos
  16. Licencias de terceros


==============================================================================
1. QUÉ ES ESTE PROYECTO
==============================================================================
Brazo robótico de 6 articulaciones movido por 7 servos (los dos del hombro
trabajan juntos). Se controla desde una página web que corre en la laptop y
que se puede abrir también desde el celular.

  - Un ESP32 recibe las órdenes por USB y mueve los servos a través de un
    driver PCA9685, con arranques y frenados suaves (perfil trapezoidal).
  - Un servidor en Python (Flask) muestra la página, guarda poses y
    secuencias, enseña un gemelo digital 3D del brazo y procesa la cámara.
  - La cámara Logitech Brio 100 detecta cubos por color y mide su tamaño
    (5 o 7 cm).


==============================================================================
2. CÓMO FUNCIONA (VISTA GENERAL)
==============================================================================

  [ Navegador: laptop o celular ]
        |   HTTP: la página y las órdenes (mover, HOME, STOP, poses...)
        |   SSE : estado en vivo (posición, ESP32, cámara)
        |   MJPEG: video de la cámara con las detecciones
        v
  [ Servidor Flask  servidor_web/app.py ] <--- vision.py <--- [ Cámara USB ]
        |
        |   USB-Serial a 115200 baudios, hasta 50 órdenes por segundo
        v
  [ ESP32 DevKit  firmware_esp32/src/main.cpp ]
        |
        |   I2C (SDA = GPIO21, SCL = GPIO22), dirección 0x40
        v
  [ PCA9685: genera los pulsos PWM de 50 Hz ]
        |
        |   canales 0 a 6
        v
  [ 7 servos = 6 articulaciones ]

Flujo de una orden:
  1. Mueves una barra en la página.
  2. El navegador manda el ángulo al servidor (solo una petición a la vez y
     siempre con el valor más nuevo, para que no se acumule retraso).
  3. El servidor lo manda al ESP32 como texto, por ejemplo  "J2 120".
  4. El ESP32 recorta el ángulo a los límites guardados en su memoria y
     mueve el servo con un perfil trapezoidal (acelera, va a velocidad
     constante y frena).
  5. Mientras se mueve, el ESP32 reporta su posición 20 veces por segundo
     ("A ..."). El servidor la reenvía a la página y el gemelo 3D la copia.

Ángulo a pulso (lo calcula el firmware):
  pulso_us = 500 + (ángulo / 180) x 2000      ->   0° = 500 us, 180° = 2500 us

Importante: los servos no tienen sensor que el ESP32 pueda leer. La
"posición" que ves en la página y en el gemelo es la posición que el ESP32
le está pidiendo al servo, no una medición real.


==============================================================================
3. QUÉ HAY EN ESTA CARPETA
==============================================================================

brazo_robotico\
|
|-- readme.txt                    Este archivo.
|-- requerimientos.txt            Qué instalar en una laptop nueva (VS Code,
|                                 Python, drivers, librerías y versiones).
|-- preparar_mudanza.bat          Crea el Python portátil y el .zip para
|                                 llevar el proyecto a otra laptop (sec. 5).
|-- python\                       (Lo crea preparar_mudanza.bat.) Python 3.12
|                                 portátil con Flask, pyserial y OpenCV ya
|                                 instalados. Si existe, el proyecto corre
|                                 sin instalar Python en la laptop.
|
|-- firmware_esp32\               Programa del ESP32 (proyecto de PlatformIO)
|   |-- platformio.ini            Placa esp32dev, monitor a 115200 y la
|   |                             librería Adafruit PWM Servo Driver.
|   |-- src\main.cpp              Todo el firmware: protocolo, límites,
|   |                             HOME, memoria y perfil de movimiento.
|   |-- .pio\                     (Se genera solo al compilar. No hace falta
|   |                             copiarlo; pesa mucho.)
|   |-- .vscode\                  (Lo genera PlatformIO. Opcional.)
|
|-- servidor_web\                 Servidor y página web (Python)
    |-- arrancar_servidor.bat     DOBLE CLIC AQUÍ para arrancar todo:
    |                             instala lo que falte, abre el servidor y
    |                             el navegador en http://localhost:5000
    |-- app.py                    Servidor Flask: conexión con el ESP32,
    |                             página, poses, secuencias, gemelo, cámara.
    |-- vision.py                 Visión artificial (OpenCV): cámara,
    |                             detección por color, medida en cm, video.
    |-- simulador.py              ESP32 simulado: si no hay ESP32 conectado,
    |                             la página funciona igual para pruebas.
    |-- requirements.txt          Librerías de Python: flask, pyserial,
    |                             opencv-python.
    |
    |-- poses.json        (*)     TUS poses y secuencias guardadas.
    |-- gemelo.json       (*)     TU calibración del gemelo 3D.
    |-- vision.json       (*)     TUS ajustes de cámara (se crea la primera
    |                             vez que cambias algo en "Ajustes de
    |                             visión"; si no existe, es normal).
    |
    |-- templates\index.html      Estructura de la página.
    |-- static\
        |-- app.js                Lógica de la página (barras, botones,
        |                         poses, secuencias, cámara, calibración).
        |-- estilos.css           Diseño (se adapta a laptop y celular).
        |-- gemelo.js             Gemelo digital: carga el modelo 3D y lo
        |                         mueve con los ángulos del ESP32.
        |-- modelo\
        |   |-- brazo_articulado.glb   Modelo 3D del brazo (8 MB).
        |   |-- arm-controller.js      Mueve las piezas del modelo.
        |   |-- robot_manifest.json    Medidas, piezas y ejes del modelo.
        |-- vendor\three\
            |-- three-urumagod.module.js  Librería Three.js (3D) guardada
            |                             localmente: funciona sin internet.
            |-- LICENSE.txt                Licencia MIT de Three.js.

(*) = archivos con TUS DATOS. Son los más importantes al mudar el proyecto.
      Los límites y el HOME NO están aquí: viven en la memoria del ESP32.


==============================================================================
4. HARDWARE: COMPONENTES, CANALES Y CONEXIONES
==============================================================================

4.1 Componentes
  - ESP32 DevKit (esp32dev), conectado a la laptop por USB (datos y su
    propia alimentación).
  - Driver PCA9685 de 16 canales (I2C, dirección 0x40).
  - 4 servos DS3225 (25 kg·cm): base, hombro A, hombro B y codo.
  - 3 servos MG90S (2.2 kg·cm): muñeca, giro de pinza y pinza.
  - Fuente de laboratorio regulable para los servos (hoy 5.5 V / 5 A).
  - Cámara Logitech Brio 100 (USB).

4.2 Articulaciones, canales y valores de fábrica

  Art.  Nombre en la página   Servo(s)          Canal PCA9685   HOME fábrica
  ----  --------------------  ----------------  --------------  ------------
  J0    Base (giro)           Motor 1  DS3225   0               95°
  J1    Hombro                Motores 2 + 3     1 y 2           38°
                              DS3225 (x2)       (el canal 2 va
                                                en espejo)
  J2    Codo                  Motor 4  DS3225   3               155°
  J3    Muñeca                Motor 5  MG90S    4               95°
  J4    Giro de pinza         Motor 6  MG90S    5               113°
  J5    Pinza                 Motor 7  MG90S    6               90°

  - Límites de fábrica de todas: 9° a 171° (90 % del recorrido).
  - Hombro: M2 y M3 siempre reciben el mismo ángulo; M3 en espejo:
        ángulo_M3 = 180 - ángulo_M2
  - Los límites y el HOME reales se calibran desde la página y se guardan
    en la memoria del ESP32 (sección 8).

4.3 Conexiones

  Desde                      Hacia                    Nota
  -------------------------  -----------------------  ----------------------
  ESP32  3V3                 PCA9685  VCC             Lógica del PCA9685
  ESP32  GND                 PCA9685  GND             Tierra común
  ESP32  GPIO21              PCA9685  SDA             I2C datos
  ESP32  GPIO22              PCA9685  SCL             I2C reloj
  Fuente (+)  5.5 a 6.0 V    PCA9685  bornera V+      Potencia de servos
  Fuente (-)                 PCA9685  bornera GND     Potencia de servos
  ESP32  USB                 Laptop                   Datos + alimentación
  Servo canal 0..6           Pines PWM del PCA9685    Naranja = señal,
                                                      rojo = V+,
                                                      café = GND

  Reglas de seguridad:
  - Nunca alimentes los servos desde el ESP32 (ni de 3V3 ni de 5V/VIN).
  - Las tierras deben estar unidas (ESP32, PCA9685 y fuente).
  - Recomendado: capacitor electrolítico de 1000 uF / 16 V en la bornera
    V+ / GND del PCA9685, para aguantar los picos de corriente.

4.4 Alimentación
  - DS3225: 4.8 a 6.8 V.  MG90S: 4.8 a 6.0 V.  Por eso el máximo seguro
    para todo el brazo es 6.0 V.
  - Recomendado: 6.0 V. Si el LED "CC" de la fuente se enciende al mover,
    la fuente está limitando corriente: el voltaje cae y los servos
    pierden fuerza o el ESP32 se reinicia.


==============================================================================
5. MUDAR EL PROYECTO A OTRA LAPTOP (PASO A PASO)
==============================================================================

Hay dos formas. La A es la recomendada: no instalas nada en la laptop nueva.

5.1 Forma A (recomendada): proyecto portátil en un .zip
  En la laptop VIEJA (donde ya funciona), una sola vez y con internet:
    1. Doble clic en  preparar_mudanza.bat  (carpeta principal).
       - Descarga Python 3.12.10 portátil oficial (python.org) en la
         carpeta  python\  del proyecto.
       - Le instala Flask, pyserial y OpenCV adentro de esa carpeta.
       - Copia el runtime de Visual C++ que usa OpenCV.
       - Prueba que todo carga.
       - Crea  brazo_robotico_portable.zip  junto a la carpeta del
         proyecto, sin las carpetas temporales (.pio y __pycache__).
       - Todo lo que hizo queda escrito en  preparar_mudanza.log
    2. Copia ese .zip a la laptop nueva (USB, Drive, etc.).
  En la laptop NUEVA:
    3. Clic derecho en el .zip > "Extraer todo".
    4. Doble clic en  servidor_web\arrancar_servidor.bat
       Detecta la carpeta python\ y arranca directo: sin instalar Python
       y sin internet.
  Lo único que quizá tengas que instalar es el driver USB del ESP32
  (punto 5.3 b).

  Por qué funciona: el Python "embebido" (embeddable) es un Python
  completo dentro de una carpeta, que no depende del registro de Windows
  ni de lo que haya instalado en la laptop. El archivo
  python\python312._pth le indica dónde están sus librerías y la carpeta
  servidor_web.

  Para correr el código desde VS Code con ese Python: abre la carpeta
  brazo_robotico (File > Open Folder) y elige el intérprete una vez:
  Ctrl + Shift + P > "Python: Select Interpreter" > "Enter interpreter
  path..." > busca  python\python.exe  dentro del proyecto.

  Limitación: el Python portátil no trae pip. Si después quieres agregar
  librerías grandes (por ejemplo YOLO con la GPU), instala Python normal
  en esa laptop (Forma B y requerimientos.txt).

5.2 Forma B: copiar la carpeta e instalar Python
  Copia la carpeta "brazo_robotico" completa. Lo esencial:
    - firmware_esp32\platformio.ini y firmware_esp32\src\
    - todo servidor_web\  (incluye poses.json, gemelo.json y vision.json)
  Puedes NO copiar (se regeneran solos):
    - firmware_esp32\.pio\          (compilación, cientos de MB)
    - servidor_web\__pycache__\     (archivos temporales de Python)
  Luego instala lo del punto 5.3. La lista completa con versiones está en
  requerimientos.txt.

  En las dos formas: no necesitas copiar nada del ESP32. El firmware, los
  límites y el HOME ya están dentro de él y viajan con el brazo.

5.3 Qué instalar en la laptop nueva
  a) SOLO Forma B: Python 3.12 (o 3.10 o más nuevo) desde python.org.
     MUY IMPORTANTE: en la primera pantalla del instalador marca
     "Add python.exe to PATH". Sin eso el archivo .bat no encuentra Python.
     Comprueba en una terminal:   python --version
  b) Driver USB del ESP32 (si Windows no lo reconoce solo):
     - Chip CP2102/CP210x: driver "CP210x" de Silicon Labs.
     - Chip CH340/CH9102: driver "CH340" de WCH.
     El chip viene escrito junto al conector USB de la placa.
  c) Solo si vas a modificar el firmware: VS Code + extensión
     "PlatformIO IDE". Para usar el brazo no hace falta.

5.4 Primer arranque en la laptop nueva
  1. Conecta el ESP32 por USB con un cable de DATOS (algunos cables solo
     cargan).
  2. Conecta la cámara.
  3. Doble clic en  servidor_web\arrancar_servidor.bat
     Forma A: arranca directo. Forma B: la primera vez descarga Flask,
     pyserial y OpenCV (necesita internet, unos minutos).
  4. Si Windows pregunta por el Firewall: permite Python en "Redes
     privadas" (si no, el celular no podrá entrar).
  5. Se abre http://localhost:5000. Revisa los indicadores de arriba:
     "Servidor" y "ESP32" en verde. La terminal debe mostrar algo como:
        [ESP32] Puerto COM3 abierto, esperando al ESP32...
     (el número de COM puede cambiar en la otra laptop; se busca solo).
  6. Prueba: botón HOME, una barra a la vez y STOP (tecla Esc).
  7. En el panel de cámara: "Buscar cámaras", elige la Brio 100 y
     "Encender". Si cambió la altura o posición de la cámara, vuelve a
     calibrar px/cm (sección 8.4).


==============================================================================
6. USO DIARIO
==============================================================================
  Encender:
    1. Fuente de los servos encendida (6.0 V recomendado).
    2. ESP32 conectado por USB.
    3. Doble clic en servidor_web\arrancar_servidor.bat
  Desde el celular:
    Misma red WiFi que la laptop. Abre la dirección que la terminal muestra
    en "En el celular", por ejemplo  http://192.168.1.70:5000
  Apagar:
    1. Presiona HOME y espera a que llegue.
    2. Cierra la ventana negra del servidor (o Ctrl + C).
    3. Apaga la fuente.
  Por qué HOME antes de apagar: al encender, el ESP32 no sabe dónde quedó
  el brazo y lo manda a HOME de golpe. Si ya estaba en HOME, no se mueve.

  Notas:
  - Al abrir el puerto USB el ESP32 se reinicia; el servidor espera 2 s.
  - Si no hay ESP32, la página usa un ESP32 SIMULADO (sirve para probar)
    y lo sigue buscando cada 2 segundos.
  - Solo un programa puede usar el puerto del ESP32 a la vez. Cierra el
    Monitor Serial de PlatformIO o de Arduino IDE antes de arrancar.


==============================================================================
7. LA INTERFAZ WEB
==============================================================================
  Barra superior
    Indicadores: Servidor, ESP32, Cámara y latencia (ms).
    STOP: congela todo donde está (no suelta los servos, para que el brazo
    no caiga). Atajo: tecla Esc.

  Control de articulaciones
    Una tarjeta compacta por articulación (el hombro M2 + M3 es una sola
    barra). El servo se mueve mientras arrastras la barra.
    HOME: va a la posición inicial guardada en el ESP32.
    Velocidad general: 25 %, 50 % o 100 %.

  Gemelo digital
    Modelo 3D del brazo que copia la posición pedida al ESP32.
    Ver brazo / Ver pinza: cambia la vista. Arrastra para girar, rueda o
    pellizco para zoom, clic derecho para desplazar.
    Muestra las coordenadas de la punta de la pinza.
    "Calibrar": ceros y sentidos de giro (sección 8.3).

  Cámara · visión artificial
    Elegir cámara, encender, video con los cubos marcados (rectángulo
    girado y centro) y la lista de detecciones (color, tamaño y posición).
    "Ajustes de visión": colores a buscar, exposición y calibración px/cm.

  Poses
    Guarda la posición actual con un nombre. "Ir" mueve el brazo a esa pose.

  Secuencias
    Lista de pasos (poses) que se reproducen en orden (teach and play).
    "Repetir" la deja en ciclo. STOP la detiene.

  Calibración de límites y HOME
    Panel plegable al final de la página (sección 8).


==============================================================================
8. CALIBRACIONES
==============================================================================

8.1 Límites de cada articulación (se guardan en el ESP32)
  1. Abre "Calibración de límites y HOME" > "Entrar a modo calibración".
     Las barras se abren de 0° a 180° y la velocidad baja a 25 %.
     La zona roja de cada barra es lo que hoy queda fuera de su límite.
  2. Mueve la articulación con  -1 / +1  hasta que toque algo o el servo
     empiece a zumbar. Regresa de 3 a 5 grados.
  3. "Fijar mín" o "Fijar máx" en esa tarjeta.
  Regla del firmware: el límite debe estar entre 0° y 180° y dejar al
  menos 10° de recorrido.

8.2 HOME (se guarda en el ESP32)
  Lleva el brazo a su posición de descanso y toca
  "Guardar posición actual como HOME".
  "Restaurar valores de fábrica" regresa límites 9° a 171° y el HOME de
  la tabla 4.2.

8.3 Gemelo digital (se guarda en servidor_web\gemelo.json)
  Para cada articulación:
     ángulo_modelo = sentido x (ángulo_servo - cero)
     cero    = ángulo del servo cuando el brazo real está igual que el
               modelo 3D.
     sentido = +1 o -1 (Normal o Invertido) según hacia dónde gira.
  Pinza: ángulo del servo con la pinza totalmente abierta (85 mm) y
  hacia qué lado cierra. Apertura que dibuja el modelo:
     apertura_mm = 85 - 18 x radianes(sentido_cierre x (ángulo - abierta))
     limitada entre 45 y 85 mm (piñón de 18 dientes, radio de paso 9 mm).
  Pasos (también vienen escritos en la página):
     1. "Calibrar" > activa "Mostrar postura del modelo".
     2. Deja el brazo real igual que el modelo.
     3. "Usar posición actual como cero".
     4. Desactiva la postura, mueve cada barra y elige Normal o Invertido.
     5. "Guardar".
  Si una articulación no tiene cero y sentido, el gemelo la deja quieta
  y lo avisa. Nada se inventa.

8.4 Cámara: tamaño real (se guarda en servidor_web\vision.json)
  1. Cámara fija viendo desde arriba (no la muevas después).
  2. Deja UN solo cubo de medida conocida a la vista.
  3. Escribe su lado (ej. 7 cm) > "Calibrar con el cubo a la vista".
  Se calcula:   px_por_cm = lado_px / lado_cm
  y luego cada cubo se mide como   lado_cm = lado_px / px_por_cm
  Si mueves o cambias la altura de la cámara, repite este paso.


==============================================================================
9. FIRMWARE DEL ESP32  (firmware_esp32\src\main.cpp)
==============================================================================

9.1 Qué hace
  - Lazo de control a 50 Hz (cada 20 ms).
  - Perfil trapezoidal por articulación: velocidad y aceleración máximas.
    Para frenar justo en el objetivo usa la velocidad de frenado discreta:
        v = a x ( raíz(dt²/4 + 2|e|/a) - dt/2 )
    donde e = distancia que falta, a = aceleración máxima, dt = 0.02 s.
  - Velocidad y aceleración máximas (al 100 %):
        Base 180 °/s y 500 °/s²   |  Hombro 150 °/s y 400 °/s²
        Codo 180 °/s y 500 °/s²   |  Muñeca, giro y pinza 300 °/s y 1500 °/s²
  - Recorta cualquier orden a los límites guardados (aunque la página
    mande otra cosa).
  - Guarda límites y HOME en la memoria NVS (librería Preferences): se
    conservan al apagar y también al volver a subir el firmware (solo se
    borran con "Erase Flash" o con el botón de valores de fábrica).
  - Al arrancar imprime  "LISTO v2 cfg=memoria"  (o  cfg=fabrica  si aún
    no hay nada guardado).

9.2 Protocolo serie (115200 baudios, una orden por línea)
  Laptop -> ESP32
    J<i> <g>          mover la articulación i (0 a 5) a g grados
    H                 ir a HOME
    HG                guardar la posición actual como HOME
    S                 STOP (congela, no suelta los servos)
    V <p>             velocidad general en % (10 a 100)
    X <0|1>           modo calibración (0° a 180°, velocidad <= 25 %)
    L<i> <min> <max>  nuevos límites de la articulación i
    R                 restaurar límites y HOME de fábrica
    ?                 pedir objetivos y posición
    C                 pedir configuración
  ESP32 -> Laptop
    LISTO v2 cfg=...  arranque
    P o0 .. o5        objetivos de cada articulación
    A a0 .. a5 m      posición actual (m = 1 si se está moviendo),
                      20 veces por segundo mientras hay movimiento
    C n0 x0 h0 .. n5 x5 h5   mínimo, máximo y HOME de cada articulación
    V p  /  X c       confirmaciones
    E texto           error (ej. "E no se encontro el PCA9685")
  Puedes probarlo a mano en el Monitor Serial de PlatformIO (115200),
  con el servidor CERRADO. Ejemplo:  J0 120   y luego   H

9.3 Cómo subir el firmware (solo si lo cambias)
  1. Cierra el servidor (el puerto USB debe estar libre).
  2. VS Code > File > Open Folder > elige la carpeta  firmware_esp32
  3. Barra azul de abajo: palomita (Build) y flecha (Upload).
     La primera vez PlatformIO descarga la plataforma espressif32 y la
     librería del PCA9685 (necesita internet).
  4. Si se queda en "Connecting...", mantén presionado el botón BOOT del
     ESP32 hasta que empiece a escribir.
  5. Monitor Serial (icono de enchufe) a 115200: debe salir "LISTO v2".


==============================================================================
10. SERVIDOR WEB  (servidor_web\app.py)
==============================================================================

10.1 Ajustes al inicio de app.py
  PUERTO_SERIAL = "AUTO"   Busca solo el ESP32 (chips CP210x, CH340,
                           CH9102...). Si falla, ponlo fijo, ej. "COM5".
                           (Mira el número en Administrador de dispositivos
                           > Puertos COM y LPT.)
  BAUDIOS = 115200         Igual que el firmware. No lo cambies.
  PUERTO_WEB = 5000        Puerto de la página.

10.2 Rutas principales (para referencia)
  GET  /                         la página
  GET  /api/config               articulaciones, límites, HOME, gemelo
  GET  /api/estado               estado actual
  GET  /api/eventos              estado en vivo (SSE)
  POST /api/mover                mover una articulación
  POST /api/home  |  /api/stop  |  /api/velocidad
  POST /api/calibracion          entrar o salir de modo calibración
  POST /api/limite               fijar mín o máx
  POST /api/home/guardar         guardar HOME
  POST /api/fabrica              valores de fábrica
  GET/POST/DELETE /api/poses     poses ( /api/poses/<id>/ir  para ir )
  POST/DELETE /api/secuencias    secuencias (reproducir y detener)
  GET/POST /api/gemelo           calibración del gemelo
  GET  /video                    video MJPEG de la cámara
  GET  /api/vision/camaras       lista de cámaras
  POST /api/vision               ajustes de la cámara
  POST /api/vision/calibrar      calibración px/cm

10.3 Librerías (requirements.txt)
  flask >= 3.0, pyserial >= 3.5, opencv-python >= 4.8
  Instalación manual (si no usas el .bat ni el Python portátil):
     python -m pip install -r requirements.txt
  Con el Python portátil, la lista exacta de versiones instaladas queda en
  python\paquetes_instalados.txt


==============================================================================
11. VISIÓN ARTIFICIAL  (servidor_web\vision.py)
==============================================================================
  Es visión artificial CLÁSICA (reglas con OpenCV), no un modelo de IA
  entrenado.
  Pasos por cada imagen:
    1. Captura 1280 x 720 en su propio hilo (no frena el control).
    2. Copia reducida a 640 px de ancho y suavizado.
    3. Conversión BGR -> HSV (separa el color del brillo).
    4. Filtro por color (inRange): rojo, verde, azul y amarillo.
    5. Limpieza de ruido (apertura y cierre) y búsqueda de contornos.
    6. Rectángulo mínimo (minAreaRect): centro, lado y ángulo del cubo.
    7. Tamaño en cm con px/cm y clasificación a 5 o 7 cm (tolerancia
       ±20 %).
    8. Dibuja los resultados y manda el video a la página (960 px,
       20 imágenes por segundo).
  Ajustes en la página: colores activos, exposición automática o manual
  (-11 oscuro a -1 claro) y calibración px/cm.
  "Imagen de prueba": fuente sintética para probar sin cámara.


==============================================================================
12. GEMELO DIGITAL 3D  (servidor_web\static\gemelo.js)
==============================================================================
  - Modelo: static\modelo\brazo_articulado.glb (pinza de cremalleras).
  - Three.js está guardado localmente: no necesita internet.
  - Recibe los ángulos del ESP32 (telemetría "A") y los convierte con la
    calibración de gemelo.json (sección 8.3).
  - Suaviza el movimiento entre lecturas y solo redibuja cuando algo
    cambia (ahorra procesador).
  - Muestra la posición de la punta de la pinza respecto a la base.


==============================================================================
13. SOLUCIÓN DE PROBLEMAS
==============================================================================

  Problema                         Revisa
  -------------------------------  -------------------------------------------
  "python no se reconoce..."       Usa la Forma A (Python portátil) o
                                   reinstala Python marcando
                                   "Add python.exe to PATH".
  Python portátil: "DLL load       Instala "Microsoft Visual C++
  failed" al cargar OpenCV         Redistributable x64" en esa laptop.
                                   (La página sigue funcionando; solo la
                                   cámara queda apagada.)
  ESP32 en rojo o "simulado"       Cable de datos; driver CP210x o CH340;
                                   Monitor Serial cerrado; fija el COM en
                                   PUERTO_SERIAL (10.1).
  "E no se encontro el PCA9685"    Cables SDA (21), SCL (22), VCC (3V3) y GND.
  El celular no abre la página     Misma red WiFi; Firewall: permitir Python
                                   en redes privadas; usa la IP que muestra
                                   la terminal.
  La cámara no aparece             Cierra otras apps que la usen (Cámara de
                                   Windows, Zoom, Teams); "Buscar cámaras";
                                   cambia de puerto USB.
  Detecta mal los colores          Desactiva colores que no uses; exposición
                                   manual; luz pareja; fondo de otro color.
  Medidas en cm incorrectas        Repite la calibración px/cm (8.4).
  El gemelo 3D no carga            Que exista static\modelo y
                                   static\vendor; recarga con Ctrl + F5.
  Un servo zumba quieto o se       Potenciómetro interno dañado (pasa hoy con
  regresa a mitad de recorrido     la muñeca). Desconéctalo para que no se
                                   caliente y reemplázalo.
  El ESP32 se reinicia o la        Sube a 6.0 V; revisa el LED CC de la
  fuente entra en corto o CC       fuente; tierras comunes; capacitor en V+.
  Cambiaste un servo               Móntalo con el servo en 90°; recalibra
                                   sus límites (8.1) y su cero del gemelo
                                   (8.3).


==============================================================================
14. ESTADO ACTUAL Y PENDIENTES  (noviembre 2026)
==============================================================================
  Funcionando:
    - Firmware v2 en el ESP32; servidor v2 en la laptop (ESP32 en COM3).
    - Interfaz con control, HOME, STOP, velocidad, poses y secuencias.
    - Gemelo 3D integrado y calibrado (gemelo.json del 10 de noviembre
      de 2026).
    - Visión por color con la Brio 100.
  Pendientes:
    - MUÑECA (MG90S, canal 4): su potenciómetro interno está dañado
      (pasando unos 90° se regresa y zumba aunque esté quieto). Cambiar el
      servo. Mientras tanto: máximo de la muñeca en unos 85° o
      desconectarla. Al montar el nuevo: mándalo a 90° antes de poner el
      brazo del servo, y vuelve a capturar su cero en el gemelo.
    - PINZA: el recorrido útil de la cremallera es de unos 127° de servo
      (de 85 a 45 mm). Ajusta sus límites para que no se trabe.
    - FUENTE: subir de 5.5 V a 6.0 V.


==============================================================================
15. PRÓXIMOS PASOS
==============================================================================
  - IA en la cámara (laptop nueva con RTX 5060): modelo YOLO26s-obb de
    Ultralytics, entrenado con fotos propias de los cubos. Da centro y
    ángulo de cada cubo. Plan:
       1. Botón en la página para guardar fotos ya etiquetadas.
       2. Script de entrenamiento en la GPU.
       3. Selector "Color / IA" en el panel de cámara (el detector por
          color se queda como respaldo).
    Nota de instalación: las RTX serie 50 necesitan PyTorch con CUDA 12.8
    o más nuevo. Instala primero
       pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
    y después  pip install ultralytics
  - Banda transportadora con motor NEMA 17 y driver TMC2208.
  - Registro de datos en la nube (Industria 4.0).


==============================================================================
16. LICENCIAS DE TERCEROS
==============================================================================
  - Three.js: licencia MIT (static\vendor\three\LICENSE.txt).
  - Adafruit PWM Servo Driver Library: licencia BSD (la descarga
    PlatformIO).
  - Flask, pyserial y OpenCV: licencias libres (BSD / Apache 2.0).
  - Si en el futuro se usa Ultralytics YOLO: licencia AGPL-3.0. Para
    vender el brazo con ese software incluido se necesita su licencia
    Enterprise o publicar el código.

==============================================================================
  Fin del archivo
==============================================================================
