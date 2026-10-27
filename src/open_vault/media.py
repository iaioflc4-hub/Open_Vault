"""Medios: OCR local, detección de videos y miniatura con ffmpeg.

Todo local. Tesseract para el texto dentro de las imágenes y ffmpeg (si está
instalado) para sacarle un cuadro al video: así un video también entra al vault
como algo que se ve, y no solo como un enlace.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
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


def _extract_frame(video_path: Path, destination: Path, second: float) -> bool:
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
            "scale=880:-2",
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
