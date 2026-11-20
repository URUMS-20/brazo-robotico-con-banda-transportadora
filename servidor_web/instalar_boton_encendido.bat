@echo off
rem ==================================================================
rem  Instala (una sola vez) el permiso para que la pagina web pueda
rem  encender el servidor. Solo afecta a TU usuario de Windows.
rem  Si mueves la carpeta del proyecto, vuelve a ejecutarlo.
rem  Para quitarlo: desinstalar_boton_encendido.bat
rem ==================================================================
set "K=HKCU\Software\Classes\genesis-brazo"
reg add "%K%" /ve /d "URL:Brazo Robotico Genesis" /f >nul
reg add "%K%" /v "URL Protocol" /d "" /f >nul
reg add "%K%\shell\open\command" /ve /d "\"%~dp0encender_desde_web.bat\"" /f >nul
if errorlevel 1 (
  echo No se pudo instalar.
) else (
  echo Listo. Ahora el boton "Encender servidor" de la pagina funciona en esta computadora.
  echo Ruta registrada: %~dp0encender_desde_web.bat
)
pause
