@echo off
rem Lo llama el boton "Encender servidor" de la pagina de documentacion.
rem Arranca el servidor del brazo en segundo plano (ventana minimizada).
cd /d "%~dp0"
netstat -ano | findstr /R /C:":5000 .*LISTENING" >nul && exit /b 0
set "PY=%~dp0..\python\python.exe"
if not exist "%PY%" (
  start "" "%~dp0arrancar_servidor.bat"
  exit /b 0
)
start "Brazo Robotico - servidor" /min "%PY%" app.py
exit /b 0
