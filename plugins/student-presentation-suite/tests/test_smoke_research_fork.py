"""Headless Live E2E permission contract for smoke_research_fork.py."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    path = ROOT / "scripts" / "smoke_research_fork.py"
    spec = importlib.util.spec_from_file_location("smoke_research_fork", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


smoke = load()


class SmokeResearchForkPermissionTests(unittest.TestCase):
    def test_core_tools_cover_researcher_frontmatter(self) -> None:
        text = (ROOT / "agents" / "presentation-researcher.md").read_text(encoding="utf-8")
        match = re.search(r"^tools:\s*(.+)$", text, re.M)
        self.assertIsNotNone(match)
        declared = {item.strip() for item in match.group(1).split(",") if item.strip()}
        core = set(smoke.CORE_ALLOWED_TOOLS)
        missing = declared - core - set(smoke.WEB_TOOLS)
        self.assertFalse(missing, f"researcher tools not pre-allowed: {sorted(missing)}")
        self.assertTrue({"Agent", "Skill"} <= core)

    def test_scope_a_allows_web_and_adds_plugin_dir(self) -> None:
        plugin = ROOT
        command = smoke.build_command(
            "claude", plugin, "/student-presentation-suite:sp-research w b A -", 1.0, None, scope="A"
        )
        joined = " ".join(command)
        self.assertIn("--add-dir", command)
        self.assertEqual(str(plugin.resolve()), command[command.index("--add-dir") + 1])
        self.assertEqual("acceptEdits", command[command.index("--permission-mode") + 1])
        allowed = command[command.index("--allowedTools") + 1]
        for tool in (*smoke.CORE_ALLOWED_TOOLS, *smoke.WEB_TOOLS):
            self.assertIn(tool, allowed.split(","))
        self.assertNotIn("--disallowedTools", command)
        self.assertNotIn("bypassPermissions", joined)

    def test_scope_d_denies_web_tools(self) -> None:
        command = smoke.build_command(
            "claude", ROOT, "/student-presentation-suite:sp-research w b D m", 1.0, None, scope="D"
        )
        allowed = command[command.index("--allowedTools") + 1].split(",")
        self.assertEqual(["WebSearch", "WebFetch"], command[command.index("--disallowedTools") + 1].split(","))
        self.assertNotIn("WebSearch", allowed)
        self.assertNotIn("WebFetch", allowed)
        for tool in smoke.CORE_ALLOWED_TOOLS:
            self.assertIn(tool, allowed)

    def test_remaining_permission_denials_still_fail_mechanism(self) -> None:
        ok, problems, _notes = smoke.mechanism_verdict(
            {
                "subagent_stats": {"spawned": 1, "started_in_background": 0},
                "permission_denials": [{"tool": "Bash", "reason": "prompt denied"}],
            }
        )
        self.assertFalse(ok)
        self.assertTrue(any("permission denials" in item for item in problems))

        ok, problems, _notes = smoke.mechanism_verdict(
            {"subagent_stats": {"spawned": 1, "started_in_background": 0}, "permission_denials": []}
        )
        self.assertTrue(ok)
        self.assertEqual([], problems)

    def test_live_prompt_run_sheets_document_headless_preallow(self) -> None:
        prompts = ROOT / "scripts" / "live_prompts"
        for name in ("README.md", "run-ai-agent-trends.md", "run-own-paper-d-mode.md"):
            text = (prompts / name).read_text(encoding="utf-8")
            self.assertIn("--add-dir", text, name)
            self.assertIn("--allowedTools", text, name)
            self.assertNotIn("--permission-mode bypassPermissions", text, name)
            self.assertNotIn("dangerously-skip-permissions", text, name)
        d_mode = (prompts / "run-own-paper-d-mode.md").read_text(encoding="utf-8")
        self.assertIn("--disallowedTools", d_mode)


if __name__ == "__main__":
    unittest.main()
