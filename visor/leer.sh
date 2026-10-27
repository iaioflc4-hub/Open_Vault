#!/usr/bin/env bash
# Vista web del vault, servida solo en tu propia máquina.
#
# Arma un sitio con búsqueda, diagramas Mermaid y fórmulas, y lo abre en
# http://localhost. Nada se publica y el servidor escucha solo en 127.0.0.1.
# Si lo que querés es leer en Obsidian, el comando es visor/sincronizar.sh.
#
# Uso (Linux, macOS o Git Bash en Windows):
#   bash visor/leer.sh
#   PUERTO=9000 bash visor/leer.sh
#   bash visor/leer.sh --mover        # además trae y VACÍA el servidor
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=visor/comun.sh
. "$PROYECTO/visor/comun.sh"

COPIA="$BASE/vault"
SITIO="$BASE/sitio"
PUERTO="${PUERTO:-8000}"
MOVER=0

for argumento in "$@"; do
  case "$argumento" in
    --mover) MOVER=1 ;;
    --conservar) MOVER=0 ;;
    -h|--help) sed -n '2,12p' "$0"; ayuda_comun; exit 0 ;;
    *) error "Opción desconocida: $argumento"; exit 2 ;;
  esac
done

requiere_ssh
PYTHON="$(preparar_python "$PROYECTO" | tail -1)"
sirve_python "$PYTHON" || { error "Ese Python no puede importar el proyecto."; exit 1; }

if [ "$MOVER" -eq 1 ]; then
  mkdir -p "$BASE"
  huella_servidor > "$BASE/manifiesto.md5"
fi

bajar_vault "$COPIA"

if [ "$MOVER" -eq 1 ]; then
  vaciar_servidor "$COPIA" "$BASE/manifiesto.md5"
fi

info "Armando la vista web"
"$PYTHON" -m open_vault.visor --vault "$COPIA" --salida "$SITIO" --assets "$PROYECTO/visor/assets" --servir --puerto "$PUERTO"
