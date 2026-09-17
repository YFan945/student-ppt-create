from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class RuntimeEvidenceTeammateGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)

    def event(self, tool: str, **tool_input) -> dict:
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
        }

    def test_generic_named_researcher_or_critic_teammates_are_blocked(self) -> None:
        for name in ("researcher-carbon-pv-wind", "critic-helper"):
            with self.subTest(name=name):
                rc = runtime.handle(
                    self.event(
                        "Agent",
                        subagent_type="general-purpose",
                        name=name,
                        prompt="do evidence work",
                    )
                )
                self.assertEqual(2, rc)

    def test_sendmessage_to_named_evidence_teammate_is_blocked(self) -> None:
        for destination in ("researcher-carbon-pv-wind", "critic-helper"):
            with self.subTest(destination=destination):
                rc = runtime.handle(
                    self.event("SendMessage", to=destination, message="continue")
                )
                self.assertEqual(2, rc)

    def test_unrelated_named_teammate_is_not_blocked_by_evidence_guard(self) -> None:
        rc = runtime.handle(
            self.event(
                "Agent",
                subagent_type="general-purpose",
                name="layout-helper",
                prompt="inspect layout notes",
            )
        )
        self.assertEqual(0, rc)


if __name__ == "__main__":
    unittest.main()
