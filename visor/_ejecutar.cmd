@echo off
REM Lanzador compartido: busca Git Bash y llama al script que se le pide.
REM Se usa desde leer.cmd y sincronizar.cmd (nadie deberia ejecutarlo a mano).
REM Uso: _ejecutar.cmd <script.sh> [argumentos...]
setlocal EnableDelayedExpansion

if "%~1"=="" (
  echo Falta el script a ejecutar.
  exit /b 2
)

set "SCRIPT=%~1"
shift
set "ARGUMENTOS=%*"

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
  exit /b 1
)

echo Usando: !BASH!
"!BASH!" "%~dp0%SCRIPT%" !ARGUMENTOS!
exit /b %ERRORLEVEL%
