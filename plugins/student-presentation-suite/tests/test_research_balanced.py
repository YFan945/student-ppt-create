"""Behavioral regression tests for usable-first research and continuation."""
from __future__ import annotations

import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import test_research_evidence as fixtures

from shared.pptx_runtime import fetch_text

binding = fixtures.load_module(fixtures.ROOT / "scripts/research_task_binding.py")
smoke = fixtures.load_module(fixtures.ROOT / "scripts/smoke_research_fork.py")


class BalancedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TextEvidenceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.pack = self.fixture.pack
        self.pack["evidence_contract"] = "source-backed-v1"
        for entity in self.pack["findings"] + self.pack["data_points"]:
            entity["confidence"] = "medium"
            entity["status"] = "usable"
        self.pack["must_verify"][0]["status"] = "usable"
        self.pack["evidence"] = [b for b in self.pack["evidence"] if b["source_id"] == "S01"]
        for b in self.pack["evidence"]:
            for key in ("year", "unit", "region", "metric"):
                b.pop(key, None)

    def task(self, verification="source"):
        brief = self.fixture.work / "brief.json"
        brief.write_text("{}", encoding="utf-8")
        task = {"work_id": "demo", "work_dir": str(self.fixture.work), "brief_path": str(brief),
                "materials_path": None, "scope": "A", "budget": "standard", "background": "测试",
                "claims": [{"id": "C01", "claim": self.pack["must_verify"][0]["claim"],
                            "acceptance": "来源直接支撑", "verification": verification}]}
        path = self.fixture.work / "research-task.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        return path

    def verdict(self):
        return fixtures.validator.validate(self.pack, fetch_report=self.fixture.report, work_dir=self.fixture.work)

    def test_ordinary_claim_uses_one_source_without_strict_measurement_fields(self):
        self.task()
        report = self.verdict()
        binding.apply_task(report, self.pack, self.fixture.work)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual("ready", report["delivery_status"])

    def enable_review(self):
        path = self.task()
        task = json.loads(path.read_text())
        task["semantic_review_required"] = True
        path.write_text(json.dumps(task), encoding="utf-8")
        entities = {e["id"]: e for key in ("findings", "data_points") for e in self.pack[key]}
        for evidence in self.pack["evidence"]:
            entity = entities[evidence["entity_id"]]
            evidence["support_check"] = {"statement": entity.get("claim", entity.get("meaning")),
                "verdict": "supported", "subject_scope": "matches", "time_scope": "matches",
                "causal_scope": "not_applicable", "rationale": "原文直接支持", "limitations": ""}

    def test_missing_second_pass_cannot_silently_pass_new_tasks(self):
        self.enable_review()
        self.pack["evidence"][0].pop("support_check")
        self.assertFalse(self.verdict()["ok"])

    def test_review_rejects_scope_overreach_and_unrelated_support(self):
        self.enable_review()
        self.assertTrue(self.verdict()["ok"])
        self.pack["evidence"][0]["support_check"]["subject_scope"] = "mismatch"
        self.assertIn("evidence_support_review_rejected", [p["code"] for p in self.verdict()["problems"]])
        self.pack["evidence"][0]["support_check"]["subject_scope"] = "matches"
        self.pack["evidence"][0]["support_check"]["verdict"] = "unsupported"
        self.assertFalse(self.verdict()["ok"])

    def test_qualified_support_requires_visible_limits(self):
        self.enable_review()
        check = self.pack["evidence"][0]["support_check"]
        check["verdict"] = "qualified"
        self.assertFalse(self.verdict()["ok"])
        check["limitations"] = "仅限原文统计范围"
        self.pack["findings"][0]["notes"] = "仅限原文统计范围"
        self.assertTrue(self.verdict()["ok"])

    def test_review_does_not_bless_a_changed_statement(self):
        self.enable_review()
        self.pack["findings"][0]["claim"] = "将局部实验推广成全球事实"
        self.assertIn("evidence_support_review_missing", [p["code"] for p in self.verdict()["problems"]])

    def test_task_text_requirement_cannot_be_weakened_by_entity(self):
        self.task("text")
        self.pack["must_verify"][0]["status"] = "verified"
        self.pack["data_points"][0]["verification"] = "source"
        self.assertIn("evidence_measurement_context_missing", [p["code"] for p in self.verdict()["problems"]])

    def test_source_mode_still_rejects_fabricated_numbers(self):
        self.pack["data_points"][0]["value"] = "83%"
        self.assertFalse(self.verdict()["ok"])

    def test_optional_gap_is_partial_and_core_gap_is_insufficient(self):
        path = self.task()
        task = json.loads(path.read_text())
        gap = {"id": "C02", "claim": "辅助历史", "acceptance": "有来源", "importance": "supporting"}
        task["claims"].append(gap)
        self.pack["must_verify"].append({"id": "C02", "claim": "辅助历史", "status": "unresolved"})
        self.assertEqual("partial", binding.delivery(self.pack, task)["delivery_status"])
        gap["importance"] = "core"
        self.assertEqual(["C02"], binding.delivery(self.pack, task)["core_gaps"])

    def test_claim_cannot_close_using_a_located_entity(self):
        self.pack["data_points"][0]["status"] = "located"
        self.assertFalse(self.verdict()["ok"])

    def test_compiler_discovers_task_even_without_task_argument(self):
        self.task()
        self.pack["must_verify"][0]["claim"] = "偷偷替换任务"
        path = self.fixture.work / "research-pack.json"
        path.write_text(json.dumps(self.pack), encoding="utf-8")
        fetched = self.fixture.fetched / "fetch-text-report.json"
        fetched.write_text(json.dumps(self.fixture.report), encoding="utf-8")
        self.assertEqual(2, fixtures.compiler.main([str(path)]))

    def test_deleted_task_cannot_fall_back_to_legacy_mode(self):
        task_path = self.task()
        _, frozen, _ = binding.task_verdict(self.pack, self.fixture.work)
        (self.fixture.work / "research-task-binding.json").write_text(json.dumps(frozen), encoding="utf-8")
        task_path.unlink()
        errors, _, _ = binding.task_verdict(self.pack, self.fixture.work)
        self.assertTrue(errors)

    def test_scope_denied_before_web_tools_or_shell_fetch(self):
        task_path = self.task()
        task = json.loads(task_path.read_text())
        task["scope"] = "C"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        project = self.fixture.work.parents[2]
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
            event = {"cwd": str(project), "session_id": "scope-test", "hook_event_name": "PreToolUse",
                     "tool_name": "Agent", "tool_input": {"subagent_type": fixtures.runtime.RESEARCHER,
                     "prompt": str(self.fixture.work)}}
            self.assertEqual(0, fixtures.runtime.handle(event))
            event.update(agent_id="child", agent_type=fixtures.runtime.RESEARCHER)
            for tool, inputs in (("WebSearch", {"query": "test"}), ("WebFetch", {"url": "https://example.org/report"}),
                                 ("Bash", {"command": "python pptx_tool.py fetch-text --scope A"})):
                event.update(tool_name=tool, tool_input=inputs)
                self.assertEqual(2, fixtures.runtime.handle(event))

    def start_bound_child(self, agent_type=None):
        self.task()
        project = self.fixture.work.parents[2]
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)})
        env.start()
        self.addCleanup(env.stop)
        event = {"cwd": str(project), "session_id": "parent", "hook_event_name": "PreToolUse",
                 "tool_name": "Agent", "tool_input": {"subagent_type": fixtures.runtime.RESEARCHER,
                 "prompt": str(self.fixture.work)}}
        self.assertEqual(0, fixtures.runtime.handle(event))
        event.update(agent_id="child", agent_type=agent_type or fixtures.runtime.RESEARCHER,
                     hook_event_name="SubagentStart")
        self.assertEqual(0, fixtures.runtime.handle(event))
        event.update(hook_event_name="PostToolUse", tool_name="Read",
                     tool_input={"file_path": str(self.fixture.work / "research-task.json")})
        self.assertEqual(0, fixtures.runtime.handle(event))
        fixtures.runtime.handle({"cwd": str(project), "session_id": "parent", "hook_event_name": "Stop"})
        return project, event

    def test_parent_stop_does_not_unbind_background_retrieval_or_payloads(self):
        project, event = self.start_bound_child()
        other = project / "outputs/.pptx-work/other"
        other.mkdir()
        fixtures.runtime.pipeline_context.mark_research_active(project, {"session_id": "other"}, work_ids=["other"])
        for tool, inputs in (("WebSearch", {"query": "test"}),
                             ("WebFetch", {"url": "https://example.org/report"}),
                             ("Bash", {"command": "python pptx_tool.py fetch-text --scope A"})):
            self.assertEqual(0, fixtures.runtime.handle({**event, "hook_event_name": "PreToolUse",
                                                        "tool_name": tool, "tool_input": inputs}))
        fixtures.runtime.handle({**event, "tool_name": "WebSearch", "tool_input": {"query": "test"},
                                 "tool_response": [{"title": "Report", "url": "https://example.org/report"}]})
        self.assertTrue((self.fixture.work / "research/search-payloads.json").is_file())
        self.assertFalse((other / "research/search-payloads.json").exists())

    def test_bound_child_retains_task_and_control_guards_after_parent_stop(self):
        _, event = self.start_bound_child()
        event.update(hook_event_name="PreToolUse", tool_name="WebSearch", tool_input={"query": "test"})
        task = self.fixture.work / "research-task.json"
        original = task.read_bytes()
        task.write_bytes(original + b" ")
        self.assertEqual(2, fixtures.runtime.handle(event))
        task.write_bytes(original)
        from shared.research_io import atomic_json
        control_path = self.fixture.work / "research-control.json"
        control = json.loads(control_path.read_text(encoding="utf-8"))
        control["reason"] = "user"
        atomic_json(control_path, control)
        self.assertEqual(2, fixtures.runtime.handle(event))
        task.unlink()
        self.assertEqual(2, fixtures.runtime.handle(event))

    def test_budget_and_scope_still_block_after_parent_stop(self):
        _, event = self.start_bound_child()
        event.update(hook_event_name="PreToolUse", tool_name="WebSearch", tool_input={"query": "test"})
        control_path = self.fixture.work / "research-control.json"
        control = json.loads(control_path.read_text(encoding="utf-8"))
        control["started_at"] -= 1000
        control_path.write_text(json.dumps(control), encoding="utf-8")
        self.assertEqual(2, fixtures.runtime.handle(event))
        task_path = self.fixture.work / "research-task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["scope"] = "C"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        import hashlib
        binding_path = self.fixture.work / "research-task-binding.json"
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        binding["sha256"] = hashlib.sha256(task_path.read_bytes()).hexdigest()
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        control_path.unlink()
        self.assertEqual(2, fixtures.runtime.handle(event))

    def test_zcode_child_uses_same_persistent_task_binding(self):
        project, event = self.start_bound_child("zcode-student-presentation-suite:presentation-researcher")
        self.assertEqual([self.fixture.work], fixtures.runtime._armed_work_dirs(project, event))
        self.assertEqual(0, fixtures.runtime.handle({**event, "hook_event_name": "PreToolUse",
                                                    "tool_name": "WebSearch", "tool_input": {"query": "test"}}))

    def test_reading_two_tasks_does_not_select_an_arbitrary_deck(self):
        project, event = self.start_bound_child()
        other = project / "outputs/.pptx-work/other"
        other.mkdir()
        task = other / "research-task.json"
        task.write_text("{}", encoding="utf-8")
        fixtures.runtime.handle({**event, "tool_input": {"file_path": str(task)}})
        self.assertEqual([], fixtures.runtime._armed_work_dirs(project, event))
        self.assertEqual(2, fixtures.runtime.handle({**event, "hook_event_name": "PreToolUse",
                                                    "tool_name": "WebSearch", "tool_input": {"query": "test"}}))


