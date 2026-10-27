@echo off
REM Deja el vault al dia solo, cada minuto, mientras tenes Obsidian abierto.
REM Doble clic y deja esta ventana abierta (podes minimizarla). Ctrl+C la corta.
REM Con --cada N cambia el intervalo; con --una-vez hace una sola pasada.
setlocal

call "%~dp0_ejecutar.cmd" automatico.sh %*
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
  echo.
  echo La sincronizacion automatica termino con codigo %CODIGO%.
  echo Revisa que ssh este configurado y que el servidor este encendido: ssh %SERVIDOR%
)
echo.
pause
exit /b %CODIGO%
