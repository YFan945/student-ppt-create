from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "hooks.json"


class HookResponsibilityTests(unittest.TestCase):
    def pretool_matchers_for(self, script_name: str) -> list[str]:
        data = json.loads(HOOKS.read_text(encoding="utf-8"))
        matchers: list[str] = []
        for entry in data["hooks"]["PreToolUse"]:
            commands = [hook.get("command", "") for hook in entry.get("hooks", [])]
            if any(script_name in command for command in commands):
                matchers.append(entry.get("matcher", ""))
        return matchers

    def test_cost_guard_only_handles_cost_related_tools(self) -> None:
        self.assertEqual(["Bash|Read|Grep"], self.pretool_matchers_for("cost_guard.py"))

    def test_runtime_evidence_owns_agent_spawn_integrity(self) -> None:
        matchers = self.pretool_matchers_for("runtime_evidence.py")
        self.assertTrue(any("Agent" in matcher.split("|") for matcher in matchers))
        self.assertTrue(any("Write" in matcher.split("|") for matcher in matchers))
        self.assertTrue(any("WebSearch" in matcher.split("|") for matcher in matchers))

    def test_production_entry_guard_remains_bash_only(self) -> None:
        self.assertEqual(["Bash"], self.pretool_matchers_for("production_entry_guard.py"))


if __name__ == "__main__":
    unittest.main()
