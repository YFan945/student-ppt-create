from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.work = self.project / "outputs/.pptx-work/test"
        self.work.mkdir(parents=True)
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)
        self.event = {"cwd": str(self.project), "session_id": "parent", "agent_id": "child", "agent_type": runtime.CRITIC}

    def event_call(self, event, **extra):
        return runtime.handle({**self.event, "hook_event_name": event, **extra})

    def test_receipt_requires_start_successful_read_and_write(self):
        review = self.work / "visual-review.json"
        review.write_text("{}")
        self.event_call("SubagentStop")
        self.assertFalse((self.work / "critic-execution.json").exists())
        self.event_call("SubagentStart")
        page = self.work / "slide-1.png"
        page.write_bytes(b"test-image")
        self.event_call("PostToolUse", tool_name="Read", tool_input={"file_path": str(page)})
        self.event_call("PostToolUse", tool_name="Write", tool_input={"file_path": str(review)})
        self.event_call("SubagentStop")
        receipt = json.loads((self.work / "critic-execution.json").read_text())
        self.assertEqual(receipt["reads"][str(page)], runtime.digest(page))
        self.assertEqual(receipt["artifact"]["sha256"], runtime.digest(review))
        self.assertEqual(receipt["agent_id"], "child")

    def test_critic_cannot_write_generator_or_other_work_area(self):
        self.assertEqual(self.event_call("PreToolUse", tool_name="Write", tool_input={"file_path": str(self.work / "deck.js")}), 2)
        self.assertEqual(self.event_call("PreToolUse", tool_name="Write", tool_input={"file_path": str(self.work / "visual-review.json")}), 0)

    def test_research_scope_blocks_parent_web_but_not_unrelated_sessions(self):
        base = {"cwd": str(self.project), "session_id": "parent", "hook_event_name": "PreToolUse"}
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 0)
        runtime.handle({**base, "tool_name": "Skill", "tool_input": {"skill": "student-presentation-suite:sp-research"}})
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 2)
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch", "agent_type": runtime.RESEARCHER, "agent_id": "research-child"}), 0)
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch", "session_id": "unrelated"}), 0)

    def test_parallel_image_events_do_not_lose_read_hashes(self):
        self.event_call("SubagentStart")
        paths = [self.work / f"page-{index}.png" for index in range(8)]
        for path in paths:
            path.write_bytes(path.name.encode())

        def record(path):
            with runtime.event_lock(self.event):
                self.event_call("PostToolUse", tool_name="Read", tool_input={"file_path": str(path)})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(record, paths))
        review = self.work / "visual-review.json"
        review.write_text("{}")
        self.event_call("PostToolUse", tool_name="Write", tool_input={"file_path": str(review)})
        self.event_call("SubagentStop")
        receipt = json.loads((self.work / "critic-execution.json").read_text())
        self.assertEqual(receipt["reads"], {str(path): runtime.digest(path) for path in paths})
