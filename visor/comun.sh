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

# --- Dónde está tu copia del vault -----------------------------------------
# Si ya hay una copia en un lugar habitual del sistema, se usa esa: así el doble
# clic no crea una segunda carpeta en otro lado y Obsidian sigue mirando la misma.
# Se puede forzar con OBSIDIAN_VAULT=/ruta/a/tu/vault.
deteccion_destino() {
  local candidato
  for candidato in "$HOME/Obsidian/Open_Vault" "$HOME/Documents/Open_Vault" "$HOME/Open_Vault" \
                   "$HOME/Documentos/Open_Vault" "$HOME/Obsidian/OpenVault"; do
    if [ -d "$candidato/Categorías" ] || [ -d "$candidato/Categorias" ] || [ -d "$candidato/.git" ]; then
      printf '%s\n' "$candidato"
      return 0
    fi
  done
  printf '%s\n' "$HOME/Obsidian/Open_Vault"
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
# Solo viajan las notas: el `.git` del servidor (con su configuración y su clave) y
# la carpeta `.obsidian` son de cada máquina. Sin este filtro, el historial del
# servidor pisaba el de la computadora y el remoto quedaba configurado con la clave
# del servidor, que acá no existe.
EXCLUIR="--exclude=./.git --exclude=./.obsidian --exclude=./.trash"

huella_servidor() {
  ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && find . -type f -not -path './.git/*' -not -path './.obsidian/*' -not -path './.trash/*' -print0 | xargs -0 md5sum"
}

bajar_vault() {
  local destino="$1"
  mkdir -p "$destino"
  info "Trayendo las capturas desde $SERVIDOR:$VAULT_REMOTO"
  if ssh "$SERVIDOR" "tar czf - -C '$VAULT_REMOTO' $EXCLUIR ." | tar xzf - -C "$destino"; then
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

# Cuando una captura cambia de tema, en el servidor se mueve de carpeta; acá la
# copia vieja quedaría duplicada en dos carpetas. Esto borra de tu copia lo que ya
# no existe en el servidor, y **solo** dentro de lo que administra el proyecto:
# tus propios archivos y la configuración de Obsidian nunca se tocan.
CARPETAS_ADMINISTRADAS="Categorías Temas Attachments"
MAPA_VAULT="Mapa del vault.md"

purgar_borrados() {
  local destino="$1" archivo relativo borrados=0 lista
  [ -d "$destino" ] || return 0
  lista="$(mktemp)"
  if ! ssh "$SERVIDOR" "cd '$VAULT_REMOTO' && find . -type f -not -path './.git/*' -not -path './.obsidian/*'" > "$lista" 2>/dev/null; then
    aviso "No pude leer la lista del servidor: no borro nada de tu copia."
    rm -f "$lista"
    return 0
  fi

  local rutas=""
  local carpeta
  for carpeta in $CARPETAS_ADMINISTRADAS; do
    [ -d "$destino/$carpeta" ] && rutas="$rutas $destino/$carpeta"
  done
  [ -f "$destino/$MAPA_VAULT" ] && rutas="$rutas $destino/$MAPA_VAULT"

  # shellcheck disable=SC2086
  while IFS= read -r archivo; do
    relativo="${archivo#"$destino"/}"
    if grep -Fxq "./$relativo" "$lista"; then
      continue
    fi
    rm -f "$archivo"
    borrados=$((borrados + 1))
  done < <(find $rutas -type f 2>/dev/null)
  rm -f "$lista"
  [ "$borrados" -eq 0 ] || info "$borrados archivos que ya no están en el servidor (notas movidas o borradas)"

  for carpeta in $CARPETAS_ADMINISTRADAS; do
    [ -d "$destino/$carpeta" ] || continue
    find "$destino/$carpeta" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  done
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

  if [ -z "$(git -C "$destino" remote)" ]; then
    aviso "Todavía no hay un remoto configurado: no puedo subir el vault."
    aviso "Una vez: git -C \"$destino\" remote add origin <tu-repo-privado>.git"
  fi

  local rama
  rama="$(git -C "$destino" rev-parse --abbrev-ref HEAD)"

  # El servidor también escribe en este repo: antes de commitear se trae lo suyo.
  # Si no se hiciera, los dos historiales se separan y el push de acá rebota.
  if git -C "$destino" rev-parse --verify --quiet "origin/$rama" >/dev/null 2>&1; then
    if ! git -C "$destino" pull --rebase --autostash --quiet origin "$rama"; then
      aviso "No pude traer lo último de GitHub: sigo con tu copia local."
    fi
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
    return 0
  fi

  if git -C "$destino" push --quiet origin "$rama"; then
    info "Subido a GitHub: en el celular, Obsidian → Git → Pull y ya lo ves"
    return 0
  fi

  # El servidor también sube (cada 5 minutos): si subió algo entre nuestro rebase y
  # el push, alcanza con volver a traer y empujar. Otra vez no: si falla de nuevo es
  # credenciales o remoto, y eso se avisa en vez de reintentar en loop.
  if git -C "$destino" pull --rebase --autostash --quiet origin "$rama" \
     && git -C "$destino" push --quiet origin "$rama"; then
    info "Subido a GitHub (después de traer lo que había subido el servidor)"
    return 0
  fi
  aviso "No pude subir a GitHub: revisá el remoto y tus credenciales (git -C \"$destino\" push)"
}
