from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from open_vault.classify import classify
from open_vault.extract import PageContent, validate_public_http_url
from open_vault.media import is_video_url, video_thumbnail
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


class PageContentTests(unittest.TestCase):
    def test_page_content_holds_metadata(self) -> None:
        page = PageContent(url="https://example.org/a", title="T", text="cuerpo", site_name="example.org")
        self.assertEqual(page.image_url, "")
        self.assertEqual(page.site_name, "example.org")


if __name__ == "__main__":
    unittest.main()
