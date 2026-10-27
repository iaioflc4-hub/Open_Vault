@echo off
REM Vista web del vault en Windows, solo en tu maquina (127.0.0.1).
REM Si lo que queres es leer en Obsidian, usa sincronizar.cmd.
setlocal

call "%~dp0_ejecutar.cmd" leer.sh %*
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
  echo.
  echo Algo fallo ^(codigo %CODIGO%^). Si el mensaje habla de Python, revisa que
  echo Python 3.11 o superior este instalado, o borra la carpeta .venv y volve a intentar.
)
echo.
pause
exit /b %CODIGO%
