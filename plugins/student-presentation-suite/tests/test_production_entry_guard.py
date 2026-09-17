from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
guard = load_module(ROOT / "scripts/production_entry_guard.py")


class ProductionEntryGuardTests(unittest.TestCase):
    def event(self, command: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    def run_guard(self, command: str) -> tuple[int, str]:
        stream = io.StringIO(json.dumps(self.event(command)))
        errors = io.StringIO()
        original = sys.stdin
        sys.stdin = stream
        try:
            with redirect_stderr(errors):
                code = guard.main()
        finally:
            sys.stdin = original
        return code, errors.getvalue()

    def test_public_deck_entrypoints_are_allowed(self) -> None:
        commands = [
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir wd --json',
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" build --work-dir wd --entry deck.js',
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/calibration_preview.py" --work-dir wd --slides 1 3 --json',
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/visual_reference_select.py" --role cover --count 3',
            'sh "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/run_gates.sh" --slide-spec spec.yaml',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual((0, ""), self.run_guard(command))

    def test_internal_deck_scripts_are_default_denied(self) -> None:
        for name in (
            "art_direction_check.py",
            "copy_fit_preflight.py",
            "page_copy_fidelity_check.py",
            "pptx_delivery_check.py",
            "generator_scaffold.py",
        ):
            command = f'python "${{CLAUDE_PLUGIN_ROOT}}/skills/sp-deck/scripts/{name}" --json'
            with self.subTest(name=name):
                code, message = self.run_guard(command)
                self.assertEqual(2, code)
                self.assertIn(name, message)
                self.assertIn("ppt_pipeline.py next", message)

    def test_unknown_future_internal_script_is_denied_without_new_regex(self) -> None:
        code, message = self.run_guard(
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/new_magic_bypass.py" --work-dir wd'
        )
        self.assertEqual(2, code)
        self.assertIn("new_magic_bypass.py", message)

    def test_pipeline_unknown_action_is_denied(self) -> None:
        code, message = self.run_guard(
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" secret-debug --work-dir wd'
        )
        self.assertEqual(2, code)
        self.assertIn("stable actions", message)

    def test_pipeline_help_probe_is_not_a_public_action(self) -> None:
        code, _message = self.run_guard(
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" --help'
        )
        self.assertEqual(2, code)

    def test_windows_style_path_is_recognized(self) -> None:
        command = r'python "C:\Users\me\.claude\plugins\student-presentation-suite\skills\sp-deck\scripts\pptx_actual_content_check.py" --json'
        code, message = self.run_guard(command)
        self.assertEqual(2, code)
        self.assertIn("pptx_actual_content_check.py", message)

    def test_other_skills_and_project_bash_are_out_of_scope(self) -> None:
        commands = [
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-review/scripts/pptx_static_check.py" deck.pptx --json',
            'python scripts/my_project_tool.py --input data.json',
            'npm test',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual((0, ""), self.run_guard(command))

    def test_one_blocked_script_blocks_a_compound_command(self) -> None:
        command = (
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/visual_reference_select.py" --role cover '
            '&& python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/delivery_check.py" --json'
        )
        code, message = self.run_guard(command)
        self.assertEqual(2, code)
        self.assertIn("delivery_check.py", message)


if __name__ == "__main__":
    unittest.main()
