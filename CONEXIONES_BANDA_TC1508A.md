# Banda transportadora con TC1508A

Actualización del 11 de noviembre de 2026 para ESP32 DevKit (esp32dev).

## Conexiones de un motor DC

Usa el primer puente del módulo. Los nombres y la posición física de las
terminales cambian entre placas: identifica las etiquetas de tu módulo.
IN1/IN2 y OUT1/OUT2 son nombres alternativos frecuentes; deben corresponder
a INA/INB y OUTA/OUTB del mismo puente.

| Desde | Hacia |
|---|---|
| ESP32 GPIO25 | INA / IN1 del puente H |
| ESP32 GPIO26 | INB / IN2 del mismo puente H |
| ESP32 GND | GND del módulo y negativo de la fuente del motor |
| Positivo de la fuente externa del motor | VCC / VDD / + del módulo |
| OUTA / OUT1 | Un cable del motor DC |
| OUTB / OUT2 | El otro cable del motor DC |
| ESP32 USB | Laptop (alimentación del ESP32 y comunicación) |

El PCA9685 sigue conectado a GPIO21 (SDA) y GPIO22 (SCL). La banda utiliza
directamente los GPIO25/26; no se conecta a los canales de los servos.
Si no usas el segundo puente, sus entradas INC/IND pueden quedar conectadas
a GND y sus salidas OUTC/OUTD quedan libres. No unas las salidas de ambos puentes.

## Alimentación

- Usa una fuente externa adecuada al voltaje nominal y a la corriente de
  arranque/bloqueo de tu motor. No alimentes el motor desde 3V3 ni desde el USB
  del ESP32.
- La ficha del TC1508A indica 2.4–7.2 V de alimentación y 7.2 V como máximo
  absoluto. **No conectes 12 V.** Trabaja por debajo del máximo y no excedas
  el voltaje admitido por tu motor. Para control directo de 3.3 V, la alimentación
  del módulo debe ser al menos 3.3 V: la entrada no debe superar VCC.
- El chip especifica hasta 1.8 A continuos y 2.5 A de pico por puente; el módulo
  real puede admitir menos según su disipación. Si el motor supera su capacidad
  al arrancar o atascarse, se necesita otro controlador.
- Une las tierras del ESP32, puente y fuente. Conecta con la alimentación apagada.
- Recomendación para evitar movimiento con entradas flotantes durante el arranque:
  una resistencia de 10 kΩ desde INA a GND y otra desde INB a GND.

## Cargar y usar la actualización

1. Cierra el servidor y cualquier monitor serie.
2. Abre `firmware_esp32` en PlatformIO y sube el firmware al ESP32. Esta actualización
   añade control del motor; cambiar solo la página web no basta. Una subida normal
   sin borrar la flash conserva los límites y HOME guardados.
3. Ejecuta `servidor_web/arrancar_servidor.bat` y recarga la página con Ctrl+F5.
4. En **Banda transportadora**, elige velocidad y sentido; pulsa **Encender**.
   La velocidad inicial seleccionada es 30 %, pero la salida arranca apagada.
5. Cambia la barra durante la marcha para regularla. 0 % la apaga. Para invertir
   el giro, primero pulsa **Detener banda**, espera la parada mecánica del motor
   y después selecciona el otro sentido.
6. **STOP / Esc** detiene las órdenes del brazo y quita potencia al motor.

Si el sentido llamado Adelante resulta invertido respecto a tu montaje, usa
Reversa o intercambia los dos cables del motor con la alimentación apagada.

El porcentaje controla PWM (potencia relativa), no una velocidad medida en
cm/s o RPM. Sin encoder, el movimiento depende de la carga y la alimentación.
A porcentajes bajos algunos motores no arrancan: aumenta el ajuste gradualmente.

## Comportamiento ante pérdidas de comunicación

- El motor inicia apagado y no recuerda un estado de marcha tras reiniciar.
- El navegador renueva un permiso de marcha cada 400 ms. Sin ese permiso,
  el servidor apaga la banda en aproximadamente 1.5 s.
- El firmware corta la potencia si no recibe renovación USB durante 2 s.
- Tras desconexión o STOP, hay que volver a pulsar Encender.
- La parada usa INA=INB=0 (salidas en alta impedancia). El motor queda en rueda
  libre y puede tardar en detenerse; este botón no sustituye un paro físico.
- Con firmware anterior, el panel muestra **Actualizar ESP32** y bloquea el inicio.
- Sin ESP32 se puede probar todo en simulación, sin accionar hardware.

## Detalles de implementación

PWM de 1 kHz, 8 bits, canales LEDC 0/1. Estos canales pertenecen al ESP32;
son independientes de los canales 0–6 del PCA9685. Firmware compatible con las
API LEDC de Arduino-ESP32 2.x y 3.x.

Protocolo USB: `B?` consulta; `B 0` apaga; `B 40` adelante al 40 %;
`B -40` reversa al 40 %. La respuesta `B <porcentaje>` confirma la salida
aplicada. `S` también apaga la banda. El latido de consulta `B?` no renueva marcha.

La velocidad de la banda es independiente de la velocidad general del brazo.
Las poses y secuencias existentes conservan sus seis ángulos y no arrancan la banda.

## Referencias

- [Ficha TC1508A: alimentación, entradas, corriente y tabla lógica](https://www.chipsourcetek.com/DataSheet/TC1508A.pdf).
- [Producto TC1508A de ChipSourceTek](https://en.chipsourcetek.com/Driver-Chip/2636.html).
- [Cambios de LEDC entre Arduino-ESP32 2.x y 3.x](https://docs.espressif.com/projects/arduino-esp32/en/latest/migration_guides/2.x_to_3.0.html#ledc).
