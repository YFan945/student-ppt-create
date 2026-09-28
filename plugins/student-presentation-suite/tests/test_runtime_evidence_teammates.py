from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class RuntimeEvidenceTeammateGuardTests(unittest.TestCase):
    """CD-5 governs deck evidence work, so the fuzzy name refusal is scoped to
    a managed pipeline session (Batch 6.1). The exact plugin-agent-type spawn
    refusals (test_runtime_evidence.py) stay unscoped — they cannot
    false-positive on unrelated workflows."""

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

    def arm_research(self) -> None:
        runtime.pipeline_context.mark_research_active(self.project, {"session_id": "parent"})

    def test_generic_named_researcher_or_critic_teammates_are_blocked(self) -> None:
        self.arm_research()
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
        self.arm_research()
        for destination in ("researcher-carbon-pv-wind", "critic-helper"):
            with self.subTest(destination=destination):
                rc = runtime.handle(
                    self.event("SendMessage", to=destination, message="continue")
                )
                self.assertEqual(2, rc)

    def test_unscoped_session_may_name_a_researcher_or_critic_teammate(self) -> None:
        """2026-09-28 scope isolation: a plain development session naming a
        teammate "research-assistant" is not the pipeline's business — the
        refusal must not fire without managed research scope."""
        for tool, tool_input in (
            ("Agent", {"subagent_type": "general-purpose", "name": "researcher-carbon-pv-wind", "prompt": "summarize notes"}),
            ("SendMessage", {"to": "critic-helper", "message": "continue"}),
        ):
            with self.subTest(tool=tool):
                rc = runtime.handle(self.event(tool, **tool_input))
                self.assertEqual(0, rc)

    def test_unrelated_named_teammate_is_not_blocked_by_evidence_guard(self) -> None:
        self.arm_research()
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
