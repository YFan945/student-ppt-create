from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.visual_system_smoke_gallery import (
    clipping_overflow_pages,
    generate_one,
    layout_deck_source,
    style_deck_source,
    svg_atlas_source,
)
from shared.design_tokens import resolve_design_tokens

ROOT = Path(__file__).resolve().parents[1]


class VisualSystemSmokeGalleryTests(unittest.TestCase):
    def test_style_gallery_covers_all_styles_with_six_slide_jobs(self) -> None:
        catalog = json.loads((ROOT / "references" / "design-tokens.json").read_text(encoding="utf-8"))
        self.assertEqual(12, len(catalog["styles"]))
        for style_key in catalog["styles"]:
            with self.subTest(style=style_key):
                source = style_deck_source(resolve_design_tokens(style_key))
                self.assertEqual(6, source.count("= baseSlide("))
                for family in ("architecture", "dashboard", "summary"):
                    self.assertIn(f"'{family}'", source)
                self.assertNotIn("L.resolveLayout", source)
                self.assertNotIn("L.selectLayouts", source)
                self.assertNotIn("H.addStyleMotif", source)
                self.assertIn("没有可靠素材时，用图表、关系图或留白，不制造纪实感", source)
                self.assertIn("SVG.addCornerDecoration", source)

    def test_gallery_ci_fails_only_on_clipping_not_risk_band(self) -> None:
        findings = [
            {
                "slide": 2,
                "risk": ["text-vertical-overflow-risk"],
                "overflow_estimate": {"fill_ratio_raw": 0.99},
            },
            {
                "slide": 4,
                "risk": ["text-vertical-overflow-risk"],
                "overflow_estimate": {"fill_ratio_raw": 1.0},
            },
            {
                "slide": 5,
                "risk": ["text-vertical-overflow"],
                "overflow_estimate": {"fill_ratio_raw": 1.05},
            },
        ]
        self.assertEqual([5], clipping_overflow_pages(findings))

    def test_academic_rigorous_style_gallery_does_not_clip(self) -> None:
        import tempfile

        tokens = resolve_design_tokens("academic-rigorous")
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_one(
                Path(tmp),
                "style-academic-rigorous",
                style_deck_source(tokens),
                False,
                6,
            )
        self.assertEqual(0, result["static_qa"]["text_overflow_clip_count"])


    def test_layout_gallery_contains_all_36_layout_ids(self) -> None:
        registry = json.loads((ROOT / "skills" / "sp-deck" / "references" / "layout-library.json").read_text(encoding="utf-8"))
        source = layout_deck_source(resolve_design_tokens("Modern Minimal"), registry)
        self.assertEqual(36, len(registry["layouts"]))
        self.assertIn("reference", source.lower())
        self.assertIn("L.resolveLayout", source)
        self.assertIn("renderLayoutSample", source)
        self.assertIn("V.renderVisual", source)
        for layout in registry["layouts"]:
            self.assertIn(layout["id"], source)

    def test_svg_atlas_contains_all_style_corner_sets(self) -> None:
        source = svg_atlas_source(resolve_design_tokens("Modern Minimal"))
        self.assertIn("SVG.CORNER_SETS", source)
        self.assertIn("SVG.addCornerDecoration", source)


if __name__ == "__main__":
    unittest.main()
