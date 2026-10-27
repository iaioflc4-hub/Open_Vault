#!/usr/bin/env bash
# Instalador de Open_Vault para Debian/Ubuntu.
#
# Qué hace: crea un usuario de sistema sin privilegios, instala el proyecto en su
# propio directorio, arma el vault, deja el .env listo para completar y habilita
# el servicio systemd.
#
# Qué NO hace: no borra ni sobrescribe nada existente (si el .env ya está, no lo
# toca; si el vault ya tiene notas, no las toca) y no abre ningún puerto: el bot
# sale a buscar los mensajes a la API de Telegram.
#
# Uso:
#   sudo bash install.sh                  # instala o actualiza
#   sudo APP_DIR=/opt/mi-vault bash install.sh
#   sudo SERVICE_USER=mi-usuario VAULT_PATH=/home/mi-usuario/vault bash install.sh
#   sudo bash install.sh --sin-apt        # no intenta instalar tesseract/ffmpeg
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/openvault}"
SERVICE_USER="${SERVICE_USER:-openvault}"
VAULT_PATH="${VAULT_PATH:-/srv/obsidian/Open_Vault}"
REPO_URL="${REPO_URL:-https://github.com/iaioflc4-hub/Open_Vault.git}"
UNIT_PATH="/etc/systemd/system/open-vault.service"
INSTALAR_APT=1

for arg in "$@"; do
  case "$arg" in
    --sin-apt) INSTALAR_APT=0 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Hay que correrlo como root (o con sudo): crea un usuario de sistema y una unidad de systemd." >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "No encontré python3. Instalalo (apt install python3 python3-venv) y volvé a correr." >&2
  exit 1
fi
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "${PY_VERSION%%.*}" -lt 3 ] || { [ "${PY_VERSION%%.*}" -eq 3 ] && [ "${PY_VERSION##*.}" -lt 11 ]; }; then
  echo "Se necesita Python 3.11 o superior; este es $PY_VERSION." >&2
  exit 1
fi
log "Python $PY_VERSION detectado"

# --- 1. Usuario de sistema -------------------------------------------------
if id "$SERVICE_USER" >/dev/null 2>&1; then
  log "El usuario $SERVICE_USER ya existe"
else
  log "Creando usuario de sistema $SERVICE_USER (sin shell, sin privilegios)"
  # Sin --create-home a propósito: el directorio lo llena el paso siguiente, y
  # así el clonado/la copia no se encuentran con archivos de esqueleto en el medio.
  useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- 2. Código -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
  log "Instalando desde el checkout local $SCRIPT_DIR"
  mkdir -p "$APP_DIR"
  tar -C "$SCRIPT_DIR" --exclude=.venv --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$APP_DIR" -xf -
elif [ -d "$APP_DIR/.git" ]; then
  if [ -n "$(git -C "$APP_DIR" status --porcelain)" ]; then
    warn "Hay cambios locales en $APP_DIR: no actualizo el código para no pisarlos."
  else
    log "Actualizando el código en $APP_DIR"
    git -C "$APP_DIR" fetch --quiet origin
    git -C "$APP_DIR" checkout --quiet "$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"
    git -C "$APP_DIR" merge --ff-only --quiet FETCH_HEAD || warn "No se pudo avanzar rápido; quedó como estaba."
  fi
else
  log "Clonando el proyecto en $APP_DIR"
  git clone --quiet "$REPO_URL" "$APP_DIR"
fi

# --- 3. Dependencias del sistema (OCR y miniatura de video) ----------------
if [ "$INSTALAR_APT" -eq 1 ] && command -v apt-get >/dev/null 2>&1; then
  FALTAN=()
  command -v tesseract >/dev/null 2>&1 || FALTAN+=(tesseract-ocr tesseract-ocr-spa)
  command -v ffmpeg >/dev/null 2>&1 || FALTAN+=(ffmpeg)
  if [ "${#FALTAN[@]}" -gt 0 ]; then
    log "Instalando utilidades locales: ${FALTAN[*]}"
    export DEBIAN_FRONTEND=noninteractive
    if ! apt-get install -y --no-install-recommends "${FALTAN[@]}"; then
      warn "No se pudieron instalar. El bot funciona igual: sin OCR y sin miniaturas."
    fi
  fi
else
  command -v tesseract >/dev/null 2>&1 || warn "Sin tesseract: el OCR de imágenes queda apagado."
  command -v ffmpeg >/dev/null 2>&1 || warn "Sin ffmpeg: los videos quedan sin miniatura."
fi

# --- 4. Entorno virtual ----------------------------------------------------
log "Armando el entorno virtual en $APP_DIR/.venv"
if [ ! -d "$APP_DIR/.venv" ]; then
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install --quiet -e "$APP_DIR"

# --- 5. Vault --------------------------------------------------------------
if [ -d "$VAULT_PATH" ]; then
  log "El vault $VAULT_PATH ya existe: no toco su contenido"
  # Si está vacío, el problema es solo de dueño y se arregla acá. Si ya tiene
  # notas, no se cambia nada: los permisos los define quien lo administra.
  if [ -z "$(find "$VAULT_PATH" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$VAULT_PATH"
    chmod 0750 "$VAULT_PATH"
    log "Estaba vacío: le asigné el dueño $SERVICE_USER"
  fi
else
  log "Creando el vault $VAULT_PATH"
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$VAULT_PATH"
fi
if ! su -s /bin/sh -c "test -w '$VAULT_PATH'" "$SERVICE_USER" 2>/dev/null; then
  warn "$SERVICE_USER no puede escribir en $VAULT_PATH. Revisá permisos (chown $SERVICE_USER: $VAULT_PATH)."
fi

# --- 6. Configuración ------------------------------------------------------
if [ -f "$APP_DIR/.env" ]; then
  log "Ya hay un .env en $APP_DIR: lo dejo como está"
else
  log "Creando $APP_DIR/.env a partir de la plantilla"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
# Solo se toca el .env: es el único archivo que el servicio necesita leer como
# su propio usuario y que no debe ser legible por nadie más.
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

# --- 7. Servicio systemd ---------------------------------------------------
log "Instalando la unidad systemd"
sed -e "s|__APP_DIR__|$APP_DIR|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    -e "s|__VAULT_PATH__|$VAULT_PATH|g" \
    "$APP_DIR/deploy/open-vault.service" > "$UNIT_PATH"
systemctl daemon-reload
systemctl enable --quiet open-vault.service

TOKEN_SET=0
grep -qE '^BOT_TOKEN=.+' "$APP_DIR/.env" && TOKEN_SET=1

printf '\n\033[1;32mListo.\033[0m\n\n'
if [ "$TOKEN_SET" -eq 1 ]; then
  echo "Reiniciando el servicio con la configuración actual:"
  systemctl restart open-vault.service
  echo "  systemctl status open-vault   # ver cómo arrancó"
  echo "  journalctl -u open-vault -f   # seguir los mensajes"
else
  cat <<PASOS
Falta lo único que no se puede automatizar: tu token de Telegram.

  1. Hablá con @BotFather en Telegram, mandá /newbot y copiá el token.
  2. Editá la configuración:   sudo nano $APP_DIR/.env
     - BOT_TOKEN=el token de BotFather
  3. Arrancá el servicio:      sudo systemctl start open-vault
  4. Escribile /id al bot y poné tu número en ALLOWED_TELEGRAM_USER_IDS.
  5. Recargá la configuración: sudo systemctl restart open-vault

El vault queda en:  $VAULT_PATH
Para leerlo: abrí esa carpeta con Obsidian (o cualquier editor de Markdown).
PASOS
fi
