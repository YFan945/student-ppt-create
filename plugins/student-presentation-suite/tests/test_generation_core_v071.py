from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"
QUALITY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_quality_gate_v071.py"
DELIVERY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_delivery_check_v071.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenerationCoreV071Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = load_module("slide_spec_guard_v071_test", SPEC_GUARD)
        cls.quality = load_module("pptx_quality_gate_v071_test", QUALITY)
        cls.delivery = load_module("pptx_delivery_check_v071_test", DELIVERY)

    def make_frozen_spec(self, root: Path, text: str = "slides: []\n"):
        spec = root / "slide-spec.yaml"
        spec.write_text(text, encoding="utf-8")
        report = root / "slide-spec-report.json"
        report.write_text(
            json.dumps(
                {
                    "valid": True,
                    "slide_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        lock = root / "slide-spec-lock.json"
        self.guard.write_lock(
            lock,
            self.guard.make_lock(
                spec,
                report,
                revision=1,
                reason="initial approved production plan",
            ),
        )
        return spec, report, lock

    def test_frozen_spec_detects_silent_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec, _, lock = self.make_frozen_spec(root, "slides:\n  - id: 1\n")
            self.assertTrue(self.guard.check_lock(lock, spec)["ok"])
            spec.write_text("slides:\n  - id: 2\n", encoding="utf-8")
            result = self.guard.check_lock(lock, spec)
            self.assertFalse(result["ok"])
            self.assertTrue(any("changed after approval" in item for item in result["errors"]))

    def test_explicit_spec_revision_creates_parent_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec, _, lock = self.make_frozen_spec(root, "slides:\n  - id: 1\n")
            first_hash = self.guard.load_lock(lock)["slide_spec_sha256"]
            spec.write_text("slides:\n  - id: 1\n  - id: 2\n", encoding="utf-8")
            report = root / "slide-spec-report-v2.json"
            report.write_text(
                json.dumps(
                    {
                        "valid": True,
                        "slide_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            revised = self.guard.make_lock(
                spec,
                report,
                revision=2,
                reason="user-approved plan correction",
                parent_sha256=first_hash,
            )
            self.guard.write_lock(lock, revised)
            after = self.guard.load_lock(lock)
            self.assertEqual(2, after["revision"])
            self.assertEqual(first_hash, after["parent_slide_spec_sha256"])
            self.assertTrue(self.guard.check_lock(lock, spec)["ok"])

    def test_visual_critic_blocks_consecutive_equal_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = root / "visual.json"
            slides = []
            for number, structure in enumerate(
                ["cover", "equal-cards", "equal-cards", "typography", "flow", "reference"],
                start=1,
            ):
                slides.append(
                    {
                        "slide": number,
                        "visual_structure": structure,
                        "scores": {
                            "hierarchy": 8,
                            "focal_point": 8,
                            "composition": 8,
                            "visual_interest": 8,
                            "whitespace": 8,
                        },
                        "ai_template_feel": "none",
                        "issues": [],
                    }
                )
            report.write_text(
                json.dumps({"pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(), "slides": slides}),
                encoding="utf-8",
            )
            result = self.quality.validate_visual_report(report, pptx, 6, high_score=True)
            self.assertFalse(result["ok"])
            self.assertIn("repetitive_structure_pair", {item["code"] for item in result["issues"]})

    def test_visual_critic_blocks_low_high_score_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"pptx")
            report = root / "visual.json"
            report.write_text(
                json.dumps(
                    {
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "slides": [
                            {
                                "slide": 1,
                                "visual_structure": "statement",
                                "scores": {
                                    "hierarchy": 8,
                                    "focal_point": 5,
                                    "composition": 8,
                                    "visual_interest": 8,
                                    "whitespace": 8,
                                },
                                "ai_template_feel": "none",
                                "issues": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = self.quality.validate_visual_report(report, pptx, 1, high_score=True)
            self.assertFalse(result["ok"])
            self.assertIn("visual_score_low", {item["code"] for item in result["issues"]})

    def test_evidence_closure_blocks_missing_final_reference(self) -> None:
        spec = {
            "meta": {"citation_style": "classroom"},
            "evidence_ledger": [
                {
                    "id": "paper-a",
                    "title": "SelfCheckGPT: Zero-Resource Black-Box Hallucination Detection",
                    "source_type": "paper",
                    "locator": "EMNLP 2023",
                    "author": "Manakul et al.",
                    "date": "2023",
                    "confidence": "high",
                    "used_on_slides": [2],
                }
            ],
            "slides": [
                {"id": 1, "title": "Cover"},
                {"id": 2, "title": "Detection", "evidence_refs": ["paper-a"]},
                {"id": 3, "title": "Conclusion"},
            ],
        }
        result = self.quality.check_evidence(spec, ["Cover", "Detection source: Manakul 2023", "Conclusion only"])
        self.assertFalse(result["ok"])
        self.assertIn("missing_final_reference", {item["code"] for item in result["issues"]})

    def test_evidence_closure_passes_when_reference_is_in_final_area(self) -> None:
        spec = {
            "meta": {"citation_style": "classroom"},
            "evidence_ledger": [
                {
                    "id": "paper-a",
                    "title": "SelfCheckGPT: Zero-Resource Black-Box Hallucination Detection",
                    "source_type": "paper",
                    "locator": "EMNLP 2023",
                    "author": "Manakul et al.",
                    "date": "2023",
                    "confidence": "high",
                    "used_on_slides": [2],
                }
            ],
            "slides": [
                {"id": 1, "title": "Cover"},
                {"id": 2, "title": "Detection", "evidence_refs": ["paper-a"]},
                {"id": 3, "title": "References", "kind": "references"},
            ],
        }
        result = self.quality.check_evidence(
            spec,
            ["Cover", "Detection source: Manakul 2023", "Manakul et al. SelfCheckGPT. EMNLP 2023."],
        )
        self.assertTrue(result["ok"], result["issues"])

    def test_timing_estimator_blocks_deck_overrun(self) -> None:
        spec = {
            "meta": {"duration_min": 1, "include_speaker_notes": True},
            "slides": [
                {
                    "id": 1,
                    "timing_sec": 60,
                    "speaker_notes": "这是测试讲稿。" * 60,
                }
            ],
        }
        result = self.quality.check_timing(spec)
        self.assertFalse(result["ok"])
        self.assertIn("deck_timing_overrun", {item["code"] for item in result["issues"]})

    def test_delivery_quality_report_rejects_stale_pptx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec, _, lock = self.make_frozen_spec(root)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"current")
            quality = root / "quality.json"
            quality.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "generation_core_version": "0.7.1",
                        "pptx_sha256": "0" * 64,
                        "slide_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
                        "spec_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
                        "slide_count": 1,
                        "blocker_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            result = self.delivery.validate_quality_report(quality, pptx, spec, lock, 1)
            self.assertFalse(result["valid"])
            self.assertTrue(any("current PPTX" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
