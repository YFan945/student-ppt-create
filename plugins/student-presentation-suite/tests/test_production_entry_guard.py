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
            'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" doctor --work-dir wd --json',
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
            "slide_spec_guard.py",
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

    def test_root_evidence_compiler_is_denied(self) -> None:
        commands = [
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/research_pack_to_evidence.py" pack.json --output map.json',
            'python plugins/student-presentation-suite/scripts/research_pack_to_evidence.py pack.json --output map.json',
            'python "C:\\Users\\me\\.claude\\plugins\\student-presentation-suite\\0.14.0\\scripts\\research_pack_to_evidence.py" pack.json',
        ]
        for command in commands:
            with self.subTest(command=command):
                code, message = self.run_guard(command)
                self.assertEqual(2, code)
                self.assertIn("evidence-map compilation", message)

    def test_direct_pptx_builder_is_denied_but_probe_is_allowed(self) -> None:
        blocked = [
            'node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --output out.pptx deck.js',
            'node plugins/student-presentation-suite/scripts/run_with_pptxgenjs.js --output out.pptx deck.js',
        ]
        for command in blocked:
            with self.subTest(command=command):
                code, message = self.run_guard(command)
                self.assertEqual(2, code)
                self.assertIn("Direct run_with_pptxgenjs.js generation", message)
        self.assertEqual(
            (0, ""),
            self.run_guard('node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --probe'),
        )

    def test_probe_does_not_whitelist_later_builder_generation(self) -> None:
        command = (
            'node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --probe '
            '&& node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --output out.pptx deck.js'
        )
        code, message = self.run_guard(command)
        self.assertEqual(2, code)
        self.assertIn("Direct run_with_pptxgenjs.js generation", message)

    def test_unrelated_root_utilities_are_out_of_scope(self) -> None:
        commands = [
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/session_cost.py" --json session.jsonl',
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_research_pack.py" pack.json',
            'node "${CLAUDE_PLUGIN_ROOT}/scripts/pptx-helpers.js" --describe',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual((0, ""), self.run_guard(command))

    def test_mentions_of_internal_scripts_are_reads_not_invocations(self) -> None:
        """2026-09-26 trap: deck maintenance (`sed`/`grep`/`cat`/`git diff` carrying
        internal script names) was refused because any occurrence matched. Reads pass;
        only interpreter-adjacent or direct-exec forms are invocations."""
        commands = [
            "sed -n '1,3p' C:/u/.claude/plugins/cache/claude-personal/student-presentation-suite/0.16.9/skills/sp-deck/scripts/deck_rhythm.py",
            'grep -n "def check_bash" plugins/student-presentation-suite/skills/sp-deck/scripts/quality_gate.py',
            'cat "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" | head -5',
            "git diff -- plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py",
            "cat plugins/student-presentation-suite/scripts/research_pack_to_evidence.py",
        ]
        for command in commands:
            with self.subTest(command=command[:60]):
                self.assertEqual((0, ""), self.run_guard(command))

    def test_invocations_still_refused_after_anchoring(self) -> None:
        """Anchoring must not re-open the bypasses the guard exists to close."""
        commands = [
            "python C:/u/.claude/plugins/cache/claude-personal/student-presentation-suite/0.16.9/skills/sp-deck/scripts/deck_rhythm.py --work-dir wd",
            './skills/sp-deck/scripts/art_direction_check.py --json',
            'py -3 "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/art_direction_check.py" --json',
            'FOO=bar python skills/sp-deck/scripts/quality_gate.py --json',
            'grep x skills/sp-deck/scripts/quality_gate.py && python skills/sp-deck/scripts/quality_gate.py --json',
            'python "${CLAUDE_PLUGIN_ROOT}/scripts/research_pack_to_evidence.py" pack.json',
        ]
        for command in commands:
            with self.subTest(command=command[:60]):
                code, message = self.run_guard(command)
                self.assertEqual(2, code)
                self.assertTrue(message.strip())

    def test_probe_mention_does_not_break_probe_allowance(self) -> None:
        """A non-invocation mention of run_with_pptxgenjs.js must not make the
        probe-check see a non-probe invocation. (Known adjacency limit: a mention
        whose path directly follows a word like `node` is indistinguishable from
        an invocation for a text scanner — conservative refusal wins there.)"""
        command = (
            'node "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js" --probe '
            '&& grep -c run_with "${CLAUDE_PLUGIN_ROOT}/scripts/run_with_pptxgenjs.js"'
        )
        self.assertEqual((0, ""), self.run_guard(command))

    def test_windows_style_path_is_recognized(self) -> None:
        command = r'python "C:\Users\me\.claude\plugins\student-presentation-suite\skills\sp-deck\scripts\pptx_actual_content_check.py" --json'
        command = command.replace(r'\"', '"')
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

    def test_builder_child_gets_allowlist_instead_of_pipeline_dead_end(self) -> None:
        """The builder may not run ppt_pipeline.py; its refusals must not point there."""
        command = 'python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/slide_spec_guard.py" freeze --slide-spec s.yaml'
        stream = io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "agent_type": "student-presentation-suite:presentation-builder",
                    "agent_id": "child-1",
                }
            )
        )
        errors = io.StringIO()
        original = sys.stdin
        sys.stdin = stream
        try:
            with redirect_stderr(errors):
                code = guard.main()
        finally:
            sys.stdin = original
        message = errors.getvalue()
        self.assertEqual(2, code)
        self.assertIn("isolated builder", message)
        self.assertIn("pptx-helpers.js", message)
        self.assertNotIn("ppt_pipeline.py next", message)


if __name__ == "__main__":
    unittest.main()
