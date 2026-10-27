from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_vault.classify import UNCATEGORIZED, classify, etiqueta_explicita
from open_vault.enrich import hashtags, tags
from open_vault.grafo import MAPA, TEMAS_DIR, tejer
from open_vault.links import vtt_to_text, ytdlp_metadata, youtube_id
from open_vault.pdf import pypdf_available, text_of_pdf
from open_vault.reclasificar import reclasificar
from open_vault.rehacer import notas_pendientes, titulo_parece_url
from open_vault.vault import (
    completar_nota_video,
    reemplazar_titulo,
    reemplazar_transcripcion,
    save_note,
    save_video_reference,
)


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

    def test_sin_pistas_no_inventa_un_tema(self) -> None:
        """Sin contenido ni etiqueta no hay categoría: nunca el formato del archivo."""
        self.assertEqual(classify("texto sin términos conocidos"), UNCATEGORIZED)
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(Path(temp), title="Video del 2026-10-27", source="https://youtu.be/x")
            self.assertIn("por-clasificar", str(nota.parent))

    def test_hashtag_manda_en_la_clasificacion(self) -> None:
        self.assertEqual(classify("#seguridad #linux", title="charla"), "Seguridad")

    def test_una_etiqueta_desconocida_define_el_tema(self) -> None:
        """El vault se ordena con las palabras de quien lo usa, no solo con las listas."""
        self.assertEqual(classify("", title="avances de la huerta #huerta-organica"), "Huerta organica")
        self.assertEqual(etiqueta_explicita("clase de #Huerta"), "Huerta")
        self.assertEqual(etiqueta_explicita("sin etiquetas"), "")

    def test_el_pie_del_mensaje_decide_el_tema(self) -> None:
        """Un video sin transcripción pero con pie temático se clasifica por el pie."""
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(
                Path(temp),
                title="mirá esto #seguridad",
                source="https://youtu.be/xyz",
            )
            self.assertIn("seguridad", str(nota.parent))


class HashtagTests(unittest.TestCase):
    def test_etiquetas_escritas_a_mano(self) -> None:
        self.assertEqual(hashtags("hola #Linux y #seguridad, otra vez #linux"), ["linux", "seguridad"])

    def test_las_etiquetas_a_mano_van_primero(self) -> None:
        resultado = tags("#linux texto texto texto")
        self.assertEqual(resultado[0], "linux")

    def test_un_color_no_es_un_tema(self) -> None:
        """Los códigos de color del SVG aparecían en el gráfico como temas."""
        self.assertEqual(hashtags("<svg fill=\"#00cc66\">#linux</svg>"), ["linux"])

    def test_no_etiqueta_dominios_ni_palabras_de_la_plantilla(self) -> None:
        limpio = tags("https://youtu.be/abc youtu.be video transcripción pendiente software")
        self.assertIn("software", limpio)
        for ruido in ("youtu", "video", "transcripción", "pendiente"):
            self.assertNotIn(ruido, limpio)


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

    def test_lee_la_ficha_aunque_ytdlp_salga_con_error(self) -> None:
        """Un carrusel de Instagram: la ficha viene completa y el código de salida
        igual es error, porque las fotos no tienen formato de video."""
        import subprocess

        salida = '{"id": "x", "title": "Post by alguien", "description": "texto #osint"}'
        with patch(
            "open_vault.links._ytdlp",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout=salida, stderr="ERROR"),
        ):
            info = ytdlp_metadata("https://www.instagram.com/p/x/")
        self.assertIsNotNone(info)
        self.assertEqual(info.title, "Post by alguien")
        self.assertIn("osint", info.extra_tags)

    def test_sin_json_no_inventa_una_ficha(self) -> None:
        import subprocess

        with patch(
            "open_vault.links._ytdlp",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="ERROR: no hay nada", stderr=""),
        ):
            self.assertIsNone(ytdlp_metadata("https://www.instagram.com/p/x/"))


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

    def test_saca_del_mapa_los_temas_que_quedaron_sin_capturas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            nota = save_note(
                vault, title="Nota", content="texto con #viejo", source="https://e.org/a", kind="web"
            )
            tejer(vault)
            self.assertTrue((vault / TEMAS_DIR / "viejo.md").is_file())
            # La nota se reclasifica y deja de usar ese tema: el mapa no debe
            # seguir mostrándolo como un punto suelto. El orden es el del
            # sincronizador: primero la clasificación, después los enlaces.
            nota.write_text(nota.read_text(encoding="utf-8").replace("#viejo", "#nuevo"), encoding="utf-8")
            reclasificar(vault)
            tejer(vault)
            self.assertFalse((vault / TEMAS_DIR / "viejo.md").exists())
            self.assertTrue((vault / TEMAS_DIR / "nuevo.md").is_file())

    def test_no_borra_una_nota_de_tema_escrita_a_mano(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            save_note(vault, title="Nota", content="texto", source="https://e.org/a", kind="web")
            carpeta = vault / TEMAS_DIR
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "mi-tema.md").write_text("---\ntitle: Mi tema\n---\n\nlo que escribí\n", encoding="utf-8")
            tejer(vault)
            self.assertTrue((carpeta / "mi-tema.md").is_file())


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


