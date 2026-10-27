#!/usr/bin/env bash
# Trae las capturas del servidor a tu carpeta de Obsidian y las sincroniza.
#
# Es el camino recomendado para leer: las notas quedan en una carpeta común de
# Markdown, Obsidian las abre tal cual (en la computadora y en el celular, este
# último por el plugin Git) y no hace falta ninguna web de por medio.
#
# Uso (Linux, macOS o Git Bash en Windows):
#   bash visor/sincronizar.sh                    # trae y sube a tu repo
#   bash visor/sincronizar.sh --sin-git          # solo trae la copia local
#   bash visor/sincronizar.sh --mover            # además VACÍA el servidor
#   OBSIDIAN_VAULT=~/Notas bash visor/sincronizar.sh
#
# En Windows: doble clic en visor\sincronizar.cmd
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=visor/comun.sh
. "$PROYECTO/visor/comun.sh"

DESTINO="${OBSIDIAN_VAULT:-$(deteccion_destino)}"
HACER_GIT=1
MOVER=0

for argumento in "$@"; do
  case "$argumento" in
    --mover) MOVER=1 ;;
    --conservar) MOVER=0 ;;
    --sin-git) HACER_GIT=0 ;;
    --git) HACER_GIT=1 ;;
    -h|--help) sed -n '2,15p' "$0"; ayuda_comun; exit 0 ;;
    *) error "Opción desconocida: $argumento"; exit 2 ;;
  esac
done

requiere_ssh

if [ "$MOVER" -eq 1 ]; then
  mkdir -p "$BASE"
  huella_servidor > "$BASE/manifiesto.md5"
fi

bajar_vault "$DESTINO"

if [ "$MOVER" -eq 1 ]; then
  vaciar_servidor "$DESTINO" "$BASE/manifiesto.md5"
else
  # Sin --mover el servidor conserva todo: hay que limpiar acá lo que ya no existe,
  # si no la misma nota queda en la carpeta vieja y en la nueva.
  purgar_borrados "$DESTINO"
fi

if [ "$HACER_GIT" -eq 1 ]; then
  sincronizar_git "$DESTINO"
fi

info "Listo. Tus notas están en: $DESTINO"
printf '\nCómo leerlas:\n' >&2
printf '  · En la computadora: Obsidian → "Abrir carpeta como vault" → %s\n' "$DESTINO" >&2
printf '  · En el celular: Obsidian → Git → Pull (el mismo repo privado)\n' >&2
printf '  · Vista web (opcional): bash visor/leer.sh\n' >&2
