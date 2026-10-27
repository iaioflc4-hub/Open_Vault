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
GIT_ID=(-c user.name="Open_Vault" -c user.email="openvault@localhost")

[ -d "$VAULT_PATH" ] || exit 0
[ -d "$VAULT_PATH/.git" ] || exit 0

# Los pasos 1 y 2 no deben tumbar la subida si fallan: primero lo importante.
"$PY" -m open_vault.reclasificar --vault "$VAULT_PATH" >/dev/null 2>&1 || true
"$PY" -m open_vault.grafo --vault "$VAULT_PATH" >/dev/null 2>&1 || true

cd "$VAULT_PATH"
rama="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"

# Antes de armar el commit se trae lo que haya subido la computadora (una nota
# escrita o editada a mano). Cada captura es un archivo propio —su nombre lleva
# la fuente—, así que el rebase casi nunca choca; si choca, se avisa y no se
# toca nada. Perder una nota es peor que subir un rato más tarde.
if git rev-parse --verify --quiet "origin/$rama" >/dev/null; then
  if ! git "${GIT_ID[@]}" pull --rebase --autostash --quiet origin "$rama"; then
    echo "aviso: no pude actualizar desde GitHub; lo intento en la próxima corrida" >&2
    exit 0
  fi
fi

git add -A
if git diff --cached --quiet; then
  exit 0
fi
git "${GIT_ID[@]}" commit --quiet -m "$MENSAJE"

subir() {
  git push --quiet origin "HEAD:$rama"
}

if subir; then
  exit 0
fi
# Un solo reintento: si alguien subió entre el rebase y el push, se vuelve a
# rebasar y listo. Si vuelve a fallar, es credenciales o remoto: se avisa.
if git "${GIT_ID[@]}" pull --rebase --autostash --quiet origin "$rama" && subir; then
  exit 0
fi
echo "aviso: no pude subir el vault a GitHub (revisá la clave de despliegue en /etc/openvault/git.env)" >&2
