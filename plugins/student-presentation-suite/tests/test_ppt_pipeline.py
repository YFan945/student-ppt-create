"""Unit tests for ppt_pipeline state, idempotence and QA DAG wiring."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("ppt_pipeline", PIPELINE)
pp = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("ppt_pipeline", pp)
_SPEC.loader.exec_module(pp)

_SCAFFOLD_SPEC = importlib.util.spec_from_file_location(
    "generator_scaffold", ROOT / "skills" / "sp-deck" / "scripts" / "generator_scaffold.py"
)
assert _SCAFFOLD_SPEC is not None and _SCAFFOLD_SPEC.loader is not None
scaffold = importlib.util.module_from_spec(_SCAFFOLD_SPEC)
sys.modules.setdefault("generator_scaffold", scaffold)
_SCAFFOLD_SPEC.loader.exec_module(scaffold)


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

        if "art_direction_check.py" in joined:
            out = flag_value("--output")
            if out:
                Path(out).write_text(
                    json.dumps({"ok": True, "blocker_count": 0, "issues": []}),
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
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
        if "research_pack_to_evidence.py" in joined:
            out = flag_value("--output")
            if out:
                Path(out).write_text("{}", encoding="utf-8")
            compiled = flag_value("--compiled-slide-spec")
            if compiled:
                source = flag_value("--slide-spec")
                Path(compiled).write_text(
                    Path(source).read_text(encoding="utf-8") if source else "{}",
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        out = flag_value("--output")
        if out:
            report_path = Path(out)
            failures = getattr(self, "report_failures", None) or {}
            if report_path.name in failures:
                report_path.write_text(
                    json.dumps({"ok": False, "issues": failures[report_path.name]}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 2, stdout="", stderr="")
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
        self.work = Path(self._tmp.name) / "outputs" / ".pptx-work" / "work-01"
        self.work.mkdir(parents=True)
        self.env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self._tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self._original_runner = pp._runner
        self.summary = self.work / "production-summary.md"
        self.summary.write_text("approved", encoding="utf-8")
        self.workflow_state = self.work / "workflow-state.json"
        self.confirm_intake()

    def confirm_intake(self) -> None:
        self.workflow_state.write_text(
            json.dumps({
                "workflow_version": "1.0",
                "work_id": self.work.name,
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
        files["spec"].write_text(
            json.dumps(
                {
                    "meta": {"slide_count": 1, "topic": "test"},
                    "slides": [
                        {"id": 1, "title": "Title", "kind": "cover", "role": "opening"},
                    ],
                }
            ),
            encoding="utf-8",
        )
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

    def render_evidence(self, files):
        from PIL import Image
        manifest = self.manifest()
        page = self.work / "render" / "slide-1.png"
        page.parent.mkdir(exist_ok=True)
        preview = Image.new("RGB", (640, 360), "white")
        preview.paste("navy", (0, 0, 640, 80))
        preview.save(page)
        contact = self.work / "contact-sheet.png"
        pp.make_contact_sheet([page], contact)
        manifest["render"] = {"pptx_sha256": pp.sha256_file(files["pptx"]), "pages": [pp.bind(page)], "contact_sheet": pp.bind(contact), "page_count": 1}
        pp.save_manifest(self.work, manifest)
        review = {"pptx_sha256": pp.sha256_file(files["pptx"]), "contact_sheet_sha256": pp.sha256_file(contact), "page_sha256": {"1": pp.sha256_file(page)}}
        files["visual_review"].write_text(json.dumps(review), encoding="utf-8")
        receipt = {"agent": "student-presentation-suite:visual-critic", "agent_id": "test-child", "spawn_verified": True, "work_id": self.work.name, "artifact": pp.bind(files["visual_review"]), "reads": {str(p): pp.sha256_file(p) for p in [page, contact]}}
        (self.work / "critic-execution.json").write_text(json.dumps(receipt), encoding="utf-8")
        (self.work / "speaker-notes.md").write_text("# Slide 1\nSpeaker notes for the test.", encoding="utf-8")

    def entry(self) -> Path:
        """Return a buildable generator.

        `plan` scaffolds pages that carry SCAFFOLD_MARKER and build refuses
        those, so this fixture strips the marker — the way an implemented page
        would look. `unimplemented_entry()` keeps the stubs for gate tests.
        """
        entry = self.work / "deck.js"
        pages = self.work / "pages"
        if entry.is_file() and any(pages.glob("p*.js")):
            self.implement_scaffolded_pages()
            return entry
        pages.mkdir(exist_ok=True)
        (pages / "p01-cover.js").write_text(
            "module.exports = function (ctx) {};\n", encoding="utf-8"
        )
        entry.write_text("require('./pages/p01-cover.js');\n", encoding="utf-8")
        return entry

    def implement_scaffolded_pages(self) -> None:
        for page in (self.work / "pages").glob("p*.js"):
            text = page.read_text(encoding="utf-8")
            if scaffold.SCAFFOLD_MARKER in text:
                page.write_text(text.replace(scaffold.SCAFFOLD_MARKER, "implemented"), encoding="utf-8")


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
        pp.mirror_workflow_state(manifest, manifest["state"])
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
        # The Art Direction gate needs the work dir to resolve this session's image
        # capability; dropping the flag silently disables asset_plan feasibility checking.
        art_call = next(c for c in runner.calls if "art_direction_check.py" in " ".join(c))
        self.assertIn("--work-dir", art_call)
        self.assertEqual(str(self.work), art_call[art_call.index("--work-dir") + 1])
        mirrored = json.loads(self.workflow_state.read_text(encoding="utf-8"))
        self.assertEqual(mirrored["state"], "planned")
        self.assertTrue((self.work / "pages" / "p01-cover.js").is_file())
        self.assertTrue((self.work / "deck.js").is_file())
        self.assertTrue((self.work / "stage-planned-summary.md").is_file())
        self.assertTrue((self.work / "composition").is_dir())
        stub = (self.work / "pages" / "p01-cover.js").read_text(encoding="utf-8")
        self.assertIn("const COPY", stub)

    def test_plan_accepts_pack_alias_and_ignores_research_execution_flag(self) -> None:
        args = pp.parse_args([
            "plan", "--work-dir", str(self.work),
            "--slide-spec", "spec.yaml",
            "--validation-report", "report.json",
            "--art-direction", "ad.yaml",
            "--pack", "research-pack.json",
            "--research-execution", "research-execution.json",
        ])
        self.assertEqual(args.research_pack, Path("research-pack.json"))

    def test_research_plan_compiles_evidence_map_without_agent_flags(self) -> None:
        files = self.write_inputs()
        spec = json.loads(files["spec"].read_text(encoding="utf-8"))
        spec["research_scope"] = "A"
        files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        pack = self.work / "research-pack.json"
        pack.write_text("{}", encoding="utf-8")
        (self.work / "research-pack-validation.json").write_text("{}", encoding="utf-8")
        (self.work / "research-execution.json").write_text(
            json.dumps({
                "agent": "student-presentation-suite:presentation-researcher",
                "agent_id": "child",
                "spawn_verified": True,
                "work_id": self.work.name,
                "artifact": pp.bind(pack),
            }),
            encoding="utf-8",
        )
        runner = self.plan(files)
        self.assertTrue(any("research_pack_to_evidence.py" in " ".join(call) for call in runner.calls))
        self.assertTrue((self.work / "evidence-map.json").is_file())
        self.assertIn("evidence_map", self.manifest()["inputs"])

    def test_research_plan_without_pack_is_refused(self) -> None:
        files = self.write_inputs()
        spec = json.loads(files["spec"].read_text(encoding="utf-8"))
        spec["research_scope"] = "A"
        files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaises(pp.RefusedError) as raised:
            pp.cmd_plan(ns(
                "plan", self.work, workflow_state=self.workflow_state,
                slide_spec=files["spec"], validation_report=files["spec_report"],
                art_direction=files["art"],
            ))
        self.assertIn("evidence-map", str(raised.exception).lower())

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
        pptx = manifest["build"]["pptx"]
        self.assertTrue(Path(pptx["path"]).is_file())
        generator_paths = [Path(f["path"]).name for f in manifest["build"]["generator_files"]]
        self.assertIn("deck.js", generator_paths)
        self.assertIn("p01-cover.js", generator_paths)

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
        pp.mirror_workflow_state(manifest, manifest["state"])
        self.assertEqual(pp.main(["repair", "--work-dir", str(self.work), "--reason", "fix"]), 0)
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 2)
        page = next((self.work / "pages").glob("p*.js"))
        page.write_text(page.read_text(encoding="utf-8") + "\n/* changed */\n", encoding="utf-8")
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)

    def test_repair_budget_is_hard_limited(self) -> None:
        self.prepared()
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {"ok": False, "blockers": 1, "stages": {}}
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        pp.save_manifest(self.work, manifest)
        pp.mirror_workflow_state(manifest, manifest["state"])
        self.assertEqual(pp.main(["repair", "--work-dir", str(self.work), "--reason", "again"]), 2)

    def qa_with_blockers(self, blockers: int = 1) -> None:
        manifest = self.manifest()
        manifest["state"] = "qa"
        manifest["qa"] = {"ok": False, "blockers": blockers, "stages": {}}
        pp.save_manifest(self.work, manifest)
        pp.mirror_workflow_state(manifest, manifest["state"])

    def test_repair_extend_grants_rounds_and_records_the_justification(self) -> None:
        """A run out of rounds must be able to continue without editing the installed
        plugin's pipeline-contract.json — the 2026-09-17 live run raised the budget that
        way, which does not survive a reinstall and is not auditable."""
        self.prepared()
        self.qa_with_blockers()
        manifest = self.manifest()
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        pp.save_manifest(self.work, manifest)

        self.assertEqual(
            pp.main(["repair", "--work-dir", str(self.work), "--reason", "retry"]),
            2,
            "base budget is exhausted",
        )
        self.assertEqual(
            pp.main(
                [
                    "repair", "--work-dir", str(self.work), "--reason", "fix what round 3 broke",
                    "--extend", "2",
                    "--extend-reason",
                    "round 3 resolved 4 blockers and introduced 1 (chart axis); that one is bounded",
                ]
            ),
            0,
        )
        entry = self.manifest()["build"]["repair_budget_grants"][0]
        self.assertEqual(2, entry["rounds"])
        self.assertIn("blocker", entry["reason"])
        budget = pp.repair_budget(self.manifest())
        self.assertEqual(pp.MAX_REPAIRS + 2, budget["effective"])
        self.assertEqual(pp.MAX_REPAIRS_HARD_CAP, budget["hard_cap"])

    def test_repair_extend_requires_a_blocker_diff_not_just_a_bigger_budget(self) -> None:
        self.prepared()
        self.qa_with_blockers()
        manifest = self.manifest()
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        pp.save_manifest(self.work, manifest)
        self.assertEqual(
            pp.main(["repair", "--work-dir", str(self.work), "--reason", "again", "--extend", "3"]),
            2,
            "--extend without --extend-reason is refused",
        )
        self.assertEqual(
            pp.main(
                [
                    "repair", "--work-dir", str(self.work), "--reason", "again",
                    "--extend", "3", "--extend-reason", "more",
                ]
            ),
            2,
            "a one-word justification is not a blocker diff",
        )

    def test_repair_extend_cannot_exceed_the_hard_cap(self) -> None:
        self.prepared()
        self.qa_with_blockers()
        manifest = self.manifest()
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        manifest["build"]["repair_budget_grants"] = [
            {"rounds": pp.MAX_REPAIRS_HARD_CAP, "reason": "earlier grants"}
        ]
        pp.save_manifest(self.work, manifest)
        self.assertEqual(
            pp.main(
                [
                    "repair", "--work-dir", str(self.work), "--reason", "again",
                    "--extend", "1", "--extend-reason", "one more bounded round for the axis fix",
                ]
            ),
            2,
        )

    def test_next_reports_the_effective_budget(self) -> None:
        self.prepared()
        self.qa_with_blockers()
        manifest = self.manifest()
        manifest["build"]["repair_count"] = pp.MAX_REPAIRS
        manifest["build"]["repair_budget_grants"] = [
            {"rounds": 2, "reason": "round 3 net-resolved 4 blockers"}
        ]
        pp.save_manifest(self.work, manifest)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(0, code)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(pp.MAX_REPAIRS, payload["repair_budget"]["base"])
        self.assertEqual(2, payload["repair_budget"]["granted"])
        self.assertEqual(pp.MAX_REPAIRS + 2, payload["repair_budget"]["effective"])

    def test_build_without_pages_is_refused(self) -> None:
        self.prepared()
        entry = self.work / "deck.js"
        for leftover in (self.work / "pages").glob("*.js"):
            leftover.unlink()
        rc = pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)])
        self.assertEqual(rc, 2)

    def test_build_refuses_pages_that_are_still_scaffold_stubs(self) -> None:
        """A stub-only deck must fail at build, not after render and visual QA."""
        self.prepared()
        entry = self.work / "deck.js"
        stub = next((self.work / "pages").glob("p*.js"))
        self.assertIn(scaffold.SCAFFOLD_MARKER, stub.read_text(encoding="utf-8"))
        self.assertEqual(
            pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 2
        )
        self.implement_scaffolded_pages()
        self.assertEqual(
            pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0
        )

    def test_deck_js_may_keep_the_scaffold_marker(self) -> None:
        """deck.js is assembly-only; the marker gate applies to pages/ only."""
        self.prepared()
        deck = (self.work / "deck.js").read_text(encoding="utf-8")
        self.assertIn(scaffold.SCAFFOLD_MARKER, deck)
        self.implement_scaffolded_pages()
        self.assertEqual(
            pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.work / "deck.js")]), 0
        )

    def next_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_next_after_plan_dispatches_to_calibration_builder(self) -> None:
        """Fresh planned create-mode work must spawn the builder, not edit pages directly."""
        self.plan(self.files)
        payload = self.next_payload()
        self.assertEqual("planned", payload["state"])
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertNotIn("build", payload["next_command"])
        self.assertIn("mode=calibration", payload["notes"])
        # planned create/rebuild keeps the build stage contract (calibration flow)
        self.assertEqual("build", payload["contract"]["stage"])

    def test_next_with_calibration_manifest_but_no_render_points_at_preview(self) -> None:
        self.plan(self.files)
        calibration = self.work / "calibration"
        calibration.mkdir()
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 6, 7]}), encoding="utf-8"
        )
        payload = self.next_payload()
        self.assertIn("calibration_preview.py", payload["next_command"])
        self.assertIn("--slides 1 6 7", payload["next_command"])

    def test_next_with_calibration_render_points_at_review_not_build(self) -> None:
        """Interrupted calibration-fix rounds resume via review, never a raw full build."""
        self.plan(self.files)
        calibration = self.work / "calibration"
        render = calibration / "render"
        render.mkdir(parents=True)
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 6, 7]}), encoding="utf-8"
        )
        (render / "calibration-1.png").write_bytes(b"png")
        payload = self.next_payload()
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertNotIn("build", payload["next_command"])
        self.assertIn("calibration preview is on disk", payload["notes"])
        self.assertEqual("build", payload["contract"]["stage"])

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
        self.render_evidence(self.files)
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

    def test_artifact_gate_failure_stops_the_dag(self) -> None:
        """`rendered` is an artifact-availability gate: without render evidence the later
        gates have nothing valid to read, so the DAG stops there."""
        self.producing_manifest()
        runner = FakeRunner(self.work)
        runner.render_fails = True
        pp._runner = runner
        rc = pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        self.assertEqual(rc, 2)
        executed = " | ".join(" ".join(c) for c in runner.calls)
        self.assertIn("qa-rendered.json", executed)
        self.assertNotIn("qa-delivery.json", executed)

    def test_content_gate_failure_still_runs_every_later_gate(self) -> None:
        """2026-09-17 live: fail-fast let each repair round see only one gate's problems, so
        6 rounds were spent discovering one gate per round (~199M tokens, 60% of the session).
        Every content gate must run on the same build and report together."""
        self.producing_manifest()
        runner = FakeRunner(self.work)
        runner.report_failures = {
            "qa-actual-content.json": [
                {"severity": "major", "code": "missing_key_claim", "message": "slide 3 claim is not on the page"},
                {"severity": "major", "code": "planned_numbers_missing", "message": "85% is missing", "slide": 3},
            ],
            "qa-quality.json": [
                {"severity": "major", "code": "speaker_notes_missing", "message": "slide 4 has no notes in the notes pane"},
            ],
            "qa-delivery.json": [
                {"severity": "major", "code": "delivery_incomplete", "message": "upstream gates failed"},
            ],
        }
        pp._runner = runner
        rc = pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        self.assertEqual(rc, 2)

        executed = " | ".join(" ".join(c) for c in runner.calls)
        for report in (
            "qa-package.json", "qa-rendered.json", "qa-actual-content.json",
            "qa-quality.json", "qa-delivery.json",
        ):
            self.assertIn(report, executed)

        report = json.loads((self.work / "pipeline-qa.json").read_text(encoding="utf-8"))
        self.assertEqual(["actual_content", "quality", "delivery"], report["failed_stages"])
        self.assertEqual(
            {
                "actual_content": ["missing_key_claim", "planned_numbers_missing"],
                "quality": ["speaker_notes_missing"],
            },
            report["blockers_by_gate"],
        )
        # delivery only summarises its upstream reports; its failure is derived, not a blocker
        # of its own, and must not be handed to the builder as a separate thing to fix.
        self.assertIn("delivery_incomplete", report["derived_problems"])
        self.assertEqual(3, report["counts"]["blockers"])

    def test_incomplete_plan_inputs_skip_delivery_and_block_completion(self) -> None:
        self.producing_manifest()
        manifest = self.manifest()
        del manifest["inputs"]["visual_generation_report"]
        self.files["vgr"].unlink()
        pp.save_manifest(self.work, manifest)
        pp.mirror_workflow_state(manifest, manifest["state"])
        self.assertEqual(pp.main([
            "qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])
        ]), 2)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)


class GateRegressionTests(PipelineTestCase):
    """A gate that passed and now fails means the last change broke it.

    2026-09-17 live: repair round 6 broke `actual_content`, which had passed since build 3.
    Nothing compared gate status across rounds, so it showed up only as another pile of
    blockers — after the budget was gone, on a round that had effectively undone its own
    predecessor.
    """

    def test_a_gate_that_used_to_pass_and_now_fails_is_named(self) -> None:
        (self.work / "gate-history.json").write_text(
            json.dumps({"actual_content": {"ok": True, "round": 3}, "rendered": {"ok": True, "round": 3}}),
            encoding="utf-8",
        )
        problems, history = pp.gate_regressions(
            self.work,
            {"actual_content": {"ok": False}, "rendered": {"ok": True}},
        )
        self.assertEqual(["gate_regression"], [item["code"] for item in problems])
        self.assertIn("actual_content", problems[0]["message"])
        self.assertEqual(4, history["actual_content"]["round"])
        self.assertFalse(history["actual_content"]["ok"])

    def test_gates_that_did_not_run_keep_their_record(self) -> None:
        """A hard stop must not erase the record of a gate that had been passing."""
        (self.work / "gate-history.json").write_text(
            json.dumps({"delivery": {"ok": True, "round": 2}}), encoding="utf-8"
        )
        _, history = pp.gate_regressions(self.work, {"package": {"ok": True}})
        self.assertEqual({"ok": True, "round": 2}, history["delivery"])

    def test_a_first_run_is_not_a_regression(self) -> None:
        problems, history = pp.gate_regressions(self.work, {"quality": {"ok": False}})
        self.assertEqual([], problems)
        self.assertEqual(1, history["quality"]["round"])


class RepairConvergenceTests(PipelineTestCase):
    """`next` publishes the round-over-round blocker trend so "keep going or stop" is a
    reading rather than another question to the user (2026-09-17: the budget ran out with 23
    majors left, the user was asked twice, and one granted round only undid its predecessor)."""

    def write_history(self, rounds: list[dict]) -> None:
        (self.work / "gate-history.json").write_text(
            json.dumps({"_rounds": rounds}), encoding="utf-8"
        )

    def test_progress_is_reported_with_the_numbers(self) -> None:
        self.write_history([
            {"round": 1, "blockers": 23, "failed": ["quality"]},
            {"round": 2, "blockers": 9, "failed": ["quality"]},
        ])
        result = pp.repair_convergence(self.work)
        self.assertEqual("improving", result["trend"])
        self.assertEqual(23, result["previous_blockers"])
        self.assertEqual(9, result["current_blockers"])

    def test_a_flat_round_says_change_approach(self) -> None:
        self.write_history([
            {"round": 3, "blockers": 9, "failed": ["quality"]},
            {"round": 4, "blockers": 9, "failed": ["quality"]},
        ])
        result = pp.repair_convergence(self.work)
        self.assertEqual("flat", result["trend"])
        self.assertIn("no blockers net", result["advice"])

    def test_a_round_that_added_blockers_says_recover_first(self) -> None:
        """2026-09-17: round 6 broke `actual_content`, which had been passing since build 3."""
        self.write_history([
            {"round": 5, "blockers": 4, "failed": []},
            {"round": 6, "blockers": 7, "failed": ["actual_content"]},
        ])
        result = pp.repair_convergence(self.work)
        self.assertEqual("worse", result["trend"])
        self.assertIn("ADDED", result["advice"])

    def test_without_two_rounds_there_is_nothing_to_compare(self) -> None:
        self.assertIsNone(pp.repair_convergence(self.work))
        self.write_history([{"round": 1, "blockers": 5, "failed": []}])
        self.assertIsNone(pp.repair_convergence(self.work))


class CompleteTests(PipelineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def state_qa(self, *, ok: bool, delivery_checked: bool) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files)
        pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        manifest = self.manifest()
        manifest["qa"]["ok"] = ok
        manifest["qa"]["blockers"] = 0 if ok else 2
        if not delivery_checked:
            manifest["qa"]["stages"].pop("delivery", None)
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
