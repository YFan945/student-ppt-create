"""Anti-self-proving contract tests for the quality and delivery gates.

The review's fatal finding #1: the generating model both creates findings and
declares them ``resolved``/``reviewed``. These tests lock in the fix:

1. ``resolved: true`` without sha256-bound ``resolved_evidence`` is ignored,
   reported as ``resolved_without_evidence``, and still blocks;
2. a bound ``resolved_evidence`` (before digest + matching after digest) clears
   the finding;
3. delivery completion requires a visual-review report file bound to the PPTX
   via ``pptx_sha256`` — the bare ``--visual-reviewed`` flag is not evidence.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_quality_gate_v071.py"
DELIVERY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_delivery_check.py"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ResolutionEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quality = load_module(QUALITY)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pptx = Path(self.tmp.name) / "deck.pptx"
        self.pptx.write_bytes(b"PK\x03\x04 not really a pptx, just a stable digest")
        self.digest = _digest(self.pptx)

    def _report(self, finding: dict) -> Path:
        report = {
            "pptx_sha256": self.digest,
            "slides": [
                {
                    "slide": 1,
                    "visual_structure": "diagram",
                    "scores": {
                        "hierarchy": 8,
                        "focal_point": 8,
                        "composition": 8,
                        "visual_interest": 8,
                        "whitespace": 8,
                    },
                    "issues": [finding],
                }
            ],
        }
        path = Path(self.tmp.name) / "visual-review.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_resolved_without_evidence_still_blocks(self) -> None:
        report = self._report(
            {"code": "cluttered_rail", "severity": "major", "message": "too busy", "resolved": True}
        )
        result = self.quality.validate_visual_report(report, self.pptx, 1, high_score=False)
        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("resolved_without_evidence", codes)
        self.assertIn("cluttered_rail", codes)
        self.assertFalse(result["ok"])

    def test_resolved_with_bound_evidence_is_accepted(self) -> None:
        report = self._report(
            {
                "code": "cluttered_rail",
                "severity": "major",
                "message": "too busy",
                "resolved": True,
                "resolved_evidence": {
                    "before_sha256": "0" * 64,
                    "after_sha256": self.digest,
                },
            }
        )
        result = self.quality.validate_visual_report(report, self.pptx, 1, high_score=False)
        self.assertEqual([], result["issues"])
        self.assertTrue(result["ok"])

    def test_stale_after_digest_does_not_clear_finding(self) -> None:
        report = self._report(
            {
                "code": "cluttered_rail",
                "severity": "major",
                "message": "too busy",
                "resolved": True,
                "resolved_evidence": {
                    "before_sha256": "0" * 64,
                    "after_sha256": "f" * 64,
                },
            }
        )
        result = self.quality.validate_visual_report(report, self.pptx, 1, high_score=False)
        self.assertFalse(result["ok"])


class VisualReviewReportBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.delivery = load_module(DELIVERY)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pptx = Path(self.tmp.name) / "deck.pptx"
        self.pptx.write_bytes(b"PK\x03\x04 deck bytes")

    def _write_report(self, pptx_sha: str) -> Path:
        report = {
            "pptx_sha256": pptx_sha,
            "slides": [{"slide": 1, "visual_structure": "diagram"}],
        }
        path = Path(self.tmp.name) / "visual-review.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_bound_report_is_valid(self) -> None:
        check = self.delivery.verify_visual_review_report(self._write_report(_digest(self.pptx)), self.pptx)
        self.assertTrue(check["valid"], check)

    def test_stale_binding_is_rejected(self) -> None:
        check = self.delivery.verify_visual_review_report(self._write_report("a" * 64), self.pptx)
        self.assertFalse(check["valid"])
        self.assertIn("not bound", check["reason"])

    def test_missing_file_is_rejected(self) -> None:
        check = self.delivery.verify_visual_review_report(Path(self.tmp.name) / "nope.json", self.pptx)
        self.assertFalse(check["valid"])


if __name__ == "__main__":
    unittest.main()
