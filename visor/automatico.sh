#!/usr/bin/env bash
# Deja el vault al día solo, sin apretar nada: pensado para dejarlo corriendo
# mientras tenés Obsidian abierto.
#
# Por qué existe: Obsidian mira la carpeta del vault, pero una nota que llega de
# afuera no aparece hasta que algo la trae. Este proceso la trae cada minuto, así
# que lo que le mandás al bot aparece en pantalla sin cerrar y volver a abrir.
#
# Uso (Linux, macOS o Git Bash en Windows):
#   bash visor/automatico.sh                 # cada 60 segundos, hasta Ctrl+C
#   bash visor/automatico.sh --cada 20       # cada 20 segundos
#   bash visor/automatico.sh --una-vez       # una sola corrida (para probar)
#   OBSIDIAN_VAULT=~/Notas bash visor/automatico.sh
#
# En Windows: doble clic en visor\automatico.cmd y dejá la ventana abierta
# (minimizada está bien). Para que arranque solo al iniciar sesión, ver README.
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=visor/comun.sh
. "$PROYECTO/visor/comun.sh"

INTERVALO="${INTERVALO:-60}"
UNA_VEZ=0
PASAR=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --cada)
      INTERVALO="${2:?Falta el intervalo en segundos después de --cada}"
      shift 2
      ;;
    --una-vez) UNA_VEZ=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; ayuda_comun; exit 0 ;;
    *) PASAR+=("$1"); shift ;;
  esac
done

if ! [[ "$INTERVALO" =~ ^[0-9]+$ ]] || [ "$INTERVALO" -lt 5 ]; then
  error "El intervalo tiene que ser un número de segundos (5 o más)."
  exit 2
fi

requiere_ssh

printf '\033[1;34m==>\033[0m Sincronización automática cada %s s. Ctrl+C para cortar.\n' "$INTERVALO" >&2
printf '    Obsidian puede quedar abierto: las notas aparecen solas.\n\n' >&2

while true; do
  printf '\033[1;34m[%s]\033[0m buscando capturas nuevas…\n' "$(date '+%H:%M:%S')" >&2
  if ! bash "$PROYECTO/visor/sincronizar.sh" ${PASAR[@]+"${PASAR[@]}"}; then
    aviso "La corrida falló. Reviso de nuevo en $INTERVALO s (Ctrl+C para cortar)."
  fi
  [ "$UNA_VEZ" -eq 1 ] && exit 0
  sleep "$INTERVALO"
done
