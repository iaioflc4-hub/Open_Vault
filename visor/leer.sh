#!/usr/bin/env bash
# Lee el vault de Open_Vault en tu propia computadora.
#
# Qué hace: trae una copia del vault desde el servidor por SSH, arma la vista web
# y la abre en el navegador. Nada se publica: el sitio queda en tu carpeta de
# usuario y el servidor escucha solo en 127.0.0.1 (tu máquina).
#
# Uso (Linux, macOS o Git Bash en Windows):
#   bash visor/leer.sh
#   SERVIDOR=mi-servidor PUERTO=9000 bash visor/leer.sh
#   PYTHON=".venv/Scripts/python.exe" bash visor/leer.sh    # con el venv del proyecto
set -euo pipefail

SERVIDOR="${SERVIDOR:-openvault}"                              # nombre del host en tu ~/.ssh/config
VAULT_REMOTO="${VAULT_REMOTO:-/srv/obsidian/Open_Vault}"
BASE="${BASE:-$HOME/.openvault}"
COPIA="$BASE/vault"
SITIO="$BASE/sitio"
PUERTO="${PUERTO:-8000}"
PYTHON="${PYTHON:-python3}"

command -v ssh >/dev/null || { echo "Falta ssh en el PATH." >&2; exit 1; }
command -v "$PYTHON" >/dev/null || command -v python >/dev/null || { echo "Falta python3 en el PATH." >&2; exit 1; }
PYTHON="$(command -v "$PYTHON" || command -v python)"

mkdir -p "$COPIA"
echo "==> Trayendo las capturas desde $SERVIDOR:$VAULT_REMOTO"
ssh "$SERVIDOR" "tar czf - -C '$VAULT_REMOTO' ." | tar xzf - -C "$COPIA"

echo "==> Armando la vista web"
"$PYTHON" -m open_vault.visor --vault "$COPIA" --salida "$SITIO" --servir --puerto "$PUERTO"
