# Cámara del teléfono en el panel

## Opción integrada: Android + IP Webcam por WiFi

1. Instala [IP Webcam desde Google Play](https://play.google.com/store/apps/details?id=com.pas.webcam&hl=es)
   en el teléfono. Es la app con identificador `com.pas.webcam`.
2. Conecta la laptop y el teléfono a la misma red WiFi. En la app permite el
   acceso a la cámara e inicia su servidor. No hace falta activar servicios en la nube.
3. La app muestra una dirección, por ejemplo `http://192.168.1.50:8080`.
   La dirección del ejemplo no es la de tu teléfono: usa la que te muestre tu app.
4. En el servidor del brazo abre **Conectar teléfono por WiFi**. Pega esa dirección
   y pulsa **Conectar teléfono**. El panel selecciona **Mi teléfono (WiFi / IP Webcam)**.
5. También puedes elegir esa opción desde la lista de cámaras y pulsar Encender.
   La dirección queda guardada en `servidor_web/vision.json`.
6. Selecciona la cámara trasera y ajusta orientación, resolución y exposición desde
   la app. Después vuelve a calibrar px/cm con el cubo conocido en el panel.

Una dirección sin ruta se transforma automáticamente en `/video`, la ruta de
video de IP Webcam. Si tu app proporciona una URL MJPEG completa, pégala tal cual.
La aplicación debe ofrecer video HTTP(S) sin autenticación para esta integración;
las URLs con usuario/contraseña o enlaces a una página web de control se rechazan
o no producirán video. No abras puertos del router: la conexión prevista es local.

La cámara del teléfono pasa por el mismo detector de colores y tamaños que la USB.
Cambiar de cámara reinicia la escala px/cm porque cambia la geometría de la imagen.
Si la app se desconecta, el servidor informa el error e intenta recuperar la fuente.
Al cambiar de red, la dirección del teléfono puede cambiar y debes actualizarla.

## Alternativa: Iriun Webcam

Ya hay un cliente Iriun Webcam en esta laptop. Con su app de teléfono y el cliente
de Windows abiertos, el teléfono aparece como una cámara virtual del sistema.
Pulsa **Buscar cámaras**, selecciona la entrada que corresponda y comprueba la
imagen. OpenCV enumera los dispositivos como Cámara 0, Cámara 1, etc.; el número
de la cámara virtual depende del equipo y no se asigna automáticamente por nombre.

Descarga oficial y enlaces de Iriun: [iriun.com](https://iriun.com/).
La opción llamada **Mi teléfono (WiFi / IP Webcam)** corresponde al video por URL,
no al controlador virtual de Iriun.

## Puesta en marcha

Reinicia `servidor_web/arrancar_servidor.bat` después de aplicar la actualización
y recarga la página con Ctrl+F5. No hace falta modificar el firmware del ESP32
para cambiar la cámara; el firmware nuevo sí hace falta para el motor de la banda.

Esta entrega prepara el servidor y la selección de cámara. La instalación de la
app y la autorización de la cámara deben hacerse en el teléfono; no se ha probado
el enlace con un teléfono físico.

Referencias: [IP Webcam en Google Play](https://play.google.com/store/apps/details?id=com.pas.webcam&hl=es),
[Iriun](https://iriun.com/) y [captura de red y tiempos de espera de OpenCV](https://docs.opencv.org/4.10.0/d4/d15/group__videoio__flags__base.html).
