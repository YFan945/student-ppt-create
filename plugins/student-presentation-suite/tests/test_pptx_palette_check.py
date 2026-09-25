from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "sp-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pptx_palette_check as palette_check  # noqa: E402


class PptxPaletteCheckTests(unittest.TestCase):
    def write_fixture(self, root: Path, colors: list[str]) -> tuple[Path, Path]:
        pptx = root / "deck.pptx"
        with zipfile.ZipFile(pptx, "w") as archive:
            archive.writestr(
                "ppt/slides/slide1.xml",
                "<p:sld xmlns:p='p' xmlns:a='a'>"
                + "".join(f'<a:srgbClr val="{value}"/>' for value in colors)
                + "</p:sld>",
            )
        art = root / "art-direction.yaml"
        art.write_text('style_seed: "Data Driven"\n', encoding="utf-8")
        return pptx, art

    def test_approved_light_and_dark_colors_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx, art = self.write_fixture(Path(tmp), ["F8FAFC", "2563EB", "0F1A25"])
            self.assertTrue(palette_check.check_pptx(pptx, art)["ok"])

    def test_unapproved_color_names_the_slide_and_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx, art = self.write_fixture(Path(tmp), ["F8FAFC", "D7D1C4"])
            report = palette_check.check_pptx(pptx, art)
            self.assertFalse(report["ok"])
            self.assertEqual(report["issues"][0]["slide"], 1)
            self.assertEqual(report["issues"][0]["colors"], {"D7D1C4": 1})

    def test_chart_part_colors_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx, art = self.write_fixture(Path(tmp), ["F8FAFC"])
            with zipfile.ZipFile(pptx, "a") as archive:
                archive.writestr(
                    "ppt/charts/chart1.xml",
                    '<c:chart xmlns:c="c" xmlns:a="a"><a:srgbClr val="D7D1C4"/></c:chart>',
                )
            report = palette_check.check_pptx(pptx, art)
            self.assertFalse(report["ok"])
            self.assertEqual(report["issues"][0]["part"], "ppt/charts/chart1.xml")

    def test_chart_defaults_are_attributed_to_the_slide_and_element(self) -> None:
        """Black axis/legend/title is a generator default: name slide + element, not guesswork."""
        with tempfile.TemporaryDirectory() as tmp:
            pptx, art = self.write_fixture(Path(tmp), ["F8FAFC"])
            with zipfile.ZipFile(pptx, "a") as archive:
                archive.writestr(
                    "ppt/slides/_rels/slide1.xml.rels",
                    '<Relationships><Relationship Type="x/chart" Target="../charts/chart1.xml"/></Relationships>',
                )
                archive.writestr(
                    "ppt/charts/chart1.xml",
                    '<c:chart xmlns:c="c" xmlns:a="a">'
                    '<c:catAx><a:srgbClr val="000000"/></c:catAx>'
                    '<c:legend><a:srgbClr val="000000"/></c:legend>'
                    '<c:ser><c:tx><a:t>ok</a:t></c:tx></c:ser>'
                    '</c:chart>',
                )
            report = palette_check.check_pptx(pptx, art)
            self.assertFalse(report["ok"])
            issue = report["issues"][0]
            self.assertEqual(issue["slide"], 1)
            self.assertEqual(issue["elements"]["axis"], {"000000": 1})
            self.assertEqual(issue["elements"]["legend"], {"000000": 1})
            self.assertIn("pptxgenjs defaults", issue["message"])
            self.assertIn("pptx-visuals.js", issue["message"])

    def test_chart_element_colors_classify_chrome(self) -> None:
        elements = palette_check.chart_element_colors(
            '<c:valAx><a:srgbClr val="111111"/></c:valAx>'
            '<c:title><a:srgbClr val="222222"/></c:title>'
            '<c:dLbls><a:srgbClr val="333333"/></c:dLbls>'
        )
        self.assertEqual(elements["axis"], {"111111": 1})
        self.assertEqual(elements["title"], {"222222": 1})
        self.assertEqual(elements["data-labels"], {"333333": 1})

    def test_theme_scheme_color_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            art = root / "art-direction.yaml"
            art.write_text('style_seed: "Data Driven"\n', encoding="utf-8")
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr(
                    "ppt/theme/theme1.xml",
                    '<a:theme xmlns:a="a"><a:themeElements><a:clrScheme name="x">'
                    '<a:accent1><a:srgbClr val="D7D1C4"/></a:accent1>'
                    '</a:clrScheme></a:themeElements></a:theme>',
                )
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="p" xmlns:a="a"><a:schemeClr val="accent1"/></p:sld>',
                )
            report = palette_check.check_pptx(pptx, art)
            self.assertFalse(report["ok"])
            self.assertEqual(report["issues"][0]["colors"], {"D7D1C4": 1})


if __name__ == "__main__":
    unittest.main()
