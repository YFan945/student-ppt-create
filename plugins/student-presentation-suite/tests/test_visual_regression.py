from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_quality_gate_v071.py"


def review(scores_by_slide: dict[int, float]) -> dict:
    return {
        "slides": [
            {
                "slide": number,
                "visual_structure": "editorial",
                "scores": {
                    "hierarchy": score,
                    "focal_point": score,
                    "composition": score,
                    "visual_interest": score,
                    "whitespace": score,
                },
                "issues": [],
            }
            for number, score in scores_by_slide.items()
        ]
    }


class VisualRegressionTests(unittest.TestCase):
    """2026-09-17 live: repair round 5 raised scores on paper while making pages worse,
    and round 6 (40.1M tokens) existed only to undo it. Nothing compared reviews, so the
    regression could not be attributed — this comparison is that missing step."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.history = Path(self.tmp.name) / "visual-score-history.json"
        self.gate = load_module(QUALITY)

    def test_first_review_records_scores_without_claiming_a_regression(self) -> None:
        issues, merged = self.gate.check_visual_regression(self.history, review({3: 8.0}))
        self.assertEqual([], issues)
        self.assertEqual({"3": {"average": 8.0, "best": 8.0}}, merged)

    def test_a_worse_page_is_reported_with_both_scores(self) -> None:
        self.history.write_text(json.dumps({"3": {"average": 8.0, "best": 8.0}}), encoding="utf-8")
        issues, merged = self.gate.check_visual_regression(self.history, review({3: 6.0}))
        self.assertEqual(["visual_regression"], [item["code"] for item in issues])
        self.assertEqual("major", issues[0]["severity"])
        self.assertEqual(3, issues[0]["slide"])
        self.assertIn("8", issues[0]["message"])
        self.assertIn("6", issues[0]["message"])
        self.assertEqual({"3": {"average": 6.0, "best": 8.0}}, merged)

    def test_small_moves_are_not_regressions(self) -> None:
        self.history.write_text(json.dumps({"3": {"average": 8.0, "best": 8.0}}), encoding="utf-8")
        issues, _ = self.gate.check_visual_regression(self.history, review({3: 7.0}))
        self.assertEqual([], issues, "a half-point of noise must not cost a repair round")

    def test_improvement_raises_the_stored_best(self) -> None:
        self.history.write_text(json.dumps({"3": {"average": 6.0, "best": 8.0}}), encoding="utf-8")
        issues, merged = self.gate.check_visual_regression(self.history, review({3: 9.0}))
        self.assertEqual([], issues)
        self.assertEqual({"3": {"average": 9.0, "best": 9.0}}, merged)

    def test_slow_erosion_is_caught_against_the_best_accepted_score(self) -> None:
        """Each step is under the threshold, so only a comparison against the best score
        notices that the deck has been sliding for three rounds."""
        self.history.write_text(json.dumps({"3": {"average": 8.0, "best": 8.0}}), encoding="utf-8")
        issues, merged = self.gate.check_visual_regression(self.history, review({3: 7.0}))
        self.assertEqual([], issues)
        merged_history = Path(self.tmp.name) / "second.json"
        merged_history.write_text(json.dumps(merged), encoding="utf-8")
        issues, merged = self.gate.check_visual_regression(merged_history, review({3: 6.2}))
        self.assertEqual(["visual_regression_sustained"], [item["code"] for item in issues])
        self.assertEqual(8.0, issues[0]["best_average"])
        self.assertEqual(8.0, merged["3"]["best"])

    def test_slides_missing_from_this_review_keep_their_history(self) -> None:
        self.history.write_text(json.dumps({"1": {"average": 9.0, "best": 9.0}}), encoding="utf-8")
        _, merged = self.gate.check_visual_regression(self.history, review({3: 7.0}))
        self.assertEqual({"1": {"average": 9.0, "best": 9.0}, "3": {"average": 7.0, "best": 7.0}}, merged)

    def test_a_corrupt_history_file_is_not_fatal(self) -> None:
        self.history.write_text("{not json", encoding="utf-8")
        issues, merged = self.gate.check_visual_regression(self.history, review({3: 7.0}))
        self.assertEqual([], issues)
        self.assertEqual({"3": {"average": 7.0, "best": 7.0}}, merged)


if __name__ == "__main__":
    unittest.main()