class RetrievalContinuationTests(unittest.TestCase):
    def test_smoke_inspects_tool_events_and_ignores_status_mentions(self):
        content = [{"type": "tool_use", "name": "WebSearch"}]
        child = {"type": "assistant", "parent_tool_use_id": "spawn", "message": {"content": content}}
        parent = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": content}}
        payload = {"result": "WebSearch: 1, WebFetch: 0; researcher completed"}
        self.assertEqual([], smoke.main_flow_leaked_retrieval(payload, [child]))
        self.assertTrue(smoke.main_flow_leaked_retrieval(payload, [parent]))

    def test_hash_metadata_is_allowed_but_printing_body_is_refused(self):
        prefix = 'cd "E:/work/research/fetched" && python -c '
        code = "import hashlib; p='source.txt'; h=hashlib.sha256(open(p,'rb').read()).hexdigest(); print('text_sha256',h)"
        self.assertFalse(fixtures.runtime.dumps_fetched_body(prefix + '"' + code + '"'))
        self.assertTrue(fixtures.runtime.dumps_fetched_body(prefix + '"' + code + "; print(open(p).read())" + '"'))
        excerpt = "p='source.txt'; s=open(p).read(); i=s.find('uses a pool'); print(repr(s[i-80:i+90]))"
        self.assertFalse(fixtures.runtime.dumps_fetched_body(prefix + '"' + excerpt + '"'))
        self.assertTrue(fixtures.runtime.dumps_fetched_body(prefix + '"' + excerpt.replace('i+90', '') + '"'))

    def test_permission_checked_before_warm_cache_and_corruption_refetches(self):
        calls = []
        def getter(url, _timeout):
            calls.append(url)
            return 200, {"content-type": "text/plain"}, b"source"
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            url = "https://example.org/report"
            first = fetch_text.fetch_many([url], out, scope="A", getter=getter)
            denied = fetch_text.fetch_many([url], out, scope="D", getter=getter)
            self.assertFalse(denied["ok"])
            self.assertEqual(1, len(calls))
            Path(first["this_call"][0]["text_path"]).write_bytes(b"tampered")
            fresh = fetch_text.fetch_many([url], out, scope="A", getter=getter)
            self.assertEqual(2, len(calls))
            self.assertFalse(fresh["this_call"][0].get("reused", False))

    def test_parallel_fetch_deduplicates_and_saves_each_result(self):
        barrier = threading.Barrier(2)
        def getter(url, _timeout):
            barrier.wait(timeout=5)
            return 200, {"content-type": "text/plain"}, url.encode()
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            urls = ["https://example.org/a", "https://example.org/b"]
            fetch_text.fetch_many(urls + urls, out, scope="A", getter=getter, workers=2)
            self.assertEqual(set(urls), {r["url"] for r in fetch_text.load_records(out)})

    def test_simultaneous_report_writers_do_not_lose_rows(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [{"url": f"https://example.org/{n}", "ok": False, "reason": "unreachable"} for n in range(8)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda r: fetch_text.write_report({"scope": "A", "records": [r]}, out), rows))
            self.assertEqual(8, len(fetch_text.load_records(out)))


if __name__ == "__main__":
    unittest.main()
