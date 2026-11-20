@echo off
setlocal
rem ==================================================================
rem  BRAZO ROBOTICO (The Genesis) - preparar la mudanza a otra laptop
rem
rem  Ejecutalo UNA VEZ en la laptop donde YA funciona el proyecto
rem  (necesita internet y el Python que ya tienes instalado).
rem
rem   1) Descarga Python 3.12 portatil (oficial de python.org) en la
rem      carpeta  python\  del proyecto.
rem   2) Le instala Flask, pyserial y OpenCV dentro de esa carpeta.
rem   3) Copia el runtime de Visual C++ que usa OpenCV.
rem   4) Prueba que todo carga bien.
rem   5) Crea  brazo_robotico_portable.zip  junto a la carpeta del
rem      proyecto (sin .pio ni __pycache__), listo para copiar.
rem
rem  Todo lo que pasa se guarda en  preparar_mudanza.log
rem
rem  En la otra laptop: descomprime el .zip y da doble clic en
rem  servidor_web\arrancar_servidor.bat  (no hay que instalar Python).
rem ==================================================================
cd /d "%~dp0"

set "VERSION=3.12.10"
set "ZIP_PY=python-%VERSION%-embed-amd64.zip"
set "TAMANO_PY=11133606"
set "URL_PY=https://www.python.org/ftp/python/%VERSION%/%ZIP_PY%"
set "DIR_PY=%~dp0python"
set "SITE=%DIR_PY%\Lib\site-packages"
set "DESCARGA=%TEMP%\%ZIP_PY%"
set "LOG=%~dp0preparar_mudanza.log"
for %%I in ("%~dp0.") do set "NOMBRE=%%~nxI"
for %%I in ("%~dp0..") do set "PADRE=%%~fI"
set "DESTINO=%PADRE%\%NOMBRE%_portable.zip"

if /i "%~1"=="_trabajo" goto :trabajo

rem ================= Ventana visible =================
title Brazo Robotico - preparar mudanza
echo ==================================================================
echo  Preparando el proyecto para llevarlo a otra laptop
echo  Tarda de 2 a 5 minutos (descarga unos 70 MB). No cierres esta ventana.
echo ==================================================================
call "%~f0" _trabajo > "%LOG%" 2>&1
set "RESULTADO=%errorlevel%"
type "%LOG%"
echo.
if not "%RESULTADO%"=="0" goto :fin
if exist "%DESTINO%" explorer /select,"%DESTINO%"
:fin
echo Esta ventana se cierra sola en 2 minutos (o presiona una tecla).
timeout /t 120 >nul
exit /b %RESULTADO%

rem ================= Trabajo (salida al .log) =================
:trabajo
echo Inicio: %date% %time%
where python >nul 2>nul
if errorlevel 1 goto :sin_python

rem ---------- 1) Python portatil ----------
echo [1/5] Descargando Python %VERSION% portatil (unos 11 MB)...
if exist "%DIR_PY%" rmdir /s /q "%DIR_PY%"
call :descargar
if errorlevel 1 goto :error_descarga
mkdir "%DIR_PY%"
tar -xf "%DESCARGA%" -C "%DIR_PY%"
if errorlevel 1 goto :error_extraer
if not exist "%DIR_PY%\python.exe" goto :error_extraer
del /q "%DESCARGA%" >nul 2>nul

rem  El archivo ._pth le dice al Python portatil donde buscar modulos:
rem   - su libreria estandar, su carpeta y Lib\site-packages
rem   - ..\servidor_web  para que app.py encuentre vision.py y simulador.py
> "%DIR_PY%\python312._pth" (
  echo python312.zip
  echo .
  echo Lib\site-packages
  echo ..\servidor_web
  echo import site
)
echo       OK  Python portatil en la carpeta python

rem ---------- 2) Librerias ----------
echo [2/5] Descargando Flask, pyserial y OpenCV para el Python portatil...
python -m pip install --target "%SITE%" --platform win_amd64 --python-version 3.12 --only-binary=:all: -r servidor_web\requirements.txt --disable-pip-version-check --no-warn-script-location --progress-bar off
if errorlevel 1 goto :error_pip
python -m pip freeze --path "%SITE%" > "%DIR_PY%\paquetes_instalados.txt" 2>nul

