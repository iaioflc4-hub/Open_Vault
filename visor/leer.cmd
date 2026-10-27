@echo off
REM Lee el vault de Open_Vault en Windows: llama a leer.sh con Git Bash.
REM Nada se publica; la vista se arma en tu carpeta de usuario y se sirve solo en
REM tu propia máquina (127.0.0.1).
setlocal

set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=bash"

"%BASH%" "%~dp0leer.sh" %*
if errorlevel 1 (
  echo.
  echo Algo falló. Revisá que Git para Windows y Python estén instalados.
)
pause
