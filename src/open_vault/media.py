"""Medios: OCR local, detección de videos y miniatura con ffmpeg.

Todo local. Tesseract para el texto dentro de las imágenes y ffmpeg (si está
instalado) para sacarle un cuadro al video: así un video también entra al vault
como algo que se ve, y no solo como un enlace.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .extract import validate_public_http_url

VIDEO_HOSTS = {
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "vimeo.com",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "dailymotion.com",
    "twitch.tv",
}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".svg"}


def _host_matches(host: str, domain: str) -> bool:
    """`notyoutube.com` no es YouTube: se compara la etiqueta completa."""
    host = host.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def ocr_image(image_path: Path, language: str = "spa+eng") -> str:
    if not shutil.which("tesseract"):
        raise RuntimeError("Tesseract is not installed; install tesseract-ocr and language data")
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", language],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        detail = result.stderr.strip()[-500:]
        raise RuntimeError(f"OCR failed: {detail}")
    text = result.stdout.strip()
    if not text:
        raise ValueError("OCR found no readable text")
    return text


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def is_video_url(value: str) -> bool:
    """¿Es un video? Por host conocido o por extensión del archivo."""
    try:
        host = urlparse(validate_public_http_url(value)).hostname or ""
    except ValueError:
        return False
    if any(_host_matches(host, domain) for domain in VIDEO_HOSTS):
        return True
    return Path(urlparse(value).path).suffix.lower() in VIDEO_SUFFIXES


def is_image_suffix(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_SUFFIXES


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_frame(video_path: Path, destination: Path, second: float, *, width: int = 880) -> bool:
    """Extrae un cuadro en el segundo pedido. True si quedó un archivo con contenido."""
    seek = ["-ss", str(second)] if second > 0 else []
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            *seek,
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-y",
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0 and destination.is_file() and destination.stat().st_size > 0:
        return True
    # Un intento fallido puede dejar un archivo vacío: no sirve como miniatura.
    destination.unlink(missing_ok=True)
    return False


def video_thumbnail(video_path: Path, destination: Path, *, second: float = 2.0) -> bool:
    """Saca un cuadro del video. Devuelve False (sin romper nada) si no hay ffmpeg.

    Si el video es más corto que `second`, se reintenta con el primer cuadro:
    buscar el segundo 2 en un clip de 2 segundos no devuelve nada.
    """
    if not ffmpeg_available() or not video_path.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    attempts = [second, 0.0] if second > 0 else [0.0]
    return any(_extract_frame(video_path, destination, attempt) for attempt in attempts)


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def video_duration(video_path: Path) -> float | None:
    """Duración del video en segundos, o None si no se puede saber."""
    if not ffprobe_available() or not video_path.is_file():
        return None
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def extract_audio(video_path: Path, destination: Path) -> bool:
    """Saca el audio como WAV mono de 16 kHz: el formato que comen los motores."""
    if not ffmpeg_available() or not video_path.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "-y",
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    ok = result.returncode == 0 and destination.is_file() and destination.stat().st_size > 44
    if not ok:
        destination.unlink(missing_ok=True)
    return ok


def video_frames(video_path: Path, folder: Path, count: int = 4, *, width: int = 1280) -> list[Path]:
    """Cuadros repartidos a lo largo del video, para leer el texto que aparece en pantalla.

    Son temporales: se leen y se tiran. Al vault solo va el texto, así el video no
    suma peso al disco.
    """
    if not ffmpeg_available() or not video_path.is_file() or count <= 0:
        return []
    folder.mkdir(parents=True, exist_ok=True)
    duration = video_duration(video_path) or 0.0
    if duration > 0:
        momentos = [duration * (indice + 1) / (count + 1) for indice in range(count)]
    else:
        momentos = [0.0]
    cuadros: list[Path] = []
    for indice, segundo in enumerate(momentos, start=1):
        destino = folder / f"cuadro-{indice:02d}.jpg"
        if _extract_frame(video_path, destino, round(segundo, 2), width=width):
            cuadros.append(destino)
    return cuadros


def merge_ocr_texts(texts: Iterable[str], *, limit: int = 4000) -> str:
    """Une el texto de varios cuadros sin repetir líneas repetidas entre cuadros."""
    vistos: set[str] = set()
    lineas: list[str] = []
    for text in texts:
        for linea in text.splitlines():
            limpia = " ".join(linea.split())
            clave = limpia.casefold()
            if len(limpia) < 3 or clave in vistos:
                continue
            vistos.add(clave)
            lineas.append(limpia)
    return "\n".join(lineas)[:limit]


def ocr_frames(frames: Iterable[Path], language: str = "spa+eng") -> str:
    """Lee el texto de cada cuadro. Los que no dan texto legible se ignoran."""
    textos = []
    for frame in frames:
        try:
            textos.append(ocr_image(frame, language))
        except (RuntimeError, ValueError):
            continue
    return merge_ocr_texts(textos)
