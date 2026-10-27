from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from open_vault.svg import bars_svg, card_svg, color_for, format_number


class CardTests(unittest.TestCase):
    def test_card_is_valid_xml(self) -> None:
        svg = card_svg(title="Informe de energía solar", category="Ciencia", source_host="example.org", words=120)
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("Informe de energía solar", svg)

    def test_special_characters_are_escaped(self) -> None:
        svg = card_svg(title="A <B> & C", category="Tecnología", tags=["a<b"])
        ET.fromstring(svg)
        self.assertNotIn("<B>", svg)
        self.assertIn("&lt;B&gt;", svg)
        self.assertIn("&amp;", svg)

    def test_long_title_is_truncated_not_overflowing(self) -> None:
        svg = card_svg(title="palabra " * 60, category="Por clasificar")
        self.assertIn("…", svg)
        ET.fromstring(svg)

    def test_color_is_stable_per_category_and_defaulted(self) -> None:
        self.assertEqual(color_for("Ciencia"), color_for("Ciencia"))
        self.assertEqual(color_for("Categoría inexistente"), "#8b949e")


class BarsTests(unittest.TestCase):
    def test_bars_are_valid_xml_and_scaled(self) -> None:
        svg = bars_svg(items=[("Chico", 10), ("Grande", 100)])
        ET.fromstring(svg)
        widths = [float(chunk.split('"')[0]) for chunk in svg.split('width="')[2:]]
        self.assertGreater(max(widths), min(widths))

    def test_zero_and_negative_values_are_dropped(self) -> None:
        svg = bars_svg(items=[("Bueno", 10), ("Cero", 0), ("Negativo", -4)])
        self.assertIn("Bueno", svg)
        self.assertNotIn("Cero", svg)
        ET.fromstring(svg)

    def test_empty_input_still_produces_valid_xml(self) -> None:
        ET.fromstring(bars_svg(items=[]))

    def test_long_values_stay_inside_the_chart(self) -> None:
        svg = bars_svg(items=[("Inversión", 340_000_000_000), ("Cobertura", 87.5)])
        ultimo = svg.strip().split("<text")[-1]
        x = float(ultimo.split('x="')[1].split('"')[0])
        # El texto del valor tiene que entrar en el ancho del SVG contando sus
        # 15 caracteres a 9 px cada uno (fuente de 15 px).
        self.assertLessEqual(x + 9 * len("340.000.000.000"), 880)

    def test_number_format_is_local(self) -> None:
        self.assertEqual(format_number(1234), "1.234")
        self.assertEqual(format_number(1234.5), "1.234,5")
        self.assertEqual(format_number(87.5), "87,5")


if __name__ == "__main__":
    unittest.main()
