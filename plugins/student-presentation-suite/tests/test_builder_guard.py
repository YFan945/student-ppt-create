from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
guard = load_module(ROOT / "scripts/builder_guard.py")


class BuilderGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.page = self.project / "outputs/.pptx-work/demo/pages/p01-cover.js"
        self.page.parent.mkdir(parents=True)
        self.page.write_text("// page", encoding="utf-8")
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)

    def event(self, tool: str, **extra):
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"file_path": str(self.page)},
            **extra,
        }

    def test_main_session_cannot_read_edit_or_write_page_modules(self) -> None:
        for tool in ("Read", "Edit", "Write"):
            with self.subTest(tool=tool):
                self.assertEqual(2, guard.handle(self.event(tool)))

    def test_only_isolated_builder_can_access_page_modules(self) -> None:
        event = self.event(
            "Edit",
            agent_type=guard.BUILDER,
            agent_id="builder-child",
        )
        self.assertEqual(0, guard.handle(event))
        self.assertEqual(
            2,
            guard.handle(self.event("Edit", agent_type=guard.BUILDER)),
            "agent_type without a child id is still the parent context",
        )

    def test_non_page_work_artifacts_are_untouched(self) -> None:
        manifest = self.project / "outputs/.pptx-work/demo/build-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        event = self.event("Read")
        event["tool_input"] = {"file_path": str(manifest)}
        self.assertEqual(0, guard.handle(event))

    def shell_event(self, command: str, **extra):
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            **extra,
        }

    def test_builder_inline_json_extraction_is_redirected(self) -> None:
        """2026-09-17 live: 19-46 inline scripts per repair round, each one a full context
        round-trip at ~150K resident context. page_brief.py answers the same question once."""
        command = (
            "cd \"$WD\" && node -e \" const q=require('./qa-quality.json');"
            " const s=JSON.stringify(q); console.log(s.slice(0,3000)); \""
        )
        event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(2, guard.handle(event))

    def test_builder_keeps_legitimate_node_commands(self) -> None:
        for command in (
            "node --check pages/p07-s07.js",
            "node deck.js /tmp/check.pptx",
            "node -e \"console.log(1+1)\"",
            "node \"$CLAUDE_PLUGIN_ROOT/scripts/pptx-helpers.js\" --describe",
        ):
            with self.subTest(command=command):
                event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
                self.assertEqual(0, guard.handle(event))

    def test_parent_session_inline_node_is_not_policed(self) -> None:
        command = "node -e \"console.log(require('./build-manifest.json').state)\""
        self.assertEqual(0, guard.handle(self.shell_event(command)))


if __name__ == "__main__":
    unittest.main()
