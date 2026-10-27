@echo off
REM Lee el vault de Open_Vault en Windows: busca Git Bash y le pasa el trabajo a leer.sh.
REM Nada se publica: la vista se arma en tu carpeta de usuario y se sirve solo en
REM tu propia maquina (127.0.0.1). Podes arrastrarle opciones: --mover, etc.
setlocal EnableDelayedExpansion

set "BASH="
set "CANDIDATOS=%ProgramFiles%\Git\bin\bash.exe;%ProgramFiles(x86)%\Git\bin\bash.exe;%LOCALAPPDATA%\Programs\Git\bin\bash.exe;%USERPROFILE%\scoop\apps\git\current\bin\bash.exe"

for %%C in ("%CANDIDATOS:;=" "%") do (
  if not defined BASH if exist %%C set "BASH=%%~C"
)

if not defined BASH (
  for /f "delims=" %%W in ('where bash 2^>nul') do (
    if not defined BASH set "BASH=%%W"
  )
)

if not defined BASH (
  echo.
  echo No encontre Git Bash en esta computadora.
  echo Instala Git para Windows desde https://git-scm.com/download/win y volve a probar.
  echo.
  pause
  exit /b 1
)

echo Usando: !BASH!
"!BASH!" "%~dp0leer.sh" %*
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
  echo.
  echo Algo fallo ^(codigo %CODIGO%^). Si el mensaje habla de Python, revisa que
  echo Python 3.10 o superior este instalado, o borra la carpeta .venv y volve a intentar.
)
echo.
pause
exit /b %CODIGO%
