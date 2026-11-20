# Publicar en GitHub y GitHub Pages

Todos los comandos se ejecutan en la carpeta `brazo_robotico` (la que contiene `docs/`, `firmware_esp32/` y `servidor_web/`).

## 1. Antes de empezar (una sola vez)
1. Instala Git: https://git-scm.com/download/win
2. Crea una cuenta en https://github.com
3. Presenta tu identidad a Git:
   ```bash
   git config --global user.name "Tu Nombre"
   git config --global user.email "tu_correo@ejemplo.com"
   ```
4. En GitHub: **New repository** → nombre `brazo-robotico-con-banda-transportadora` → **Public** (Pages gratis exige repo público en cuentas gratuitas) → **sin** README, .gitignore ni licencia (ya los tienes) → Create.

## 2. Personaliza el enlace del repo
En `docs/assets/js/main.js` ya apunta a tu usuario y repositorio (URUMS-20).

## 3. Commit inicial y enlace con GitHub
```bash
git init -b main
git add .
git status                       # revisa que NO aparezcan python/, .pio/ ni .zip
git commit -m "Commit inicial: brazo robotico, servidor web y documentacion"
git remote add origin https://github.com/URUMS-20/brazo-robotico-con-banda-transportadora.git
git push -u origin main
```
GitHub pedirá iniciar sesión en el navegador la primera vez.

## 4. Activar GitHub Pages
1. Repositorio → **Settings** → **Pages**.
2. **Source:** *Deploy from a branch*.
3. **Branch:** `main` · carpeta **`/docs`** → **Save**.
4. En 1 a 3 minutos aparece la URL: `https://urums-20.github.io/brazo-robotico-con-banda-transportadora/`
5. Ábrela en el celular y revisa las 6 páginas y el visor 3D.

## 5. Actualizar después
```bash
git add .
git commit -m "Describe el cambio"
git push
```

## 6. Tag NFC / código QR
- Escribe en el tag NFC la URL de la página (registro tipo *URL/URI*) con una app como "NFC Tools".
- Haz también un QR de la misma URL como respaldo (los iPhone antiguos o teléfonos sin NFC lo necesitan).
- Prueba el tag con un teléfono Android y uno iPhone antes de pegarlo.
