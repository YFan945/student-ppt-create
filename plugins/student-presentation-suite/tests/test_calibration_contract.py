from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CalibrationContractTests(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_machine_contract_requires_calibration_before_full_generation(self) -> None:
        contract = json.loads(self.read("references/pipeline-contract.json"))
        repeat = contract["repeat_policy"]
        self.assertTrue(repeat["page_generation_requires_isolated_builder"])
        self.assertTrue(repeat["high_leverage_calibration_before_full_generation"])
        build = "\n".join(contract["stage_contracts"]["build"])
        calibration_pos = build.index("mode=calibration")
        preview_pos = build.index("calibration_preview.py")
        initial_pos = build.index("mode=initial")
        self.assertLess(calibration_pos, preview_pos)
        self.assertLess(preview_pos, initial_pos)
        # 0.26.0: the independent review moved to a single production-boundary pass;
        # calibration is gated by deterministic evidence + palette + style summary.
        self.assertFalse(repeat["calibration_requires_independent_review"])
        self.assertIn("the independent review happens ONCE at the production boundary", build)
        self.assertNotIn("calibration-visual-review.json", build)
        self.assertIn("does not mutate production manifest/build state", build)

    def test_skill_requires_visual_check_before_remaining_pages(self) -> None:
        skill = self.read("skills/sp-deck/SKILL.md")
        calibration_pos = skill.index("**Calibration Build**")
        preview_pos = skill.index("**Calibration Preview（确定性门，无 critic）**")
        full_pos = skill.index("**Full Isolated Page Build**")
        production_pos = skill.index("**Exploration Gates + Production Build**")
        self.assertLess(calibration_pos, preview_pos)
        self.assertLess(preview_pos, full_pos)
        self.assertLess(full_pos, production_pos)
        self.assertIn("不触碰生产 manifest/state", skill)
        self.assertIn("剩余 scaffold 页面", skill)

    def test_calibration_is_deterministic_and_review_is_production_only(self) -> None:
        """0.26.0: the 2026-09-18 lesson (main session accepted its own calibration PNGs;
        the independent critic then rejected the repeated treatment on all 13 built pages,
        76.4M tokens = 58.8% of that session) is now carried by the production-boundary
        review — calibration itself is gated deterministically (evidence + palette +
        style summary), and an old review file is advisory only."""
        skill = self.read("skills/sp-deck/SKILL.md")
        self.assertIn("校准不再有 critic 轮", skill)
        self.assertIn("review_advisory", skill)
        self.assertIn("student-presentation-suite:visual-critic", skill)
        self.assertIn("失败归属判定", skill)
        templates = self.read("references/spawn-templates.md")
        self.assertIn("critic（生产评审——0.26.0 起唯一一次独立评审）", templates)
        self.assertIn("主会话永远不代替 critic 看图", templates)
        self.assertNotIn("calibration 评审，同一 agent，不同范围", templates)

    def test_builder_has_distinct_calibration_and_initial_modes(self) -> None:
        builder = self.read("agents/presentation-builder.md")
        self.assertIn("`calibration`, `initial`, or `repair`", builder)
        self.assertIn("leave every non-calibration page as a scaffold stub", builder)
        self.assertIn("preserve already calibrated page modules", builder)
        # Batch 4.2: the established visual system travels as the calibration_style
        # contract, and the calibration builder records it in style-summary.json.
        self.assertIn("Calibration establishes the visual thesis", builder)
        self.assertIn("calibration_style", builder)
        self.assertIn("calibration/style-summary.json", builder)
        self.assertIn("never read calibration page modules to infer style", builder)

    def test_preview_helper_is_not_a_production_pipeline_transition(self) -> None:
        helper = self.read("skills/sp-deck/scripts/calibration_preview.py")
        self.assertIn("outside the production manifest/state machine", helper)
        self.assertIn("calibration-manifest.json", helper)
        self.assertNotIn("save_manifest(", helper)
        self.assertNotIn("mirror_workflow_state(", helper)


if __name__ == "__main__":
    unittest.main()
