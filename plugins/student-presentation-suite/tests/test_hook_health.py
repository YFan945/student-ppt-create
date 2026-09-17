from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
hook_health = load_module(ROOT / "scripts/hook_health.py")


class HookHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        self.work = self.project / "outputs/.pptx-work/work-01"
        self.work.mkdir(parents=True)
        env = patch.dict(
            os.environ,
            {
                "CLAUDE_PROJECT_DIR": str(self.project),
                "CLAUDE_PLUGIN_ROOT": str(ROOT),
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def event(self, command: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(self.project),
            "session_id": "session-1",
            "tool_input": {"command": command},
        }

    def plan_command(self, work: Path | None = None) -> str:
        target = work or self.work
        return (
            f'python "{ROOT / "skills/sp-deck/scripts/ppt_pipeline.py"}" plan '
            f'--work-dir "{target}" --slide-spec spec.yaml '
            '--validation-report report.json --art-direction art.yaml'
        )

    def test_pretooluse_plan_arms_one_shot_receipt(self) -> None:
        target = hook_health.arm(self.event(self.plan_command()))
        self.assertIsNotNone(target)
        self.assertTrue(target.is_file())
        payload = hook_health.verify_plan_receipt(self.work)
        self.assertEqual(payload["work_dir"], str(self.work))
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(RuntimeError, "receipt missing"):
            hook_health.verify_plan_receipt(self.work)

    def test_stale_receipt_is_refused(self) -> None:
        target = hook_health.arm(self.event(self.plan_command()))
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["created_at"] = time.time() - hook_health.HEALTH_TTL_SECONDS - 1
        target.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "stale"):
            hook_health.verify_plan_receipt(self.work)

    def test_receipt_cannot_be_reused_for_another_work_dir(self) -> None:
        other = self.project / "outputs/.pptx-work/work-02"
        other.mkdir(parents=True)
        hook_health.arm(self.event(self.plan_command(self.work)))
        with self.assertRaisesRegex(RuntimeError, "receipt missing"):
            hook_health.verify_plan_receipt(other)

    def test_environment_variable_work_dir_is_expanded(self) -> None:
        command = self.plan_command().replace(str(self.work), "$CLAUDE_PROJECT_DIR/outputs/.pptx-work/work-01")
        target = hook_health.arm(self.event(command))
        self.assertEqual(target, hook_health.receipt_path(self.project, self.work))
        hook_health.verify_plan_receipt(self.work)

    def test_relative_work_dir_is_resolved_against_event_project(self) -> None:
        command = self.plan_command().replace(str(self.work), "outputs/.pptx-work/work-01")
        target = hook_health.arm(self.event(command))
        self.assertEqual(target, hook_health.receipt_path(self.project, self.work))
        hook_health.verify_plan_receipt(self.work)

    def test_bootstrap_refuses_missing_hooks_only_for_real_plugin_plan(self) -> None:
        argv = [
            str(ROOT / "skills/sp-deck/scripts/ppt_pipeline.py"),
            "plan",
            "--work-dir",
            str(self.work),
        ]
        with self.assertRaises(SystemExit) as caught:
            hook_health.enforce_pipeline_plan_bootstrap(argv)
        self.assertEqual(caught.exception.code, 2)

        hook_health.enforce_pipeline_plan_bootstrap(
            [str(ROOT / "skills/sp-deck/scripts/ppt_pipeline.py"), "next", "--work-dir", str(self.work)]
        )

    def test_bootstrap_accepts_fresh_pretooluse_receipt(self) -> None:
        hook_health.arm(self.event(self.plan_command()))
        hook_health.enforce_pipeline_plan_bootstrap(
            [
                str(ROOT / "skills/sp-deck/scripts/ppt_pipeline.py"),
                "plan",
                "--work-dir",
                str(self.work),
            ]
        )
        self.assertFalse(hook_health.receipt_path(self.project, self.work).exists())


if __name__ == "__main__":
    unittest.main()
