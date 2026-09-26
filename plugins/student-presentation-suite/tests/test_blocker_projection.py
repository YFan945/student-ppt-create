"""Blockers must reach the repair packet with location and structured detail."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "skills" / "sp-deck" / "scripts"), str(ROOT / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import builder_packet as packet  # noqa: E402
import pptx_static_risk_check as static_gate  # noqa: E402
from pipeline.core import slide_number_of  # noqa: E402


class SlideNumberTests(unittest.TestCase):
    def test_all_gate_label_shapes_resolve(self) -> None:
        self.assertEqual(3, slide_number_of(3))
        self.assertEqual(3, slide_number_of("3"))
        self.assertEqual(3, slide_number_of("slide-3"))
        self.assertIsNone(slide_number_of(None))
        self.assertIsNone(slide_number_of(True))
        self.assertIsNone(slide_number_of("deck"))


class BlockerProjectionTests(unittest.TestCase):
    def test_string_slide_labels_land_in_the_packet(self) -> None:
        """The rendered gate wrote 'slide-3'; the packet matched ints and dropped it."""
        report = {"issues": [
            {"slide": "slide-3", "severity": "blocker", "code": "dead-space",
             "detail": "bottom whitespace 22% exceeds 10%"},
        ]}
        blockers = packet.report_slide_blockers(report, 3)
        self.assertEqual(1, len(blockers))
        self.assertEqual(3, blockers[0]["slide"])
        self.assertIn("22%", blockers[0]["detail"])

    def test_structured_fields_survive_projection(self) -> None:
        report = {"issues": [
            {"slide": 2, "severity": "major", "code": "planned_numbers_missing",
             "expected": ["0.044"], "missing": ["0.044"]},
            {"slide": 5, "severity": "major", "code": "off-palette-color",
             "part": "ppt/charts/chart1.xml", "colors": {"000000": 3},
             "elements": {"axis": {"000000": 2}}},
        ]}
        numbers = packet.report_slide_blockers(report, 2)[0]
        self.assertEqual(["0.044"], numbers["expected"])
        palette = packet.report_slide_blockers(report, 5)[0]
        self.assertEqual("ppt/charts/chart1.xml", palette["part"])
        self.assertEqual({"axis": {"000000": 2}}, palette["elements"])

    def test_nested_visual_review_findings_are_flattened(self) -> None:
        report = {
            "slides": [
                {"slide": 7, "issues": [
                    {"code": "weak-hierarchy", "severity": "major", "message": "title competes"},
                ]},
            ],
        }
        blockers = packet.report_slide_blockers(report, 7)
        self.assertEqual(1, len(blockers))
        self.assertEqual("weak-hierarchy", blockers[0]["code"])
        deck = [
            item for item in packet.report_items(report)
            if packet.slide_number_of(item.get("slide")) is None
        ]
        self.assertEqual([], deck, "a slide-scoped finding is never deck-level")


class RepairMinimisationContractTests(unittest.TestCase):
    def test_schema_declares_locate_and_fix_fields(self) -> None:
        schema = json.loads(
            (ROOT / "references" / "visual-review.schema.json").read_text(encoding="utf-8")
        )
        props = schema["$defs"]["finding"]["properties"]
        for field in ("element", "fix", "repair_level", "resolved_evidence"):
            self.assertIn(field, props)
        self.assertEqual(
            ["before_sha256", "after_sha256"], props["resolved_evidence"]["required"],
        )

    def test_repair_packet_carries_minimal_edit_and_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "slide-spec.json"
            spec.write_text(
                json.dumps({"slides": [{"id": 1, "title": "封面", "kind": "cover"}]}),
                encoding="utf-8",
            )
            (work / "pipeline-qa.json").write_text(
                json.dumps({"problems": [
                    {"gate": "quality", "severity": "major", "code": "overflow",
                     "slide": 1, "message": "body text overflows its box"},
                ]}),
                encoding="utf-8",
            )
            built = packet.build_packet(
                work, "repair", [1], qa_reports=[work / "pipeline-qa.json"],
                convergence={"trend": "flat", "suspect_gate_defect": {"code": "overflow"}},
            )
        self.assertIn("minimal_edit", built)
        self.assertIn("blockers", built["minimal_edit"]["scope"])
        self.assertEqual("flat", built["repair_convergence"]["trend"])

    def test_repair_packet_records_pages_touched(self) -> None:
        """D3 (informational): the packet shows which pages the blockers name
        versus the full assignment, so flat rounds on the same pages are visible."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "slide-spec.json"
            spec.write_text(json.dumps({
                "slides": [
                    {"id": 1, "title": "封面", "kind": "cover"},
                    {"id": 2, "title": "数据", "kind": "content"},
                ]
            }), encoding="utf-8")
            (work / "pipeline-qa.json").write_text(json.dumps({"problems": [
                {"gate": "quality", "severity": "major", "code": "overflow",
                 "slide": 1, "message": "body text overflows its box"},
            ]}), encoding="utf-8")
            built = packet.build_packet(
                work, "repair", [1, 2], qa_reports=[work / "pipeline-qa.json"],
            )
            self.assertEqual({"named": [1], "deck_level": False}, built["pages_touched"])

    def test_deck_level_blockers_mark_pages_touched_deck_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "slide-spec.json"
            spec.write_text(json.dumps({
                "slides": [{"id": 1, "title": "封面", "kind": "cover"}]
            }), encoding="utf-8")
            (work / "pipeline-qa.json").write_text(json.dumps({"problems": [
                {"gate": "quality", "severity": "major", "code": "bibliography_mismatch",
                 "message": "deck-level: evidence claims must match the bibliography"},
            ]}), encoding="utf-8")
            built = packet.build_packet(
                work, "repair", [1], qa_reports=[work / "pipeline-qa.json"],
            )
            self.assertTrue(built["pages_touched"]["deck_level"])
            self.assertEqual([], built["pages_touched"]["named"])

    def test_critic_contract_demands_element_and_fix(self) -> None:
        templates = (ROOT / "references" / "spawn-templates.md").read_text(encoding="utf-8")
        self.assertIn("`element`", templates)
        self.assertIn("`fix`", templates)
        self.assertIn("repair_level", templates)
        agent = (ROOT / "agents" / "visual-critic.md").read_text(encoding="utf-8")
        self.assertIn("executable `fix`", agent)


