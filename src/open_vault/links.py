"""Enlaces de video: sacarles el contenido sin depender de la suerte.

Un link de YouTube o de Instagram no se puede leer como una página: el contenido
está dentro del video. Acá se lo saca en dos intentos, en este orden:

1. **API pública tipo Piped** (para YouTube): devuelve título, canal, duración,
   descripción y miniatura reales. Funciona desde un servidor sin cuenta ni
   cookies, que es justo el caso de un VPS.
2. **yt-dlp** (para todo lo demás): Instagram, TikTok, Vimeo, Twitter… De ahí se
   bajan los subtítulos si existen y, si no, solo el audio, que se transcribe en
   la misma máquina.

YouTube bloquea la descarga desde una IP de servidor ("confirmá que no sos un
bot"). Con `YTDLP_COOKIES` apuntando a un archivo de cookies exportado del
navegador se destraba, y también se pueden bajar sus subtítulos. Sin cookies, al
menos queda la ficha real del video en lugar de un enlace pelado.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .enrich import hashtags

# Instancias públicas probadas: la primera responde desde el servidor de
# referencia. Se prueban en orden y se usa la primera que devuelva datos.
PIPED_INSTANCES = (
    "https://api.piped.private.coffee",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
)
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
SUBTITLE_LANGS = ("es", "en")
VTT_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s*-->")
TAG_RE = re.compile(r"<[^>]+>")
MAX_AUDIO_SECONDS = int(os.getenv("LINK_AUDIO_MAX_SECONDS", "1800"))


@dataclass
class LinkInfo:
    """Lo que se pudo sacar de un enlace de video."""

    url: str
    title: str = ""
    uploader: str = ""
    duration: float | None = None
    description: str = ""
    thumbnail_url: str = ""
    transcript: str = ""
    transcript_source: str = ""
    audio_path: Path | None = None
    note: str = ""
    extra_tags: list[str] = field(default_factory=list)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold()


def youtube_id(url: str) -> str | None:
    """ID del video si el enlace es de YouTube. `None` si es de otro sitio."""
    host = _host(url)
    if not any(host == esperado or host.endswith(f".{esperado}") for esperado in YOUTUBE_HOSTS):
        return None
    parsed = urlparse(url)
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0] or None
    if parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
        return parsed.path.strip("/").split("/")[1] or None
    return parse_qs(parsed.query).get("v", [""])[0] or None


def _get_json(url: str, *, timeout: int = 25) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None
    return datos if isinstance(datos, dict) else None


def _texto_plano(texto: str) -> str:
    """El HTML que viene en las descripciones no tiene nada que hacer en la nota."""
    limpio = html.unescape(texto or "")
    limpio = re.sub(r"<br\s*/?>", "\n", limpio, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", TAG_RE.sub("", limpio)).strip()


def vtt_to_text(vtt: str) -> str:
    """Convierte subtítulos VTT en texto corrido, sin repetir líneas.

    Los subtítulos automáticos repiten cada línea mientras se van escribiendo:
    sin este filtro el texto sale al doble y es ilegible.
    """
    lineas: list[str] = []
    for bruto in (vtt or "").splitlines():
        linea = TAG_RE.sub("", bruto).strip()
        if not linea or linea.upper().startswith(("WEBVTT", "NOTE", "STYLE", "KIND", "LANGUAGE")):
            continue
        if VTT_TIMESTAMP_RE.match(linea) or "-->" in linea:
            continue
        texto = re.sub(r"\s+", " ", linea).strip()
        if not texto or texto.isdigit():
            continue
        if lineas and lineas[-1].casefold() == texto.casefold():
            continue
        lineas.append(texto)
    return " ".join(lineas).strip()


def piped_metadata(video_id: str) -> LinkInfo | None:
    """Ficha del video por API pública: sin cookies y sin bajar el archivo."""
    for instancia in PIPED_INSTANCES:
        datos = _get_json(f"{instancia}/streams/{video_id}")
        if not datos or not datos.get("title"):
            continue
        info = LinkInfo(
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=_texto_plano(str(datos["title"]))[:200],
            uploader=_texto_plano(str(datos.get("uploader") or ""))[:120],
            duration=float(datos["duration"]) if datos.get("duration") else None,
            description=_texto_plano(str(datos.get("description") or ""))[:4000],
            thumbnail_url=str(datos.get("thumbnailUrl") or ""),
            note=f"ficha vía {urlparse(instancia).netloc}",
        )
        info.extra_tags = hashtags(f"{info.title} {info.description}")
        return info
    return None


def ytdlp_available() -> bool:
    """yt-dlp instalado en el mismo entorno que el bot."""
    return shutil.which("yt-dlp") is not None or importlib_find("yt_dlp")


def importlib_find(nombre: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(nombre) is not None


def cookies_path() -> str:
    return os.getenv("YTDLP_COOKIES", "").strip()


def _ytdlp(extra: list[str], *, timeout: int = 240) -> subprocess.CompletedProcess | None:
    """yt-dlp como módulo del mismo intérprete: no depende del PATH del servicio."""
    if not ytdlp_available():
        return None
    comando = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist"]
    cookies = cookies_path()
    if cookies:
        comando += ["--cookies", cookies]
    try:
        return subprocess.run(
            comando + extra, check=False, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def ytdlp_metadata(url: str) -> LinkInfo | None:
    """Ficha del video con yt-dlp (sirve para casi cualquier sitio)."""
    resultado = _ytdlp(["--dump-single-json", "--skip-download", url], timeout=180)
    if resultado is None or resultado.returncode != 0 or not resultado.stdout.strip():
        return None
    try:
        datos = json.loads(resultado.stdout)
    except ValueError:
        return None
    info = LinkInfo(
        url=url,
        title=_texto_plano(str(datos.get("title") or ""))[:200],
        uploader=_texto_plano(str(datos.get("uploader") or datos.get("channel") or ""))[:120],
        duration=float(datos["duration"]) if datos.get("duration") else None,
        description=_texto_plano(str(datos.get("description") or ""))[:4000],
        thumbnail_url=str(datos.get("thumbnail") or ""),
        note="ficha vía yt-dlp",
    )
    if datos.get("is_live"):
        info.note += " (transmisión en vivo)"
    info.extra_tags = hashtags(f"{info.title} {info.description}")
    return info


def ytdlp_transcript(url: str, folder: Path, *, timeout: int = 240) -> tuple[str, str]:
    """Subtítulos del video si existen. Devuelve (texto, de dónde salió)."""
    folder.mkdir(parents=True, exist_ok=True)
    idiomas = ",".join(f"{codigo}.*" for codigo in SUBTITLE_LANGS) + ",es,en"
    resultado = _ytdlp(
        [
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            idiomas,
            "--sub-format",
            "vtt",
            "--paths",
            f"temp:{folder}",
            "-o",
            "subs.%(language)s.%(ext)s",
            url,
        ],
        timeout=timeout,
    )
    if resultado is None:
        return "", ""
    for archivo in sorted(folder.glob("subs*.vtt")):
        texto = vtt_to_text(archivo.read_text(encoding="utf-8", errors="replace"))
        if len(texto) > 40:
            idioma = archivo.stem.split(".")[-1]
            tipo = "automáticos" if "orig" in archivo.name else "del propio video"
            return texto, f"subtítulos {tipo} ({idioma})"
    return "", ""


def ytdlp_audio(url: str, folder: Path, *, max_seconds: int = 0, timeout: int = 900) -> Path | None:
    """Baja solo el audio para transcribirlo acá. Corta los videos muy largos."""
    folder.mkdir(parents=True, exist_ok=True)
    tope = max_seconds or MAX_AUDIO_SECONDS
    extra = ["-f", "bestaudio/best", "-x", "--audio-format", "wav", "--audio-quality", "5", "--max-filesize", "80M"]
    if tope > 0:
        extra += ["--download-sections", f"*0-{tope}"]
    extra += ["-o", "audio.%(ext)s", url]
    if _ytdlp(extra, timeout=timeout) is None:
        return None
    for archivo in sorted(folder.glob("audio.*")):
        if archivo.stat().st_size > 1024:
            return archivo
    return None


def fetch_video_link(url: str, trabajo: Path) -> LinkInfo:
    """Todo lo que se puede sacar de un enlace de video, sin fallar en silencio.

    `trabajo` es una carpeta temporal que administra quien llama: ahí queda el
    audio descargado (si hizo falta) mientras se lo transcribe.
    """
    video_id = youtube_id(url)
    info = piped_metadata(video_id) if video_id else None
    if info is None:
        info = ytdlp_metadata(url)
    if info is None:
        return LinkInfo(
            url=url,
            note="no pude leer la ficha: el sitio la pide con sesión iniciada o bloquea la IP del servidor",
        )

    if not ytdlp_available():
        info.note += " · falta yt-dlp: sin subtítulos ni audio"
        return info

    carpeta = trabajo / "enlace"
    carpeta.mkdir(parents=True, exist_ok=True)
    texto, origen = ytdlp_transcript(url, carpeta)
    if texto:
        info.transcript = texto
        info.transcript_source = origen
        return info

    audio = ytdlp_audio(url, carpeta)
    if audio is None:
        info.note += (
            " · no pude bajar subtítulos ni audio; en YouTube suele ser el bloqueo a la IP "
            "del servidor (se destraba con YTDLP_COOKIES)"
        )
        return info
    info.audio_path = audio
    info.note += " · audio bajado para transcribir acá"
    return info


__all__ = [
    "LinkInfo",
    "fetch_video_link",
    "piped_metadata",
    "vtt_to_text",
    "ytdlp_audio",
    "ytdlp_available",
    "ytdlp_metadata",
    "ytdlp_transcript",
    "youtube_id",
]
