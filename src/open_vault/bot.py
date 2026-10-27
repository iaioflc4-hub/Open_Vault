"""Bot de Telegram: la única puerta de entrada.

Se maneja por long polling, así que **no hace falta abrir ningún puerto ni
webhook**: el proceso sale a buscar los mensajes. Eso permite correrlo igual en
el VPS o en una notebook, y quien replique el proyecto solo necesita su token.

Qué se puede mandar:
  - texto suelto            -> nota enriquecida
  - una URL de página       -> texto íntegro + imagen principal + estructura
  - una URL de video        -> referencia, miniatura si hay ffmpeg
  - una imagen o captura    -> original guardado + OCR
  - un video (archivo)      -> original local + miniatura, texto en pantalla y
                               transcripción si el motor local está activado
"""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .config import Settings, load_settings
from .extract import download_image, extract_page, validate_public_http_url
from .media import (
    extract_audio,
    ffmpeg_available,
    is_video_url,
    ocr_available,
    ocr_frames,
    ocr_image,
    video_duration,
    video_frames,
    video_thumbnail,
)
from .transcribe import available as transcription_available
from .transcribe import transcribe
from .vault import ATTACHMENTS_DIR, save_note, save_text_note, save_video_reference

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOG = logging.getLogger("open_vault")

URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
MAX_TITLE = 120

AYUDA = (
    "Mandame lo que querés guardar:\n\n"
    "• *Texto*: lo guarda como nota (con estructura, cifras y etiquetas).\n"
    "• *Link de una web*: extrae el texto íntegro, sin resumir, y le agrega la "
    "imagen principal.\n"
    "• *Imagen*: guarda el original y le saca el texto con OCR.\n"
    "• *Video* (enlace o archivo): guarda la referencia, una miniatura y lo que se "
    "pueda leer del contenido.\n\n"
    "Todo queda en tu vault de Obsidian, sin pasar por servicios de resumen.\n"
    "Usá /id si necesitás ver tu ID de Telegram."
)


def authorized(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.allowed_user_ids)


async def reject_unless_allowed(update: Update, settings: Settings) -> bool:
    if authorized(update, settings):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Acceso no autorizado. Este bot es privado.")
    return False


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _title_from_text(text: str, fallback: str) -> str:
    first_line = next((line.strip("# -") for line in text.splitlines() if line.strip()), "")
    return (first_line or fallback)[:MAX_TITLE]


