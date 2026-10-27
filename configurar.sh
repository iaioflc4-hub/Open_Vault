#!/usr/bin/env bash
# Asistente de configuración de Open_Vault.
#
# Hace las preguntas que hoy había que responder a mano en el .env y verifica
# cada respuesta contra la API de Telegram: si el token está mal lo dice, y el ID
# no lo tenés que copiar de ningún lado (el asistente lo lee del mensaje que le
# mandás al bot). Al final manda un mensaje de prueba a tu chat: si te llega, está
# todo conectado; si no, te dice qué falló.
#
# Uso:
#   sudo bash configurar.sh                 # interactivo: pregunta lo que falta
#   sudo bash configurar.sh --simular       # valida y muestra qué haría, sin tocar nada
#   sudo BOT_TOKEN=123:abc bash configurar.sh    # sin preguntas (instalación desatendida)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/openvault}"
SERVICIO="${SERVICIO:-open-vault}"
ENV_FILE="$APP_DIR/.env"
PY="$APP_DIR/.venv/bin/python"
ESPERA_ID="${ESPERA_ID:-90}"        # segundos que espera tu mensaje al bot
SIMULAR=0

for arg in "$@"; do
  case "$arg" in
    --simular) SIMULAR=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

info()  { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
aviso() { printf '\033[1;33m[!]\033[0m %s\n' "$1"; }
error() { printf '\033[1;31m[x]\033[0m %s\n' "$1" >&2; }
ok()    { printf '\033[1;32m[ok]\033[0m %s\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  error "Corrélo como root (o con sudo): escribe el .env y reinicia el servicio."
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  error "No encuentro $ENV_FILE. Primero corré: sudo bash install.sh"
  exit 1
fi
if [ ! -x "$PY" ]; then
  error "No encuentro el entorno virtual en $APP_DIR/.venv. Corré: sudo bash install.sh"
  exit 1
fi

leer_env() { sed -n "s|^$1=||p" "$ENV_FILE" | head -1; }

poner_env() {
  local clave="$1" valor="$2"
  if grep -qE "^${clave}=" "$ENV_FILE"; then
    sed -i "s|^${clave}=.*|${clave}=${valor}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$clave" "$valor" >> "$ENV_FILE"
  fi
}

# Interactivo solo si hay una terminal: así el asistente también sirve para
# instalaciones desatendidas (con BOT_TOKEN ya puesto en el entorno).
INTERACTIVO=0
[ -t 0 ] && INTERACTIVO=1

# --- API de Telegram (el token va por entorno, nunca en la línea de comandos) ---
api() {
  TOKEN="$1" METODO="$2" DATOS="${3:-}" "$PY" - <<'PY'
import json, os, urllib.error, urllib.request

token, metodo, datos = os.environ["TOKEN"], os.environ["METODO"], os.environ.get("DATOS", "")
peticion = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/{metodo}",
    data=datos.encode() if datos else None,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(peticion, timeout=40) as respuesta:
        print(respuesta.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode())
except Exception as exc:  # sin red, DNS raro, etc.
    print(json.dumps({"ok": False, "description": str(exc)}))
PY
}

campo() {  # $1 = json, $2 = expresión de acceso
  JSON="$1" RUTA="$2" "$PY" - <<'PY'
import json, os

try:
    dato = json.loads(os.environ["JSON"])
except ValueError:
    print("")
    raise SystemExit
for parte in os.environ["RUTA"].split("."):
    if parte.isdigit() and isinstance(dato, list):
        dato = dato[int(parte)] if int(parte) < len(dato) else None
    elif isinstance(dato, dict):
        dato = dato.get(parte)
    else:
        dato = None
    if dato is None:
        break
print("" if dato is None else dato)
PY
}

# --- 1. Token ---------------------------------------------------------------
TOKEN="${BOT_TOKEN:-$(leer_env BOT_TOKEN)}"
info "Token del bot"
if [ -n "${BOT_TOKEN:-}" ]; then
  echo "Uso el token que vino en el entorno."
elif [ "$INTERACTIVO" -eq 1 ]; then
  printf 'Pegá el token de @BotFather (no se muestra en pantalla): '
  read -rs TOKEN
  echo
fi
TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
if ! printf '%s' "$TOKEN" | grep -qE '^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$'; then
  error "Ese token no tiene forma de token de Telegram (se ve como: 123456:ABC...)."
  echo "Hablá con @BotFather, mandá /newbot y copiá el token completo." >&2
  exit 1
fi

RESPUESTA="$(api "$TOKEN" getMe)"
if [ "$(campo "$RESPUESTA" ok)" != "True" ]; then
  error "Telegram rechazó el token: $(campo "$RESPUESTA" description)"
  exit 1
fi
BOT_USUARIO="$(campo "$RESPUESTA" result.username)"
ok "El bot es @$BOT_USUARIO"

# --- 2. Tu ID ---------------------------------------------------------------
IDS_ACTUALES="$(leer_env ALLOWED_TELEGRAM_USER_IDS)"
info "Quién puede usarlo"
if [ -n "$IDS_ACTUALES" ]; then
  ok "Ya está autorizado el ID $IDS_ACTUALES (lo dejo igual)"
  IDS="$IDS_ACTUALES"
else
  aviso "Todavía no hay ningún ID autorizado. Abrí https://t.me/$BOT_USUARIO en"
  aviso "Telegram y mandale /id. Espero tu mensaje hasta $ESPERA_ID segundos..."
  ENCONTRADOS=""
  SEGUNDOS=0
  while [ "$SEGUNDOS" -lt "$ESPERA_ID" ]; do
    UPDATES="$(api "$TOKEN" getUpdates)"
    ENCONTRADOS="$(USUARIOS="$UPDATES" "$PY" - <<'PY'
import json, os

datos = json.loads(os.environ.get("USUARIOS", "{}"))
vistos = {}
for actualizacion in datos.get("result", []):
    mensaje = actualizacion.get("message") or actualizacion.get("edited_message") or {}
    quien = mensaje.get("from") or {}
    if quien.get("id"):
        nombre = quien.get("first_name") or "sin nombre"
        usuario = f" (@{quien['username']})" if quien.get("username") else ""
        vistos[quien["id"]] = f"{nombre}{usuario}"
for identificador, nombre in vistos.items():
    print(f"{identificador} :: {nombre}")
PY
)"
    [ -n "$ENCONTRADOS" ] && break
    printf '.'
    sleep 3
    SEGUNDOS=$((SEGUNDOS + 3))
  done
  echo
  if [ -z "$ENCONTRADOS" ]; then
    error "No recibí ningún mensaje. Probá de nuevo cuando tengas Telegram a mano."
    echo "Cuando escribas /id, volvé a correr este asistente o poné tu número en $ENV_FILE" >&2
    exit 1
  fi
  CANTIDAD="$(printf '%s\n' "$ENCONTRADOS" | grep -c . || true)"
  if [ "$CANTIDAD" -gt 1 ]; then
    aviso "Le escribieron al bot varias personas:"
    printf '   %s\n' "$ENCONTRADOS"
    if [ "$INTERACTIVO" -eq 1 ]; then
      printf '¿Cuáles autorizo? (números separados por coma, según el orden de arriba): '
      read -r OBJETIVOS
      IDS=""
      for numero in $(printf '%s' "$OBJETIVOS" | tr ',' ' '); do
        elegido="$(printf '%s\n' "$ENCONTRADOS" | sed -n "${numero}p" | cut -d' ' -f1)"
        [ -n "$elegido" ] && IDS="${IDS:+$IDS,}$elegido"
      done
      [ -n "$IDS" ] || { error "No entendí la elección."; exit 1; }
    else
      IDS="$(printf '%s\n' "$ENCONTRADOS" | head -1 | cut -d' ' -f1)"
      aviso "Sin terminal, autorizo solo al primero: $IDS"
    fi
  else
    IDS="$(printf '%s\n' "$ENCONTRADOS" | cut -d' ' -f1)"
    NOMBRE="$(printf '%s\n' "$ENCONTRADOS" | cut -d' ' -f3-)"
    ok "Tu ID es $IDS ($NOMBRE)"
    if [ "$INTERACTIVO" -eq 1 ]; then
      printf '¿Autorizo a ese ID? [S/n]: '
      read -r CONFIRMA
      case "${CONFIRMA:-s}" in
        s|S|si|sí|y|Y) ;;
        *) error "Ok, no cambio nada."; exit 1 ;;
      esac
    fi
  fi