class StaticRiskGateMappingTests(unittest.TestCase):
    def test_overflow_finding_maps_to_a_major_with_element_detail(self) -> None:
        finding = {
            "slide": 4,
            "shape": "body text",
            "text_preview": "很长的正文……",
            "bounds": {"x": 100, "y": 200, "cx": 300, "cy": 80},
            "overflow_estimate": {"fill_ratio_raw": 1.4},
            "risk": ["text-vertical-overflow"],
        }
        with patch("pptx_static_risk_check.inspect_pptx", return_value={"findings": [finding]}):
            with patch("pptx_static_risk_check.summarize_static_risks",
                       return_value={"blocker_like": [finding], "risk_counter": {}}):
                report = static_gate.check(Path("/tmp/deck.pptx"))
        self.assertFalse(report["ok"])
        issue = report["issues"][0]
        self.assertEqual("major", issue["severity"])
        self.assertEqual("text-vertical-overflow", issue["code"])
        self.assertEqual(4, issue["slide"])
        self.assertEqual(finding["bounds"], issue["detail"]["bounds"])

    def test_clean_deck_passes(self) -> None:
        with patch("pptx_static_risk_check.inspect_pptx", return_value={"findings": []}):
            with patch("pptx_static_risk_check.summarize_static_risks",
                       return_value={"blocker_like": [], "risk_counter": {}}):
                report = static_gate.check(Path("/tmp/deck.pptx"))
        self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()
