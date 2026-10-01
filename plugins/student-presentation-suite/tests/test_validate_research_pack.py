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

    def test_tier_letters_are_metadata_and_gate_nothing(self) -> None:
        pack = base_pack()
        pack["sources"][0]["type"] = "news"
        pack["sources"][0]["tier"] = "S"
        pack["sources"][1]["type"] = "industry-report"
        pack["sources"][1]["tier"] = "C"
        codes = self.codes(pack)
        self.assertNotIn("weak_source_for_high_confidence", codes, "tier gates are removed")
        self.assertNotIn("weak_source_for_data_point", codes, "tier gates are removed")
        self.assertNotIn("tier_above_type_ceiling", codes, "type ceilings are removed")

    def test_same_registrable_domain_is_one_independent_origin(self) -> None:
        pack = base_pack()
        pack["sources"][1]["url"] = "https://example.org/s02"
        codes = self.codes(pack, "major")
        self.assertIn("sources_are_not_independent", codes)

    def test_cross_domain_sources_stay_independent(self) -> None:
        pack = base_pack()
        pack["sources"][1]["url"] = "https://other-site.cn/s02"
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])

    def test_independence_note_overrides_domain_grouping_with_an_advisory(self) -> None:
        pack = base_pack()
        pack["sources"][1]["url"] = "https://example.org/s02"
        pack["sources"][1]["independence_note"] = "同一门户下两份不同机构发布的报告"
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])
        codes = [p["code"] for p in report["problems"]]
        self.assertIn("independence_override_used", codes)
        self.assertEqual(0, report["counts"]["blockers"])
        self.assertEqual(2, report["counts"]["minor"])

    def test_opinion_only_support_is_an_advisory_not_a_rejection(self) -> None:
        # Owner ruling 2026-09-30: too strict to reject. The pack passes; the flag
        # tells the slide to attribute the number as a community/vendor view.
        pack = base_pack()
        pack["sources"][0]["type"] = "community"
        pack["sources"][0]["tier"] = "D"
        pack["sources"] = [pack["sources"][0]]
        pack["findings"][0]["source_ids"] = ["S01"]
        pack["data_points"][0]["source_ids"] = ["S01"]
        pack["data_points"][0]["confidence"] = "medium"
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(0, report["counts"]["blockers"])
        # flagged per entity (finding + data_point), never blocking
        self.assertIn("opinion_only_support", self.codes(pack, "minor"))

    def test_the_opinion_advisory_is_kind_based_not_tier_based(self) -> None:
        pack = base_pack()
        pack["sources"][0]["tier"] = "D"
        pack["sources"][0]["type"] = "paper"
        pack["findings"][0]["confidence"] = "medium"
        pack["data_points"][0]["confidence"] = "medium"
        codes = self.codes(pack)
        self.assertNotIn("opinion_only_support", codes)
        self.assertNotIn("tier_d_cannot_support_claim", codes)

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

    def test_query_and_source_counts_are_not_capped(self) -> None:
        """owner 指令（2026-09-28）：检索/抓取不设次数配额——超量不再产生 blocker，
        band 只是深度建议。"""
        pack = base_pack()
        pack["budget"] = "simple"
        pack["queries"] = [f"q{i}" for i in range(20)]
        pack["sources"] = pack["sources"] * 8
        report = self.module.validate(pack)
        self.assertNotIn(
            "budget_exceeded", [p["code"] for p in report["problems"]], report["problems"]
        )

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

    def test_tier_type_mismatch_is_no_longer_a_blocker(self) -> None:
        # The ceiling table is gone with the tier gates (0.23.3): a source's tier
        # letter is metadata, so a news source self-graded A validates cleanly.
        pack = base_pack()
        pack["sources"][0]["type"] = "news"
        pack["sources"][0]["tier"] = "A"
        self.assertNotIn("tier_above_type_ceiling", self.codes(pack))

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

    def test_backend_unavailable_is_a_valid_reason_distinct_from_not_found(self) -> None:
        pack = base_pack()
        pack["unresolved"] = [
            {
                "query": "国家能源局 2025年全国电力工业统计数据",
                "reason": "search_unavailable",
                "impact": "装机数据降级为区间表述，页面标注无来源",
            }
        ]
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])

    def test_entity_link_satisfies_closure_without_retyped_sources(self) -> None:
        # 0.23.6: entity_ids is the preferred support declaration — sources travel
        # with the entity, so must_verify does not re-type them in source_ids.
        pack = base_pack()
        pack["must_verify"] = [
            {"claim": "对象幻觉是 LVLM 最常见的幻觉类型之一", "status": "verified", "entity_ids": ["F01", "D01"]},
            {"claim": "幻觉率约 38%", "status": "verified", "entity_ids": ["D01"]},
            {"claim": "原文表格无法获取", "status": "unresolved"},
        ]
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])

    def test_unknown_entity_reference_is_major(self) -> None:
        pack = base_pack()
        pack["must_verify"] = [
            {"claim": "对象幻觉是 LVLM 最常见的幻觉类型之一", "status": "verified", "entity_ids": ["F99"]},
        ]
        self.assertIn("must_verify_unknown_entity", self.codes(pack, "major"))

    def test_verified_claim_on_a_conflicted_entity_is_refused(self) -> None:
        pack = base_pack()
        pack["findings"][0]["conflict"] = True
        pack["findings"][0]["confidence"] = "low"
        pack["findings"][0]["notes"] = "两项研究结论方向相反"
        pack["conflicts"] = [
            {
                "id": "C01",
                "topic": "幻觉率口径",
                "entries": [
                    {"value": "38%", "source_id": "S01"},
                    {"value": "52%", "source_id": "S02"},
                ],
                "affected_ids": ["F01"],
            }
        ]
        pack["must_verify"] = [
            {"claim": "对象幻觉是 LVLM 最常见的幻觉类型之一", "status": "verified", "entity_ids": ["F01"]},
        ]
        codes = self.codes(pack, "major")
        self.assertIn("must_verify_conflicted_entity", codes)

    def test_claim_count_is_minor_not_blocking(self) -> None:
        pack = base_pack()
        pack["must_verify"] = [
            {"claim": "c1", "status": "verified", "entity_ids": ["F01"]},
            {"claim": "c2", "status": "verified", "entity_ids": ["D01"]},
        ]
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])
        self.assertIn("must_verify_count", self.codes(pack, "minor"))

    def test_verified_entry_must_link_entities_when_the_pack_has_them(self) -> None:
        # 0.23.7: the re-typed-source path is closed — bare source_ids closure is refused
        # so the ledger exists in exactly one place (the entity), the closure points at it.
        pack = base_pack()
        pack["must_verify"] = [
            {"claim": "对象幻觉是 LVLM 最常见的幻觉类型之一", "status": "verified", "source_ids": ["S01", "S02"]},
        ]
        self.assertIn("must_verify_unlinked", self.codes(pack, "major"))

    def test_sources_listed_by_a_linked_claim_must_be_used_by_the_entity(self) -> None:
        pack = base_pack()
        pack["must_verify"] = [
            {
                "claim": "对象幻觉是 LVLM 最常见的幻觉类型之一",
                "status": "verified",
                "entity_ids": ["F01"],
                "source_ids": ["S01", "S02"],
            },
        ]
        # F01 rests on S01+S02 so both travel; an orphan is S99-style extra — craft one:
        pack["must_verify"][0]["entity_ids"] = ["D01"]  # D01 also uses S01+S02
        self.assertNotIn("must_verify_orphan_source", self.codes(pack, "major"))
        pack["sources"].append(
            {"id": "S03", "title": "extra", "type": "news", "tier": "B", "independence_group": "e"}
        )
        pack["must_verify"][0]["source_ids"] = ["S01", "S02", "S03"]
        self.assertIn("must_verify_orphan_source", self.codes(pack, "major"))

    def test_d_class_import_pack_still_closes_with_bare_sources(self) -> None:
        # No F/D entities (D-class import) keeps the legacy path by definition.
        pack = base_pack()
        pack["findings"] = []
        pack["data_points"] = []
        pack["visual_candidates"] = []
        pack["must_verify"] = [
            {"claim": "c1", "status": "verified", "source_ids": ["S01"]},
            {"claim": "c2", "status": "verified", "source_ids": ["S01"]},
            {"claim": "c3", "status": "verified", "source_ids": ["S01"]},
        ]
        report = self.module.validate(pack)
        self.assertTrue(report["ok"], report["problems"])


    def test_budget_reason_is_no_longer_accepted(self) -> None:
        pack = base_pack()
        pack["unresolved"] = [
            {"query": "某数据", "reason": "out_of_budget", "impact": "降级为常识表述"}
        ]
        report = self.module.validate(pack)
        self.assertFalse(report["ok"], "the removed budget vocabulary must not validate")
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


