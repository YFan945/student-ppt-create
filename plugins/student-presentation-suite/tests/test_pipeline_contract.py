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

    def test_qa_gate_registry_matches_the_pipeline(self) -> None:
        """Batch 5: the contract's qa_gates registry is the machine truth for the
        QA DAG — its order, scripts, report keys and dependency edges must match
        the runtime, and every gate script must exist."""
        registry = self.contract["qa_gates"]
        self.assertEqual(list(registry), self.contract["qa_order"])
        script_roots = (ROOT / "skills" / "sp-deck" / "scripts", ROOT / "scripts")
        for name, entry in registry.items():
            with self.subTest(gate=name):
                self.assertIn("script", entry)
                script = entry["script"].split()[0]
                self.assertTrue(any((root / script).is_file() for root in script_roots), script)
                self.assertIn(entry["artifact"], (name, name.replace("_", "-")))
                for dependency in entry["dependencies"]:
                    self.assertIn(dependency, registry)
                self.assertIn(entry["phase"], {"post_build", "post_critic", "final"})
        # pre-build (deterministic) subset: exactly what the build's pre-QA runs
        self.assertEqual(
            ["rendered", "actual_content", "quality"],
            [name for name, entry in registry.items() if entry["pre_build"]],
        )
        # the quality gate is the only pre-build gate that has a critic half
        self.assertTrue(registry["quality"]["critic"])
        self.assertFalse(registry["rendered"]["critic"])

    def test_pre_qa_and_qa_stages_share_one_builder(self) -> None:
        """One gate argv builder: QA and pre-QA must construct the same gate the
        same way, differing only in report prefix and the critic's visual report."""
        pp = self.pipeline
        manifest = {
            "inputs": {
                "slide_spec": {"path": "/tmp/spec.json"},
                "spec_lock": {"path": "/tmp/lock.json"},
            },
            "build": {"pptx": {"path": "/tmp/deck.pptx"}},
        }
        stages = pp.pre_qa_stages(manifest, self.tmp_dir())
        self.assertEqual(
            ["rendered", "actual-content", "quality-deterministic"], [s.name for s in stages]
        )
        self.assertEqual(["rendered", "actual_content", "quality"], [s.artifact for s in stages])
        for stage in stages:
            # the quality stage keeps report name pre-qa-quality.json even though
            # its deterministic variant is named quality-deterministic
            report_name = stage.name.replace("-deterministic", "")
            self.assertTrue(
                str(stage.report).replace(chr(92), "/").endswith(f"pre-qa-{report_name}.json")
            )
        # the deterministic quality stage must NOT receive a visual report
        self.assertNotIn("--visual-report", stages[-1].argv)
        full = pp.build_qa_stages(
            {**manifest},
            self.tmp_dir(),
            visual_review=None,
        )
        # without a critic review, full QA degrades to the same deterministic gates
        self.assertEqual(["package", "rendered", "actual-content"], [s.name for s in full])

    def tmp_dir(self) -> Path:
        import tempfile

        if not hasattr(self, "_stage_dir"):
            self._stage_dir = tempfile.TemporaryDirectory()
            self.addCleanup(self._stage_dir.cleanup)
        return Path(self._stage_dir.name)

    def test_registry_scripts_match_what_the_builder_actually_runs(self) -> None:
        """Batch 5.1: the qa_gates registry must describe what _gate_stage really
        executes — every registry script token has to appear in the constructed
        stage argv, or the registry is documentation, not machine truth."""
        pp = self.pipeline
        registry = self.contract["qa_gates"]
        gate_inputs = {
            "pptx": "/tmp/deck.pptx",
            "slide_spec": "/tmp/spec.json",
            "spec_lock": "/tmp/lock.json",
            "art_direction": "/tmp/art.yaml",
            "visual_generation_report": "/tmp/vgr.json",
            "slide_spec_report": "/tmp/report.json",
        }
        for name, entry in registry.items():
            with self.subTest(gate=name):
                stage = pp._gate_stage(name, self.tmp_dir(), "qa", gate_inputs)
                argv_joined = " ".join(stage.argv).replace(chr(92), "/")
                for token in entry["script"].split():
                    self.assertIn(token, argv_joined)
                # the registered artifact is what collect() keys the stage on
                self.assertEqual(entry["artifact"], stage.artifact)
        # the pre-build quality stage runs the SAME script without the critic report
        deterministic = pp._gate_stage("quality", self.tmp_dir(), "pre-qa", gate_inputs)
        self.assertNotIn("--visual-report", deterministic.argv)
        self.assertIn("pptx_quality_gate_v071.py", " ".join(deterministic.argv))

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
        self.assertIn("advance --brief-json", self.skill)
        self.assertIn("独立视觉", self.skill)

    def test_docs_do_not_teach_manual_production_transitions(self) -> None:
        """Agents follow README/intake; those must not revive workflow_guard production hops."""
        repo = ROOT.parents[1]
        paths = (
            ROOT / "README.md",
            ROOT / "README-zh.md",
            ROOT / "AGENTS.md",
            ROOT / "references" / "presentation-intake.md",
            ROOT / "references" / "shared-standards.md",
            ROOT / "skills" / "sp-deck" / "references" / "pptx-qa.md",
            ROOT / "scripts" / "slide_spec_to_pptx_brief.py",
            repo / "README.md",
            repo / "README-zh.md",
        )
        forbidden = ("transition --to producing", "transition --to complete")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, path)

    def test_repair_budget_is_bounded(self) -> None:
        value = int(self.contract["max_repairs"])
        self.assertGreaterEqual(value, 1)
        self.assertLessEqual(value, 3)


if __name__ == "__main__":
    unittest.main()
