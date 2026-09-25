"""Delivery tiers: one decision table, three behaviors (fast / standard / rigorous)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "skills" / "sp-deck" / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from shared.quality_tiers import DEFAULT_TIER, normalize, tier_policy  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class QualityTierTableTests(unittest.TestCase):
    def test_legacy_aliases_map_to_tiers(self) -> None:
        self.assertEqual("fast", normalize("basic"))
        self.assertEqual("rigorous", normalize("high-score"))
        self.assertEqual("fast", normalize("fast"))
        self.assertEqual("standard", normalize("standard"))
        self.assertEqual("rigorous", normalize("rigorous"))

    def test_missing_or_unknown_defaults_to_fast(self) -> None:
        self.assertEqual(DEFAULT_TIER, normalize(None))
        self.assertEqual(DEFAULT_TIER, normalize(""))
        self.assertEqual(DEFAULT_TIER, normalize("unspecified"))
        self.assertEqual(DEFAULT_TIER, normalize("turbo"))

    def test_fast_spends_nothing_beyond_one_shot(self) -> None:
        policy = tier_policy("fast")
        self.assertFalse(policy["calibration"])
        self.assertEqual(0, policy["calibration_max_rounds"])
        self.assertEqual(1, policy["shard_cap"])
        self.assertFalse(policy["block_structural"])
        self.assertFalse(policy["block_style_major"])
        self.assertFalse(policy["block_regression"])

    def test_standard_calibrates_once_and_blocks_structural_lows(self) -> None:
        policy = tier_policy("standard")
        self.assertTrue(policy["calibration"])
        self.assertEqual(1, policy["calibration_max_rounds"])
        self.assertEqual(2, policy["shard_cap"])
        self.assertTrue(policy["block_structural"])
        self.assertFalse(policy["block_style_major"])
        self.assertFalse(policy["block_regression"])

    def test_rigorous_keeps_the_full_high_score_contract(self) -> None:
        policy = tier_policy("high-score")  # legacy value resolves here
        self.assertEqual("rigorous", policy["tier"])
        self.assertTrue(policy["calibration"])
        self.assertEqual(2, policy["calibration_max_rounds"])
        self.assertEqual(3, policy["shard_cap"])
        self.assertTrue(policy["block_structural"])
        self.assertTrue(policy["block_style_major"])
        self.assertTrue(policy["block_regression"])
        self.assertTrue(policy["strict_v08"])


class TierGateMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.quality = load_module(
            "pptx_quality_gate_v071_tier_test",
            ROOT / "skills" / "sp-deck" / "scripts" / "pptx_quality_gate_v071.py",
        )

    def write_review(self, root: Path, pptx: Path, scores: dict, issues: list) -> Path:
        report = root / "visual.json"
        report.write_text(
            json.dumps({
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "slides": [
                    {
                        "slide": 1,
                        "visual_structure": "statement",
                        "scores": scores,
                        "ai_template_feel": "none",
                        "issues": issues,
                    }
                ],
            }),
            encoding="utf-8",
        )
        return report

    def base_scores(self, **over) -> dict:
        scores = {field: 8 for field in self.quality.SCORE_FIELDS}
        scores.update(over)
        return scores

    def test_standard_blocks_structural_lows_but_advises_style_majors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = self.write_review(root, pptx, self.base_scores(hierarchy=4), [])
            result = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("standard")
            )
            self.assertFalse(result["ok"])
            low = [item for item in result["issues"] if item["code"] == "visual_score_low"]
            self.assertEqual(["major"], [item["severity"] for item in low])

            report = self.write_review(
                root, pptx, self.base_scores(),
                [{"code": "style", "severity": "major", "message": "repetitive"}],
            )
            advised = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("standard")
            )
            self.assertTrue(advised["ok"])
            self.assertTrue(all(item["severity"] == "advisory" for item in advised["issues"]))

    def test_fast_advises_structural_lows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = self.write_review(root, pptx, self.base_scores(hierarchy=4), [])
            result = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("fast")
            )
            self.assertTrue(result["ok"])
            low = [item for item in result["issues"] if item["code"] == "visual_score_low"]
            self.assertEqual(["advisory"], [item["severity"] for item in low])

    def test_rigorous_blocks_style_majors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = self.write_review(
                root, pptx, self.base_scores(),
                [{"code": "style", "severity": "major", "message": "repetitive"}],
            )
            result = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("rigorous")
            )
            self.assertFalse(result["ok"])
            majors = [item for item in result["issues"] if item["severity"] == "major"]
            self.assertTrue(majors)


if __name__ == "__main__":
    unittest.main()
