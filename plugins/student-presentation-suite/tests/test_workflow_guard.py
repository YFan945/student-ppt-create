from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "workflow_guard.py"


class StateTransitionTests(unittest.TestCase):
    """状态机转换规则测试"""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module(SCRIPT)

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

    def test_second_qa_rework_cycle_is_rejected(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            module.save_state(
                state,
                {
                    "workflow_version": "1.0",
                    "state": "qa",
                    "topic": "t",
                    "rework_count": 1,
                },
            )
            with self.assertRaises(SystemExit):
                module.state_command(
                    self._ns(
                        "transition",
                        state_file=state,
                        to="producing",
                        reason="second blocker cycle",
                    )
                )

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

    def test_complete_requires_valid_qa_manifest(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            content_qa = root / "content-qa.json"
            visual_report = root / "visual-inspection.json"
            asset_manifest = root / "asset-manifest.json"
            asset_report = root / "asset-report.json"
            content_qa.write_text("{}", encoding="utf-8")
            visual_report.write_text("{}", encoding="utf-8")
            asset_manifest.write_text("{}", encoding="utf-8")
            asset_report.write_text("{}", encoding="utf-8")
            manifest = root / "qa.json"
            manifest.write_text(json.dumps({
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "slide_count": 1,
                "rendered_page_count": 1,
                "scenario_contract_passed": True,
                "visual_inspection": {
                    "completed": True,
                    "remaining_blockers": 0,
                    "inspected_pages": [1],
                    "repair_cycles": 0,
                    "no_repair_needed_reason": "No visual defect was found.",
                },
                "content_qa_report": str(content_qa),
                "content_qa_report_sha256": hashlib.sha256(content_qa.read_bytes()).hexdigest(),
                "visual_inspection_report": str(visual_report),
                "visual_inspection_report_sha256": hashlib.sha256(visual_report.read_bytes()).hexdigest(),
                "asset_manifest": str(asset_manifest),
                "asset_manifest_sha256": hashlib.sha256(asset_manifest.read_bytes()).hexdigest(),
                "asset_manifest_report": str(asset_report),
                "asset_manifest_report_sha256": hashlib.sha256(asset_report.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            delivery = root / "delivery.json"
            package = root / "package.json"
            package.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            delivery.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "complete",
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "qa_manifest_sha256": hashlib.sha256(
                            manifest.read_bytes()
                        ).hexdigest(),
                        "package_report_sha256": hashlib.sha256(
                            package.read_bytes()
                        ).hexdigest(),
                        "package_blockers": 0,
                        "package_validation_passed": True,
                        "preview_page_coverage": "1/1",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [],
                module.validate_completion_manifest(manifest, pptx, delivery),
            )
            manifest.write_text("{}", encoding="utf-8")
            self.assertTrue(module.validate_completion_manifest(manifest, pptx))

    def test_complete_accepts_simplified_delivery_without_qa_manifest(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            delivery = root / "delivery.json"
            delivery.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "complete",
                        "gate_profile": "simplified-v1",
                        "generation_core_version": "0.7.1",
                        "actual_content_check_passed": True,
                        "quality_check_passed": True,
                        "quality_report_sha256": "1" * 64,
                        "slide_spec_sha256": "2" * 64,
                        "spec_lock_sha256": "3" * 64,
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "slide_spec_validation_passed": True,
                        "package_validation_passed": True,
                        "package_blockers": 0,
                        "visual_reviewed": True,
                        "preview_page_coverage": "1/1",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [], module.validate_completion_manifest(None, pptx, delivery)
            )
            broken = json.loads(delivery.read_text(encoding="utf-8"))
            broken["visual_reviewed"] = False
            delivery.write_text(json.dumps(broken), encoding="utf-8")
            self.assertTrue(module.validate_completion_manifest(None, pptx, delivery))

    def test_complete_rejects_pre_v071_simplified_delivery(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            delivery = root / "delivery.json"
            delivery.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "complete",
                        "gate_profile": "simplified-v1",
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "slide_spec_validation_passed": True,
                        "package_validation_passed": True,
                        "package_blockers": 0,
                        "visual_reviewed": True,
                        "preview_page_coverage": "1/1",
                    }
                ),
                encoding="utf-8",
            )
            errors = module.validate_completion_manifest(None, pptx, delivery)
            self.assertTrue(any("0.7.1" in item for item in errors))
            self.assertTrue(any("quality gate" in item for item in errors))

    def test_complete_accepts_simplified_v08_delivery(self) -> None:
        """v0.8 门禁链的交付报告必须能走 complete 转换（实战暴露的口径分裂）。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            delivery = root / "delivery.json"
            delivery.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "complete",
                        "gate_profile": "simplified-v08",
                        "generation_core_version": "0.8",
                        "slide_spec_validation_passed": True,
                        "package_validation_passed": True,
                        "package_blockers": 0,
                        "visual_reviewed": True,
                        "actual_content_check_passed": True,
                        "quality_check_passed": True,
                        "visual_generation_check_passed": True,
                        "visual_review_check_passed": True,
                        "quality_report_sha256": "1" * 64,
                        "actual_content_report_sha256": "4" * 64,
                        "visual_generation_report_sha256": "5" * 64,
                        "slide_spec_sha256": "2" * 64,
                        "spec_lock_sha256": "3" * 64,
                        "art_direction_sha256": "6" * 64,
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "preview_page_coverage": "1/1",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [], module.validate_completion_manifest(None, pptx, delivery)
            )
            # 任一 v0.8 检查项失败都必须拒绝。
            broken = json.loads(delivery.read_text(encoding="utf-8"))
            broken["visual_review_check_passed"] = False
            delivery.write_text(json.dumps(broken), encoding="utf-8")
            errors = module.validate_completion_manifest(None, pptx, delivery)
            self.assertTrue(any("视觉复核证据绑定" in item for item in errors))

    def test_complete_rejects_missing_manifest(self) -> None:
        module = self.module
        self.assertTrue(module.validate_completion_manifest(None, None))

    def test_complete_rejects_hash_mismatch(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            other = root / "other.pptx"
            with zipfile.ZipFile(other, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide><!-- different --></slide>")
            manifest = root / "qa.json"
            manifest.write_text(json.dumps({
                "pptx_sha256": hashlib.sha256(other.read_bytes()).hexdigest(),
                "slide_count": 1,
                "rendered_page_count": 1,
                "visual_inspection": {"completed": True, "remaining_blockers": 0},
            }), encoding="utf-8")
            errors = module.validate_completion_manifest(manifest, pptx)
            self.assertTrue(any("pptx_sha256" in e for e in errors))

    def test_complete_rejects_remaining_blockers(self) -> None:
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            manifest = root / "qa.json"
            manifest.write_text(json.dumps({
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "slide_count": 1,
                "rendered_page_count": 1,
                "visual_inspection": {"completed": True, "remaining_blockers": 2},
            }), encoding="utf-8")
            errors = module.validate_completion_manifest(manifest, pptx)
            self.assertTrue(any("blocker" in e.lower() for e in errors))

    def test_complete_rejects_missing_visual_inspection(self) -> None:
        """没有逐页渲染证据时不能 complete。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            manifest = root / "qa.json"
            manifest.write_text(json.dumps({
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "slide_count": 1,
                "scenario_contract_passed": True,
            }), encoding="utf-8")
            delivery = root / "delivery.json"
            delivery.write_text(json.dumps({
                "ok": True,
                "status": "complete",
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "qa_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "package_blockers": 0,
                "package_validation_passed": True,
                "preview_page_coverage": "0/0",
            }), encoding="utf-8")
            errors = module.validate_completion_manifest(manifest, pptx, delivery)
            self.assertTrue(any("visual_inspection" in error for error in errors))
            self.assertTrue(any("渲染页面" in error for error in errors))

    def test_complete_allows_completed_inspection_without_repair_reason(self) -> None:
        """no_repair_needed_reason 为可选：completed + remaining_blockers=0 即可 complete。"""
        module = self.module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            content_qa = root / "content-qa.json"
            visual_report = root / "visual-inspection.json"
            asset_manifest = root / "asset-manifest.json"
            asset_report = root / "asset-report.json"
            content_qa.write_text("{}", encoding="utf-8")
            visual_report.write_text("{}", encoding="utf-8")
            asset_manifest.write_text("{}", encoding="utf-8")
            asset_report.write_text("{}", encoding="utf-8")
            manifest = root / "qa.json"
            manifest.write_text(json.dumps({
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "slide_count": 1,
                "rendered_page_count": 1,
                "scenario_contract_passed": True,
                "visual_inspection": {"completed": True, "remaining_blockers": 0},
                "content_qa_report": str(content_qa),
                "content_qa_report_sha256": hashlib.sha256(content_qa.read_bytes()).hexdigest(),
                "visual_inspection_report": str(visual_report),
                "visual_inspection_report_sha256": hashlib.sha256(visual_report.read_bytes()).hexdigest(),
                "asset_manifest": str(asset_manifest),
                "asset_manifest_sha256": hashlib.sha256(asset_manifest.read_bytes()).hexdigest(),
                "asset_manifest_report": str(asset_report),
                "asset_manifest_report_sha256": hashlib.sha256(asset_report.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            delivery = root / "delivery.json"
            delivery.write_text(json.dumps({
                "ok": True,
                "status": "complete",
                "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                "qa_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "package_blockers": 0,
                "package_validation_passed": True,
                "preview_page_coverage": "1/1",
            }), encoding="utf-8")
            self.assertEqual(
                [],
                module.validate_completion_manifest(manifest, pptx, delivery),
            )

    def _ns(self, action: str, **kwargs: object) -> argparse.Namespace:
        base: dict[str, object] = {
            "action": action,
            "state_file": None,
            "topic": "test",
            "summary_file": None,
            "to": None,
            "qa_manifest": None,
            "pptx": None,
            "delivery_report": None,
            "reason": None,
            "force": False,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

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
            summary.write_text("revised", encoding="utf-8")
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
            summary.write_text("revised", encoding="utf-8")
            module.save_state(
                state,
                {"workflow_version": "1.0", "state": "producing", "topic": "t"},
            )
            with self.assertRaises(SystemExit):
                module.state_command(
                    self._ns("confirm", state_file=state, summary_file=summary)
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
