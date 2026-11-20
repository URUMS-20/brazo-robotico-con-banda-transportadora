@echo off
rem ==================================================================
rem  BRAZO ROBOTICO (The Genesis) - arrancar el servidor web
rem  Doble clic en este archivo:
rem    - Si existe la carpeta  ..\python  (Python portatil creado con
rem      preparar_mudanza.bat) lo usa directo: no instala nada.
rem    - Si no, usa el Python de la laptop e instala o revisa lo que
rem      necesita (Flask, pyserial, OpenCV).
rem    Luego arranca app.py y abre http://localhost:5000
rem  Para detenerlo: cierra esta ventana o presiona Ctrl + C
rem ==================================================================
cd /d "%~dp0"
title Brazo Robotico - servidor

set "PY=%~dp0..\python\python.exe"
if exist "%PY%" goto :portatil

set "PY=python"
echo Revisando dependencias (Flask, pyserial, OpenCV)...
"%PY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :error_pip
goto :arrancar

:portatil
echo Usando el Python portatil del proyecto (carpeta python): no hay nada que instalar.
goto :arrancar

:error_pip
echo.
echo No se pudieron instalar las dependencias.
echo  - Revisa tu conexion a internet, o
echo  - instala Python marcando "Add python.exe to PATH", o
echo  - usa el Python portatil (ver readme.txt, seccion 5).
pause
exit /b 1

:arrancar
echo.
echo Arrancando el servidor del brazo...
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:5000"
"%PY%" app.py
echo.
echo El servidor se detuvo.
pause
