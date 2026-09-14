"""Unit tests for ppt_pipeline state, idempotence and QA DAG wiring."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("ppt_pipeline", PIPELINE)
pp = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("ppt_pipeline", pp)
_SPEC.loader.exec_module(pp)


def ns(command: str, work_dir: Path, **extra: Any) -> argparse.Namespace:
    base: dict[str, Any] = {"work_dir": work_dir}
    if command == "plan":
        base.update(
            workflow_state=None,
            slide_spec=None,
            validation_report=None,
            art_direction=None,
            visual_generation_report=None,
            research_pack=None,
            research_validation=None,
            evidence_map=None,
            reason="test plan",
            force=False,
        )
    elif command == "build":
        base.update(entry=None, output_name="deck.pptx", generator_args=[])
    elif command == "qa":
        base.update(
            visual_review=None, notes=None, preview=None,
            allow_missing_preview=False, max_items=12,
        )
    elif command == "repair":
        base.update(reason="test repair", force=False)
    base.update(extra)
    return argparse.Namespace(**base)


def ok_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ok": True, "issues": []}), encoding="utf-8")


class FakeRunner:
    def __init__(self, work_dir: Path, *, check_ok: bool = True) -> None:
        self.work_dir = work_dir
        self.check_ok = check_ok
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        joined = " ".join(argv)

        def flag_value(flag: str) -> str:
            return argv[argv.index(flag) + 1] if flag in argv else ""

        if "copy_fit_preflight.py" in joined:
            out = flag_value("--output")
            if out:
                ok_report(Path(out))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "slide_spec_guard.py" in joined and " freeze " in f" {joined} ":
            Path(flag_value("--lock-file")).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "slide_spec_guard.py" in joined and " check " in f" {joined} ":
            return subprocess.CompletedProcess(
                argv, 0 if self.check_ok else 2,
                stdout="", stderr="bad lock" if not self.check_ok else "",
            )
        if "run_with_pptxgenjs.js" in joined:
            Path(flag_value("--output")).write_bytes(b"PK\x03\x04 fake pptx")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        out = flag_value("--output")
        if out:
            report_path = Path(out)
            if report_path.name == "qa-rendered.json" and getattr(self, "render_fails", False):
                report_path.write_text(
                    json.dumps({"ok": False, "issues": [{
                        "severity": "major", "code": "blur", "message": "blurry slide"
                    }]}), encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 2, stdout="", stderr="")
            ok_report(report_path)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name) / "work-01"
        self.work.mkdir()
        self._original_runner = pp._runner
        self.summary = self.work / "production-summary.md"
        self.summary.write_text("approved", encoding="utf-8")
        self.workflow_state = self.work / "workflow-state.json"
        self.confirm_intake()

    def confirm_intake(self) -> None:
        self.workflow_state.write_text(
            json.dumps({
                "workflow_version": "1.0",
                "state": "intake_confirmed",
                "summary_file": str(self.summary),
                "summary_sha256": pp.sha256_file(self.summary),
            }),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        pp._runner = self._original_runner
        self._tmp.cleanup()

    def write_inputs(self) -> dict[str, Path]:
        files = {
            "spec": self.work / "slide-spec.json",
            "lock": self.work / "slide-spec-lock.json",
            "art": self.work / "art-direction.yaml",
            "vgr": self.work / "visual-generation-report.json",
            "spec_report": self.work / "slide-spec-validation.json",
            "visual_review": self.work / "visual-review.json",
            "pptx": self.work / "deck.pptx",
        }
        files["spec"].write_text("{}", encoding="utf-8")
        files["lock"].write_text("{}", encoding="utf-8")
        files["art"].write_text("{}", encoding="utf-8")
        files["vgr"].write_text("{}", encoding="utf-8")
        files["spec_report"].write_text("{}", encoding="utf-8")
        files["visual_review"].write_text("{}", encoding="utf-8")
        files["pptx"].write_bytes(b"PK\x03\x04 fake")
        return files

    def plan(self, files: dict[str, Path], runner: FakeRunner | None = None) -> FakeRunner:
        runner = runner or FakeRunner(self.work)
        pp._runner = runner
        rc = pp.main([
            "plan", "--work-dir", str(self.work),
            "--workflow-state", str(self.workflow_state),
            "--slide-spec", str(files["spec"]),
            "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
            "--visual-generation-report", str(files["vgr"]),
        ])
        self.assertEqual(rc, 0)
        return runner

    def manifest(self) -> dict[str, Any]:
        return json.loads((self.work / pp.MANIFEST_NAME).read_text(encoding="utf-8"))

    def entry(self) -> Path:
        pages = self.work / "pages"
        pages.mkdir(exist_ok=True)
        (pages / "p01-title.js").write_text("export default () => {}", encoding="utf-8")
        entry = self.work / "deck.js"
        entry.write_text("export default () => {}", encoding="utf-8")
        return entry


class StateMachineTests(PipelineTestCase):
    def test_plan_requires_confirmed_intake(self) -> None:
        files = self.write_inputs()
        self.workflow_state.write_text(json.dumps({"state": "intake_pending"}), encoding="utf-8")
        rc = pp.main([
            "plan", "--work-dir", str(self.work), "--workflow-state", str(self.workflow_state),
            "--slide-spec", str(files["spec"]), "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
        ])
        self.assertEqual(rc, 2)

    def test_plan_refuses_changed_summary(self) -> None:
        files = self.write_inputs()
        self.summary.write_text("changed", encoding="utf-8")
        rc = pp.main([
            "plan", "--work-dir", str(self.work), "--workflow-state", str(self.workflow_state),
            "--slide-spec", str(files["spec"]), "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
        ])
        self.assertEqual(rc, 2)

    def test_build_without_manifest_is_refused(self) -> None:
        with self.assertRaises(pp.RefusedError):
            pp.cmd_build(ns("build", self.work, entry=self.work / "deck.js"))

    def test_qa_before_build_is_refused(self) -> None:
        with self.assertRaises(pp.RefusedError):
            pp.cmd_qa(ns("qa", self.work))

    def test_complete_before_qa_is_refused(self) -> None:
        with self.assertRaises(pp.RefusedError):
            pp.cmd_complete(ns("complete", self.work))

    def test_repair_without_blockers_is_refused(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {"ok": True, "blockers": 0, "stages": {}}
        pp.save_manifest(self.work, manifest)
        with self.assertRaises(pp.RefusedError):
            pp.cmd_repair(ns("repair", self.work))


class PlanTests(PipelineTestCase):
    def test_plan_creates_manifest_and_binds_intake(self) -> None:
        files = self.write_inputs()
        runner = self.plan(files)
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "planned")
        self.assertEqual(manifest["manifest_version"], pp.MANIFEST_VERSION)
        self.assertEqual(manifest["workflow"]["summary_sha256"], pp.sha256_file(self.summary))
        self.assertIn("slide_spec", manifest["inputs"])
        self.assertTrue((self.work / "slide-spec-lock.json").is_file())
        self.assertEqual(len([c for c in runner.calls if "freeze" in c]), 1)
        mirrored = json.loads(self.workflow_state.read_text(encoding="utf-8"))
        self.assertEqual(mirrored["state"], "planned")

    def test_replan_without_force_is_refused(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        with self.assertRaises(pp.RefusedError):
            pp.cmd_plan(ns(
                "plan", self.work, workflow_state=self.workflow_state,
                slide_spec=files["spec"], validation_report=files["spec_report"], art_direction=files["art"],
            ))

    def test_force_replan_requires_reconfirmed_intake(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        self.confirm_intake()
        pp._runner = FakeRunner(self.work)
        rc = pp.main([
            "plan", "--work-dir", str(self.work), "--workflow-state", str(self.workflow_state), "--force",
            "--slide-spec", str(files["spec"]), "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
        ])
        self.assertEqual(rc, 0)


class BuildTests(PipelineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def prepared(self) -> None:
        self.plan(self.files)

    def test_build_records_pptx_and_counts(self) -> None:
        self.prepared()
        entry = self.entry()
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "producing")
        self.assertEqual(manifest["build"]["build_count"], 1)
        self.assertTrue(manifest["build"]["generator_fingerprint"])
        self.assertFalse(manifest["build"]["pending_repair"])

    def test_identical_repeat_build_is_refused(self) -> None:
        self.prepared()
        entry = self.entry()
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 2)

    def test_repair_requires_generator_change_before_rebuild(self) -> None:
        self.prepared()
        entry = self.entry()
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)])
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {"ok": False, "blockers": 1, "stages": {}}
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["repair", "--work-dir", str(self.work), "--reason", "fix"]), 0)
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 2)
        entry.write_text("export default () => { /* changed */ }", encoding="utf-8")
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)

    def test_repair_budget_is_hard_limited(self) -> None:
        self.prepared()
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {"ok": False, "blockers": 1, "stages": {}}
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["repair", "--work-dir", str(self.work), "--reason", "again"]), 2)

    def test_build_rechecks_the_freeze(self) -> None:
        self.prepared()
        runner = FakeRunner(self.work, check_ok=False)
        pp._runner = runner
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())]), 2)


class QaDagTests(PipelineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def producing_manifest(self) -> dict[str, Any]:
        self.plan(self.files)
        entry = self.entry()
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)])
        return self.manifest()

    def test_delivery_consumes_this_runs_reports_in_contract_order(self) -> None:
        self.producing_manifest()
        runner = FakeRunner(self.work)
        pp._runner = runner
        rc = pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        self.assertEqual(rc, 0)
        manifest = self.manifest()
        self.assertEqual(list(manifest["qa"]["stages"]), list(pp.QA_ORDER))
        delivery = [c for c in runner.calls if "pptx_delivery_check_v08.py" in " ".join(c)]
        self.assertEqual(len(delivery), 1)
        joined = " ".join(delivery[0])
        self.assertIn("qa-quality.json", joined)
        self.assertIn("qa-package.json", joined)
        self.assertIn("qa-actual-content.json", joined)
        self.assertIn("sha256", manifest["qa"]["stages"]["delivery"])
        self.assertIn("sha256", manifest["qa"]["visual_review"])

    def test_identical_qa_reuses_previous_result(self) -> None:
        self.producing_manifest()
        runner = FakeRunner(self.work)
        pp._runner = runner
        argv = ["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])]
        self.assertEqual(pp.main(argv), 0)
        first_calls = len(runner.calls)
        self.assertEqual(pp.main(argv), 0)
        self.assertEqual(len(runner.calls), first_calls)

    def test_previews_and_visual_review_are_hash_bound(self) -> None:
        self.producing_manifest()
        previews = self.work / "preview-01.png", self.work / "preview-02.png"
        for index, preview in enumerate(previews):
            preview.write_bytes(f"png-{index}".encode())
        pp._runner = FakeRunner(self.work)
        self.assertEqual(pp.main([
            "qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"]),
            "--preview", str(previews[0]), "--preview", str(previews[1]),
        ]), 0)
        qa = self.manifest()["qa"]
        self.assertEqual([Path(p["path"]).name for p in qa["previews"]], ["preview-01.png", "preview-02.png"])
        self.assertTrue(all(p["sha256"] for p in qa["previews"]))

    def test_failing_stage_stops_the_dag(self) -> None:
        self.producing_manifest()
        runner = FakeRunner(self.work)
        runner.render_fails = True
        pp._runner = runner
        rc = pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        self.assertEqual(rc, 2)
        executed = " | ".join(" ".join(c) for c in runner.calls)
        self.assertIn("qa-rendered.json", executed)
        self.assertNotIn("qa-delivery.json", executed)

    def test_incomplete_plan_inputs_skip_delivery_and_block_completion(self) -> None:
        self.producing_manifest()
        manifest = self.manifest()
        del manifest["inputs"]["visual_generation_report"]
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main([
            "qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])
        ]), 0)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)


class CompleteTests(PipelineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def state_qa(self, *, ok: bool, delivery_checked: bool) -> None:
        self.plan(self.files)
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {
            "ok": ok, "blockers": 0 if ok else 2,
            "stages": {"delivery": {"checked": delivery_checked, "ok": ok}} if delivery_checked else {},
        }
        pp.save_manifest(self.work, manifest)

    def test_complete_closes_deck_and_mirrors_workflow(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)
        self.assertEqual(self.manifest()["state"], "complete")
        mirrored = json.loads(self.workflow_state.read_text(encoding="utf-8"))
        self.assertEqual(mirrored["state"], "complete")

    def test_complete_with_blockers_is_refused(self) -> None:
        self.state_qa(ok=False, delivery_checked=True)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)

    def test_complete_without_delivery_is_refused(self) -> None:
        self.state_qa(ok=True, delivery_checked=False)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)


class StatusTests(PipelineTestCase):
    def test_status_is_one_line(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.cmd_status(ns("status", self.work))
        self.assertEqual(rc, 0)
        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("planned", lines[0])

    def test_status_without_manifest_fails(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.cmd_status(ns("status", self.work))
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
