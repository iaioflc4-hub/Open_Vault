from __future__ import annotations

import unittest

from open_vault.enrich import Figure, key_figures, math_blocks, mermaid_tree, outline, stats, tags


class OutlineTests(unittest.TestCase):
    def test_reads_heading_levels_in_order(self) -> None:
        text = "# Uno\n\ntexto\n\n### Tres\n\n## Dos"
        self.assertEqual(outline(text), [(1, "Uno"), (3, "Tres"), (2, "Dos")])

    def test_text_without_headings_is_empty(self) -> None:
        self.assertEqual(outline("solo párrafos\nsin encabezados"), [])


class MermaidTests(unittest.TestCase):
    def test_returns_none_with_too_little_structure(self) -> None:
        self.assertIsNone(mermaid_tree("Nota", [(1, "Uno"), (2, "Dos")]))

    def test_builds_mindmap_with_sanitized_labels(self) -> None:
        headings = [(1, "Introducción (teoría)"), (2, "Datos [ver aquí]"), (2, "Cierre")]
        tree = mermaid_tree("Informe", headings)
        assert tree is not None
        self.assertIn("mindmap", tree)
        self.assertIn("root((Informe))", tree)
        self.assertIn("Introducción teoría", tree)
        self.assertNotIn("(", tree.split("root((Informe))")[1])
        self.assertTrue(tree.startswith("```mermaid") and tree.endswith("```"))


class KeyFigureTests(unittest.TestCase):
    def test_parses_local_number_format_and_units(self) -> None:
        text = "- Cobertura: 87,5 %\n- Ventas: 1.250 millones\n- Peso: 12,5 kg"
        figures = key_figures(text)
        self.assertIn(Figure(label="Cobertura", value=87.5, unit="%"), figures)
        self.assertIn(Figure(label="Ventas", value=1_250_000_000.0, unit="millones"), figures)
        self.assertIn(Figure(label="Peso", value=12.5, unit="kg"), figures)

    def test_technical_units_and_currency_are_kept(self) -> None:
        figures = key_figures("- Potencia instalada: 1.250 GW\n- Precio del panel: $340.000\n- Por ciento de avance: 42 %")
        self.assertIn(Figure(label="Potencia instalada", value=1250.0, unit="GW"), figures)
        self.assertIn(Figure(label="Precio del panel", value=340_000.0, unit="$"), figures)

    def test_times_are_not_mistaken_for_figures(self) -> None:
        self.assertEqual(key_figures("A las 10:30 de la mañana salimos"), [])

    def test_ignores_lines_without_label_or_number(self) -> None:
        text = "Sin datos acá\n- lista suelta\n- Otra: texto"
        self.assertEqual(key_figures(text), [])

    def test_respects_limit_and_deduplicates(self) -> None:
        text = "\n".join(f"- Dato{i}: {i}" for i in range(1, 11))
        self.assertEqual(len(key_figures(text, limit=3)), 3)
        text = "- Cobertura: 10\n- cobertura: 20"
        self.assertEqual(len(key_figures(text)), 1)


class MathTests(unittest.TestCase):
    def test_currency_is_not_math(self) -> None:
        self.assertEqual(math_blocks("El plan cuesta $5 por mes y ahorrás $120 al año"), [])

    def test_display_block_and_latex_command_are_kept(self) -> None:
        text = "Antes\n$$\nE = mc^2\n$$\n\ndespués $\\frac{a}{b}$ y $x + 1$"
        blocks = math_blocks(text)
        self.assertIn("E = mc^2", blocks)
        self.assertIn("\\frac{a}{b}", blocks)
        self.assertIn("x + 1", blocks)

    def test_numeric_range_without_variable_is_not_math(self) -> None:
        self.assertEqual(math_blocks("La franja va de $5 - 10$"), [])

    def test_plain_dollar_text_is_ignored(self) -> None:
        self.assertEqual(math_blocks("cuesta $5 y cuesta $10 dolares"), [])


class TagsAndStatsTests(unittest.TestCase):
    def test_tags_skip_stopwords_and_short_words(self) -> None:
        result = tags("El fotosíntesis usa la luz y el fotosíntesis produce glucosa", limit=3)
        self.assertIn("fotosíntesis", result)
        self.assertNotIn("para", result)
        self.assertNotIn("con", result)

    def test_tags_are_bounded(self) -> None:
        self.assertLessEqual(len(tags("energía solar energía solar panel panel batería batería", limit=2)), 2)

    def test_stats_counts_words_and_reading_time(self) -> None:
        measured = stats("Una oración corta. Otra oración más larga con palabras.")
        self.assertEqual(measured.sentences, 2)
        self.assertGreaterEqual(measured.words, 8)
        self.assertEqual(measured.reading_minutes, 1)


if __name__ == "__main__":
    unittest.main()
