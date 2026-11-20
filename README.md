# Brazo Robótico · The Genesis

Brazo de 6 articulaciones (7 servos) controlado desde una página web, con gemelo digital 3D,
visión artificial por color y banda transportadora. ESP32 + PCA9685 + Flask + OpenCV.

📖 **Documentación en línea:** https://urums-20.github.io/brazo-robotico-con-banda-transportadora/

## Contenido
| Carpeta | Qué es |
|---|---|
| `firmware_esp32/` | Firmware del ESP32 (PlatformIO) |
| `servidor_web/` | Servidor Flask, interfaz web, visión y gemelo 3D |
| `docs/` | Sitio de documentación (GitHub Pages) |
| `readme.txt`, `requerimientos.txt` | Documentación completa y requisitos |

## Arranque rápido
```bash
cd servidor_web
python -m pip install -r requirements.txt
python app.py        # abre http://localhost:5000
```
Sin ESP32 conectado se usa un ESP32 simulado.
