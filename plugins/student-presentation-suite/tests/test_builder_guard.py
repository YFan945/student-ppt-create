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


if __name__ == "__main__":
    unittest.main()