fi

# --- 3. Transcripción local -------------------------------------------------
info "Transcripción de audio y video"
MOTOR_ACTUAL="$(leer_env TRANSCRIPTION_ENGINE)"
QUIERE_MOTOR=0
if [ -n "$MOTOR_ACTUAL" ]; then
  ok "Ya está encendida ($MOTOR_ACTUAL)"
  QUIERE_MOTOR=1
elif [ "$INTERACTIVO" -eq 1 ]; then
  printf '¿Querés transcribir audios y videos? Agrega ~350 MB de disco y usa hasta ~400 MB de memoria mientras transcribe. [s/N]: '
  read -r RESPUESTA_MOTOR
  case "${RESPUESTA_MOTOR:-n}" in s|S|si|sí|y|Y) QUIERE_MOTOR=1 ;; esac
else
  aviso "Sin terminal: la dejo apagada (se enciende después con TRANSCRIPTION_ENGINE)."
fi

if [ "$QUIERE_MOTOR" -eq 1 ]; then
  if "$PY" -c 'import faster_whisper' >/dev/null 2>&1; then
    ok "El motor (faster-whisper) ya está instalado"
  elif [ "$SIMULAR" -eq 1 ]; then
    aviso "Falta el motor: en la corrida real correría: $PY -m pip install faster-whisper"
  else
    info "Instalando el motor local (puede tardar unos minutos)"
    if "$PY" -m pip install --quiet faster-whisper; then
      ok "Motor instalado"
    else
      aviso "No se pudo instalar: el bot funciona igual, sin transcripción."
      QUIERE_MOTOR=0
    fi
  fi
