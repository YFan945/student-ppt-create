"""Batch 4.3: the deck rhythm plan — per-page tone from the Art Direction's
background_rhythm, composition family letters per archetype, and run-of-three
warnings surfaced at generation time instead of at critic time."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "sp-deck" / "scripts" / "deck_rhythm.py"

_SPEC = importlib.util.spec_from_file_location("deck_rhythm", SCRIPT)
dr = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("deck_rhythm", dr)
_SPEC.loader.exec_module(dr)


def slide(number: int, **fields: object) -> dict[str, object]:
    return {"id": number, "title": f"Slide {number}", **fields}


class DeckRhythmTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, slides: list[dict[str, object]], rhythm: str | None = None) -> None:
        (self.work / "slide-spec.json").write_text(
            json.dumps({"meta": {"slide_count": len(slides)}, "slides": slides}), encoding="utf-8"
        )
        if rhythm is not None:
            (self.work / "art-direction.yaml").write_text(rhythm, encoding="utf-8")

    BACKGROUND_RHYTHM = (
        "background_rhythm:\n"
        "  - role: cover\n"
        "    mode: dark\n"
        "  - role: content\n"
        "    mode: light\n"
        "  - role: section\n"
        "    mode: accent\n"
        "  - role: closing\n"
        "    mode: dark\n"
    )

    def test_tone_follows_background_rhythm_through_role_mapping(self) -> None:
        self.write(
            [
                slide(1, kind="cover", role="opening"),
                slide(2, role="problem"),
                slide(3, role="evidence"),
                slide(4, kind="section-divider", role="background"),
                slide(5, kind="closing", role="conclusion"),
            ],
            rhythm=self.BACKGROUND_RHYTHM,
        )
        plan = dr.build_rhythm(self.work)
        self.assertEqual("art_direction", plan["tone_source"])
        tones = {page["slide"]: page["tone"] for page in plan["pages"]}
        self.assertEqual(
            {"1": "dark", "2": "light", "3": "light", "4": "accent", "5": "dark"},
            {str(k): v for k, v in tones.items()},
        )

    def test_family_letters_follow_first_archetype_appearance(self) -> None:
        self.write(
            [
                slide(1, kind="cover"),
                slide(2, role="problem"),
                slide(3, role="method"),
                slide(4, layout="survey"),
                slide(5, layout="cover"),
            ]
        )
        plan = dr.build_rhythm(self.work)
        families = {page["slide"]: page["family"] for page in plan["pages"]}
        self.assertEqual(families[1], families[5])  # same grammar, same letter
        self.assertNotEqual(families[1], families[2])
        self.assertNotEqual(families[1], families[4])

    def test_run_of_three_same_family_warns_at_generation_time(self) -> None:
        self.write([slide(n, role="problem") for n in range(1, 8)])
        plan = dr.build_rhythm(self.work)
        self.assertEqual(1, len(plan["warnings"]))
        self.assertIn("slides 1-7", plan["warnings"][0])
        self.assertIn("family A", plan["warnings"][0])

    def test_no_warning_when_families_alternate(self) -> None:
        self.write(
            [
                slide(1, kind="cover"),
                slide(2, role="problem"),
                slide(3, layout="survey"),
                slide(4, layout="comparison"),
                slide(5, kind="closing", role="conclusion"),
            ]
        )
        self.assertEqual([], dr.build_rhythm(self.work)["warnings"])

    def test_default_tone_is_light_without_background_rhythm(self) -> None:
        self.write([slide(1, kind="cover"), slide(2, role="problem")])
        plan = dr.build_rhythm(self.work)
        self.assertEqual("default", plan["tone_source"])
        self.assertEqual({"light"}, {page["tone"] for page in plan["pages"]})

    def test_ensure_is_idempotent_and_page_rhythm_keyed_by_slide(self) -> None:
        self.write(
            [slide(1, kind="cover"), slide(2, role="problem"), slide(3, role="evidence")],
            rhythm=self.BACKGROUND_RHYTHM,
        )
        path = dr.ensure_rhythm(self.work)
        first = path.read_text(encoding="utf-8")
        self.assertEqual(path, dr.ensure_rhythm(self.work))
        self.assertEqual(first, path.read_text(encoding="utf-8"))
        by_slide = dr.page_rhythm(self.work)
        self.assertEqual("dark", by_slide[1]["tone"])
        self.assertEqual("A", by_slide[1]["family"])
        self.assertEqual("A", by_slide[2]["prev_family"])
        self.assertEqual("light", by_slide[2]["tone"])

    def test_no_spec_returns_none(self) -> None:
        self.assertIsNone(dr.build_rhythm(self.work))


if __name__ == "__main__":
    unittest.main()
