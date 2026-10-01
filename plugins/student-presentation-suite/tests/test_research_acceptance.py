"""Acceptance must distinguish actual search execution from a valid artifact."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_helpers import load_module

matrix = load_module(Path(__file__).resolve().parents[1] / "scripts/research_acceptance_matrix.py")


class AcceptanceTests(unittest.TestCase):
    def test_valid_pack_without_websearch_does_not_pass_search_acceptance(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name, data in (("research-pack.json", {"must_verify": []}),
                               ("research-pack-validation.json", {"ok": True, "delivery_status": "ready"}),
                               ("research-task.json", {"semantic_review_required": True})):
                (work / name).write_text(json.dumps(data), encoding="utf-8")
            payload = {"pack_path": str(work / "research-pack.json"), "mechanism_ok": True}
            report = matrix.summarize(payload, [], "ready", True)
            self.assertFalse(report["passed"])
            event = {"type": "assistant", "parent_tool_use_id": "child", "message": {
                "content": [{"type": "tool_use", "name": "WebSearch"}]}}
            self.assertTrue(matrix.summarize(payload, [event], "ready", True)["passed"])
            self.assertFalse(matrix.summarize(payload, [event], "partial", True)["passed"])


if __name__ == "__main__":
    unittest.main()
