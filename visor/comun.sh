#!/usr/bin/env bash
# Piezas compartidas por los dos caminos de lectura: la vista web (leer.sh) y la
# carpeta de Obsidian (sincronizar.sh). Este archivo no se ejecuta: se sourcea.
#
# Convención: los avisos van a stderr y la salida estándar queda limpia, así las
# funciones que devuelven algo (por ejemplo el intérprete de Python) se pueden
# capturar con $( ) sin que se les mezclen mensajes.

SERVIDOR="${SERVIDOR:-openvault}"                              # host de tu ~/.ssh/config
VAULT_REMOTO="${VAULT_REMOTO:-/srv/obsidian/Open_Vault}"
BASE="${BASE:-$HOME/.openvault}"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1" >&2; }
aviso() { printf '\033[1;33m[!]\033[0m %s\n' "$1" >&2; }
error() { printf '\033[1;31m[x]\033[0m %s\n' "$1" >&2; }

ayuda_comun() {
  cat <<TEXTO
Variables de entorno:
  SERVIDOR       host del servidor en tu ~/.ssh/config   (por defecto: openvault)
  VAULT_REMOTO   carpeta del vault en el servidor        (por defecto: /srv/obsidian/Open_Vault)
  BASE           dónde se guarda la copia y el estado    (por defecto: ~/.openvault)
TEXTO
}

requiere_ssh() {
  command -v ssh >/dev/null || { error "Falta ssh en el PATH."; exit 1; }
  command -v tar >/dev/null || { error "Falta tar en el PATH."; exit 1; }
}

# --- Python (solo para la vista web) ---------------------------------------
# En Windows el PATH suele traer el Python de la tienda de Microsoft, que arranca
# pero no tiene nada instalado: por eso se prueba cada candidato antes de usarlo.
sirve_python() {
  [ -n "${1:-}" ] || return 1
  "$1" -c 'import open_vault, material' >/dev/null 2>&1
}

preparar_python() {
  local proyecto="$1"
  local candidato
  for candidato in "${PYTHON:-}" "$proyecto/.venv/Scripts/python.exe" "$proyecto/.venv/bin/python" python3 python; do
    [ -n "$candidato" ] || continue
    if sirve_python "$candidato"; then
      info "Python: $candidato"
      echo "$candidato"
      return 0
    fi
  done

  local base_python=""
  for base_python in "${PYTHON:-}" python3 python; do
    [ -n "$base_python" ] || continue
    if "$base_python" -c 'import sys' >/dev/null 2>&1; then break; fi
    base_python=""
  done
  if [ -z "${base_python:-}" ]; then
    error "No encontré un Python usable. Instalá Python 3.11 o superior."
    return 1
  fi
  info "Primera vez: creo el entorno del proyecto en $proyecto/.venv"
  "$base_python" -m venv "$proyecto/.venv"
  local entorno="$proyecto/.venv/bin/python"
  [ -x "$proyecto/.venv/Scripts/python.exe" ] && entorno="$proyecto/.venv/Scripts/python.exe"
  "$entorno" -m pip install --quiet --upgrade pip
  "$entorno" -m pip install --quiet -e "$proyecto"
  sirve_python "$entorno" || { error "El entorno quedó armado pero el proyecto no importa."; return 1; }
  info "Python: $entorno"
  echo "$entorno"
}

# --- Traer las capturas ----------------------------------------------------
huella_servidor() {
  ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && find . -type f -print0 | xargs -0 md5sum"
}

bajar_vault() {
  local destino="$1"
  mkdir -p "$destino"
  info "Trayendo las capturas desde $SERVIDOR:$VAULT_REMOTO"
  if ssh "$SERVIDOR" "tar czf - -C '$VAULT_REMOTO' ." | tar xzf - -C "$destino"; then
    info "Copia local: $destino"
    return 0
  fi
  if [ -n "$(ls -A "$destino" 2>/dev/null)" ]; then
    aviso "No pude llegar al servidor: sigo con la copia que ya tenía en $destino"
    return 0
  fi
  error "No pude traer nada del servidor y no hay copia local."
  return 1
}

# Borra del servidor solo lo que se verificó acá. Si algo no coincide, no se toca:
# perder una captura es mucho peor que dejar unos KB de más.
vaciar_servidor() {
  local destino="$1" manifiesto="$2"
  if [ ! -s "$manifiesto" ]; then
    aviso "No tengo la huella del servidor: no borro nada."
    return 0
  fi
  info "Verificando la copia antes de borrar del servidor"
  local verificados="$BASE/verificados.txt" pendientes=0 huella ruta archivo
  : > "$verificados"
  while read -r huella ruta; do
    [ -n "${ruta:-}" ] || continue
    ruta="${ruta#./}"
    archivo="$destino/$ruta"
    if [ -f "$archivo" ] && [ "$(md5sum "$archivo" | cut -d' ' -f1)" = "$huella" ]; then
      printf '%s\n' "$ruta" >> "$verificados"
    else
      pendientes=$((pendientes + 1))
      aviso "Sin verificar (no lo borro): $ruta"
    fi
  done < "$manifiesto"
  local total
  total=$(wc -l < "$verificados")
  if [ "${total:-0}" -gt 0 ]; then
    ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && xargs -d '\n' rm -f --" < "$verificados"
    ssh "$SERVIDOR" "find '$VAULT_REMOTO' -mindepth 1 -type d -empty -delete"
    info "$total archivos borrados del servidor (quedan solo en tu copia)"
  fi
  [ "$pendientes" -eq 0 ] || aviso "$pendientes archivos quedaron en el servidor: no se pudieron verificar"
}

# --- Sincronización por Git (para leer en Obsidian desde el celular) -------
GITIGNORE_VAULT='.obsidian/workspace*.json
.obsidian/cache
.trash/
.DS_Store
*.tmp'

sincronizar_git() {
  local destino="$1"
  if ! command -v git >/dev/null 2>&1; then
    aviso "No hay git instalado: dejo la copia lista, sin sincronizar."
    return 0
  fi
  if [ ! -d "$destino/.git" ]; then
    info "Primera vez: convierto la copia en un repositorio propio"
    git -C "$destino" init --quiet -b main
    printf '%s\n' "$GITIGNORE_VAULT" > "$destino/.gitignore"
  fi
  # El commit se hace siempre, aunque no haya remoto: así el histórico local
  # arranca desde la primera captura y conectar el remoto después es un paso más.
  git -C "$destino" add -A
  if git -C "$destino" diff --cached --quiet; then
    info "Sin capturas nuevas: no hay nada que guardar"
  else
    git -C "$destino" -c user.name="${GIT_USER:-Open_Vault}" \
      -c user.email="${GIT_EMAIL:-openvault@localhost}" \
      commit --quiet -m "Capturas del $(date '+%Y-%m-%d %H:%M')"
    info "Capturas guardadas en el historial local"
  fi

  if [ -z "$(git -C "$destino" remote)" ]; then
    aviso "Todavía no hay un remoto configurado: no puedo subir el vault."
    aviso "Una vez: git -C \"$destino\" remote add origin <tu-repo-privado>.git"
    return 0
  fi

  local rama
  rama="$(git -C "$destino" rev-parse --abbrev-ref HEAD)"
  if git -C "$destino" push --quiet origin "$rama"; then
    info "Subido a GitHub: en el celular, Obsidian → Git → Pull y ya lo ves"
  else
    aviso "No pude subir a GitHub: revisá el remoto y tus credenciales (git -C \"$destino\" push)"
  fi
}
