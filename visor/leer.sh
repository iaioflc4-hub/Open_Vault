#!/usr/bin/env bash
# Lee el vault de Open_Vault en tu propia computadora.
#
# Qué hace:
#   1. trae una copia del vault desde el servidor por SSH;
#   2. arma la vista web (búsqueda, diagramas y fórmulas);
#   3. la sirve en 127.0.0.1 y abre el navegador.
#
# Nada se publica: el sitio queda en tu carpeta de usuario y el servidor solo
# escucha en 127.0.0.1 (tu máquina). Con Ctrl+C se apaga.
#
# Uso (Linux, macOS o Git Bash en Windows):
#   bash visor/leer.sh                     # copia: el servidor conserva todo
#   bash visor/leer.sh --mover             # trae y VACÍA el servidor (queda solo en tu PC)
#   PUERTO=9000 bash visor/leer.sh         # otro puerto
#   SERVIDOR=mi-vps bash visor/leer.sh     # otro servidor de tu ~/.ssh/config
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVIDOR="${SERVIDOR:-openvault}"
VAULT_REMOTO="${VAULT_REMOTO:-/srv/obsidian/Open_Vault}"
BASE="${BASE:-$HOME/.openvault}"
COPIA="$BASE/vault"
SITIO="$BASE/sitio"
PUERTO="${PUERTO:-8000}"

MOVER=0
for argumento in "$@"; do
  case "$argumento" in
    --mover) MOVER=1 ;;
    --conservar) MOVER=0 ;;
  esac
done

command -v ssh >/dev/null || { echo "Falta ssh en el PATH." >&2; exit 1; }

# --- 1. Python: tiene que poder importar el proyecto (y mkdocs para la vista) ---
# En Windows el PATH suele traer el Python de la tienda de Microsoft, que arranca
# pero no tiene nada instalado: por eso se prueba cada candidato antes de usarlo.
sirve_python() {
  [ -n "${1:-}" ] || return 1
  "$1" -c 'import open_vault, material' >/dev/null 2>&1
}

elegir_python() {
  local candidatos=()
  [ -n "${PYTHON:-}" ] && candidatos+=("$PYTHON")
  candidatos+=("$PROYECTO/.venv/Scripts/python.exe" "$PROYECTO/.venv/bin/python")
  candidatos+=("python3" "python")
  local candidato
  for candidato in "${candidatos[@]}"; do
    if sirve_python "$candidato"; then echo "$candidato"; return 0; fi
  done
  return 1
}

crear_entorno() {
  local base_python
  for base_python in "${PYTHON:-}" python3 python; do
    [ -n "$base_python" ] || continue
    if "$base_python" -c 'import sys' >/dev/null 2>&1; then break; fi
    base_python=""
  done
  [ -n "${base_python:-}" ] || { echo "No encontré un Python usable. Instalá Python 3.10 o superior." >&2; exit 1; }

  echo "==> Primera vez: creo el entorno del proyecto en $PROYECTO/.venv"
  "$base_python" -m venv "$PROYECTO/.venv"
  if [ -x "$PROYECTO/.venv/Scripts/python.exe" ]; then
    PYTHON_ENTORNO="$PROYECTO/.venv/Scripts/python.exe"
  else
    PYTHON_ENTORNO="$PROYECTO/.venv/bin/python"
  fi
  "$PYTHON_ENTORNO" -m pip install --quiet --upgrade pip
  "$PYTHON_ENTORNO" -m pip install --quiet -e "$PROYECTO"
  echo "$PYTHON_ENTORNO"
}

if PYTHON="$(elegir_python)"; then
  echo "==> Python: $PYTHON"
else
  PYTHON="$(crear_entorno | tail -1)"
  sirve_python "$PYTHON" || { echo "El entorno quedó armado pero el proyecto no importa." >&2; exit 1; }
fi

# --- 2. Traer el vault ---------------------------------------------------------
mkdir -p "$COPIA"
MANIFIESTO="$BASE/manifiesto.md5"
if [ "$MOVER" -eq 1 ]; then
  # Huella de cada archivo del servidor ANTES de bajar: sirve para borrar después
  # solo lo que se verificó acá. Si algo se corta a mitad de camino, no se borra nada.
  echo "==> Huella de los archivos del servidor"
  ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && find . -type f -print0 | xargs -0 md5sum" > "$MANIFIESTO"
fi

echo "==> Trayendo las capturas desde $SERVIDOR:$VAULT_REMOTO"
if ssh "$SERVIDOR" "tar czf - -C '$VAULT_REMOTO' ." | tar xzf - -C "$COPIA"; then
  echo "    copia local: $COPIA"
elif [ -n "$(ls -A "$COPIA" 2>/dev/null)" ]; then
  echo "    no pude llegar al servidor: sigo con la copia que ya tenía en $COPIA" >&2
else
  echo "    no pude traer nada del servidor y no hay copia local." >&2
  exit 1
fi

# --- 3. Vaciar el servidor (opcional) -----------------------------------------
if [ "$MOVER" -eq 1 ] && [ -s "$MANIFIESTO" ]; then
  echo "==> Verificando la copia antes de borrar del servidor"
  VERIFICADOS="$BASE/verificados.txt"
  PENDIENTES=0
  : > "$VERIFICADOS"
  while read -r huella ruta; do
    [ -n "${ruta:-}" ] || continue
    ruta="${ruta#./}"
    archivo="$COPIA/$ruta"
    if [ -f "$archivo" ] && [ "$(md5sum "$archivo" | cut -d' ' -f1)" = "$huella" ]; then
      printf '%s\n' "$ruta" >> "$VERIFICADOS"
    else
      PENDIENTES=$((PENDIENTES + 1))
      echo "    sin verificar (no lo borro): $ruta" >&2
    fi
  done < "$MANIFIESTO"
  TOTAL=$(wc -l < "$VERIFICADOS")
  if [ "$TOTAL" -gt 0 ]; then
    ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && xargs -d '\n' rm -f --" < "$VERIFICADOS"
    ssh "$SERVIDOR" "find '$VAULT_REMOTO' -mindepth 1 -type d -empty -delete"
    echo "    $TOTAL archivos borrados del servidor (quedan solo en tu PC)"
  fi
  [ "$PENDIENTES" -eq 0 ] || echo "    $PENDIENTES archivos quedaron en el servidor: no se pudieron verificar" >&2
fi

# --- 4. Vista web y servidor local -------------------------------------------
echo "==> Armando la vista web"
"$PYTHON" -m open_vault.visor --vault "$COPIA" --salida "$SITIO" --assets "$PROYECTO/visor/assets" --servir --puerto "$PUERTO"