rem ---------- 3) Runtime de Visual C++ (lo necesita OpenCV) ----------
echo [3/5] Copiando el runtime de Visual C++...
for %%D in (msvcp140.dll msvcp140_1.dll msvcp140_2.dll vcruntime140.dll vcruntime140_1.dll concrt140.dll) do (
  if exist "%SystemRoot%\System32\%%D" if not exist "%DIR_PY%\%%D" copy /y "%SystemRoot%\System32\%%D" "%DIR_PY%\" >nul
)

rem ---------- 4) Prueba ----------
echo [4/5] Probando el Python portatil...
"%DIR_PY%\python.exe" -c "import importlib.metadata as m, cv2, serial, flask, vision, simulador; print('      OK  flask', m.version('flask'), '| pyserial', m.version('pyserial'), '| opencv', cv2.__version__)"
if errorlevel 1 goto :error_prueba
rem  Prueba real de la vision (detectar, dibujar y codificar el video) con la
rem  imagen de prueba, para confirmar que la version de OpenCV funciona.
"%DIR_PY%\python.exe" -c "import os, tempfile, vision as v; x=v.Vision(os.path.join(tempfile.gettempdir(),'_prueba_vision.json')); ok,f=v.FuenteSintetica().read(); d=x.detectar(f); j=x._codificar(x.dibujar(f,d)); assert len(d)>=2 and j; print('      OK  vision:', len(d), 'cubos detectados en la imagen de prueba')"
if errorlevel 1 goto :error_prueba

rem ---------- 5) Comprimir ----------
echo [5/5] Comprimiendo el proyecto...
if exist "%DESTINO%" del /q "%DESTINO%"
tar -a -c -f "%DESTINO%" --exclude=.pio --exclude=__pycache__ --exclude=preparar_mudanza.log -C "%PADRE%" "%NOMBRE%"
if errorlevel 1 goto :error_zip
if not exist "%DESTINO%" goto :error_zip

echo.
echo ==================================================================
echo  LISTO   (%date% %time%)
echo  Archivo para copiar a la otra laptop:
echo     %DESTINO%
echo.
echo  En la otra laptop:
echo     1. Descomprime el .zip (clic derecho, Extraer todo).
echo     2. Doble clic en  %NOMBRE%\servidor_web\arrancar_servidor.bat
echo ==================================================================
exit /b 0

rem ---------- Descarga con reintentos ----------
rem  Hasta 5 intentos (curl y, si falla, PowerShell). El archivo se acepta
rem  solo si pesa exactamente lo que publica python.org (11133606 bytes),
rem  asi una descarga cortada nunca se usa.
:descargar
for /l %%N in (1,1,5) do (
  if exist "%DESCARGA%" del /q "%DESCARGA%"
  curl.exe -L --fail --silent --show-error --connect-timeout 20 -o "%DESCARGA%" "%URL_PY%"
  call :revisar_descarga
  if not errorlevel 1 exit /b 0
  if exist "%DESCARGA%" del /q "%DESCARGA%"
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%URL_PY%' -OutFile '%DESCARGA%'" >nul 2>nul
  call :revisar_descarga
  if not errorlevel 1 exit /b 0
  echo       Intento %%N sin exito, reintentando en 10 s...
  ping -n 11 127.0.0.1 >nul
)
exit /b 1

:revisar_descarga
if not exist "%DESCARGA%" exit /b 1
for %%F in ("%DESCARGA%") do if "%%~zF"=="%TAMANO_PY%" exit /b 0
exit /b 1

rem ---------- Errores ----------
:sin_python
echo ERROR: no encontre Python en esta laptop. Este paso se hace en la
echo laptop donde el proyecto YA funciona (la que tiene Python instalado).
exit /b 1

:error_descarga
echo ERROR: no se pudo descargar Python portatil despues de 5 intentos.
echo Revisa tu conexion a internet y vuelve a ejecutar este archivo.
exit /b 1

:error_extraer
echo ERROR: no se pudo descomprimir %ZIP_PY%.
exit /b 1

:error_pip
echo ERROR: no se pudieron descargar las librerias. Revisa tu conexion a internet.
exit /b 1

:error_prueba
echo ERROR: el Python portatil no pudo cargar las librerias (mira el error arriba).
echo Si dice "DLL load failed": instala "Microsoft Visual C++ Redistributable
echo x64" en esta laptop y vuelve a ejecutar este archivo.
exit /b 1

:error_zip
echo ERROR: no se pudo crear el .zip. La carpeta python ya quedo lista: puedes
echo copiar la carpeta del proyecto completa (sin firmware_esp32\.pio).
exit /b 1
