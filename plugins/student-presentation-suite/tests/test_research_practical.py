"""Research must validate support without imposing a tool/receipt bureaucracy."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

from shared.pptx_runtime import fetch_text
from shared.research_evidence import value_present
from shared.research_model import normalize

ROOT = Path(__file__).resolve().parents[1]
compiler = load_module(ROOT / "scripts/research_pack_to_evidence.py")
validator = load_module(ROOT / "scripts/validate_research_pack.py")
handoff = load_module(ROOT / "scripts/research_handoff.py")
guard = load_module(ROOT / "skills/sp-deck/scripts/slide_spec_guard.py")
runtime = load_module(ROOT / "scripts/runtime_evidence.py")
controller = load_module(ROOT / "scripts/research_control.py")


class PracticalResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.pack = {"version": "0.10", "topic": "课程数据", "evidence_contract": "source-backed-v1",
                     "findings": [], "data_points": [{"id": "D01", "value": "820", "meaning": "煤电指标",
                     "source_ids": ["S01"]}], "sources": [{"id": "S01", "title": "原始报告",
                     "url": "https://example.org/report.pdf"}], "evidence": [{"entity_id": "D01",
                     "source_id": "S01", "excerpt": "740 820 910", "locator": "第12页表3",
                     "method": "PDF table extraction"}]}

    def report(self):
        return validator.validate(self.pack, work_dir=self.work)

    def assert_valid(self):
        result = self.report()
        self.assertTrue(result["ok"], result["problems"])

    def test_numeric_boundaries_preserve_table_cells_and_next_year(self):
        for value, text in (("820", "740 820 910"), ("11", "10 11 12"),
                            ("2,383.2", "2,383.2 2025"), ("2383.20", "2,383.2")):
            with self.subTest(value=value, text=text):
                self.assertTrue(value_present(value, text))
        for value, text in (("820", "1820"), ("11", "111"), ("94", "94.3%"), ("820", "820.5")):
            self.assertFalse(value_present(value, text), (value, text))

    def test_local_pdf_or_ocr_needs_no_fetch_receipt_or_hash(self):
        text = self.work / "parsed-by-user.txt"
        text.write_text("740 820 910\n", encoding="utf-8")
        self.pack["evidence"][0].update(text_path=str(text), text_sha256="old-parser-version")
        self.assert_valid()
        text.write_text("740\t820\t910\n", encoding="utf-8")
        self.assert_valid()

    def test_browser_or_screenshot_can_record_support_without_local_text(self):
        self.pack["evidence"][0].pop("excerpt")
        self.pack["evidence"][0]["support_note"] = "已读取第12页表3，煤电对应列为820，单位见表头。"
        self.assert_valid()

    def test_unmatched_numeric_extraction_requires_semantic_inspection(self):
        self.pack["data_points"][0]["value"] = "1820"
        report = self.report()
        self.assertTrue(report["ok"])
        self.assertIn("evidence_value_unverified", [p["code"] for p in report["problems"]])

    def test_explicit_rounding_records_original_value(self):
        self.pack["data_points"][0].update(value="94%", source_value="94.3%", transformation="按整数百分比四舍五入展示")
        self.pack["evidence"][0]["excerpt"] = "采用率为94.3%"
        self.assert_valid()
        self.pack["data_points"][0].pop("transformation")
        self.assertIn("evidence_transformation_missing", [p["code"] for p in self.report()["problems"]])

    def test_review_is_optional_and_qualification_is_recorded_once(self):
        self.pack["data_points"][0]["support_check"] = {"verdict": "qualified", "limitations": "仅限报告所列样本"}
        self.assert_valid()
        self.pack["data_points"][0]["support_check"]["verdict"] = "unsupported"
        self.assertFalse(self.report()["ok"])

    def test_extra_sources_do_not_need_duplicate_review_forms(self):
        self.pack["sources"].append({"id": "S02", "title": "另一份独立研究", "url": "https://example.org/second"})
        self.pack["data_points"][0].update(source_ids=["S01", "S02"], confidence="high",
                                         support_check={"verdict": "supported"})
        self.pack["evidence"].append({"entity_id": "D01", "source_id": "S02", "excerpt": "820"})
        self.assert_valid()
        for source in self.pack["sources"]:
            source["origin_id"] = "same-report"
        self.pack["data_points"][0]["verification"] = "cross_check"
        self.assertFalse(self.report()["ok"])

    def test_unused_sources_and_claim_count_do_not_create_cleanup_work(self):
        self.pack["sources"].append({"id": "S02", "title": "未采用候选", "url": "https://example.org/unused"})
        self.pack["must_verify"] = [{"id": "C01", "claim": "煤电指标", "entity_ids": ["D01"], "status": "usable"}]
        result = self.report()
        self.assertTrue(result["ok"], result["problems"])
        self.assertNotIn("unused_source", [p["code"] for p in result["problems"]])
        self.assertNotIn("must_verify_count", [p["code"] for p in result["problems"]])

    def test_locator_url_shape_does_not_override_readable_content(self):
        self.pack["sources"][0]["url"] = "https://example.org/index.html"
        self.assert_valid()

    def test_bad_reference_still_fails(self):
        self.pack["evidence"][0]["source_id"] = "missing"
        self.assertFalse(self.report()["ok"])

    def test_custom_ids_cannot_collide_between_content_and_sources(self):
        self.pack["data_points"][0]["id"] = "S01"
        self.assertIn("duplicate_id", [p["code"] for p in self.report()["problems"]])

    def test_malformed_content_is_reported_without_a_traceback(self):
        self.pack["data_points"] = None
        self.assertFalse(self.report()["ok"])

    def test_duplicate_document_cannot_claim_independent_support(self):
        self.pack["sources"].append({**self.pack["sources"][0], "id": "S02"})
        self.pack["data_points"][0].update(source_ids=["S01", "S02"], confidence="high", verification="cross_check")
        self.pack["evidence"].append({"entity_id": "D01", "source_id": "S02", "excerpt": "820"})
        self.assertFalse(self.report()["ok"])

    def test_broken_optional_logs_do_not_block_current_content(self):
        pack_path = self.work / "research-pack.json"
        pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        fetched = self.work / "research/fetched"
        fetched.mkdir(parents=True)
        (fetched / "fetch-text-report.json").write_text("unfinished", encoding="utf-8")
        (fetched.parent / "search-log.json").write_text("unfinished", encoding="utf-8")
        self.assertTrue(handoff.inspect(self.work)["ok"])
        self.assertEqual(0, validator.main([str(pack_path)]))
        self.assertEqual(0, compiler.main([str(pack_path)]))

    def test_handoff_and_compiler_refresh_stale_reports_without_agent_receipts(self):
        pack_path = self.work / "research-pack.json"
        pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        report = handoff.inspect(self.work)
        self.assertTrue(report["ok"], report)
        self.pack["topic"] += "修订"
        pack_path.write_text(json.dumps(self.pack, indent=2), encoding="utf-8")
        self.assertEqual(0, compiler.main([str(pack_path), "--validation-report",
                                         str(self.work / "research-pack-validation.json")]))
        saved = json.loads((self.work / "research-pack-validation.json").read_text(encoding="utf-8"))
        self.assertEqual(validator.sha256_file(pack_path), saved["research_pack_sha256"])

    def test_normalizing_limitations_and_conversions_is_idempotent(self):
        self.pack["data_points"][0].update(source_value="820", transformation="原值展示",
                                         support_check={"verdict": "qualified", "limitations": "仅限样本"})
        once = normalize(self.pack)
        self.assertEqual(once, normalize(normalize(once)))

    def test_content_gate_accepts_reformatting_but_rejects_changed_facts(self):
        pack_path = self.work / "research-pack.json"
        pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        draft = self.work / "draft.json"
        draft.write_text(json.dumps({"slides": [{"id": 1, "evidence_refs": ["D01"]}]}), encoding="utf-8")
        compiled = self.work / "compiled.json"
        validation = self.work / "research-pack-validation.json"
        evidence_map = self.work / "evidence-map.json"
        self.assertEqual(0, compiler.main([str(pack_path), "--validation-report", str(validation),
                         "--slide-spec", str(draft), "--compiled-slide-spec", str(compiled)]))
        paths = {"research_pack": pack_path, "research_validation": validation, "evidence_map": evidence_map}
        pack_path.write_text(json.dumps(self.pack, indent=4), encoding="utf-8")
        validation.write_text("{}", encoding="utf-8")
        self.assertTrue(guard.validate_research_chain(paths, validator.sha256_file(compiled)))
        self.pack["data_points"][0]["value"] = "910"
        pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        with self.assertRaises(SystemExit):
            guard.validate_research_chain(paths, validator.sha256_file(compiled))

    def bound_task(self, scope="A"):
        work = self.work / "outputs/.pptx-work/demo"
        work.mkdir(parents=True)
        brief = self.work / "brief.json"
        brief.write_text("{}", encoding="utf-8")
        task = {"work_id": "demo", "work_dir": str(work), "brief_path": str(brief), "scope": scope,
                "materials_path": None, "background": "课程研究", "claims": [
                {"id": "C01", "claim": "表格指标", "acceptance": "核对来源与表头"}]}
        task_path = work / "research-task.json"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        event = {"cwd": str(self.work), "session_id": "main", "hook_event_name": "PreToolUse",
                 "tool_name": "Agent", "tool_input": {"subagent_type": runtime.RESEARCHER, "prompt": str(work)}}
        return work, task_path, event

    def test_only_concurrent_research_is_refused_and_sequential_retry_is_allowed(self):
        _, _, event = self.bound_task()
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.work)}):
            self.assertEqual(0, runtime.handle(event))
            self.assertEqual(2, runtime.handle(event))
            child = {**event, "agent_type": runtime.RESEARCHER, "agent_id": "child", "hook_event_name": "SubagentStart"}
            self.assertEqual(0, runtime.handle(child))
            self.assertEqual(0, runtime.handle({**child, "hook_event_name": "SubagentStop"}))
            self.assertEqual(0, runtime.handle(event))

    def test_content_edits_do_not_widen_network_permission(self):
        work, task_path, event = self.bound_task("C")
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.work)}):
            self.assertEqual(0, runtime.handle(event))
            child = {**event, "agent_type": runtime.RESEARCHER, "agent_id": "child", "hook_event_name": "SubagentStart"}
            runtime.handle(child)
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task["scope"] = "A"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            search = {**child, "hook_event_name": "PreToolUse", "tool_name": "WebSearch", "tool_input": {"query": "test"}}
            self.assertEqual(2, runtime.handle(search))
            calls = []
            def getter(url, timeout):
                calls.append(url)
                return 200, {"content-type": "text/plain"}, b"820"
            result = fetch_text.fetch_many(["https://example.org/report"], work / "research/fetched", scope="A", getter=getter)
            self.assertEqual([], calls)
            self.assertFalse(result["records"][0]["ok"])
            controller.rebind(work, "用户已授权联网")
            self.assertEqual(0, runtime.handle(search))


if __name__ == "__main__":
    unittest.main()
