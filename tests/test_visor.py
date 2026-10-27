from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from open_vault.visor import convertir_markdown

MKDOCS_DISPONIBLE = importlib.util.find_spec("mkdocs") is not None


class CambiosTests(unittest.TestCase):
    def test_rebuilds_when_the_vault_is_newer_than_the_site(self) -> None:
        from open_vault.visor import _hay_cambios

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            vault = raiz / "vault"
            vault.mkdir()
            salida = raiz / "sitio"
            assets = raiz / "assets"
            assets.mkdir()
            self.assertTrue(_hay_cambios(vault, salida, assets), "sin sitio generado hay que construir")

            salida.mkdir()
            (salida / "index.html").write_text("<html></html>", encoding="utf-8")
            assets.joinpath("estilo.css").write_text("", encoding="utf-8")
            self.assertFalse(_hay_cambios(vault, salida, assets), "sin cambios no se regenera")

            nota = vault / "nueva.md"
            nota.write_text("# Nueva\n", encoding="utf-8")
            os.utime(nota, (nota.stat().st_mtime + 60, nota.stat().st_mtime + 60))
            self.assertTrue(_hay_cambios(vault, salida, assets), "una captura nueva dispara el rebuild")

    def test_touching_the_visor_also_triggers_a_rebuild(self) -> None:
        from open_vault.visor import _hay_cambios

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            vault = raiz / "vault"
            vault.mkdir()
            salida = raiz / "sitio"
            salida.mkdir()
            (salida / "index.html").write_text("<html></html>", encoding="utf-8")
            assets = raiz / "assets"
            assets.mkdir()
            estilo = assets / "estilo.css"
            estilo.write_text("", encoding="utf-8")
            futuro = (salida / "index.html").stat().st_mtime + 60
            os.utime(estilo, (futuro, futuro))
            self.assertTrue(_hay_cambios(vault, salida, assets))


class ConversionTests(unittest.TestCase):
    def test_attachment_embed_becomes_relative_image(self) -> None:
        salida = convertir_markdown("![[Attachments/ficha.svg]]", profundidad=2)
        self.assertIn("![ficha](../../Attachments/ficha.svg)", salida)

    def test_attachment_embed_at_root_has_no_parent_segments(self) -> None:
        self.assertIn("![](Attachments/ficha.svg)", convertir_markdown("![[Attachments/ficha.svg]]"))

    def test_video_embed_is_replaced_by_a_notice(self) -> None:
        salida = convertir_markdown("![[Attachments/video.mp4]]")
        self.assertNotIn("![[", salida)
        self.assertIn("no se copia a la vista web", salida)

    def test_wikilink_to_a_known_note_becomes_a_link(self) -> None:
        indices = {"panel-solar": "Categorías/tecnologia/panel-solar.md"}
        salida = convertir_markdown("Ver [[panel-solar]]", profundidad=2, indices=indices)
        self.assertIn("[panel-solar](../../Categorías/tecnologia/panel-solar.md)", salida)

    def test_unknown_wikilink_degrades_to_plain_text(self) -> None:
        self.assertEqual(convertir_markdown("Ver [[nota-que-no-existe]]"), "Ver nota-que-no-existe\n")

    def test_callout_becomes_an_admonition_with_its_body(self) -> None:
        nota = "> [!info] Captura íntegra\n> 1240 palabras\n> Fuente: https://x.example/a\n"
        salida = convertir_markdown(nota, profundidad=1)
        self.assertIn('!!! info "Captura íntegra"', salida)
        self.assertIn("    1240 palabras", salida)
        self.assertIn("    Fuente: https://x.example/a", salida)
        self.assertNotIn("> [!info]", salida)

    def test_display_math_uses_bracket_delimiters(self) -> None:
        salida = convertir_markdown("Antes\n$$\nE = mc^2\n$$\nDespués")
        self.assertIn("\\[\nE = mc^2\n\\]", salida)
        self.assertNotIn("$$", salida)

    def test_inline_math_is_converted_but_prices_are_not(self) -> None:
        salida = convertir_markdown("Cuesta $340.000 y la fórmula $x + 1$ sirve")
        self.assertIn("\\(x + 1\\)", salida)
        self.assertIn("$340.000", salida)

    def test_code_fence_content_is_left_untouched(self) -> None:
        nota = "```mermaid\nmindmap\n  root((Nota))\n    Tema\n```\n"
        salida = convertir_markdown(nota)
        self.assertIn("```mermaid", salida)
        self.assertIn("root((Nota))", salida)

    def test_headings_and_tables_survive(self) -> None:
        nota = "## Datos\n\n| Dato | Valor |\n| --- | --- |\n| Cobertura | 87,5 % |\n"
        self.assertEqual(convertir_markdown(nota), nota)


@unittest.skipUnless(MKDOCS_DISPONIBLE, "mkdocs-material no está instalado (extra `visor`)")
class BuildTests(unittest.TestCase):
    def test_builds_a_site_from_a_small_vault(self) -> None:
        from open_vault.visor import ConfiguracionVisor, construir
        from open_vault.vault import save_note

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            vault = raiz / "vault"
            save_note(
                vault,
                title="Informe de prueba",
                content="## Datos\n\n- Cobertura: 87,5 %\n- Potencia: 1.250 GW\n- Sedes: 12\n\n> [!quote] Sin resumen\n> Texto.",
                source="https://example.org/informe",
                kind="web",
            )
            salida = raiz / "sitio"
            assets = Path(__file__).resolve().parents[1] / "visor" / "assets"
            construir(ConfiguracionVisor(vault=vault, salida=salida, assets=assets))

            self.assertTrue((salida / "index.html").is_file())
            notas = list(salida.rglob("*.html"))
            self.assertGreaterEqual(len(notas), 2)
            html = next(p for p in notas if "informe" in p.name.lower()).read_text(encoding="utf-8")
            self.assertIn("admonition", html)
            self.assertIn("Cobertura", html)
            self.assertIn("-ficha.svg", html)
            self.assertTrue(any(salida.rglob("*-ficha.svg")))


if __name__ == "__main__":
    unittest.main()
