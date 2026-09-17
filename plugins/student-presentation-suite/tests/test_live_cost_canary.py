from __future__ import annotations

import sys
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
canary = load_module(SCRIPTS / "live_cost_canary.py")


class LiveCostCanaryTests(unittest.TestCase):
    def test_shipped_prompts_exist_and_have_expected_research_scope(self) -> None:
        local = canary.SCENARIOS["deck-local"]
        research = canary.SCENARIOS["deck-research"]
        self.assertTrue(Path(local["prompt"]).is_file())
        self.assertTrue(Path(research["prompt"]).is_file())
        self.assertEqual(local["scope"], "C")
        self.assertEqual(research["scope"], "A")

    def test_local_command_disallows_web_and_keeps_session_persistence(self) -> None:
        command = canary.build_command(
            "/usr/bin/claude",
            ROOT,
            "prompt",
            1.0,
            scope="C",
            resume="session-123",
        )
        joined = " ".join(command)
        self.assertIn("--disallowedTools", command)
        self.assertIn("WebSearch,WebFetch", command)
        self.assertIn("--resume", command)
        self.assertIn("session-123", command)
        self.assertNotIn("--no-session-persistence", command)
        self.assertIn("--plugin-dir", joined)

    def test_research_command_allows_web(self) -> None:
        command = canary.build_command(
            "/usr/bin/claude", ROOT, "prompt", 1.0, scope="A"
        )
        self.assertNotIn("--disallowedTools", command)
        tools = command[command.index("--allowedTools") + 1]
        self.assertIn("WebSearch", tools)
        self.assertIn("WebFetch", tools)

    def test_aggregate_model_cost_includes_subagent_profiles(self) -> None:
        main = {"requests": 10, "context": {"average": 100_000, "peak": 150_000}}
        profiles = [
            {"requests": 10, "estimated_token_context": 1_000_000},
            {"requests": 4, "estimated_token_context": 200_000},
        ]
        result = canary.aggregate_model_cost(main, profiles)
        self.assertEqual(result["main_estimated_token_context"], 1_000_000)
        self.assertEqual(result["total_estimated_token_context"], 1_200_000)
        self.assertEqual(result["all_agent_requests"], 14)
        self.assertEqual(result["main_token_context_share_pct"], 83.3)

    def test_guardrails_fail_incomplete_or_expensive_run(self) -> None:
        model = {
            "main_peak_context": 210_000,
            "main_requests": 50,
            "total_estimated_token_context": 2_000_000,
        }
        pipeline = {"state": "qa", "builds": 2, "repairs": 3}
        limits = {
            "main_peak_context": 200_000,
            "main_requests": 100,
            "total_estimated_token_context": 5_000_000,
            "builds": 3,
            "repairs": 2,
        }
        problems = canary.evaluate_guardrails(model, pipeline, limits)
        self.assertTrue(any("state" in item for item in problems))
        self.assertTrue(any("main_peak_context" in item for item in problems))
        self.assertTrue(any("repairs" in item for item in problems))

    def test_guardrails_accept_complete_bounded_run(self) -> None:
        model = {
            "main_peak_context": 120_000,
            "main_requests": 40,
            "total_estimated_token_context": 4_000_000,
        }
        pipeline = {"state": "complete", "builds": 1, "repairs": 0}
        limits = canary.SCENARIOS["deck-local"]["guardrails"]
        self.assertEqual(canary.evaluate_guardrails(model, pipeline, limits), [])


if __name__ == "__main__":
    unittest.main()
