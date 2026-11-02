from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workflow_guard.py"

# confirm 必备字段组的完整摘要 fixture：五组字段（场景/受众/篇幅/研究范围/输出交付）
# 全覆盖，供 confirm 成功路径的用例使用。
FULL_SUMMARY = (
    "# Production Summary\n\n"
    "## 场景\n课堂展示 scenario：课程报告。\n\n"
    "## 受众\n受众：同班同学与任课老师（audience）。\n\n"
    "## 篇幅\n篇幅：8 页 slides，时长 10 分钟（duration 10 min）。\n\n"
    "## 研究范围/证据\n研究范围 scope：evidence 与来源均已确认。\n\n"
    "## 输出/交付\n输出 output：交付 deliverable 到 outputs 目录。\n"
)


class StateTransitionTests(unittest.TestCase):
    """状态机转换规则测试"""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT)

    def _ns(self, action: str, **kwargs: object) -> argparse.Namespace:
        base = {"action": action, "state_file": None, "topic": "test", "summary_file": None,
                "to": None, "qa_manifest": None, "pptx": None, "delivery_report": None,
                "reason": None, "force": False}
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_all_valid_forward_transitions(self) -> None:
        module = self.module
        seq = module.SEQUENCE
        for i in range(len(seq) - 1):
            with self.subTest(before=seq[i], after=seq[i + 1]):
                self.assertTrue(
                    module.transition_allowed(seq[i], seq[i + 1])
                )

    def test_reverse_transitions_blocked(self) -> None:
        module = self.module
        seq = module.SEQUENCE
        for i in range(1, len(seq)):
            with self.subTest(before=seq[i], after=seq[i - 1]):
                if (seq[i], seq[i - 1]) in module.REWORK_EDGES:
                    # qa → producing 是允许的返工边，用于修复后重建
                    self.assertTrue(module.transition_allowed(seq[i], seq[i - 1]))
                    continue
                self.assertFalse(
                    module.transition_allowed(seq[i], seq[i - 1])
                )

    def test_rework_edge_qa_to_producing_allowed(self) -> None:
        module = self.module
        self.assertTrue(module.transition_allowed("qa", "producing"))
        # 其他回退仍被拒绝
        self.assertFalse(module.transition_allowed("complete", "qa"))
        self.assertFalse(module.transition_allowed("producing", "planned"))

    def test_second_qa_rework_cycle_is_allowed_without_a_paperwork_reason(self):
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            module.save_state(state, {"state": "qa", "rework_count": 1})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.state_command(self._ns("transition", state_file=state, to="producing", reason=None)), 0)
            self.assertEqual(module.load_state(state)["rework_count"], 2)

    def test_recovery_edge_incomplete_to_qa_allowed(self) -> None:
        module = self.module
        self.assertTrue(module.transition_allowed("incomplete", "qa"))
        # 其它从 incomplete 的出口仍被拒绝（除 reset）
        self.assertFalse(module.transition_allowed("incomplete", "planned"))
        self.assertFalse(module.transition_allowed("incomplete", "producing"))
        # 终态互转仍允许（complete→incomplete 等）
        self.assertTrue(module.transition_allowed("complete", "incomplete"))
        self.assertTrue(module.transition_allowed("incomplete", "blocked"))

    def test_skip_transitions_blocked(self) -> None:
        module = self.module
        self.assertFalse(module.transition_allowed("intake_pending", "producing"))
        self.assertFalse(module.transition_allowed("intake_confirmed", "qa"))
        self.assertFalse(module.transition_allowed("planned", "complete"))

    def test_terminal_from_intake_pending_blocked(self) -> None:
        module = self.module
        self.assertFalse(module.transition_allowed("intake_pending", "incomplete"))
        self.assertFalse(module.transition_allowed("intake_pending", "blocked"))

    def test_terminal_from_later_states_allowed(self) -> None:
        module = self.module
        for state in ("intake_confirmed", "planned", "producing", "qa", "complete"):
            for terminal in ("incomplete", "blocked"):
                with self.subTest(before=state, after=terminal):
                    self.assertTrue(
                        module.transition_allowed(state, terminal)
                    )

    def test_invalid_state_names(self) -> None:
        module = self.module
        self.assertFalse(module.transition_allowed("bogus", "planned"))
        self.assertFalse(module.transition_allowed("intake_pending", "bogus"))

    def test_same_state_blocked(self) -> None:
        module = self.module
        # SEQUENCE 内状态与终态（incomplete/blocked）的同状态自转都应被拒绝
        for state in list(module.SEQUENCE) + sorted(module.TERMINAL):
            with self.subTest(state=state):
                self.assertFalse(
                    module.transition_allowed(state, state)
                )

    def test_current_completion_needs_no_old_receipts(self):
        with mock.patch("shared.artifact_validation.validate_artifact", return_value={"ok": True}) as validator:
            self.assertEqual(self.module.validate_completion_manifest(None, Path("deck.pptx")), [])
            validator.assert_called_once_with(Path("deck.pptx"))

    def test_passing_old_receipt_cannot_override_current_artifact_error(self):
        report = {"ok": False, "package": {"findings": [{"severity": "error", "code": "corrupt", "detail": "broken package"}]}}
        with mock.patch("shared.artifact_validation.validate_artifact", return_value=report):
            self.assertEqual(self.module.validate_completion_manifest(Path("old-qa.json"), Path("broken.pptx"), Path("old-passing.json")), ["broken package"])
        self.assertTrue(self.module.validate_completion_manifest(None, None))

    def test_complete_rejects_changed_summary(self) -> None:
        """轻量防线：confirm 后 summary 被改 → complete 被拒。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            summary = root / "summary.md"
            summary.write_text("version 1", encoding="utf-8")
            module.save_state(
                state,
                {
                    "workflow_version": "1.0",
                    "state": "qa",
                    "topic": "t",
                    "summary_file": str(summary),
                    "summary_sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
                },
            )
            summary.write_text("version 2", encoding="utf-8")  # 已变更
            with self.assertRaises(SystemExit):
                module.state_command(
                    self._ns("transition", state_file=state, to="complete")
                )

    def test_complete_requires_confirmed_summary(self) -> None:
        """轻量防线：从未 confirm 直接 complete → 被拒。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            module.save_state(
                state, {"workflow_version": "1.0", "state": "qa", "topic": "t"}
            )
            with self.assertRaises(SystemExit):
                module.state_command(
                    self._ns("transition", state_file=state, to="complete")
                )

    def test_confirm_force_changed_summary_invalidates_progress(self) -> None:
        """confirm --force 修改摘要后回退到 intake_confirmed。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            summary = root / "summary.md"
            summary.write_text(FULL_SUMMARY, encoding="utf-8")
            module.save_state(
                state,
                {
                    "workflow_version": "1.0",
                    "state": "producing",
                    "topic": "t",
                    "summary_sha256": "old",
                    "rework_count": 2,
                },
            )
            module.state_command(
                self._ns(
                    "confirm", state_file=state, summary_file=summary, force=True
                )
            )
            after = module.load_state(state)
            self.assertEqual("intake_confirmed", after["state"])
            self.assertNotIn("rework_count", after)
            self.assertEqual(
                hashlib.sha256(summary.read_bytes()).hexdigest(),
                after["summary_sha256"],
            )

    def test_confirm_without_force_rejects_later_state(self) -> None:
        """无 --force 时从 producing 状态 confirm → 被拒。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            summary = root / "summary.md"
            summary.write_text(FULL_SUMMARY, encoding="utf-8")
            module.save_state(
                state,
                {"workflow_version": "1.0", "state": "producing", "topic": "t"},
            )
            with self.assertRaises(SystemExit):
                module.state_command(
                    self._ns("confirm", state_file=state, summary_file=summary)
                )

    def test_confirm_rejects_an_empty_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            summary = Path(tmp) / "summary.md"
            summary.write_text("  ", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.module.state_command(self._ns("confirm", state_file=state, summary_file=summary))

    def test_confirm_accepts_full_summary(self) -> None:
        """五组字段齐全的摘要正常 confirm，状态与哈希照常落盘。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            summary = root / "summary.md"
            summary.write_text(FULL_SUMMARY, encoding="utf-8")
            module.state_command(
                self._ns("confirm", state_file=state, summary_file=summary)
            )
            after = module.load_state(state)
            self.assertEqual("intake_confirmed", after["state"])
            self.assertEqual(
                hashlib.sha256(summary.read_bytes()).hexdigest(),
                after["summary_sha256"],
            )


class ProjectRootTests(unittest.TestCase):
    """project_root 一致性测试"""

    def test_uses_claude_project_dir(self) -> None:
        module = load_module(SCRIPT)
        with mock.patch.dict(
            "os.environ", {"CLAUDE_PROJECT_DIR": "/fake/project"}, clear=True
        ):
            root = module.project_root()
            self.assertEqual(root, Path("/fake/project").resolve())

    def test_falls_back_to_cwd(self) -> None:
        module = load_module(SCRIPT)
        with mock.patch.dict("os.environ", {}, clear=True):
            root = module.project_root()
            self.assertEqual(root, Path.cwd().resolve())


if __name__ == "__main__":
    unittest.main()
