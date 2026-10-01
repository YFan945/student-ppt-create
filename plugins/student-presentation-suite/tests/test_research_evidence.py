from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module
from test_validate_research_pack import base_pack

ROOT = Path(__file__).resolve().parents[1]
validator = load_module(ROOT / "scripts/validate_research_pack.py")
compiler = load_module(ROOT / "scripts/research_pack_to_evidence.py")
task_validator = load_module(ROOT / "scripts/validate_research_task.py")
resetter = load_module(ROOT / "scripts/reset_research_channel.py")
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class TextEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name) / "outputs/.pptx-work/demo"
        self.fetched = self.work / "research/fetched"
        self.fetched.mkdir(parents=True)
        self.pack = base_pack()
        self.pack["evidence_contract"] = "text-bound-v1"
        self.pack["evidence"] = []
        self.pack["must_verify"] = [{"id": "C01", "claim": "某基准上的幻觉率为38%", "status": "verified", "entity_ids": ["D01"]}]
        self.pack["data_points"][0]["claim_id"] = "C01"
        self.report = {"records": []}
        for source in self.pack["sources"]:
            sid = source["id"]
            source["url"] = f"https://{sid.lower()}.org/report"
            text = "2026年某基准上的幻觉率为38%。对象幻觉是 LVLM 最常见的幻觉类型之一。\n"
            path = self.fetched / f"{sid}.txt"
            path.write_bytes(text.encode("utf-8"))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.report["records"].append({"url": source["url"], "ok": True, "text_path": str(path), "text_sha256": digest, "host_class": "document"})
            for entity in ("F01", "D01"):
                self.pack["evidence"].append({"entity_id": entity, "source_id": sid, "excerpt": text.strip(), "text_path": str(path), "text_sha256": digest, "locator": "第1段", "support_note": "片段逐字列出数据和论述，地域是该基准样本。", "year": 2026, "unit": "%", "region": "基准样本", "metric": "幻觉率"})

    def codes(self):
        return [p["code"] for p in validator.validate(self.pack, fetch_report=self.report, work_dir=self.work)["problems"]]

    def test_valid_text_bound_pack_passes(self):
        result = validator.validate(self.pack, fetch_report=self.report, work_dir=self.work)
        self.assertTrue(result["ok"], result["problems"])
        self.assertTrue(result["evidence_checked"])

    def test_tampering_with_text_invalidates_hash(self):
        Path(self.pack["evidence"][0]["text_path"]).write_text("改成83%", encoding="utf-8")
        self.assertIn("evidence_hash_mismatch", self.codes())

    def test_fabricated_excerpt_is_rejected(self):
        self.pack["evidence"][0]["excerpt"] = "原文没有说过的话"
        self.assertIn("evidence_excerpt_mismatch", self.codes())

    def test_wrong_value_year_or_context_is_rejected(self):
        original = copy.deepcopy(self.pack)
        for field, value, code in (("value", "83%", "evidence_value_mismatch"), ("year", 2025, "evidence_year_mismatch")):
            self.pack = copy.deepcopy(original)
            self.pack["data_points"][0][field] = value
            self.assertIn(code, self.codes())
        self.pack = copy.deepcopy(original)
        del self.pack["evidence"][1]["unit"]
        self.assertIn("evidence_measurement_context_missing", self.codes())

    def test_missing_fetch_and_locator_source_are_rejected(self):
        saved = copy.deepcopy(self.report)
        self.report["records"] = []
        self.assertIn("evidence_fetch_binding_missing", self.codes())
        self.report = saved
        self.report["records"][0]["host_class"] = "listing"
        self.assertIn("evidence_locator_as_source", self.codes())

    def test_evidence_path_cannot_escape_research(self):
        self.pack["evidence"][0]["text_path"] = "../outside.txt"
        self.assertIn("evidence_path_outside_research", self.codes())

    def test_claim_link_and_source_coverage_are_required(self):
        del self.pack["data_points"][0]["claim_id"]
        self.assertIn("evidence_claim_link_mismatch", self.codes())
        self.pack["evidence"].pop()
        self.assertIn("evidence_support_missing", self.codes())

    def test_republished_origin_cannot_become_high_confidence(self):
        for source in self.pack["sources"]:
            source["origin_id"] = "same-upstream-report"
            source["independence_note"] = "不同网站"
        self.assertIn("sources_are_not_independent", self.codes())

    def test_quotes_are_checked_against_original_words(self):
        self.pack["quotes"] = [{"id": "Q01", "text": "杜撰引文", "source_id": "S01"}]
        quote = copy.deepcopy(self.pack["evidence"][0])
        quote["entity_id"] = "Q01"
        self.pack["evidence"].append(quote)
        self.assertIn("evidence_quote_mismatch", self.codes())

    def test_legacy_pack_remains_readable_without_claiming_text_verification(self):
        result = validator.validate(base_pack())
        self.assertTrue(result["ok"])
        self.assertFalse(result["evidence_checked"])
        self.assertIn("legacy_evidence_unbound", [p["code"] for p in result["problems"]])

    def test_direct_document_retrieval_needs_no_invented_search_query(self):
        self.pack["queries"] = []
        result = validator.validate(self.pack, fetch_report=self.report, work_dir=self.work)
        self.assertTrue(result["ok"], result["problems"])

    def test_valid_partial_pack_reports_unresolved_claim_without_blocking(self):
        self.pack["must_verify"].append({"id": "C02", "claim": "待核验的另一项数据", "status": "unresolved", "source_ids": []})
        self.pack["unresolved"] = [{"query": "待核验的另一项数据", "reason": "search_unavailable", "impact": "缺少原文，页面删除该项数据"}]
        result = validator.validate(self.pack, fetch_report=self.report, work_dir=self.work)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual({"verified": 1, "unresolved": 1}, result["completion"])

    def task(self):
        brief = self.work / "brief.json"
        brief.write_text("{}", encoding="utf-8")
        return {"work_id": "demo", "work_dir": str(self.work), "brief_path": str(brief), "scope": "A", "materials_path": None, "budget": "standard", "background": "课程报告", "claims": [{"id": "C01", "claim": "某基准上的幻觉率为38%", "acceptance": "逐字原文与年份/单位/基准口径一致"}]}

    def test_task_validation_and_pack_to_compiler_integration(self):
        task = self.task()
        task_path = self.work / "research-task.json"
        task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        self.assertEqual([], task_validator.validate_task(task, task_path))
        self.assertTrue(task_validator.validate_task({**task, "work_dir": str(self.work.parent)}, task_path))
        (self.fetched / "fetch-text-report.json").write_text(json.dumps(self.report), encoding="utf-8")
        path = self.work / "research-pack.json"
        path.write_text(json.dumps(self.pack, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(0, validator.main([str(path), "--task", str(task_path), "--fetch-report", str(self.fetched / "fetch-text-report.json")]))
        self.assertEqual(0, compiler.main([str(path)]))
        self.pack["must_verify"][0]["claim"] = "被转抄改变的内容"
        path.write_text(json.dumps(self.pack, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(2, validator.main([str(path), "--task", str(task_path), "--fetch-report", str(self.fetched / "fetch-text-report.json")]))
        Path(self.pack["evidence"][0]["text_path"]).write_text("篡改", encoding="utf-8")
        self.assertEqual(2, compiler.main([str(path)]))

    def test_task_rejects_duplicate_claim_ids_and_missing_d_materials(self):
        task = self.task()
        task["claims"] *= 2
        self.assertTrue(task_validator.validate_task(task, self.work / "research-task.json"))
        task["claims"] = task["claims"][:1]
        task["scope"] = "D"
        self.assertTrue(task_validator.validate_task(task, self.work / "research-task.json"))

    def test_main_session_recovery_preserves_failures(self):
        channel = runtime._channel_path(Path(self.temp.name), {"session_id": "session", "agent_id": "child"})
        channel.parent.mkdir(parents=True, exist_ok=True)
        channel.write_text(json.dumps({"executions": [{"payload": "failed", "execution_status": "not_executed"}]}), encoding="utf-8")
        resetter.reset(Path(self.temp.name), "session", "child", "已修复提供方响应适配器")
        rows = json.loads(channel.read_text(encoding="utf-8"))["executions"]
        self.assertEqual(2, len(rows))
        self.assertFalse(runtime.search_channel_closed(rows))
        rows.append({"payload": "失败", "execution_status": "not_executed"})
        self.assertTrue(runtime.search_channel_closed(rows))
        with self.assertRaises(ValueError):
            resetter.reset(Path(self.temp.name), "session", "child", " ")


if __name__ == "__main__":
    unittest.main()