class RetrievalAuditTests(unittest.TestCase):
    """§七 behavior rules audited against the run's own telemetry (all minor, never blocking)."""

    def setUp(self) -> None:
        self.module = load_module(SCRIPT)

    def codes(self, pack, search_log=None, fetch_report=None, search_payloads=None):
        report = self.module.validate(
            pack,
            search_log=search_log,
            fetch_report=fetch_report,
            search_payloads=search_payloads,
        )
        return [p["code"] for p in report["problems"]]

    def _pack_with_queries(self):
        pack = base_pack()
        pack["queries"] = ["国家能源局 2025年全国电力工业统计数据"]
        return pack

    def test_query_absent_from_log_is_flagged(self) -> None:
        log = {"search_executions": [{"n": 1, "query": "完全不同的问题", "status": "ok"}]}
        self.assertIn("query_unlogged", self.codes(self._pack_with_queries(), search_log=log))

    def test_empty_log_with_queries_is_flagged(self) -> None:
        self.assertIn(
            "search_log_empty", self.codes(self._pack_with_queries(), search_log={"search_executions": []})
        )

    def test_exact_repeated_query_is_flagged(self) -> None:
        pack = self._pack_with_queries()
        log = {
            "search_executions": [
                {"n": 1, "query": "国家能源局 2025年全国电力工业统计数据", "status": "ok"},
                {"n": 2, "query": "国家能源局 2025年 全国电力工业统计 数据", "status": "failed"},
            ]
        }
        self.assertIn("duplicate_query", self.codes(pack, search_log=log))

    def test_reworded_retry_of_a_failed_query_is_flagged(self) -> None:
        pack = base_pack()
        pack["queries"] = ["IRENA renewable capacity statistics 2026 solar wind"]
        log = {
            "search_executions": [
                {"n": 1, "query": "IRENA renewable capacity statistics 2026 solar wind GW", "status": "failed"},
                {"n": 2, "query": "IRENA renewable capacity statistics 2026 solar wind total GW", "status": "failed"},
            ]
        }
        self.assertIn("reworded_retry", self.codes(pack, search_log=log))

    def test_changing_the_number_is_a_new_unit_not_a_reworded_retry(self) -> None:
        # 0.23.9 threshold calibration: 2025→2026 asks for different data. The n=1
        # char-set containment flagged these; numbers must match before a retry
        # counts as re-wording.
        pack = base_pack()
        log = {
            "search_executions": [
                {"n": 1, "query": "IRENA renewable capacity statistics 2025 solar wind GW", "status": "failed"},
                {"n": 2, "query": "IRENA renewable capacity statistics 2026 solar wind GW", "status": "failed"},
            ]
        }
        codes = self.codes(pack, search_log=log)
        self.assertNotIn("reworded_retry", codes)

    def test_a_long_query_that_succeeded_is_never_called_over_broad(self) -> None:
        # Over-broad is attributed post-hoc: only a claim-shaped query that actually
        # failed earns the flag (the 49-char success in the n=1 log was the false
        # positive this removes).
        long_ok = "国家能源局 2025年 风电 光伏 累计装机 全年 新增装机 亿千瓦"
        log_ok = {"search_executions": [{"n": 1, "query": long_ok, "status": "ok"}]}
        pack = base_pack()
        pack["queries"] = [long_ok]
        self.assertNotIn("over_broad_query", self.codes(pack, search_log=log_ok))
        log_failed = {"search_executions": [{"n": 1, "query": long_ok, "status": "failed"}]}
        self.assertIn("over_broad_query", self.codes(pack, search_log=log_failed))

    def test_render_always_shows_the_retrieval_advisory_line(self) -> None:
        pack = self._pack_with_queries()
        log = {
            "search_executions": [
                {"n": 1, "query": "国家能源局 2025年全国电力工业统计数据", "status": "ok"},
                {"n": 2, "query": "国家能源局 2025年全国电力工业统计数据", "status": "ok"},
            ]
        }
        report = self.module.validate(pack, search_log=log)
        text = self.module.render(report, Path("r.json"), verbose=False, max_items=12)
        self.assertIn("retrieval audit — 1 advisory: duplicate_query", text)

    def test_pasted_claim_sentence_query_is_flagged(self) -> None:
        pack = self._pack_with_queries()
        log = {
            "search_executions": [
                {
                    "n": 1,
                    "query": "中共中央 国务院 完整准确全面贯彻新发展理念 做好碳达峰碳中和工作 意见 2030年前碳达峰 2060年前碳中和 非化石能源消费比重25%",
                    "status": "failed",
                }
            ]
        }
        self.assertIn("over_broad_query", self.codes(pack, search_log=log))

    def test_result_page_fetches_are_flagged(self) -> None:
        report = {"records": [{"url": "https://www.so.com/s?q=x", "host_class": "search_engine", "ok": True}]}
        self.assertIn("result_page_fetched", self.codes(base_pack(), fetch_report=report))

    def test_a_degenerate_endpoint_is_flagged_from_the_hashes_alone(self) -> None:
        # 2026-09-30: ten differently-parameterised requests, one identical 97-byte body,
        # and the executor varied `t=` five more times because nothing said the endpoint
        # was not answering. Recomputed from raw_sha256, not read from a field the writer
        # could omit, so an older report audits the same way.
        records = [
            {
                "url": f"https://sousuo.www.gov.cn/search-gov/data?t={t}&q=q{i}",
                "host_class": "public",
                "ok": True,
                "raw_sha256": "6ce85fba4b9588a39ecc1c33fd03a8208206d078fa9fb5bd90157538c0eeb0b0",
            }
            for i, t in enumerate(("govall", "zhengcelibrary_gw", "zhengcelibrary_cp"))
        ]
        self.assertIn("degenerate_channel", self.codes(base_pack(), fetch_report={"records": records}))

    def test_a_real_result_beside_the_shell_is_not_a_degenerate_channel(self) -> None:
        records = [
            {
                "url": "https://sousuo.www.gov.cn/search-gov/data?t=govall&q=a",
                "host_class": "public",
                "ok": True,
                "raw_sha256": "shell",
            },
            {
                "url": "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=b",
                "host_class": "public",
                "ok": True,
                "raw_sha256": "real",
            },
        ]
        self.assertNotIn("degenerate_channel", self.codes(base_pack(), fetch_report={"records": records}))

    def test_repeating_one_url_is_never_a_degenerate_channel(self) -> None:
        records = [
            {"url": "https://www.nea.gov.cn/p.htm", "host_class": "public", "ok": True, "raw_sha256": "same"},
            {"url": "https://www.nea.gov.cn/p.htm", "host_class": "public", "ok": True, "raw_sha256": "same"},
        ]
        self.assertNotIn("degenerate_channel", self.codes(base_pack(), fetch_report={"records": records}))

    def test_a_search_layer_that_never_ran_is_flagged(self) -> None:
        # The distinction the bare `search_unavailable` cannot carry: all 19 searches in
        # the live run returned the wrapper model's own prose, so the failures are an
        # environment fact, not evidence of absence.
        log = {
            "search_executions": [
                {"n": n, "query": f"查询 {n}", "status": "failed", "signature": "backend_not_executed"}
                for n in (1, 2, 3)
            ]
        }
        self.assertIn("search_backend_not_executed", self.codes(base_pack(), search_log=log))

    def test_one_executed_failure_spares_the_verdict(self) -> None:
        log = {
            "search_executions": [
                {"n": 1, "query": "查询一", "status": "failed", "signature": "backend_not_executed"},
                {"n": 2, "query": "查询二", "status": "failed", "signature": "index_empty"},
            ]
        }
        self.assertNotIn("search_backend_not_executed", self.codes(base_pack(), search_log=log))

    def test_an_unclassified_log_never_invents_an_outage(self) -> None:
        # Fail-open on a missing field: older writers and unclassified failures must not
        # be read as a dead backend.
        log = {"search_executions": [{"n": 1, "query": "查询一", "status": "failed"}]}
        self.assertNotIn("search_backend_not_executed", self.codes(base_pack(), search_log=log))

    def test_hook_payloads_are_recomputed_when_the_log_omits_the_signature(self) -> None:
        """The 16 role-played answers would not have been signed by the model. The hook
        stores the payload; the audit classifies it again and does not trust a missing field.
        """
        prose = "我会为您搜索。根据已知知识，海上风电累计装机约4000兆瓦。"
        payloads = {
            "executions": [
                {"query": "海上风电", "payload": prose},
                {"query": "储能", "payload": prose},
            ]
        }
        log = {"search_executions": []}
        self.assertIn(
            "search_response_unknown",
            self.codes(base_pack(), search_log=log, search_payloads=payloads),
        )

    def test_a_real_record_among_payloads_is_not_a_session_outage(self) -> None:
        payloads = {
            "executions": [
                {"query": "a", "payload": "根据已知知识，没有检索工具。"},
                {
                    "query": "b",
                    "payload": '[{"title": "报告", "link": "https://www.irena.org/x", "content": "1"}]',
                },
            ]
        }
        log = {
            "search_executions": [
                {"n": 1, "query": "a", "status": "failed", "signature": "backend_not_executed"},
                {"n": 2, "query": "b", "status": "failed", "signature": "backend_not_executed"},
            ]
        }
        self.assertNotIn(
            "search_backend_not_executed",
            self.codes(base_pack(), search_log=log, search_payloads=payloads),
        )

    def test_clean_trail_produces_no_audit_flags(self) -> None:
        pack = self._pack_with_queries()
        log = {
            "search_executions": [
                {"n": 1, "query": "国家能源局 2025年全国电力工业统计数据", "status": "ok"}
            ]
        }
        fetch = {"records": [{"url": "https://www.gov.cn/x.htm", "host_class": "public", "ok": True}]}
        codes = self.codes(pack, search_log=log, fetch_report=fetch)
        for audit in (
            "query_unlogged",
            "duplicate_query",
            "reworded_retry",
            "over_broad_query",
            "result_page_fetched",
            "degenerate_channel",
            "search_backend_not_executed",
        ):
            self.assertNotIn(audit, codes)

    def test_trail_arguments_may_be_paths_and_never_crash_the_validator(self) -> None:
        # 0.23.8: validate() is a public API; a caller handing the audit a path
        # string must work, and a caller handing it a broken or impossible value
        # must get a minor flag — never an AttributeError (reproduced live).
        pack = self._pack_with_queries()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "search-log.json"
            good.write_text(
                json.dumps(
                    {
                        "search_executions": [
                            {"n": 1, "query": "完全不同的问题", "status": "ok"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            codes = self.codes(pack, search_log=str(good))
            self.assertIn("query_unlogged", codes)  # str path behaves like the dict
            codes = self.codes(pack, search_log=str(root / "missing.json"))
            self.assertIn("retrieval_log_unreadable", codes)
            report = self.module.validate(pack, search_log=str(root / "missing.json"))
            self.assertTrue(report["ok"], "an unreadable trail is advisory, never a blocker")
            codes = self.codes(pack, search_log=42)  # not a dict, not a path
            self.assertIn("retrieval_log_unreadable", codes)

    def test_audit_flags_never_block(self) -> None:
        pack = self._pack_with_queries()
        log = {
            "search_executions": [
                {"n": 1, "query": "国家能源局 2025年全国电力工业统计数据", "status": "failed"},
                {"n": 2, "query": "国家能源局 2025年 全国电力工业统计 数据", "status": "failed"},
            ]
        }
        report = self.module.validate(pack, search_log=log)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(0, report["counts"]["blockers"])

    def test_cli_binds_trail_files_and_stays_advisory(self) -> None:
        import contextlib
        import io

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "research-pack.json"
            pack = base_pack()
            pack["queries"] = ["国家能源局 2025年全国电力工业统计数据"]
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            log = root / "search-log.json"
            log.write_text(
                json.dumps(
                    {
                        "search_executions": [
                            {"n": 1, "query": "国家能源局 2025年全国电力工业统计数据", "status": "ok"},
                            {"n": 2, "query": "国家能源局 2025年 全国电力工业统计 数据", "status": "ok"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report_path = root / "validation.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = self.module.main(
                    [str(pack_path), "--output", str(report_path), "--search-log", str(log), "--json"]
                )
            self.assertEqual(0, code, "audit findings are minor and never block")
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("duplicate_query", [p["code"] for p in payload["problems"]])
            self.assertEqual(64, len(payload["retrieval"]["search_log"]["sha256"]))


if __name__ == "__main__":
    unittest.main()
