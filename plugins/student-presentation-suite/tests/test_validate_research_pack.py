"""Research Pack 契约的可执行定义。"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_helpers import load_module  # noqa: E402

SCRIPT = ROOT / "scripts" / "validate_research_pack.py"


def base_pack() -> dict:
    return {
        "version": "0.10",
        "topic": "多模态大模型幻觉",
        "budget": "standard",
        "queries": ["LVLM hallucination survey 2026", "multimodal hallucination benchmark"],
        "findings": [
            {
                "id": "F01",
                "claim": "对象幻觉是 LVLM 最常见的幻觉类型之一",
                "confidence": "high",
                "source_ids": ["S01", "S02"],
            }
        ],
        "data_points": [
            {
                "id": "D01",
                "value": "38%",
                "meaning": "某基准上的幻觉率",
                "year": 2026,
                "confidence": "high",
                "source_ids": ["S01", "S02"],
            }
        ],
        "quotes": [],
        "sources": [
            {
                "id": "S01",
                "title": "LVLM Hallucination Survey",
                "type": "paper",
                "tier": "A",
                "independence_group": "cvpr-2026-survey",
                "publisher": "CVPR",
                "year": 2026,
                "url": "https://example.org/s01",
            },
            {
                "id": "S02",
                "title": "Hallucination Benchmark",
                "type": "paper",
                "tier": "S",
                "independence_group": "arxiv-2601-benchmark",
                "year": 2026,
                "locator": "arXiv:2601.00001",
            },
        ],
        "conflicts": [],
        "knowledge_gaps": [],
        "visual_candidates": [
            {"id": "V01", "type": "bar_chart", "priority": "high", "data_point_ids": ["D01"]}
        ],
        "unresolved": [],
    }


class ResearchPackContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module(SCRIPT)

    def codes(self, pack: dict, severity: str | None = None) -> list[str]:
        report = self.module.validate(pack)
        return [p["code"] for p in report["problems"] if severity is None or p["severity"] == severity]

    def test_a_well_formed_pack_passes(self) -> None:
        report = self.module.validate(base_pack())
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(0, report["counts"]["blockers"])

    def test_missing_source_reference_is_critical(self) -> None:
        pack = base_pack()
        pack["findings"][0]["source_ids"] = ["S99"]
        self.assertIn("unknown_source_ref", self.codes(pack, "critical"))

    def test_high_confidence_finding_needs_a_strong_source(self) -> None:
        pack = base_pack()
        pack["sources"] = [pack["sources"][0]]
        pack["sources"][0]["tier"] = "C"
        pack["findings"][0]["source_ids"] = ["S01"]
        pack["data_points"][0]["source_ids"] = ["S01"]
        codes = self.codes(pack, "major")
        self.assertIn("weak_source_for_high_confidence", codes)
        self.assertIn("weak_source_for_data_point", codes)

    def test_tier_d_alone_cannot_support_a_claim(self) -> None:
        pack = base_pack()
        pack["sources"][0]["tier"] = "D"
        pack["sources"] = [pack["sources"][0]]
        pack["findings"][0]["source_ids"] = ["S01"]
        self.assertIn("tier_d_cannot_support_claim", self.codes(pack, "major"))

    def test_high_confidence_number_needs_cross_validation(self) -> None:
        pack = base_pack()
        pack["data_points"][0]["source_ids"] = ["S01"]
        self.assertIn("high_confidence_needs_cross_check", self.codes(pack, "major"))

    def test_a_flagged_conflict_must_lower_confidence_and_be_recorded(self) -> None:
        pack = base_pack()
        pack["data_points"][0]["conflict"] = True
        codes = self.codes(pack, "major")
        self.assertIn("conflict_must_downgrade_confidence", codes)
        self.assertIn("conflict_not_recorded", codes)

        fixed = base_pack()
        fixed["data_points"][0]["conflict"] = True
        fixed["data_points"][0]["confidence"] = "low"
        fixed["data_points"][0]["notes"] = "两个来源口径不同，取区间表述"
        fixed["conflicts"] = [
            {
                "id": "C01",
                "topic": "幻觉率口径",
                "entries": [
                    {"value": "38%", "source_id": "S01"},
                    {"value": "52%", "source_id": "S02"},
                ],
                "affected_ids": ["D01"],
            }
        ]
        report = self.module.validate(fixed)
        self.assertTrue(report["ok"], report["problems"])

    def test_budget_caps_are_enforced(self) -> None:
        pack = base_pack()
        pack["budget"] = "simple"
        pack["queries"] = [f"q{i}" for i in range(4)]
        self.assertIn("budget_exceeded", self.codes(pack, "major"))

    def test_user_approved_budget_extension_relaxes_the_query_cap(self) -> None:
        """2026-09-17 live: deep 16/15 forced a full gap-fill revert; the recorded
        extension is the honest overage path instead of deleting audit queries."""
        pack = base_pack()
        pack["budget"] = "simple"
        pack["queries"] = [f"q{i}" for i in range(5)]
        pack["budget_extension"] = {
            "extra_queries": 2,
            "approved_by": "user",
            "reason": "用户批准为土地与选址维度补检 2 次",
        }
        self.assertNotIn("budget_exceeded", self.codes(pack, "major"))

    def test_budget_extension_requires_user_approval_and_reason(self) -> None:
        pack = base_pack()
        pack["budget"] = "simple"
        pack["queries"] = [f"q{i}" for i in range(4)]
        for bad in (
            {"extra_queries": 2, "approved_by": "model", "reason": "self-approved"},
            {"extra_queries": 2, "approved_by": "user", "reason": "  "},
            {"extra_queries": 0, "approved_by": "user", "reason": "no headroom"},
        ):
            with self.subTest(extension=bad):
                pack["budget_extension"] = bad
                self.assertIn("budget_extension_invalid", self.codes(pack, "major"))
        pack["budget_extension"] = None
        self.assertIn("budget_exceeded", self.codes(pack, "major"))

    def test_a_source_without_url_or_locator_is_not_traceable(self) -> None:
        pack = base_pack()
        del pack["sources"][0]["url"]
        self.assertIn("source_not_traceable", self.codes(pack, "major"))

    def test_bad_and_duplicate_ids_are_critical(self) -> None:
        pack = base_pack()
        pack["findings"].append(copy.deepcopy(pack["findings"][0]))
        self.assertIn("duplicate_id", self.codes(pack, "critical"))

        pack2 = base_pack()
        pack2["findings"][0]["id"] = "finding-one"
        self.assertIn("bad_id", self.codes(pack2, "critical"))

    def test_two_rows_from_one_origin_are_not_two_sources(self) -> None:
        pack = base_pack()
        pack["sources"][1]["independence_group"] = pack["sources"][0]["independence_group"]
        self.assertIn("sources_are_not_independent", self.codes(pack, "major"))

    def test_a_conflicting_finding_must_be_recorded(self) -> None:
        pack = base_pack()
        pack["findings"][0]["conflict"] = True
        pack["findings"][0]["confidence"] = "low"
        pack["findings"][0]["notes"] = "两项研究结论方向相反"
        self.assertIn("conflict_not_recorded", self.codes(pack, "major"))

    def test_tier_cannot_exceed_what_the_source_type_supports(self) -> None:
        pack = base_pack()
        pack["sources"][0]["type"] = "personal-blog"
        pack["sources"][0]["tier"] = "S"
        self.assertIn("tier_above_type_ceiling", self.codes(pack, "major"))

    def test_d_mode_requires_empty_queries_and_user_files_only(self) -> None:
        pack = base_pack()
        pack["queries"] = []
        pack["sources"][1]["type"] = "news"
        self.assertIn("sources_without_queries", self.codes(pack, "major"))

        clean = base_pack()
        clean["queries"] = []
        for source in clean["sources"]:
            source["type"] = "user-file"
            source["tier"] = "S"
        clean["findings"][0]["source_ids"] = ["S01"]
        clean["data_points"][0]["source_ids"] = ["S01"]
        clean["data_points"][0]["confidence"] = "medium"
        self.assertTrue(self.module.validate(clean)["ok"])

    def test_low_confidence_must_say_why(self) -> None:
        pack = base_pack()
        pack["data_points"][0]["confidence"] = "low"
        self.assertIn("low_confidence_without_reason", self.codes(pack, "major"))

    def test_low_confidence_data_point_with_notes_is_valid(self) -> None:
        pack = base_pack()
        pack["data_points"][0]["confidence"] = "low"
        pack["data_points"][0]["notes"] = "来源存在口径差异，因此只做保守区间表述"
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])
        self.assertNotIn("schema_violation", [p["code"] for p in report["problems"]])

    def test_blocked_retrieval_must_state_its_impact(self) -> None:
        pack = base_pack()
        pack["unresolved"] = [{"query": "IPCC AR6 原始表格", "reason": "access_blocked"}]
        report = self.module.validate(pack)
        self.assertFalse(report["ok"])
        self.assertIn("schema_violation", [p["code"] for p in report["problems"]])

    def test_unknown_visual_reference_is_major_not_minor(self) -> None:
        pack = base_pack()
        pack["visual_candidates"][0]["data_point_ids"] = ["D99"]
        self.assertIn("unknown_visual_ref", self.codes(pack, "major"))

    def test_unused_source_is_a_minor_not_a_blocker(self) -> None:
        pack = base_pack()
        pack["sources"].append(
            {
                "id": "S03",
                "title": "Unused",
                "type": "news",
                "tier": "B",
                "independence_group": "unused",
                "url": "https://example.org/s03",
            }
        )
        report = self.module.validate(pack)
        self.assertTrue(report["ok"])
        self.assertIn("unused_source", [p["code"] for p in report["problems"] if p["severity"] == "minor"])

    def test_schema_violation_is_caught(self) -> None:
        pack = base_pack()
        del pack["topic"]
        self.assertIn("schema_violation", self.codes(pack, "critical"))

    def test_cli_binds_report_to_exact_pack_hash(self) -> None:
        import contextlib
        import io

        with TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "research-pack.json"
            report_path = Path(tmp) / "validation.json"
            pack_path.write_text(json.dumps(base_pack(), ensure_ascii=False), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.module.main([str(pack_path), "--output", str(report_path)])
            self.assertEqual(0, code)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(self.module.sha256_file(pack_path), report["research_pack_sha256"])
            self.assertEqual(str(pack_path.resolve()), report["research_pack"])

    def test_cli_prints_one_line_when_ok_and_exits_two_when_blocked(self) -> None:
        import contextlib
        import io

        with TemporaryDirectory() as tmp:
            good = Path(tmp) / "research-pack.json"
            good.write_text(json.dumps(base_pack(), ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = self.module.main([str(good)])
            self.assertEqual(0, code)
            self.assertEqual(1, len(buffer.getvalue().splitlines()))

            bad_pack = base_pack()
            bad_pack["findings"][0]["source_ids"] = ["S99"]
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(bad_pack, ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = self.module.main([str(bad), "--output", str(Path(tmp) / "v.json")])
            self.assertEqual(2, code)
            self.assertIn("unknown_source_ref", buffer.getvalue())

    def test_missing_file_exits_two(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(2, self.module.main([str(Path(tmp) / "absent.json")]))


if __name__ == "__main__":
    unittest.main()
