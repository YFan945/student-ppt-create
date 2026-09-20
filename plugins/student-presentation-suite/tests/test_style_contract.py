"""Batch 4.2: the calibration style contract — one compact, deterministic
projection of the established visual system that builder packets embed, so
builders never infer style from calibration page JS they must not read."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "sp-deck" / "scripts" / "style_contract.py"

_SPEC = importlib.util.spec_from_file_location("style_contract", SCRIPT)
sc = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("style_contract", sc)
_SPEC.loader.exec_module(sc)

_CR = ROOT / "skills" / "sp-deck" / "scripts" / "calibration_review.py"
_SPEC2 = importlib.util.spec_from_file_location("calibration_review_sc", _CR)
cr = importlib.util.module_from_spec(_SPEC2)
sys.modules.setdefault("calibration_review_sc", cr)
_SPEC2.loader.exec_module(cr)


def slide(number: int, **fields: object) -> dict[str, object]:
    return {"id": number, "title": f"Slide {number}", **fields}


class StyleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def green_calibration(self, slides: list[int]) -> None:
        (self.work / "calibration").mkdir(exist_ok=True)
        pptx_sha = "calibration-pptx-sha"
        (self.work / "calibration" / "calibration-manifest.json").write_text(
            json.dumps({"slides": slides, "pptx": {"sha256": pptx_sha}}), encoding="utf-8"
        )
        review = self.work / "calibration" / "calibration-visual-review.json"
        review.write_text(
            json.dumps({"pptx_sha256": pptx_sha, "slides": [{"slide": n} for n in slides]}),
            encoding="utf-8",
        )
        (self.work / "calibration" / "calibration-critic-execution.json").write_text(
            json.dumps(
                {
                    "agent": "student-presentation-suite:visual-critic",
                    "agent_id": "test-calibration-critic",
                    "spawn_verified": True,
                    "work_id": self.work.name,
                    "artifact": cr._binding(review),
                    "reads": {},
                }
            ),
            encoding="utf-8",
        )
        self.write_summary()

    def write_summary(self) -> None:
        (self.work / "calibration" / "style-summary.json").write_text(
            json.dumps(
                {
                    "established": {
                        "title_treatment": "34pt left-aligned with a hairline under-rule",
                        "rhythm": "dense pages alternate with sparse statement pages",
                    },
                    "do_not_repeat": ["no equal-card grids as a default mapping"],
                }
            ),
            encoding="utf-8",
        )

    def write_spec(self, slides: list[dict[str, object]]) -> None:
        (self.work / "slide-spec.json").write_text(
            json.dumps({"meta": {"slide_count": len(slides)}, "slides": slides}), encoding="utf-8"
        )

    def write_art(self) -> None:
        (self.work / "art-direction.yaml").write_text(
            "concept: \"Evidence-first classroom deck\"\n"
            "style_seed: \"Academic Rigorous\"\n"
            "typography:\n"
            "  body_pt: 19\n"
            "  cover_title_pt: 52\n"
            "chart_grammar:\n"
            "  default: \"native chart, one highlighted series\"\n"
            "avoid:\n"
            "  - \"equal cards as the default mapping\"\n",
            encoding="utf-8",
        )

    def test_no_calibration_returns_none(self) -> None:
        self.assertIsNone(sc.build_style_contract(self.work))

    def test_green_review_without_style_summary_is_not_green(self) -> None:
        """Closure invariant: without the calibration builder's style summary the
        review is NOT green, so the established treatment cannot silently fail to
        propagate — the build gate refuses until it exists with usable content."""
        self.green_calibration([1])
        self.write_spec([slide(1, kind="cover")])
        (self.work / "calibration" / "style-summary.json").unlink()
        review = cr.calibration_review(self.work)
        self.assertFalse(review["ok"])
        self.assertEqual("builder", review["action"])
        self.assertIn("style-summary", review["reason"])
        self.assertIsNone(sc.build_style_contract(self.work))
        # an empty-shaped summary is equally unusable
        (self.work / "calibration" / "style-summary.json").write_text(
            json.dumps({"established": {}, "do_not_repeat": []}), encoding="utf-8"
        )
        self.assertFalse(cr.calibration_review(self.work)["ok"])

    def test_calibration_without_green_review_returns_none(self) -> None:
        (self.work / "calibration").mkdir()
        (self.work / "calibration" / "calibration-manifest.json").write_text(
            json.dumps({"slides": [1], "pptx": {"sha256": "x"}}), encoding="utf-8"
        )
        self.assertIsNone(sc.build_style_contract(self.work))

    def test_calibration_review_requires_hook_owned_receipt(self) -> None:
        self.green_calibration([1])
        receipt = self.work / "calibration" / "calibration-critic-execution.json"
        receipt.unlink()
        result = cr.calibration_review(self.work)
        self.assertFalse(result["ok"])
        self.assertEqual("critic", result["action"])
        self.assertIn("missing successful isolated calibration critic receipt", result["reason"])

    def test_allow_missing_degrades_only_an_absent_calibration_receipt(self) -> None:
        self.green_calibration([1])
        receipt = self.work / "calibration" / "calibration-critic-execution.json"
        receipt.unlink()
        (self.work / "build-manifest.json").write_text(
            json.dumps({"receipt_policy": "allow-missing"}), encoding="utf-8"
        )
        result = cr.calibration_review(self.work)
        self.assertTrue(result["ok"])
        self.assertTrue(result["receipt_degraded"])
        receipt.write_text("{}", encoding="utf-8")
        result = cr.calibration_review(self.work)
        self.assertFalse(result["ok"])
        self.assertIn("identity is invalid", result["reason"])

    def test_green_calibration_projects_style_and_archetypes(self) -> None:
        self.green_calibration([1, 4])
        self.write_spec(
            [
                slide(1, kind="cover"),
                slide(2, layout="text-heavy"),
                slide(3, layout="text-heavy"),
                slide(4, layout="survey"),
            ]
        )
        self.write_art()
        contract = sc.build_style_contract(self.work)
        self.assertIsNotNone(contract)
        self.assertEqual([1, 4], contract["calibration_slides"])
        self.assertEqual({1: "hero", 4: "data"}, contract["calibrated_archetypes"])
        self.assertEqual("Academic Rigorous", contract["style"]["style_seed"])
        self.assertIn("native chart, one highlighted series", str(contract["style"]["chart_grammar"]))
        # anti-repetition: seed list plus the Art Direction's own avoid entries
        self.assertTrue(any("same container" in item for item in contract["anti_repetition"]))
        self.assertIn("equal cards as the default mapping", contract["anti_repetition"])
        # byte-traceable provenance
        self.assertTrue(all(contract["derived_from"].values()))

    def test_builder_style_summary_is_embedded_verbatim(self) -> None:
        self.green_calibration([1])
        self.write_spec([slide(1, kind="cover")])
        (self.work / "calibration").mkdir(exist_ok=True)
        (self.work / "calibration" / "style-summary.json").write_text(
            json.dumps(
                {
                    "established": {
                        "title_treatment": "left-aligned 34pt with a hairline under-rule",
                        "rhythm": "dense evidence pages alternate with sparse statement pages",
                    },
                    "do_not_repeat": ["no full-bleed photo behind body text"],
                }
            ),
            encoding="utf-8",
        )
        contract = sc.build_style_contract(self.work)
        self.assertEqual(
            "left-aligned 34pt with a hairline under-rule",
            contract["treatment"]["title_treatment"],
        )
        self.assertIn("no full-bleed photo behind body text", contract["anti_repetition"])

    def test_ensure_writes_once_and_is_idempotent(self) -> None:
        self.green_calibration([1])
        self.write_spec([slide(1, kind="cover")])
        path = sc.ensure_style_contract(self.work)
        self.assertIsNotNone(path)
        first = path.read_text(encoding="utf-8")
        self.assertEqual(path, sc.ensure_style_contract(self.work))
        self.assertEqual(first, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
