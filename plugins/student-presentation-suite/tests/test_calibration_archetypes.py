"""Batch 4.1: deterministic archetype classification and coverage-based
calibration selection. The calibration sample must cover distinct visual
grammars, not the first three high-leverage positions."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "sp-deck" / "scripts" / "calibration_archetypes.py"

_SPEC = importlib.util.spec_from_file_location("calibration_archetypes", SCRIPT)
ca = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("calibration_archetypes", ca)
_SPEC.loader.exec_module(ca)


def slide(number: int, **fields: object) -> dict[str, object]:
    return {"id": number, "title": f"Slide {number}", **fields}


class ArchetypeClassificationTests(unittest.TestCase):
    def test_kind_drives_the_top_level_archetypes(self) -> None:
        self.assertEqual("hero", ca.archetype_of(slide(1, kind="cover")))
        self.assertEqual("section", ca.archetype_of(slide(2, kind="section-divider")))
        self.assertEqual("closing", ca.archetype_of(slide(3, kind="closing")))
        self.assertEqual("reference", ca.archetype_of(slide(4, kind="references")))
        self.assertEqual("quote", ca.archetype_of(slide(5, kind="quotation")))

    def test_visual_layout_family_maps_to_visual_grammars(self) -> None:
        self.assertEqual(
            "comparison", ca.archetype_of(slide(1, visual={"layout_family": "comparison"}))
        )
        self.assertEqual("data", ca.archetype_of(slide(2, visual={"layout_family": "dashboard"})))
        self.assertEqual(
            "process", ca.archetype_of(slide(3, visual={"layout_family": "timeline"}))
        )
        self.assertEqual(
            "diagram", ca.archetype_of(slide(4, visual={"layout_family": "architecture"}))
        )
        self.assertEqual(
            "image-led", ca.archetype_of(slide(5, visual={"layout_family": "visual-dominant"}))
        )

    def test_free_string_layout_maps_only_through_documented_keywords(self) -> None:
        self.assertEqual("hero", ca.archetype_of(slide(1, layout="cover")))
        self.assertEqual("comparison", ca.archetype_of(slide(2, layout="comparison-cards")))
        self.assertEqual("process", ca.archetype_of(slide(3, layout="three-step-process")))
        self.assertEqual("data", ca.archetype_of(slide(4, layout="survey-results")))
        # An undocumented hint degrades to narrative instead of guessing.
        self.assertEqual("narrative", ca.archetype_of(slide(5, layout="fancy-collage")))
        self.assertEqual("narrative", ca.archetype_of({}))


class CoverageSelectionTests(unittest.TestCase):
    def test_sample_maximises_distinct_archetypes(self) -> None:
        spec = {
            "slides": [
                slide(1, kind="cover"),
                slide(2, layout="text-heavy"),
                slide(3, layout="text-heavy"),
                slide(4, layout="survey"),
                slide(5, layout="comparison-cards"),
                slide(6, layout="text-heavy"),
            ]
        }
        self.assertEqual([1, 4, 5], ca.coverage_slides(spec, [], 3))

    def test_a_leverage_slide_wins_ties_between_archetypes(self) -> None:
        spec = {
            "slides": [
                slide(1, kind="cover"),
                slide(2, layout="text-heavy"),
                slide(3, layout="data-chart"),
                slide(4, layout="comparison"),
                slide(5, layout="timeline"),
                slide(6, layout="matrix-diagram"),
            ]
        }
        # Six candidate archetypes, three slots: the art direction's flagged page
        # pulls its group ahead of first-appearance order.
        self.assertEqual([1, 3, 4], ca.coverage_slides(spec, [4], 3))

    def test_a_degenerate_all_narrative_deck_still_fills_the_sample(self) -> None:
        spec = {"slides": [slide(n, layout="text-heavy") for n in range(1, 10)]}
        # One archetype exists; high-leverage pages fill the remaining slots.
        self.assertEqual([1, 4, 9], ca.coverage_slides(spec, [9, 4], 3))

    def test_smaller_decks_return_every_slide(self) -> None:
        spec = {"slides": [slide(1, kind="cover"), slide(2)]}
        self.assertEqual([1, 2], ca.coverage_slides(spec, [], 3))

    def test_empty_spec_returns_nothing(self) -> None:
        self.assertEqual([], ca.coverage_slides({"slides": []}, [1, 2], 3))
        self.assertEqual([], ca.coverage_slides({}, [], 3))


class DefaultSelectionTests(unittest.TestCase):
    """The work-dir entry point: spec-based coverage, art-direction fallback."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_spec(self, slides: list[dict[str, object]], name: str = "slide-spec.json") -> None:
        (self.work / name).write_text(
            json.dumps({"meta": {"slide_count": len(slides)}, "slides": slides}), encoding="utf-8"
        )

    def test_no_spec_falls_back_to_high_leverage(self) -> None:
        (self.work / "art-direction.yaml").write_text(
            "high_leverage_slides: [2, 7]\n", encoding="utf-8"
        )
        self.assertEqual([2, 7], ca.default_calibration_slides(self.work))

    def test_spec_drives_coverage_and_leverage_fills(self) -> None:
        self.write_spec(
            [
                slide(1, kind="cover"),
                slide(2, layout="text-heavy"),
                slide(3, layout="text-heavy"),
                slide(4, layout="data-chart"),
                slide(5, layout="comparison"),
            ]
        )
        (self.work / "art-direction.yaml").write_text(
            "high_leverage_slides: [5]\n", encoding="utf-8"
        )
        self.assertEqual([1, 4, 5], ca.default_calibration_slides(self.work))


if __name__ == "__main__":
    unittest.main()
