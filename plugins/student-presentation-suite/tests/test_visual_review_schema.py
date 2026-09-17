from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "references" / "visual-review.schema.json"
CRITIC_REFERENCE = ROOT / "skills" / "sp-deck" / "references" / "pptx-visual-critic.md"
QUALITY = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_quality_gate_v071.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def example_from_reference() -> dict[str, Any]:
    """The critic reference must keep a JSON example under `## visual-review.json`."""
    text = CRITIC_REFERENCE.read_text(encoding="utf-8")
    match = re.search(r"## visual-review\.json.*?```json\n(.*?)```", text, re.S)
    assert match, "pptx-visual-critic.md lost its json example"
    return json.loads(match.group(1))


def concretize(value: Any, key: str | None = None) -> Any:
    """Replace doc placeholders (`<...>`) with schema-valid values."""
    if isinstance(value, dict):
        return {str(k): concretize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [concretize(item, key) for item in value]
    if isinstance(value, str) and "<" in value and ">" in value:
        if key in {"pptx_sha256", "contact_sheet_sha256"} or (key or "").isdigit():
            return "0" * 64
        return "示例占位说明"
    return value


class VisualReviewSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def test_reference_example_validates_against_the_canonical_schema(self) -> None:
        """2026-09-17 live: the old example was missing 9 required fields, so the critic
        wrote an `issues` top-level structure from memory and the QA gate rejected it."""
        report = concretize(example_from_reference())
        self.validator.validate(report)

    def _bound_report(
        self,
        tmp: str,
        pptx: Path,
        structures: tuple[str, ...] = ("editorial", "chart"),
    ) -> tuple[Path, dict[str, Any]]:
        """Reference example concretized and bound to `pptx`, covering 1..N pages."""
        digest = hashlib.sha256(pptx.read_bytes()).hexdigest()
        report = concretize(example_from_reference())
        report["pptx_sha256"] = digest
        report["page_count"] = len(structures)
        report["page_sha256"] = {str(number): digest for number in range(1, len(structures) + 1)}
        first = report["slides"][0]
        report["slides"] = [
            {**first, "slide": number, "visual_structure": structure, "issues": []}
            for number, structure in enumerate(structures, start=1)
        ]
        path = Path(tmp) / "visual-review.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return path, report

    def test_canonical_schema_satisfies_the_quality_gate_structural_checks(self) -> None:
        quality = load_module("pptx_quality_gate_v071_schema_test", QUALITY)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            pptx.write_bytes(b"deck-bytes")
            report_path, report = self._bound_report(tmp, pptx)
            self.validator.validate(report)
            result = quality.validate_visual_report(report_path, pptx, 2, high_score=True)
            self.assertEqual([], result["issues"], result["issues"])
            self.assertTrue(result["ok"])

    def test_top_level_structure_drift_names_the_missing_fields(self) -> None:
        """2026-09-17 live: the critic submitted a top-level `issues` structure; the
        gate answered with derived errors and the main session pasted the schema into
        four more spawns. The schema violation must name the missing fields instead."""
        quality = load_module("pptx_quality_gate_v071_drift_test", QUALITY)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            pptx.write_bytes(b"deck-bytes")
            digest = hashlib.sha256(b"deck-bytes").hexdigest()
            report_path = Path(tmp) / "visual-review.json"
            report_path.write_text(
                json.dumps(
                    {
                        "pptx_sha256": digest,
                        "issues": [{"code": "x", "severity": "minor", "message": "y"}],
                    }
                ),
                encoding="utf-8",
            )
            result = quality.validate_visual_report(report_path, pptx, 1, high_score=True)
            self.assertFalse(result["ok"])
            messages = [item["message"] for item in result["issues"] if item["code"] == "visual_review_schema_invalid"]
            self.assertTrue(messages, result["issues"])
            self.assertIn("slides", messages[0])
            self.assertIn("visual-review.schema.json", messages[0])

    def test_declared_blocker_count_disagreeing_with_the_gate_is_named(self) -> None:
        """2026-09-17 live: critic reported 'blocker count: 0 (major 8)' under its own
        reading of the word, the caller read that as 'deliverable', and the gate counting
        critical+major answered with 23 blockers on the very same report. Both numbers and
        the definition must appear together."""
        quality = load_module("pptx_quality_gate_v071_blocker_count_test", QUALITY)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            pptx.write_bytes(b"deck-bytes")
            report_path, report = self._bound_report(tmp, pptx)
            report["blocker_count"] = 0
            report["slides"][0]["issues"] = [
                {"code": "crowded-rail", "severity": "major", "message": "左栏过密"}
            ]
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            result = quality.validate_visual_report(report_path, pptx, 2, high_score=True)
            mismatch = [item for item in result["issues"] if item["code"] == "visual_review_blocker_count_mismatch"]
            self.assertTrue(mismatch, result["issues"])
            self.assertIn("critical + major", mismatch[0]["message"])
            self.assertFalse(result["ok"], "the major itself still blocks")

    def test_extra_properties_are_advisory_not_blocking(self) -> None:
        """Unknown fields must never cost a repair round: the schema declares them
        invalid, the gate only reports them."""
        quality = load_module("pptx_quality_gate_v071_extra_test", QUALITY)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            pptx.write_bytes(b"deck-bytes")
            report_path, report = self._bound_report(tmp, pptx)
            report["reviewer_notes"] = "scratch field the schema does not know"
            with self.assertRaises(jsonschema.ValidationError):
                self.validator.validate(report)
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            result = quality.validate_visual_report(report_path, pptx, 2, high_score=True)
            codes = {item["code"] for item in result["issues"]}
            self.assertIn("visual_review_schema_extra", codes)
            self.assertTrue(result["ok"], result["issues"])

    def test_required_boundary_matches_what_the_gate_actually_reads(self) -> None:
        """required 只含门消费的最小集：给 critic 加无人读取的必填字段，只会制造
        新的漏写返工。门读 pptx_sha256 / slides（slide、visual_structure、scores、issues）。"""
        self.assertEqual(["pptx_sha256", "slides"], self.schema["required"])
        self.assertEqual(
            ["slide", "visual_structure", "scores", "issues"],
            self.schema["properties"]["slides"]["items"]["required"],
        )
        self.assertEqual(
            ["hierarchy", "focal_point", "composition", "visual_interest", "whitespace"],
            self.schema["properties"]["slides"]["items"]["properties"]["scores"]["required"],
        )


if __name__ == "__main__":
    unittest.main()
