#!/usr/bin/env bash
# Mantiene el vault al día y lo sube a GitHub.
#
# Lo corre un temporizador de systemd cada pocos minutos, como el usuario del
# servicio. Hace tres cosas, todas idempotentes (si no hay nada que hacer, no
# escribe ni un byte):
#
#   1. vuelve a clasificar las notas con las reglas actuales;
#   2. conecta cada captura con sus notas de tema y rehace el mapa;
#   3. hace un commit y lo sube, para que el celular y la computadora lo vean.
#
# Si el vault no es un repositorio con remoto, el paso 3 se saltea sin romper nada.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/openvault}"
VAULT_PATH="${VAULT_PATH:-/srv/obsidian/Open_Vault}"
PY="${APP_DIR}/.venv/bin/python"
export PYTHONPATH="${APP_DIR}/src"
MENSAJE="${1:-Capturas del $(date '+%Y-%m-%d %H:%M')}"

[ -d "$VAULT_PATH" ] || exit 0
[ -d "$VAULT_PATH/.git" ] || exit 0

# Los pasos 1 y 2 no deben tumbar la subida si fallan: primero lo importante.
"$PY" -m open_vault.reclasificar --vault "$VAULT_PATH" >/dev/null 2>&1 || true
"$PY" -m open_vault.grafo --vault "$VAULT_PATH" >/dev/null 2>&1 || true

cd "$VAULT_PATH"
git add -A
if git diff --cached --quiet; then
  exit 0
fi
git -c user.name="Open_Vault" -c user.email="openvault@localhost" commit --quiet -m "$MENSAJE"
if ! git push --quiet origin HEAD 2>/dev/null; then
  echo "aviso: no pude subir el vault a GitHub (revisá la clave de despliegue)" >&2
fi