class RehacerTests(unittest.TestCase):
    def test_encuentra_solo_las_notas_de_enlaces_pendientes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            pendiente = save_video_reference(vault, title="Video", source="https://youtu.be/abc")
            save_video_reference(vault, title="Otro", source="https://youtu.be/def", transcript="ya está")
            save_note(vault, title="Nota", content="texto", source="telegram://text/1", kind="texto")
            self.assertEqual(notas_pendientes(vault), [pendiente])

    def test_escribe_la_transcripcion_sin_perder_lo_demas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(Path(temp), title="Video", source="https://youtu.be/abc")
            texto = nota.read_text(encoding="utf-8")
            nuevo = reemplazar_transcripcion(texto, "hola mundo", "subtítulos del propio video (es)")
            self.assertIn("## Transcripción (subtítulos del propio video (es))", nuevo)
            self.assertIn("hola mundo", nuevo)
            self.assertNotIn("Transcripción pendiente", nuevo)
            self.assertNotIn("TRANSCRIPTION_ENGINE", nuevo)
            self.assertIn("## Fuente original", nuevo)
            self.assertIn("## Notas", nuevo)

    def test_agrega_la_descripcion_sin_perder_la_transcripcion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(Path(temp), title="Video", source="https://youtu.be/abc")
            texto = nota.read_text(encoding="utf-8")
            nuevo = completar_nota_video(
                texto, description="Pie con #osint", transcript="hola", transcript_origen="subtítulos"
            )
            self.assertIn("## Descripción original", nuevo)
            self.assertIn("Pie con #osint", nuevo)
            self.assertIn("## Transcripción (subtítulos)", nuevo)
            self.assertNotIn("Transcripción pendiente", nuevo)

    def test_completar_sin_datos_no_cambia_nada(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(Path(temp), title="Video", source="https://youtu.be/abc")
            texto = nota.read_text(encoding="utf-8")
            self.assertEqual(completar_nota_video(texto), texto)

    def test_la_transcripcion_vacia_no_cambia_nada(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            nota = save_video_reference(Path(temp), title="Video", source="https://youtu.be/abc")
            texto = nota.read_text(encoding="utf-8")
            self.assertEqual(reemplazar_transcripcion(texto, "   "), texto)

    def test_reconoce_un_titulo_que_es_una_url(self) -> None:
        self.assertTrue(titulo_parece_url("www.instagram.com/p/De-a-xmESTg"))
        self.assertTrue(titulo_parece_url("https://youtu.be/abc"))
        self.assertFalse(titulo_parece_url("Cómo hacer pan en casa"))
        self.assertIn('title: "Hola"', reemplazar_titulo('---\ntitle: "www.x.com"\n---\n', "Hola"))


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
