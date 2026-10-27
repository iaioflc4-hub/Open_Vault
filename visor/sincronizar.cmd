@echo off
REM Trae las capturas del servidor a tu carpeta de Obsidian y las sube a tu repo.
REM Doble clic para traer; con --mover tambien vacia el servidor.
setlocal

call "%~dp0_ejecutar.cmd" sincronizar.sh %*
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
  echo.
  echo Algo fallo ^(codigo %CODIGO%^). Revisa que ssh este configurado y que el
  echo servidor este encendido: ssh %SERVIDOR%
)
echo.
pause
exit /b %CODIGO%
