"""Stop on evidence/time/stall; retain valid partial artifacts and check handoff."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import test_research_evidence as fixtures

from shared.research_control import status

handoff = fixtures.load_module(fixtures.ROOT / "scripts/research_handoff.py")
controller = fixtures.load_module(fixtures.ROOT / "scripts/research_control.py")


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.task = self.work / "research-task.json"
        self.task.write_text(json.dumps({"budget": "simple"}), encoding="utf-8")

    def test_stall_stops_and_failures_do_not_refresh_progress(self):
        self.assertEqual("active", status(self.work, now=10, retrieval=True)["state"])
        fetched = self.work / "research/fetched/fetch-text-report.json"
        fetched.parent.mkdir(parents=True)
        fetched.write_text(json.dumps({"records": [{"ok": False, "reason": "unreachable"}]}), encoding="utf-8")
        decision = status(self.work, now=71)
        self.assertEqual("no_useful_progress", decision["reason"])
        self.assertEqual(10, decision["last_progress_at"])
        self.assertTrue(self.task.is_file())

    def test_repeated_success_does_not_refresh_but_new_text_does(self):
        status(self.work, now=10, retrieval=True)
        fetched = self.work / "research/fetched/fetch-text-report.json"
        fetched.parent.mkdir(parents=True)
        record = {"ok": True, "text_sha256": "first", "host_class": "public"}
        fetched.write_text(json.dumps({"records": [record]}), encoding="utf-8")
        self.assertEqual(40, status(self.work, now=40)["last_progress_at"])
        self.assertEqual(40, status(self.work, now=90)["last_progress_at"])
        record["text_sha256"] = "second"
        fetched.write_text(json.dumps({"records": [record]}), encoding="utf-8")
        self.assertEqual(95, status(self.work, now=95)["last_progress_at"])
        self.assertEqual("time_budget_exhausted", status(self.work, now=131)["reason"])

    def test_task_can_override_time_without_search_count_quotas(self):
        self.task.write_text(json.dumps({"budget": "simple", "time_budget_seconds": 5, "stall_timeout_seconds": 60}), encoding="utf-8")
        status(self.work, now=10)
        self.assertEqual("time_budget_exhausted", status(self.work, now=15)["reason"])

    def test_preparation_is_not_misclassified_as_stalled_search(self):
        status(self.work, now=10)
        self.assertEqual("active", status(self.work, now=100)["state"])
        self.assertEqual("active", status(self.work, now=100, retrieval=True)["state"])


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TextEvidenceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.work = self.fixture.work
        self.pack = self.work / "research-pack.json"
        self.pack.write_text(json.dumps(self.fixture.pack), encoding="utf-8")
        task = self.fixture.task()
        (self.work / "research-task.json").write_text(json.dumps(task), encoding="utf-8")
        (self.fixture.fetched / "fetch-text-report.json").write_text(json.dumps(self.fixture.report), encoding="utf-8")
        self.assertEqual(0, fixtures.validator.main([str(self.pack)]))
        self.receipt = self.work / "research-execution.json"
        self.receipt.write_text(json.dumps({"spawn_verified": True, "agent": fixtures.runtime.RESEARCHER,
            "artifact": {"path": str(self.pack), "sha256": fixtures.validator.sha256_file(self.pack)}}), encoding="utf-8")

    def test_handoff_prints_only_metadata_and_accepts_current_receipt(self):
        report = handoff.inspect(self.work)
        self.assertTrue(report["ok"], report)
        self.assertEqual("ready", report["delivery_status"])
        self.assertNotIn("evidence", report)
        self.assertEqual("sufficient_evidence", status(self.work, now=10)["reason"])

    def test_resume_requires_reason_and_preserves_seen_evidence(self):
        status(self.work, now=10)
        before = json.loads((self.work / "research-control.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            controller.resume(self.work, " ")
        controller.resume(self.work, "用户提供了新的材料")
        after = json.loads((self.work / "research-control.json").read_text(encoding="utf-8"))
        self.assertEqual(before["seen"], after["seen"])
        self.assertEqual(1, len(after["resumes"]))

    def test_stop_blocks_retrieval_but_allows_pack_finalization(self):
        import os
        from unittest.mock import patch
        project = self.work.parents[2]
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(project)}):
            event = {"cwd": str(project), "session_id": "control", "hook_event_name": "PreToolUse",
                     "tool_name": "Agent", "tool_input": {"subagent_type": fixtures.runtime.RESEARCHER, "prompt": str(self.work)}}
            self.assertEqual(0, fixtures.runtime.handle(event))
            event.update(agent_type=fixtures.runtime.RESEARCHER, agent_id="child")
            event.update(tool_name="WebSearch", tool_input={"query": "one more"})
            self.assertEqual(2, fixtures.runtime.handle(event))
            event.update(tool_name="Write", tool_input={"file_path": str(self.pack), "content": "{}"})
            self.assertEqual(0, fixtures.runtime.handle(event))
            event.update(tool_name="Bash", tool_input={"command": 'python validate_research_pack.py pack.json --fetch-report "research/fetched/fetch-text-report.json"'})
            self.assertEqual(0, fixtures.runtime.handle(event))
            event.update(tool_name="Bash", tool_input={"command": "python research_control.py --resume --reason new"})
            self.assertEqual(2, fixtures.runtime.handle(event))

    def test_tampered_text_or_receipt_is_rejected(self):
        self.receipt.write_text(json.dumps({"spawn_verified": True, "agent": fixtures.runtime.RESEARCHER,
            "artifact": {"path": str(self.pack), "sha256": "bad"}}), encoding="utf-8")
        self.assertFalse(handoff.inspect(self.work)["ok"])
        Path(self.fixture.report["records"][0]["text_path"]).write_bytes(b"changed")
        self.assertFalse(handoff.inspect(self.work)["ok"])


if __name__ == "__main__":
    unittest.main()
