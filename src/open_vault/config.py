"""Configuración: todo sale del `.env`, que nunca se versiona.

Sin `BOT_TOKEN` y sin al menos un ID autorizado el bot no arranca y dice qué
falta. Preferimos eso a un servicio corriendo en bucle contra la API de Telegram
sin permiso para nada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_VAULT = "/srv/obsidian/Open_Vault"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int]
    vault_path: Path
    max_download_bytes: int
    ocr_language: str
    fetch_main_image: bool
    video_thumbnails: bool
    max_image_bytes: int


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "si", "sí", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    raw_users = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
    try:
        allowed_users = frozenset(int(value.strip()) for value in raw_users.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError("ALLOWED_TELEGRAM_USER_IDS must be comma-separated numeric IDs") from exc
    max_mb = int(os.getenv("MAX_DOWNLOAD_MB", "18"))
    if max_mb < 1 or max_mb > 100:
        raise ValueError("MAX_DOWNLOAD_MB must be between 1 and 100")
    max_image_mb = int(os.getenv("MAX_IMAGE_MB", "3"))
    if max_image_mb < 1 or max_image_mb > 20:
        raise ValueError("MAX_IMAGE_MB must be between 1 and 20")
    return Settings(
        bot_token=token,
        allowed_user_ids=allowed_users,
        vault_path=Path(os.getenv("VAULT_PATH", DEFAULT_VAULT)).expanduser(),
        max_download_bytes=max_mb * 1024 * 1024,
        ocr_language=os.getenv("OCR_LANGUAGE", "spa+eng").strip() or "spa+eng",
        fetch_main_image=_flag("FETCH_MAIN_IMAGE", True),
        video_thumbnails=_flag("VIDEO_THUMBNAILS", True),
        max_image_bytes=max_image_mb * 1024 * 1024,
    )
