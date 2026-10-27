from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from open_vault.classify import classify
from open_vault.config import load_settings
from open_vault.extract import PageContent, validate_public_http_url
from open_vault.media import is_video_url, merge_ocr_texts, video_duration, video_frames, video_thumbnail
from open_vault.transcribe import available as transcription_available
from open_vault.transcribe import transcribe
from open_vault.vault import render_attachment, save_note, save_text_note, save_video_reference


class ClassifyTests(unittest.TestCase):
    def test_classifies_technology(self) -> None:
        self.assertEqual(classify("Python software y tecnología"), "Tecnología")

    def test_unknown_text_is_uncategorized(self) -> None:
        self.assertEqual(classify("texto sin términos conocidos"), "Por clasificar")


class UrlSafetyTests(unittest.TestCase):
    def test_rejects_non_http_and_credentials(self) -> None:
        with self.assertRaises(ValueError):
            validate_public_http_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validate_public_http_url("https://user:pass@example.org/path")

    @patch("open_vault.extract.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))])
    def test_rejects_private_resolved_address(self, _lookup) -> None:
        with self.assertRaisesRegex(ValueError, "Private"):
            validate_public_http_url("http://localhost/test")

    @patch("open_vault.extract.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 80))])
    def test_rejects_lan_address(self, _lookup) -> None:
        with self.assertRaises(ValueError):
            validate_public_http_url("http://intranet.local/api")


class ThumbnailTests(unittest.TestCase):
    def test_missing_file_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(video_thumbnail(Path(temp) / "no-existe.mp4", Path(temp) / "salida.jpg"))

    def test_returns_false_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "video.mp4"
            video.write_bytes(b"no es un video")
            with patch("open_vault.media.shutil.which", return_value=None):
                self.assertFalse(video_thumbnail(video, Path(temp) / "salida.jpg"))


class VideoReadingTests(unittest.TestCase):
    def test_ocr_merge_drops_repeated_and_short_lines(self) -> None:
        merged = merge_ocr_texts(["Hola mundo\nOk\nHola mundo", "Otra linea"])
        self.assertEqual(merged, "Hola mundo\nOtra linea")

    def test_no_frames_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(video_frames(Path(temp) / "no-existe.mp4", Path(temp), 0), [])
            self.assertEqual(video_frames(Path(temp) / "no-existe.mp4", Path(temp), 4), [])

    def test_duration_is_none_without_a_readable_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(video_duration(Path(temp) / "no-existe.mp4"))

    def test_audio_extraction_refuses_missing_file(self) -> None:
        from open_vault.media import extract_audio

        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(extract_audio(Path(temp) / "no-existe.mp4", Path(temp) / "audio.wav"))


class TranscriptionTests(unittest.TestCase):
    def test_off_without_engine(self) -> None:
        with patch.dict(os.environ, {"TRANSCRIPTION_ENGINE": ""}):
            self.assertFalse(transcription_available())

    def test_reports_the_engine_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "audio.wav"
            audio.write_bytes(b"RIFF")
            with patch.dict(os.environ, {"TRANSCRIPTION_ENGINE": "faster-whisper"}):
                with patch("open_vault.transcribe.importlib.util.find_spec", return_value=None):
                    self.assertFalse(transcription_available())
                    with self.assertRaisesRegex(RuntimeError, "no está instalado"):
                        transcribe(audio)

    def test_missing_audio_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "No existe el audio"):
                transcribe(Path(temp) / "nada.wav")


class SettingsTests(unittest.TestCase):
    """La transcripción viene apagada y los topes se validan al arrancar."""

    def leer(self, **entorno: str) -> object:
        base = {"BOT_TOKEN": "123:abc", "ALLOWED_TELEGRAM_USER_IDS": "7"}
        base.update(entorno)
        with patch("open_vault.config.load_dotenv"), patch.dict(os.environ, base, clear=True):
            return load_settings()

    def test_defaults(self) -> None:
        settings = self.leer()
        self.assertEqual(settings.transcription_engine, "")
        self.assertEqual(settings.transcription_model, "tiny")
        self.assertEqual(settings.video_frames, 4)
        self.assertTrue(settings.video_thumbnails)

    def test_transcription_can_be_enabled(self) -> None:
        settings = self.leer(TRANSCRIPTION_ENGINE="faster-whisper", TRANSCRIPTION_LANGUAGE="es")
        self.assertEqual(settings.transcription_engine, "faster-whisper")

    def test_absurd_frame_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.leer(VIDEO_FRAMES="99")


class VideoDetectionTests(unittest.TestCase):
    def test_known_hosts_and_suffixes(self) -> None:
        with patch("open_vault.media.validate_public_http_url", side_effect=lambda value: value):
            self.assertTrue(is_video_url("https://www.youtube.com/watch?v=1"))
            self.assertTrue(is_video_url("https://cdn.example.org/clip.mp4"))
            self.assertFalse(is_video_url("https://notyoutube.com/watch?v=1"))
            self.assertFalse(is_video_url("https://example.org/nota"))


class VaultTests(unittest.TestCase):
    full_text = "Primer párrafo íntegro.\n\nSegundo párrafo con todos sus detalles."
    source = "https://example.org/article?id=7"

    def test_note_preserves_full_content_and_original_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = save_note(Path(temp), title="Artículo científico", content=self.full_text, source=self.source, kind="web")
            saved = path.read_text(encoding="utf-8")
            self.assertIn(self.full_text, saved)
            self.assertIn(self.source, saved)
            self.assertIn('type: "web"', saved)
            self.assertIn("ciencia", str(path.parent))

    def test_note_includes_visual_card_as_svg_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            path = save_note(vault, title="Energía solar", content=self.full_text, source=self.source, kind="web")
            saved = path.read_text(encoding="utf-8")
            self.assertIn("![[Attachments/", saved)
            card = path.parent.parent.parent / "Attachments" / f"{path.stem}-ficha.svg"
            self.assertTrue(card.is_file())
            root = ET.fromstring(card.read_text(encoding="utf-8"))
            self.assertTrue(root.tag.endswith("svg"))
            self.assertIn(f"![[Attachments/{card.name}]]", saved)

    def test_chart_is_created_only_with_enough_figures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            content = "- Cobertura: 87,5 %\n- Ventas: 1.250\n- Sedes: 12\n\n" + self.full_text
            path = save_note(vault, title="Informe de gestión", content=content, source=self.source, kind="web")
            saved = path.read_text(encoding="utf-8")
            self.assertIn("## Cifras destacadas", saved)
            self.assertTrue((vault / "Attachments" / f"{path.stem}-cifras.svg").is_file())

            plain = save_note(vault, title="Sin datos", content=self.full_text, source="https://example.org/otra", kind="web")
            self.assertNotIn("Cifras destacadas", plain.read_text(encoding="utf-8"))

    def test_attachments_are_embedded_when_they_are_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = save_note(
                Path(temp),
                title="Captura de pantalla",
                content="texto",
                source="telegram://photo/abc",
                kind="image-ocr",
                category="Imágenes",
                attachments=["telegram-abc.jpg"],
            )
            saved = path.read_text(encoding="utf-8")
            self.assertIn("![[Attachments/telegram-abc.jpg]]", saved)
            self.assertEqual(render_attachment("Attachments/telegram-abc.jpg"), "![[Attachments/telegram-abc.jpg]]")
            self.assertEqual(render_attachment("notas.pdf"), "[[Attachments/notas.pdf]]")

    def test_frontmatter_carries_tags_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = save_note(Path(temp), title="Panel solar", content=self.full_text, source=self.source, kind="web")
            saved = path.read_text(encoding="utf-8")
            self.assertIn("tags:", saved)
            self.assertIn("words:", saved)
            self.assertIn("reading_minutes:", saved)

    def test_same_source_is_deduplicated_to_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = save_note(Path(temp), title="Una nota", content="Texto", source="https://example.org/a", kind="web")
            second = save_note(Path(temp), title="Una nota", content="Texto actualizado", source="https://example.org/a", kind="web")
            self.assertEqual(first, second)
            self.assertIn("Texto actualizado", second.read_text(encoding="utf-8"))

    def test_plain_text_note_is_enriched_the_same_way(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = save_text_note(Path(temp), title="Idea suelta", content="Recordar comprar filtros", source="telegram://text/1")
            self.assertIn('type: "texto"', path.read_text(encoding="utf-8"))

    def test_video_reference_marks_transcription_pending(self) -> None:
        source = "https://youtu.be/example123"
        with tempfile.TemporaryDirectory() as temp:
            path = save_video_reference(Path(temp), title="Video", source=source, thumbnail="miniatura.jpg")
            saved = path.read_text(encoding="utf-8")
            self.assertIn(source, saved)
            self.assertIn("Pendiente de configurar el proveedor de transcripción", saved)
            self.assertIn("![[Attachments/miniatura.jpg]]", saved)

    def test_video_note_keeps_transcript_and_screen_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = save_video_reference(
                Path(temp),
                title="Charla grabada",
                source="telegram://video/abc",
                transcript="Hola, esto es una prueba de transcripción local.",
                on_screen_text="RESULTADOS 2026\nCobertura 87,5 %",
                duration=95.0,
            )
            saved = path.read_text(encoding="utf-8")
            self.assertIn("## Transcripción", saved)
            self.assertIn("transcripción local", saved)
            self.assertIn("## Texto en pantalla (leído de los cuadros)", saved)
            self.assertIn("Cobertura 87,5 %", saved)
            self.assertIn("1 min 35 s", saved)
            self.assertNotIn("Pendiente de configurar", saved)


class BotWiringTests(unittest.TestCase):
    """Que cada tipo de mensaje tenga quien lo atienda: una nota de voz ignorada en
    silencio es el peor resultado posible (el usuario cree que la mandó)."""

    def aplicacion(self):
        from open_vault.bot import build_application

        with patch("open_vault.config.load_dotenv"), patch.dict(
            os.environ, {"BOT_TOKEN": "123:abc", "ALLOWED_TELEGRAM_USER_IDS": "7"}, clear=True
        ):
            return build_application(load_settings())

    def manejadores(self, actualizacion: object) -> list:
        from telegram.ext import MessageHandler

        aplicacion = self.aplicacion()
        return [
            manejador
            for grupo in aplicacion.handlers.values()
            for manejador in grupo
            if isinstance(manejador, MessageHandler)
            and manejador.filters
            and manejador.filters.check_update(actualizacion)
        ]

    def casos(self) -> dict:
        """Un mensaje de cada tipo que la gente manda de verdad."""
        from datetime import datetime, timezone

        from telegram import (
            Animation,
            Chat,
            Document,
            Message,
            PhotoSize,
            Sticker,
            Update,
            Video,
            VideoNote,
            Voice,
        )

        base = {"message_id": 1, "date": datetime.now(timezone.utc), "chat": Chat(id=7, type=Chat.PRIVATE)}
        archivo = {"file_id": "a", "file_unique_id": "b"}
        return {
            "nota de voz": Update(
                update_id=1, message=Message(voice=Voice(duration=3, **archivo), **base)
            ),
            "video redondo": Update(
                update_id=2,
                message=Message(video_note=VideoNote(length=240, duration=5, **archivo), **base),
            ),
            "gif": Update(
                update_id=3,
                message=Message(
                    animation=Animation(width=320, height=240, duration=2, **archivo), **base
                ),
            ),
            "video": Update(
                update_id=4,
                message=Message(video=Video(width=320, height=240, duration=2, **archivo), **base),
            ),
            "video como archivo": Update(
                update_id=5,
                message=Message(document=Document(**archivo), **base),
            ),
            "foto": Update(
                update_id=6,
                message=Message(photo=[PhotoSize(width=100, height=100, **archivo)], **base),
            ),
            "texto": Update(update_id=7, message=Message(text="una idea", **base)),
        }

    def test_cada_tipo_de_mensaje_tiene_manejador(self) -> None:
        for nombre, actualizacion in self.casos().items():
            with self.subTest(tipo=nombre):
                self.assertTrue(self.manejadores(actualizacion), f"nadie atiende: {nombre}")

    def test_lo_que_no_se_entiende_igual_recibe_respuesta(self) -> None:
        """Un sticker (o cualquier cosa rara) tiene que caer en el último manejador,
        el que avisa, en vez de perderse en silencio."""
        from datetime import datetime, timezone

        from telegram import Chat, Message, Sticker, Update

        actualizacion = Update(
            update_id=9,
            message=Message(
                message_id=1,
                date=datetime.now(timezone.utc),
                chat=Chat(id=7, type=Chat.PRIVATE),
                sticker=Sticker(
                    file_id="a",
                    file_unique_id="b",
                    type="regular",
                    width=100,
                    height=100,
                    is_animated=False,
                    is_video=False,
                ),
            ),
        )
        encontrados = self.manejadores(actualizacion)
        self.assertEqual(len(encontrados), 1, "un mensaje raro tiene que caer en un solo manejador")
        self.assertEqual(encontrados[0].callback.__name__, "handle_unsupported")

    def test_the_id_command_exists_to_discover_your_own_id(self) -> None:
        from telegram.ext import CommandHandler

        aplicacion = self.aplicacion()
        comandos = [
            comando
            for grupo in aplicacion.handlers.values()
            for manejador in grupo
            if isinstance(manejador, CommandHandler)
            for comando in manejador.commands
        ]
        self.assertIn("id", comandos)
        self.assertIn("start", comandos)


class PageContentTests(unittest.TestCase):
    def test_page_content_holds_metadata(self) -> None:
        page = PageContent(url="https://example.org/a", title="T", text="cuerpo", site_name="example.org")
        self.assertEqual(page.image_url, "")
        self.assertEqual(page.site_name, "example.org")


if __name__ == "__main__":
    unittest.main()
