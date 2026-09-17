"""Semantic contract tests for the production pipeline.

CLI-doc tests catch invented flags. These tests catch the more expensive class of
semantic drift: QA order, repair budget, manifest version and the rule that the
pipeline—not prose or workflow_guard transitions—owns production execution.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "references" / "pipeline-contract.json"
PIPELINE_PATH = ROOT / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"
SKILL_PATH = ROOT / "skills" / "sp-deck" / "SKILL.md"


def load_pipeline():
    spec = importlib.util.spec_from_file_location("pipeline_contract_test_module", PIPELINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PipelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.pipeline = load_pipeline()
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")

    def test_runtime_constants_are_loaded_from_contract(self) -> None:
        self.assertEqual(str(self.contract["manifest_version"]), self.pipeline.MANIFEST_VERSION)
        self.assertEqual(int(self.contract["max_repairs"]), self.pipeline.MAX_REPAIRS)
        self.assertEqual(tuple(self.contract["qa_order"]), self.pipeline.QA_ORDER)

    def test_contract_has_one_canonical_qa_order(self) -> None:
        self.assertEqual(
            ["package", "rendered", "actual_content", "quality", "delivery"],
            self.contract["qa_order"],
        )
        self.assertEqual(len(self.contract["qa_order"]), len(set(self.contract["qa_order"])))

    def test_repeat_policy_is_fail_closed(self) -> None:
        policy = self.contract["repeat_policy"]
        self.assertIs(policy["build_requires_changed_generator_after_repair"], True)
        self.assertIs(policy["qa_reuses_identical_inputs"], True)
        self.assertIs(policy["render_reuses_identical_pptx"], True)

    def test_stale_evidence_and_scaffold_pages_are_refused(self) -> None:
        """Render evidence must belong to the current PPTX; stubs must not build."""
        policy = self.contract["repeat_policy"]
        self.assertIs(policy["build_invalidates_render_evidence"], True)
        self.assertIs(policy["render_evidence_must_match_current_pptx"], True)
        self.assertIs(policy["no_scaffold_pages_at_build"], True)
        self.assertIs(policy["plan_compiles_evidence_map"], True)

    def test_skill_delegates_execution_semantics_to_contract(self) -> None:
        self.assertIn("pipeline-contract.json", self.skill)
        self.assertIn("build-manifest.json", self.skill)
        self.assertIn("不得再手工调用 `workflow_guard.py transition`", self.skill)
        self.assertIn("ppt_pipeline.py render", self.skill)
        self.assertIn("contact-sheet.png", self.skill)

    def test_repair_budget_is_bounded(self) -> None:
        value = int(self.contract["max_repairs"])
        self.assertGreaterEqual(value, 1)
        self.assertLessEqual(value, 3)


if __name__ == "__main__":
    unittest.main()
