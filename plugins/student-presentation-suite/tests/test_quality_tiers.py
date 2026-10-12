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

from shared.quality_tiers import (  # noqa: E402
    DEFAULT_TIER,
    calibration_enabled,
    effective_shard_cap,
    normalize,
    tier_policy,
    uses_preview_pair,
)


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

    def test_standard_records_score_lows_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = self.write_review(root, pptx, self.base_scores(hierarchy=4, composition=4), [])
            result = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("standard")
            )
            self.assertTrue(result["ok"], result["issues"])
            low = [item for item in result["issues"] if item["code"] == "visual_score_low"]
            self.assertTrue(low)
            self.assertTrue(all(item["severity"] == "advisory" for item in low))

            report = self.write_review(
                root, pptx, self.base_scores(),
                [{"code": "style", "severity": "major", "message": "repetitive", "element": "cards", "fix": "vary composition", "repair_level": "composition"}],
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
                [{"code": "style", "severity": "major", "message": "repetitive", "element": "cards", "fix": "vary composition", "repair_level": "composition"}],
            )
            result = self.quality.validate_visual_report(
                report, pptx, 1, policy=tier_policy("rigorous")
            )
            self.assertFalse(result["ok"])
            majors = [item for item in result["issues"] if item["severity"] == "major"]
            self.assertTrue(majors)


if __name__ == "__main__":
    unittest.main()



class MainSessionTierTests(unittest.TestCase):
    def test_quality_does_not_add_calibration_or_agents(self):
        for level in ('fast','standard','rigorous','basic','high-score'):
            for pages in (None, 2, 9, 40):
                self.assertFalse(calibration_enabled(level,pages))
                self.assertFalse(uses_preview_pair(level,pages))
                self.assertEqual(effective_shard_cap(level,pages),1)