fi

# --- 4. Dónde quedan las notas ---------------------------------------------
info "Carpeta del vault en el servidor"
VAULT_ACTUAL="$(leer_env VAULT_PATH)"
VAULT_ACTUAL="${VAULT_ACTUAL:-/srv/obsidian/Open_Vault}"
echo "Actual: $VAULT_ACTUAL"
if [ "$INTERACTIVO" -eq 1 ]; then
  printf '¿La cambio? (Enter para dejarla, o pegá otra ruta): '
  read -r VAULT_NUEVO
  VAULT_FINAL="${VAULT_NUEVO:-$VAULT_ACTUAL}"
else
  VAULT_FINAL="$VAULT_ACTUAL"
fi
USUARIO_SERVICIO="$(systemctl show "$SERVICIO" -p User --value 2>/dev/null || true)"
USUARIO_SERVICIO="${USUARIO_SERVICIO:-openvault}"

# --- 5. Guardar --------------------------------------------------------------
echo
info "Resumen"
echo "  Bot:              @$BOT_USUARIO"
echo "  IDs autorizados:  $IDS"
echo "  Transcripción:    $([ "$QUIERE_MOTOR" -eq 1 ] && echo 'encendida (faster-whisper)' || echo 'apagada')"
echo "  Vault:            $VAULT_FINAL"
if [ "$SIMULAR" -eq 1 ]; then
  echo
  ok "Simulación: no toqué nada (esto es --simular)."
  exit 0
fi

poner_env BOT_TOKEN "$TOKEN"
poner_env ALLOWED_TELEGRAM_USER_IDS "$IDS"
poner_env VAULT_PATH "$VAULT_FINAL"
if [ "$QUIERE_MOTOR" -eq 1 ]; then
  poner_env TRANSCRIPTION_ENGINE "faster-whisper"
  [ -n "$(leer_env TRANSCRIPTION_CACHE)" ] || poner_env TRANSCRIPTION_CACHE "$APP_DIR/modelos-whisper"
  install -d -o "$USUARIO_SERVICIO" -g "$USUARIO_SERVICIO" "$APP_DIR/modelos-whisper"
else
  poner_env TRANSCRIPTION_ENGINE ""
fi
chown "$USUARIO_SERVICIO:$USUARIO_SERVICIO" "$ENV_FILE"
chmod 600 "$ENV_FILE"
install -d -o "$USUARIO_SERVICIO" -g "$USUARIO_SERVICIO" -m 0750 "$VAULT_FINAL"
ok "Configuración guardada en $ENV_FILE (solo la lee el usuario $USUARIO_SERVICIO)"

# --- 6. Arrancar y probar ---------------------------------------------------
info "Arrancando el bot"
systemctl restart "$SERVICIO"
sleep 6
if systemctl is-active --quiet "$SERVICIO"; then
  ok "El servicio está corriendo"
else
  error "El servicio no arrancó. Mirá qué pasó: journalctl -u $SERVICIO -n 30"
  systemctl status "$SERVICIO" --no-pager | tail -12 >&2 || true
  exit 1
fi

PRIMER_ID="$(printf '%s' "$IDS" | cut -d, -f1)"
PRUEBA="$(api "$TOKEN" sendMessage "{\"chat_id\": $PRIMER_ID, \"text\": \"Open_Vault quedó configurado. Mandame un link, una foto, una nota de voz o un video y lo guardo en tu vault.\"}")"
if [ "$(campo "$PRUEBA" ok)" = "True" ]; then
  ok "Te mandé un mensaje de prueba: si te llegó, está todo conectado"
else
  aviso "No pude mandarte el mensaje de prueba: $(campo "$PRUEBA" description)"
fi

cat <<FIN
$(printf '\033[1;32mListo.\033[0m')

Cómo usarlo:
  · Telegram: mandá lo que quieras guardar a @$BOT_USUARIO
  · En tu computadora: doble clic en visor\\sincronizar.cmd (trae las notas y las sube)
  · En Obsidian: "Abrir carpeta como vault" apuntando a esa carpeta
  · En el celular: Obsidian + plugin Git → clonar tu repo privado y hacer Pull

Si algo no anda:  journalctl -u $SERVICIO -f
FIN
