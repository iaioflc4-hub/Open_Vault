from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_vault.classify import UNCATEGORIZED, classify, classify_or
from open_vault.enrich import hashtags, tags
from open_vault.grafo import MAPA, TEMAS_DIR, tejer
from open_vault.links import vtt_to_text, youtube_id
from open_vault.pdf import pypdf_available, text_of_pdf
from open_vault.reclasificar import reclasificar
from open_vault.vault import save_note, save_video_reference


class ClassifyTests(unittest.TestCase):
    def test_titulo_pesa_mas_que_el_cuerpo(self) -> None:
        cuerpo = "tiene una empresa y habla de mercados y de negocios"
        self.assertEqual(classify(cuerpo, title="¿Qué es Linux y cómo funciona?"), "Tecnología")

    def test_no_clasifica_por_el_formato(self) -> None:
        """Un video sobre Linux va a Tecnología, no a Videos."""
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(
                Path(temp),
                title="¿Qué es Linux?",
                source="https://youtu.be/abc",
                transcript="Linux es un sistema operativo de código abierto.",
            )
            texto = nota.read_text(encoding="utf-8")
            self.assertIn('category: "Tecnología"', texto)
            self.assertIn("tecnologia", str(nota.parent))

    def test_sin_pistas_usa_el_respaldo_del_formato(self) -> None:
        self.assertEqual(classify_or("bla bla", "Videos"), "Videos")
        self.assertEqual(classify("texto sin términos conocidos"), UNCATEGORIZED)

    def test_hashtag_manda_en_la_clasificacion(self) -> None:
        self.assertEqual(classify("#seguridad #linux", title="charla"), "Seguridad")


class HashtagTests(unittest.TestCase):
    def test_etiquetas_escritas_a_mano(self) -> None:
        self.assertEqual(hashtags("hola #Linux y #seguridad, otra vez #linux"), ["linux", "seguridad"])

    def test_las_etiquetas_a_mano_van_primero(self) -> None:
        resultado = tags("#linux texto texto texto")
        self.assertEqual(resultado[0], "linux")


class VideoLinkTests(unittest.TestCase):
    def test_identifica_youtube_y_nada_mas(self) -> None:
        self.assertEqual(youtube_id("https://youtu.be/NIQZOviElSU?si=x"), "NIQZOviElSU")
        self.assertEqual(youtube_id("https://www.youtube.com/watch?v=abc123&t=30"), "abc123")
        self.assertEqual(youtube_id("https://www.youtube.com/shorts/xyz"), "xyz")
        self.assertIsNone(youtube_id("https://www.instagram.com/p/De-a-xmESTg/"))

    def test_subtitulos_vtt_a_texto_sin_repetir(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHola que tal\n\n"
            "00:00:03.500 --> 00:00:05.000\nHola que tal\n\n"
            "00:00:05.000 --> 00:00:07.000\n<c>cómo estás</c>\n"
        )
        self.assertEqual(vtt_to_text(vtt), "Hola que tal cómo estás")

    def test_vtt_vacio_no_rompe(self) -> None:
        self.assertEqual(vtt_to_text(""), "")


class GrafoTests(unittest.TestCase):
    def test_conecta_las_capturas_con_sus_temas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            nota = save_note(
                vault,
                title="Linux y seguridad",
                content="Linux es un sistema operativo. #seguridad",
                source="https://example.org/linux",
                kind="web",
            )
            resumen = tejer(vault)
            self.assertGreaterEqual(resumen["temas"], 1)
            texto = nota.read_text(encoding="utf-8")
            self.assertIn("## Temas", texto)
            self.assertIn("[[Temas/", texto)
            temas = list((vault / TEMAS_DIR).glob("*.md"))
            self.assertTrue(temas, "no se creó ninguna nota de tema")
            self.assertTrue((vault / MAPA).is_file())
            tema = next(t for t in temas if t.stem == "seguridad")
            self.assertIn(f"[[{nota.stem}]]", tema.read_text(encoding="utf-8"))

    def test_es_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            save_note(vault, title="Nota", content="texto con #prueba", source="https://e.org/a", kind="web")
            tejer(vault)
            segunda = tejer(vault)
            self.assertEqual(segunda["enlazadas"], 0)


class ReclasificarTests(unittest.TestCase):
    def test_mueve_la_nota_al_tema_correcto(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            nota = save_note(
                vault,
                title="Receta de pan",
                content="ingredientes y horno",
                source="https://e.org/pan",
                kind="web",
                category="Por clasificar",
            )
            self.assertIn("por-clasificar", str(nota.parent))
            resumen = reclasificar(vault)
            self.assertEqual(resumen["movidas"], 1)
            nuevo = vault / "Categorías" / "comida" / nota.name
            self.assertTrue(nuevo.is_file(), "la nota no se movió a comida")
            self.assertIn('category: "Comida"', nuevo.read_text(encoding="utf-8"))
            self.assertFalse(nota.exists(), "quedó una copia en la carpeta vieja")

    def test_simular_no_toca_nada(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            nota = save_note(
                vault, title="Receta", content="ingredientes", source="https://e.org/b", kind="web", category="Otros"
            )
            resumen = reclasificar(vault, simular=True)
            self.assertEqual(resumen["movidas"], 1)
            self.assertTrue(nota.is_file())


class PdfTests(unittest.TestCase):
    def test_un_pdf_roto_no_tira_abajo_la_captura(self) -> None:
        """La promesa es que el bot nunca se cae leyendo un documento raro."""
        from open_vault.pdf import read_pdf

        with tempfile.TemporaryDirectory() as temp:
            archivo = Path(temp) / "x.pdf"
            archivo.write_bytes(b"%PDF-1.4 esto no es un pdf real")
            texto, ocr, paginas = read_pdf(archivo, Path(temp) / "paginas")
            self.assertEqual(texto, "")
            self.assertEqual(ocr, "")

    def test_lee_el_texto_de_un_pdf_de_verdad(self) -> None:
        if not pypdf_available():
            self.skipTest("pypdf no está instalado")
        with tempfile.TemporaryDirectory() as temp:
            archivo = Path(temp) / "real.pdf"
            _pdf_con_texto(archivo, "Hola vault")
            self.assertIn("Hola vault", text_of_pdf(archivo))


def _pdf_con_texto(destino: Path, texto: str) -> None:
    """Arma un PDF válido de una página con ese texto, para poder probarlo."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    escritor = PdfWriter()
    pagina = escritor.add_blank_page(width=200, height=200)
    fuente = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    pagina[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): escritor._add_object(fuente)})}
    )
    contenido = DecodedStreamObject()
    contenido.set_data(f"BT /F1 12 Tf 20 100 Td ({texto}) Tj ET".encode("latin-1"))
    pagina[NameObject("/Contents")] = escritor._add_object(contenido)
    with destino.open("wb") as salida:
        escritor.write(salida)


if __name__ == "__main__":
    unittest.main()