def _saved_reply(path: Path, vault: Path) -> str:
    return f"Guardado en tu vault: `{path.relative_to(vault).as_posix()}`"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not await reject_unless_allowed(update, settings):
        return
    await update.effective_message.reply_text(AYUDA, parse_mode="Markdown")


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        await update.effective_message.reply_text(f"Tu ID numérico de Telegram es: {user.id}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not await reject_unless_allowed(update, settings):
        return
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return
    match = URL_RE.search(text)
    if not match:
        await _save_plain_text(message, text, settings)
        return
    url = match.group(0).rstrip(".,);]}")
    await _save_url(message, url, text, settings)


async def _save_plain_text(message, text: str, settings: Settings) -> None:
    try:
        title = _title_from_text(text, "Nota desde Telegram")
        source = f"telegram://text/{abs(hash(text)):x}"
        path = await asyncio.to_thread(
            save_text_note, settings.vault_path, title=title, content=text, source=source
        )
        await message.reply_text(_saved_reply(path, settings.vault_path))
    except Exception as exc:  # noqa: BLE001 - se informa al usuario, no se cae el bot
        LOG.exception("Text capture failed")
        await message.reply_text(f"No pude guardar el texto: {exc}")


async def _save_url(message, url: str, original_text: str, settings: Settings) -> None:
    try:
        validate_public_http_url(url)
    except ValueError as exc:
        await message.reply_text(f"No puedo abrir esa URL: {exc}")
        return
    if is_video_url(url):
        try:
            path = await asyncio.to_thread(
                save_video_reference, settings.vault_path, title=urlparse(url).netloc or "Video", source=url
            )
            await message.reply_text(
                f"{_saved_reply(path, settings.vault_path)}\n"
                "Transcripción pendiente: no se envió el video a ningún servicio externo."
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Video reference failed")
            await message.reply_text(f"No pude guardar la referencia del video: {exc}")
        return

    try:
        page = await asyncio.to_thread(extract_page, url, settings.max_download_bytes)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Page extraction failed")
        await message.reply_text(f"No pude leer esa página: {exc}")
        return

    hero = None
    if settings.fetch_main_image and page.image_url:
        hero = await _download_main_image(page.image_url, page.url, settings)

    content = page.text
    if original_text.strip() and original_text.strip() != url:
        content = f"{content}\n\n## Comentario propio\n\n{original_text.strip()}"
    try:
        path = await asyncio.to_thread(
            save_note,
            settings.vault_path,
            title=page.title[:MAX_TITLE] or url,
            content=content,
            source=page.url,
            kind="web",
            hero=hero,
            note_metadata={"site": page.site_name} if page.site_name else None,
        )
        await message.reply_text(_saved_reply(path, settings.vault_path))
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Note saving failed")
        await message.reply_text(f"No pude guardar esa página: {exc}")


async def _download_main_image(image_url: str, page_url: str, settings: Settings) -> str | None:
    """Baja la imagen principal a `Attachments/`. Si falla, la captura sigue igual."""
    name = f"web-{abs(hash(page_url)):x}{Path(urlparse(image_url).path).suffix or '.jpg'}"
    destination = settings.vault_path / ATTACHMENTS_DIR / name
    ok = await asyncio.to_thread(download_image, image_url, destination, max_bytes=settings.max_image_bytes)
    return name if ok else None


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not await reject_unless_allowed(update, settings):
        return
    message = update.effective_message
    photo = message.photo[-1] if message.photo else message.document
    if photo is None:
        return
    if photo.file_size and photo.file_size > settings.max_download_bytes:
        await message.reply_text("La imagen supera el límite de tamaño configurado.")
        return
    suffix = Path(getattr(photo, "file_name", "") or "imagen.jpg").suffix or ".jpg"
    attachment = f"telegram-{photo.file_unique_id}{suffix.lower()}"
    target = settings.vault_path / ATTACHMENTS_DIR / attachment
    try:
        text = ""
        with tempfile.TemporaryDirectory(prefix="openvault-") as tmp:
            image_path = Path(tmp) / f"imagen{suffix}"
            tg_file = await context.bot.get_file(photo.file_id)
            await tg_file.download_to_drive(image_path)
            if ocr_available():
                try:
                    text = await asyncio.to_thread(ocr_image, image_path, settings.ocr_language)
                except (RuntimeError, ValueError) as exc:
                    LOG.warning("OCR without text: %s", exc)
                    text = ""
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(image_path.read_bytes())

        caption = (message.caption or "").strip()
        title = caption or _title_from_text(text, f"Imagen del {message.date:%Y-%m-%d}")
        body = text or "Sin texto legible en la imagen (OCR vacío o no disponible)."
        if caption and text:
            body = f"{caption}\n\n## Texto reconocido (OCR)\n\n{text}"
        note = await asyncio.to_thread(
            save_note,
            settings.vault_path,
            title=title,
            content=body,
            source=f"telegram://photo/{photo.file_unique_id}",
            kind="image-ocr",
            category="Imágenes",
            attachments=[attachment],
            hero=attachment,
        )
        detail = "con texto OCR" if text else "sin texto legible"
        await message.reply_text(f"{_saved_reply(note, settings.vault_path)} ({detail})")
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Image capture failed")
        await message.reply_text(f"No pude procesar la imagen: {exc}")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    if not await reject_unless_allowed(update, settings):
        return
    message = update.effective_message
    video = message.video or message.document
    if not video:
        return
    if video.file_size and video.file_size > settings.max_download_bytes:
        await message.reply_text(
            "El video supera el límite para guardarlo desde Telegram. Mandame el enlace y guardo la referencia."
        )
        return
    suffix = Path(getattr(video, "file_name", None) or "video.mp4").suffix or ".mp4"
    attachment = f"telegram-{video.file_unique_id}{suffix.lower()}"
    target = settings.vault_path / ATTACHMENTS_DIR / attachment
    try:
        with tempfile.TemporaryDirectory(prefix="openvault-") as tmp:
            local = Path(tmp) / f"video{suffix}"
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                tg_file = await context.bot.get_file(video.file_id)
                await tg_file.download_to_drive(local)
                target.write_bytes(local.read_bytes())

        thumbnail = None
        if settings.video_thumbnails:
            frame = settings.vault_path / ATTACHMENTS_DIR / f"{attachment.rsplit('.', 1)[0]}-miniatura.jpg"
            if await asyncio.to_thread(video_thumbnail, target, frame):
                thumbnail = frame.name

        avisos = ["con miniatura" if thumbnail else "sin miniatura (falta ffmpeg)"]
        duration = await asyncio.to_thread(video_duration, target)
        on_screen_text = ""
        transcript = None

        # Cuadros y audio se leen en una carpeta temporal: al vault solo va el texto
        # (si no, mirar un video sumaría varios MB de fotogramas al disco).
        with tempfile.TemporaryDirectory(prefix="openvault-") as tmp:
            trabajo = Path(tmp)
            if settings.video_frames > 0 and ffmpeg_available():
                frames = await asyncio.to_thread(video_frames, target, trabajo, settings.video_frames)
                if frames:
                    on_screen_text = await asyncio.to_thread(ocr_frames, frames, settings.ocr_language)
                    avisos.append(
                        f"texto en pantalla de {len(frames)} cuadros" if on_screen_text else "sin texto en pantalla"
                    )
            if transcription_available(settings.transcription_engine):
                audio = trabajo / "audio.wav"
                if await asyncio.to_thread(extract_audio, target, audio):
                    try:
                        transcript = await asyncio.to_thread(
                            transcribe,
                            audio,
                            language=settings.transcription_language,
                            model=settings.transcription_model,
                        )
                    except Exception as exc:  # noqa: BLE001 - el video se guarda igual
                        LOG.warning("Transcription failed: %s", exc)
                    avisos.append("transcripción lista" if transcript else "sin transcripción")
            elif settings.transcription_engine:
                avisos.append("transcripción apagada: el motor local no está instalado")
            else:
                avisos.append("transcripción apagada (TRANSCRIPTION_ENGINE vacío)")

        note = await asyncio.to_thread(
            save_video_reference,
            settings.vault_path,
            title=(message.caption or "").strip() or f"Video del {message.date:%Y-%m-%d}",
            source=f"telegram://video/{video.file_unique_id}",
            thumbnail=thumbnail,
            local_file=attachment,
            transcript=transcript,
            on_screen_text=on_screen_text,
            duration=duration,
        )
        await message.reply_text(f"{_saved_reply(note, settings.vault_path)}\n" + " · ".join(avisos))
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Video storage failed")
        await message.reply_text(f"No pude guardar el video: {exc}")


def build_application(settings: Settings) -> Application:
    """Arma la app de Telegram. Separado de `main` para poder testearlo."""
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("id", show_id))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return application


def main() -> None:
    settings = load_settings()
    if not settings.bot_token:
        raise SystemExit(
            "Falta BOT_TOKEN en el archivo .env: creá un bot con @BotFather y pegá el token ahí."
        )
    if not settings.allowed_user_ids:
        raise SystemExit(
            "Falta ALLOWED_TELEGRAM_USER_IDS en el .env: escribile /id al bot y poné tu ID numérico."
        )
    LOG.info("Open_Vault escuchando. Vault: %s", settings.vault_path)
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
