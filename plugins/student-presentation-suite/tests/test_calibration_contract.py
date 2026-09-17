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
        self.assertIn("2-3 preview PNGs", build)
        self.assertIn("does not mutate production manifest/build state", build)

    def test_skill_requires_visual_check_before_remaining_pages(self) -> None:
        skill = self.read("skills/sp-deck/SKILL.md")
        calibration_pos = skill.index("**Calibration Build**")
        preview_pos = skill.index("**Calibration Preview**")
        full_pos = skill.index("**Full Isolated Page Build**")
        production_pos = skill.index("**Exploration Gates + Production Build**")
        self.assertLess(calibration_pos, preview_pos)
        self.assertLess(preview_pos, full_pos)
        self.assertLess(full_pos, production_pos)
        self.assertIn("同一轮并行 Read 这 2–3 张 PNG", skill)
        self.assertIn("不触碰生产 manifest/state", skill)
        self.assertIn("剩余 scaffold 页面", skill)

    def test_builder_has_distinct_calibration_and_initial_modes(self) -> None:
        builder = self.read("agents/presentation-builder.md")
        self.assertIn("`calibration`, `initial`, or `repair`", builder)
        self.assertIn("leave every non-calibration page as a scaffold stub", builder)
        self.assertIn("preserve already calibrated page modules", builder)
        self.assertIn("Calibration pages are the visual thesis", builder)

    def test_preview_helper_is_not_a_production_pipeline_transition(self) -> None:
        helper = self.read("skills/sp-deck/scripts/calibration_preview.py")
        self.assertIn("outside the production manifest/state machine", helper)
        self.assertIn("calibration-manifest.json", helper)
        self.assertNotIn("save_manifest(", helper)
        self.assertNotIn("mirror_workflow_state(", helper)


if __name__ == "__main__":
    unittest.main()
