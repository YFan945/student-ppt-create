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
import zipfile
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


def minimal_pptx_zip_bytes(slides: int = 1) -> bytes:
    """A real OOXML zip skeleton: publish verifies the delivered slide count."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for number in range(1, slides + 1):
            archive.writestr(f"ppt/slides/slide{number}.xml", "<slide/>")
    return buffer.getvalue()


def minimal_pdf_bytes(pages: int = 1) -> bytes:
    """A structurally real PDF whose page objects the /Type /Page counter can read."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + index} 0 R".encode() for index in range(pages))
        + b"] /Count "
        + str(pages).encode()
        + b" >>",
        *(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"
            for _ in range(pages)
        ),
    ]
    out = [b"%PDF-1.4\n"]
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(sum(len(part) for part in out))
        out.append(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = sum(len(part) for part in out)
    out.append(f"xref\n0 {len(objects) + 1}\n".encode())
    out.append(b"0000000000 65535 f \n")
    out.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return b"".join(out)


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
        if "slide_spec_guard.py" in joined and any(
            f" {action} " in f" {joined} " for action in ("freeze", "revise")
        ):
            Path(flag_value("--lock-file")).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "slide_spec_guard.py" in joined and " check " in f" {joined} ":
            return subprocess.CompletedProcess(
                argv, 0 if self.check_ok else 2,
                stdout="", stderr="bad lock" if not self.check_ok else "",
            )
        if "run_with_pptxgenjs.js" in joined:
            Path(flag_value("--output")).write_bytes(minimal_pptx_zip_bytes())
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "build_support_outputs.py" in joined:
            output_dir = Path(flag_value("--output-dir"))
            prefix = flag_value("--prefix")
            suffixes = {
                "speaker-notes": "speaker-notes.md",
                "full-script": "full-script.md",
                "teleprompter": "teleprompter.html",
                "training-cards": "training-cards.md",
                "references": "references.md",
            }
            requested = [argv[index + 1] for index, item in enumerate(argv[:-1]) if item == "--only"]
            spec_data: dict[str, Any] = {}
            try:
                spec_data = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            except (OSError, ValueError, IndexError):
                spec_data = {}
            slides = [
                slide for slide in (spec_data.get("slides") or [])
                if isinstance(slide, dict)
            ] or [{"id": 1, "title": "Slide 1"}]
            bodies = {
                "speaker-notes": "# Speaker Notes\n\n" + "\n\n".join(
                    f"## 第 {slide.get('id') or position} 页 · {slide.get('title', '')}\n\n讲稿 {position}。"
                    for position, slide in enumerate(slides, 1)
                ),
                "full-script": "# Full Presentation Script\n\n" + "\n\n".join(
                    f"## Slide {slide.get('id') or position}: {slide.get('title', '')}\n\n讲稿 {position}。"
                    for position, slide in enumerate(slides, 1)
                ),
                "teleprompter": "<!doctype html><main>" + "".join(
                    f'<section data-slide="{slide.get("id") or position}"><p>讲稿 {position}。</p></section>'
                    for position, slide in enumerate(slides, 1)
                ) + "</main>",
                "training-cards": "# Presentation Training Cards\n\n" + "\n\n".join(
                    f"## Slide {slide.get('id') or position}: {slide.get('title', '')}\n\n- Keywords: a, b"
                    for position, slide in enumerate(slides, 1)
                ),
                "references": "# References (classroom)\n\n" + "\n".join(
                    f"- [F{index}] Author. (2024). Title. locator Confidence: high."
                    for index in range(1, max(1, len(spec_data.get("evidence_ledger") or [])) + 1)
                ),
            }
            outputs = {}
            for name in requested:
                path = output_dir / f"{prefix}-{suffixes[name]}"
                path.write_text(bodies[name], encoding="utf-8")
                outputs[name] = str(path.resolve())
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"ok": True, "outputs": outputs}), stderr=""
            )
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
        self._original_runner = pp._core._runner
        # Isolate runtime usage probes: the live transcript (a real rollout log
        # can be hundreds of MB) must never decide unit-test behavior or speed.
        self._usage_stub = patch("pipeline.dispatch.current_usage", return_value=None)
        self._usage_stub2 = patch("pipeline.advance.current_usage", return_value=None)
        self._usage_stub.start()
        self._usage_stub2.start()
        self.addCleanup(self._usage_stub.stop)
        self.addCleanup(self._usage_stub2.stop)
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
        pp._core._runner = self._original_runner
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

    def plan(self, files: dict[str, Path], runner: FakeRunner | None = None, extra_args: list[str] | None = None) -> FakeRunner:
        runner = runner or FakeRunner(self.work)
        pp._core._runner = runner
        level = getattr(self, "quality_level", None)
        if level:
            # Tier tests declare their level; plan injects it right before freeze
            # so it survives any fixture that rewrites the spec file first.
            spec = json.loads(files["spec"].read_text(encoding="utf-8"))
            spec.setdefault("meta", {})["quality_level"] = level
            files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        rc = pp.main([
            "plan", "--work-dir", str(self.work),
            "--workflow-state", str(self.workflow_state),
            "--slide-spec", str(files["spec"]),
            "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
            "--visual-generation-report", str(files["vgr"]),
            *(extra_args or []),
        ])
        self.assertEqual(rc, 0)
        return runner

    def manifest(self) -> dict[str, Any]:
        return json.loads((self.work / pp.MANIFEST_NAME).read_text(encoding="utf-8"))

    def write_calibration_receipt(
        self,
        review: Path,
        render_bindings: list[dict[str, Any]] | None = None,
    ) -> None:
        receipt = {
            "agent": "student-presentation-suite:visual-critic",
            "agent_id": "test-calibration-critic",
            "spawn_verified": True,
            "work_id": self.work.name,
            "artifact": pp.bind(review),
            "reads": {
                str(Path(item["path"]).resolve()): item["sha256"]
                for item in (render_bindings or [])
            },
        }
        (review.parent / "calibration-critic-execution.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )

    def render_evidence(self, files, *, write_receipt: bool = True):
        from PIL import Image
        manifest = self.manifest()
        page = self.work / "render" / "slide-1.png"
        page.parent.mkdir(exist_ok=True)
        preview = Image.new("RGB", (640, 360), "white")
        preview.paste("navy", (0, 0, 640, 80))
        preview.save(page)
        contact = self.work / "contact-sheet.png"
        pp.make_contact_sheet([page], contact)
        pdf = self.work / "render" / "slide.pdf"
        pdf.write_bytes(minimal_pdf_bytes(1))
        manifest["render"] = {
            "pptx_sha256": pp.sha256_file(files["pptx"]),
            "pages": [pp.bind(page)],
            "contact_sheet": pp.bind(contact),
            "pdf": pp.bind(pdf),
            "page_count": 1,
        }
        pp.save_manifest(self.work, manifest)
        review = {"pptx_sha256": pp.sha256_file(files["pptx"]), "contact_sheet_sha256": pp.sha256_file(contact), "page_sha256": {"1": pp.sha256_file(page)}}
        files["visual_review"].write_text(json.dumps(review), encoding="utf-8")
        if write_receipt:
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

    def test_research_plan_allows_missing_receipt_in_degraded_mode(self) -> None:
        files = self.write_inputs()
        spec = json.loads(files["spec"].read_text(encoding="utf-8"))
        spec["research_scope"] = "A"
        files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        pack = self.work / "research-pack.json"
        pack.write_text("{}", encoding="utf-8")
        (self.work / "research-pack-validation.json").write_text("{}", encoding="utf-8")
        self.plan(files, extra_args=["--receipt-policy", "allow-missing"])
        self.assertTrue((self.work / "evidence-map.json").is_file())
        research = self.manifest()["research"]
        self.assertFalse(research["spawn_verified"])
        self.assertIsNone(research["execution"])
        self.assertEqual(research["receipt_policy"], "allow-missing")

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

    def test_force_replan_after_production_started_is_refused(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        manifest = self.manifest()
        manifest["state"] = "producing"
        (self.work / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        state = json.loads(self.workflow_state.read_text(encoding="utf-8"))
        state["state"] = "producing"
        self.workflow_state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(pp.RefusedError):
            pp.cmd_plan(ns(
                "plan", self.work, workflow_state=self.workflow_state, force=True,
                slide_spec=files["spec"], validation_report=files["spec_report"],
                art_direction=files["art"],
            ))

    def test_force_replan_revises_existing_lock_without_resetting_intake(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        runner = FakeRunner(self.work)
        pp._core._runner = runner
        rc = pp.main([
            "plan", "--work-dir", str(self.work), "--workflow-state", str(self.workflow_state), "--force",
            "--slide-spec", str(files["spec"]), "--validation-report", str(files["spec_report"]),
            "--art-direction", str(files["art"]),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(any(
            "slide_spec_guard.py" in " ".join(call)
            and " revise " in f" {' '.join(call)} "
            for call in runner.calls
        ))


class PreQaGateTests(PipelineTestCase):
    """Deterministic gates run inside build: misses cost an Edit + rebuild,
    never a critic pass or a repair round (2026-09-17 live paid render + critic
    + QA before a missing planned number surfaced)."""

    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()
        self.plan(self.files)
        self.entry = self.entry_stub()

    def entry_stub(self) -> Path:
        entry = self.work / "deck.js"
        self.implement_scaffolded_pages()
        return entry

    def failing_runner(self) -> FakeRunner:
        runner = FakeRunner(self.work)
        runner.report_failures = {
            "pre-qa-actual-content.json": [
                {"severity": "major", "code": "planned_numbers_missing",
                 "message": "planned number 42 has no text run on slide 1"}
            ]
        }
        return runner

    def build(self, runner: FakeRunner) -> int:
        pp._core._runner = runner
        return pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry)])

    def edit_page(self) -> None:
        page = next((self.work / "pages").glob("p*.js"))
        page.write_text(page.read_text(encoding="utf-8") + "\n/* fixed */\n", encoding="utf-8")

    def test_build_records_green_pre_qa(self) -> None:
        self.assertEqual(self.build(FakeRunner(self.work)), 0)
        pre_qa = self.manifest()["pre_qa"]
        self.assertTrue(pre_qa["ok"])
        self.assertEqual(0, pre_qa["rounds"])
        self.assertIn("rendered", pre_qa["stages"])
        self.assertIn("actual_content", pre_qa["stages"])
        self.assertTrue((self.work / "pre-qa-actual-content.json").is_file())

    def test_pre_qa_includes_the_quality_gate_deterministic_half(self) -> None:
        """2026-09-18 live: build #1 reported 0 pre-QA blockers, render and a full critic pass
        were paid for, and QA then returned 48 — 16 of them computable from the PPTX and spec."""
        self.assertEqual(self.build(FakeRunner(self.work)), 0)
        stages = pp.pre_qa_stages(self.manifest(), self.work)
        names = [stage.name for stage in stages]
        self.assertIn("quality-deterministic", names)
        argv = " ".join(stages[names.index("quality-deterministic")].argv)
        self.assertIn("pptx_quality_gate_v071.py", argv)
        self.assertIn("pre-qa-quality.json", argv)
        self.assertNotIn("--visual-report", argv, "pre-QA must not require the critic report")

    def test_pre_qa_failure_blocks_neither_build_nor_budget(self) -> None:
        rc = self.build(self.failing_runner())
        self.assertEqual(0, rc, "the deck itself built; pre-QA is routing, not a build failure")
        manifest = self.manifest()
        pre_qa = manifest["pre_qa"]
        self.assertFalse(pre_qa["ok"])
        self.assertEqual(1, pre_qa["blockers"])
        self.assertEqual(1, pre_qa["rounds"])
        self.assertEqual(0, manifest["build"]["repair_count"],
                         "a deterministic miss must not consume a repair round")

    def test_pre_qa_failure_allows_rebuild_without_repair(self) -> None:
        self.assertEqual(self.build(self.failing_runner()), 0)
        self.edit_page()
        self.assertEqual(self.build(self.failing_runner()), 0)
        self.assertEqual(0, self.manifest()["build"]["repair_count"])
        self.assertEqual(2, self.manifest()["build"]["build_count"])

    def test_pre_qa_rebuild_requires_generator_change(self) -> None:
        self.assertEqual(self.build(self.failing_runner()), 0)
        self.assertEqual(self.build(self.failing_runner()), 2,
                         "identical rebuild must not loop the free fix path")

    def test_render_refused_while_pre_qa_blocked(self) -> None:
        self.assertEqual(self.build(self.failing_runner()), 0)
        with self.assertRaises(pp.RefusedError):
            pp.cmd_render(ns("render", self.work, cols=3, prefix="slide"))

    def next_dispatch_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_next_routes_pre_qa_failure_to_builder_not_critic(self) -> None:
        self.assertEqual(self.build(self.failing_runner()), 0)
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertFalse(payload["pre_qa"]["ok"])
        self.assertEqual(1, payload["pre_qa"]["rounds"])
        self.assertTrue(
            any(report.endswith("pre-qa-actual-content.json") for report in payload["pre_qa"]["reports"])
        )
        self.assertNotIn("visual-critic", str(payload.get("agent")))
        self.assertIn("NO repair round", payload["notes"])
        self.assertEqual("build", payload["contract"]["stage"])

    def test_pre_qa_round_cap_reopens_the_formal_path(self) -> None:
        runner = self.failing_runner()
        for _ in range(pp.MAX_PRE_QA_REBUILDS):
            self.assertEqual(self.build(runner), 0)
            self.edit_page()
        self.assertEqual(pp.MAX_PRE_QA_REBUILDS, self.manifest()["pre_qa"]["rounds"])
        payload = self.next_dispatch_payload()
        self.assertNotIn("agent", payload, "capped rounds must stop the free-fix routing")
        self.assertIn("render", payload["next_command"])

    def test_pre_qa_pass_resets_rounds(self) -> None:
        self.assertEqual(self.build(self.failing_runner()), 0)
        self.edit_page()
        self.assertEqual(self.build(FakeRunner(self.work)), 0)
        pre_qa = self.manifest()["pre_qa"]
        self.assertTrue(pre_qa["ok"])
        self.assertEqual(0, pre_qa["rounds"])


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

    def test_one_carryover_build_lets_post_build_edits_reach_the_artifact(self) -> None:
        """2026-09-18 live: an entire repair round existed only to carry two pages' tweaks.

        The builder looked at the rendered deck after building, adjusted p6/p8, and the single
        allowed build per round stranded those edits — so round 3's stated purpose was
        "把 p6/p8 排版微调带入产物".
        """
        self.prepared()
        entry = self.entry()
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)
        page = next((self.work / "pages").glob("p*.js"))
        page.write_text(page.read_text(encoding="utf-8") + "\n/* tweak */\n", encoding="utf-8")
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 0)
        manifest = self.manifest()
        self.assertEqual(1, manifest["build"]["carryover_builds"])
        # A second carry-over would be an edit->build loop that sidesteps the repair budget.
        page.write_text(page.read_text(encoding="utf-8") + "\n/* tweak again */\n", encoding="utf-8")
        self.assertEqual(pp.main(["build", "--work-dir", str(self.work), "--entry", str(entry)]), 2)

    def test_a_carryover_with_no_page_edit_is_refused(self) -> None:
        """Carry-over must not become a "rebuild because I asked" path."""
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

    def next_dispatch_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_next_after_plan_dispatches_to_calibration_builder(self) -> None:
        """Fresh planned create-mode work must spawn the builder, not edit pages directly."""
        self.quality_level = "rigorous"
        self.plan(self.files)
        payload = self.next_dispatch_payload()
        self.assertEqual("planned", payload["state"])
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertNotIn("build", payload["next_command"])
        self.assertIn("mode=calibration", payload["notes"])
        # planned create/rebuild keeps the build stage contract (calibration flow)
        self.assertEqual("build", payload["contract"]["stage"])

    def test_basic_dispatches_initial_builder_without_calibration(self) -> None:
        spec = json.loads(self.files["spec"].read_text(encoding="utf-8"))
        spec["meta"]["quality_level"] = "basic"
        self.files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        self.plan(self.files)
        payload = self.next_dispatch_payload()
        self.assertEqual("fast", self.manifest()["quality_level"])
        self.assertEqual("basic", self.manifest()["quality_level_raw"])
        self.assertEqual("initial", payload["builder_mode"])
        self.assertNotIn("calibration", payload)
        self.assertEqual(1, len(payload["builder_packets"]))
        self.assertNotIn("builder_shards", payload)
        self.implement_scaffolded_pages()
        self.assertEqual(0, pp.main(["build", "--work-dir", str(self.work)]))

    def test_high_score_cannot_build_without_calibration(self) -> None:
        spec = json.loads(self.files["spec"].read_text(encoding="utf-8"))
        spec["meta"]["quality_level"] = "high-score"
        self.files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        self.plan(self.files)
        self.implement_scaffolded_pages()
        self.assertEqual(2, pp.main(["build", "--work-dir", str(self.work)]))

    def test_next_with_calibration_manifest_but_no_render_points_at_preview(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.work / "calibration"
        calibration.mkdir()
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 6, 7]}), encoding="utf-8"
        )
        payload = self.next_dispatch_payload()
        self.assertIn("calibration_preview.py", payload["next_command"])
        self.assertIn("--slides 1 6 7", payload["next_command"])

    def calibration_with_render(self) -> Path:
        calibration = self.work / "calibration"
        render = calibration / "render"
        render.mkdir(parents=True, exist_ok=True)
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 6, 7], "pptx": {"sha256": "cal-pptx-sha"}}),
            encoding="utf-8",
        )
        (render / "calibration-1.png").write_bytes(b"png")
        return calibration

    def write_calibration_review(self, calibration: Path, slides: list[dict] | None = None) -> Path:
        review = calibration / "calibration-visual-review.json"
        review.write_text(
            json.dumps(
                {
                    "review_version": "0.8",
                    "pptx_sha256": "cal-pptx-sha",
                    "slides": slides if slides is not None else [
                        {"slide": 1, "visual_structure": "cover", "issues": []},
                        {"slide": 6, "visual_structure": "chart-led", "issues": []},
                        {"slide": 7, "visual_structure": "compare", "issues": []},
                    ],
                }
            ),
            encoding="utf-8",
        )
        # Green requires the calibration builder's style summary (Batch 1-4 closure).
        (calibration / "style-summary.json").write_text(
            json.dumps(
                {
                    "established": {
                        "title_treatment": "34pt left-aligned, hairline under-rule",
                        "rhythm": "dense pages alternate with sparse statements",
                    },
                    "do_not_repeat": ["no equal-card grids as a default mapping"],
                }
            ),
            encoding="utf-8",
        )
        self.write_calibration_receipt(review)
        return review

    def test_calibration_round_budget_releases_the_build_with_recorded_risk(self) -> None:
        """Tiers cap calibration rounds (standard 1 / rigorous 2): then production carries risk."""
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.calibration_with_render()
        self.write_calibration_review(calibration, slides=[
            {"slide": 1, "visual_structure": "cover", "issues": [
                {"code": "style", "severity": "major", "message": "weak hierarchy"},
            ]},
            {"slide": 6, "visual_structure": "chart-led", "issues": []},
            {"slide": 7, "visual_structure": "compare", "issues": []},
        ])
        manifest = self.manifest()
        manifest["calibration"] = {"rounds": 1}
        pp.save_manifest(self.work, manifest)
        payload = self.next_dispatch_payload()
        self.assertEqual("calibration", payload["builder_mode"], "rigorous has one fix round left")

        manifest = self.manifest()
        manifest["calibration"] = {"rounds": 2}
        pp.save_manifest(self.work, manifest)
        payload = self.next_dispatch_payload()
        self.assertEqual("initial", payload["builder_mode"], "budget spent: proceed to production")
        self.assertIn("budget spent", payload["notes"])
        self.assertIn("recorded risk", payload["notes"])

    def test_build_carries_calibration_risk_once_the_round_budget_is_spent(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.calibration_with_render()
        self.write_calibration_review(calibration, slides=[
            {"slide": 1, "visual_structure": "cover", "issues": [
                {"code": "style", "severity": "major", "message": "weak hierarchy"},
            ]},
            {"slide": 6, "visual_structure": "chart-led", "issues": []},
            {"slide": 7, "visual_structure": "compare", "issues": []},
        ])
        self.implement_scaffolded_pages()
        manifest = self.manifest()
        manifest["calibration"] = {"rounds": 1}
        pp.save_manifest(self.work, manifest)
        self.assertEqual(2, pp.main(["build", "--work-dir", str(self.work)]))
        manifest = self.manifest()
        manifest["calibration"] = {"rounds": 2}
        pp.save_manifest(self.work, manifest)
        self.assertEqual(0, pp.main(["build", "--work-dir", str(self.work)]))

    def test_next_with_calibration_render_dispatches_the_independent_review(self) -> None:
        """Calibration is reviewed by the critic, not by the session that chose the treatment.

        2026-09-18 live: the main session read its own calibration PNGs, accepted the visual
        system, and the independent critic then rejected the pattern on all 13 built pages.
        """
        self.quality_level = "rigorous"
        self.plan(self.files)
        self.calibration_with_render()
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:visual-critic", payload["agent"])
        self.assertNotIn("build", payload["next_command"])
        self.assertIn("no independent calibration review on disk", payload["calibration"]["status"])
        self.assertEqual([1, 6, 7], payload["calibration"]["slides"])
        self.assertIn("visual-critic", payload["notes"])
        self.assertEqual("build", payload["contract"]["stage"])

    def test_next_after_a_green_calibration_review_authorises_the_full_build(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.calibration_with_render()
        self.write_calibration_review(calibration)
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertIn("mode=initial", payload["notes"])

    def test_next_keeps_the_builder_on_a_calibration_that_still_has_findings(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.calibration_with_render()
        self.write_calibration_review(
            calibration,
            [
                {"slide": 1, "visual_structure": "cover", "issues": [
                    {"severity": "major", "code": "repetitive_structure_run", "message": "same bordered panel"},
                ]},
                {"slide": 6, "visual_structure": "panel", "issues": []},
                {"slide": 7, "visual_structure": "compare", "issues": []},
            ],
        )
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertEqual("calibration", payload["builder_mode"])
        self.assertEqual([1], payload["builder_packet"]["slides"])
        self.assertIn("repetitive_structure_run", payload["calibration"]["status"])

    def test_next_retries_critic_when_review_exists_but_receipt_is_missing(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        calibration = self.calibration_with_render()
        self.write_calibration_review(calibration)
        (calibration / "calibration-critic-execution.json").unlink()
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:visual-critic", payload["agent"])
        self.assertNotIn("builder_mode", payload)
        self.assertIn("missing successful isolated calibration critic receipt", payload["calibration"]["status"])
        self.assertIn("scope=calibration", payload["notes"])

    def prepared_calibrated_without_review(self) -> Path:
        self.prepared()
        calibration = self.work / "calibration"
        (calibration / "render").mkdir(parents=True, exist_ok=True)
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 6], "pptx": {"sha256": "cal-pptx-sha"}}),
            encoding="utf-8",
        )
        return calibration

    def test_full_build_is_refused_until_calibration_is_independently_reviewed(self) -> None:
        """Doc-only, this rule was already in SKILL.md and a live session still skipped it."""
        self.quality_level = "rigorous"
        self.prepared_calibrated_without_review()
        self.implement_scaffolded_pages()
        rc = pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.work / "deck.js")])
        self.assertEqual(rc, 2)

    def test_full_build_proceeds_once_the_calibration_review_is_green(self) -> None:
        calibration = self.prepared_calibrated_without_review()
        self.implement_scaffolded_pages()
        self.write_calibration_review(
            calibration,
            [
                {"slide": 1, "visual_structure": "cover", "issues": []},
                {"slide": 6, "visual_structure": "chart-led", "issues": []},
            ],
        )
        rc = pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.work / "deck.js")])
        self.assertEqual(rc, 0)

    def test_build_rechecks_the_freeze(self) -> None:
        self.prepared()
        runner = FakeRunner(self.work, check_ok=False)
        pp._core._runner = runner
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
        pp._core._runner = runner
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
        pp._core._runner = runner
        argv = ["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])]
        self.assertEqual(pp.main(argv), 0)
        first_calls = len(runner.calls)
        self.assertEqual(pp.main(argv), 0)
        self.assertEqual(len(runner.calls), first_calls)

    def test_visual_generation_report_refreshes_as_round_evidence(self) -> None:
        self.producing_manifest()
        self.files["vgr"].write_text('{"round": 2}', encoding="utf-8")
        manifest = self.manifest()
        # Repair-round evidence may change without invalidating frozen plan
        # inputs; QA owns the controlled rebinding.
        pp.validate_manifest_authorization(manifest)
        runner = FakeRunner(self.work)
        pp._core._runner = runner
        self.assertEqual(
            pp.main([
                "qa", "--work-dir", str(self.work),
                "--visual-review", str(self.files["visual_review"]),
            ]),
            0,
        )
        refreshed = self.manifest()
        self.assertNotIn("visual_generation_report", refreshed["inputs"])
        self.assertEqual(
            pp.sha256_file(self.files["vgr"]),
            refreshed["generation_evidence"]["visual_generation_report"]["sha256"],
        )

    def test_vgr_change_invalidates_qa_cache(self) -> None:
        self.producing_manifest()
        runner = FakeRunner(self.work)
        pp._core._runner = runner
        argv = [
            "qa", "--work-dir", str(self.work),
            "--visual-review", str(self.files["visual_review"]),
        ]
        self.assertEqual(pp.main(argv), 0)
        first_calls = len(runner.calls)
        first_hash = self.manifest()["qa"]["visual_generation_report"]["sha256"]

        self.files["vgr"].write_text('{"round": 3}', encoding="utf-8")
        self.assertEqual(pp.main(argv), 0)

        refreshed = self.manifest()["qa"]["visual_generation_report"]
        self.assertGreater(len(runner.calls), first_calls)
        self.assertNotEqual(first_hash, refreshed["sha256"])
        self.assertEqual(pp.sha256_file(self.files["vgr"]), refreshed["sha256"])

    def test_prepare_deliverables_generates_and_hash_binds_confirmed_outputs(self) -> None:
        notes_stub = patch("pptx_actual_content_check.extract_pptx_notes", return_value={1: "第一页讲稿。"})
        notes_stub.start()
        self.addCleanup(notes_stub.stop)
        spec = json.loads(self.files["spec"].read_text(encoding="utf-8"))
        spec["meta"]["deliverables"] = [
            "pptx",
            "speaker-notes",
            "full-script",
            "teleprompter",
            "training-cards",
            "references",
            "pdf",
        ]
        self.files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        self.producing_manifest()
        render_pdf = self.work / "render" / "slide.pdf"
        render_pdf.write_bytes(minimal_pdf_bytes(1))
        manifest = self.manifest()
        manifest["render"]["pdf"] = pp.bind(render_pdf)
        pp.save_manifest(self.work, manifest)

        runner = FakeRunner(self.work)
        pp._core._runner = runner
        with patch("pptx_actual_content_check.extract_pptx_notes", return_value={1: "第一页讲稿。"}):
            self.assertEqual(
                pp.main(["prepare-deliverables", "--work-dir", str(self.work)]),
                0,
            )
        prepared = self.manifest()["deliverables"]
        self.assertEqual(
            prepared["requested"],
            [
                "full-script",
                "pdf",
                "references",
                "speaker-notes",
                "teleprompter",
                "training-cards",
            ],
        )
        self.assertTrue(
            all(Path(binding["path"]).is_file() for binding in prepared["outputs"].values())
        )
        self.assertEqual(Path(prepared["outputs"]["pdf"]["path"]), self.files["pptx"].with_suffix(".pdf"))
        self.assertTrue(pp.binding_is_current(prepared["report"]))

        argv = [
            "qa", "--work-dir", str(self.work),
            "--visual-review", str(self.files["visual_review"]),
        ]
        self.assertEqual(pp.main(argv), 0)
        self.assertEqual(
            self.manifest()["qa"]["deliverables"]["outputs"],
            prepared["outputs"],
        )

        full_script = Path(prepared["outputs"]["full-script"]["path"])
        full_script.write_text("changed after QA", encoding="utf-8")
        dispatch = pp.build_next_payload(self.work)
        self.assertIn(" prepare-deliverables ", dispatch["next_command"])
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)
        with patch("pptx_actual_content_check.extract_pptx_notes", return_value={1: "第一页讲稿。"}):
            self.assertEqual(
                pp.main(["prepare-deliverables", "--work-dir", str(self.work)]),
                0,
            )
        refreshed = self.manifest()
        self.assertEqual(refreshed["state"], "producing")
        self.assertTrue(refreshed["qa"]["ok"])
        dispatch = pp.build_next_payload(self.work)
        self.assertTrue(dispatch["visual_evidence_reused"])
        self.assertNotIn("agent", dispatch)
        self.assertIn(" qa ", dispatch["next_command"])

    def test_complete_refuses_truncated_script_even_with_fresh_hashes(self) -> None:
        """Hash currency alone never proved completeness: missing pages must refuse."""
        with patch("pptx_actual_content_check.extract_pptx_notes", return_value={1: "第一页讲稿。"}):
            spec = json.loads(self.files["spec"].read_text(encoding="utf-8"))
            spec["meta"]["deliverables"] = ["pptx", "full-script"]
            self.files["spec"].write_text(json.dumps(spec), encoding="utf-8")
            self.producing_manifest()
            runner = FakeRunner(self.work)
            pp._core._runner = runner
            self.assertEqual(pp.main(["prepare-deliverables", "--work-dir", str(self.work)]), 0)
            self.assertEqual(
                pp.main([
                    "qa", "--work-dir", str(self.work),
                    "--visual-review", str(self.files["visual_review"]),
                ]),
                0,
            )
            script = Path(self.manifest()["deliverables"]["outputs"]["full-script"]["path"])
            script.write_text("# Full Presentation Script\n\n缺页的残稿。\n", encoding="utf-8")
            manifest = self.manifest()
            # Rebind so every hash check passes — only the content check can
            # catch this file (the 2026-09-22 run shipped a script missing 1-3
            # pages under exactly these conditions).
            fresh = pp.bind(script)
            manifest["deliverables"]["outputs"]["full-script"] = fresh
            manifest["qa"]["deliverables"]["outputs"]["full-script"] = fresh
            pp.save_manifest(self.work, manifest)
            self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)
            self.assertEqual(self.manifest()["state"], "qa")

    def test_previews_and_visual_review_are_hash_bound(self) -> None:
        self.producing_manifest()
        previews = self.work / "preview-01.png", self.work / "preview-02.png"
        for index, preview in enumerate(previews):
            preview.write_bytes(f"png-{index}".encode())
        pp._core._runner = FakeRunner(self.work)
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
        pp._core._runner = runner
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
        pp._core._runner = runner
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
        (manifest.get("generation_evidence") or {}).pop("visual_generation_report", None)
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

    def test_a_frozen_blocker_group_is_named_as_a_gate_candidate(self) -> None:
        """2026-09-18: 16 blockers identical in all four rounds, while everything else moved.

        The trend read "improving" (48/34/23/17), so the run spent its whole repair budget and
        5.4M tokens of forensics on a group no page edit could change.
        """
        frozen = {"missing_final_reference": 16}
        self.write_history([
            {"round": 1, "blockers": 48, "failed": ["quality"],
             "codes": {**frozen, "bordered_panel_overuse": 32}},
            {"round": 2, "blockers": 17, "failed": ["quality"], "codes": dict(frozen)},
        ])
        result = pp.repair_convergence(self.work)
        self.assertEqual("improving", result["trend"])
        suspect = result["suspect_gate_defect"]
        self.assertEqual(frozen, suspect["codes"])
        self.assertEqual(16, suspect["blockers"])
        self.assertIn("gate", suspect["advice"])

    def test_a_group_that_moved_is_not_called_a_gate_defect(self) -> None:
        self.write_history([
            {"round": 1, "blockers": 20, "failed": ["quality"],
             "codes": {"missing_final_reference": 10, "visual_score_low": 10}},
            {"round": 2, "blockers": 10, "failed": ["quality"],
             "codes": {"missing_final_reference": 4, "visual_score_low": 6}},
        ])
        self.assertNotIn("suspect_gate_defect", pp.repair_convergence(self.work))

    def test_rounds_without_code_detail_do_not_claim_a_gate_defect(self) -> None:
        """Old gate-history files predate the per-code tally; guessing from counts is not allowed."""
        self.write_history([
            {"round": 1, "blockers": 20, "failed": ["quality"]},
            {"round": 2, "blockers": 20, "failed": ["quality"]},
        ])
        self.assertNotIn("suspect_gate_defect", pp.repair_convergence(self.work))


class BuilderInstanceTests(PipelineTestCase):
    """One builder instance serving several rounds is the largest measured cost driver."""

    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()
        self.plan(self.files)
        self.guard = self.work.parent / ".guard"
        self.guard.mkdir(parents=True, exist_ok=True)

    def manifest_with_rounds(self, stamps: list[str]) -> dict:
        manifest = self.manifest()
        manifest["history"] = [
            {"command": "repair", "at": stamp, "reason": "round"} for stamp in stamps
        ]
        return manifest

    def write_instance(self, first: str, last: str, writes: int = 9) -> None:
        (self.guard / "builder-agent1.json").write_text(
            json.dumps({
                "agent_id": "agent1", "first_write_at": first, "last_write_at": last,
                "writes": writes, "work_ids": [self.work.name],
            }),
            encoding="utf-8",
        )

    def test_one_instance_spanning_two_rounds_is_reported(self) -> None:
        self.write_instance("2026-09-17T19:49:00+00:00", "2026-09-18T01:46:00+00:00")
        manifest = self.manifest_with_rounds(["2026-09-17T21:00:00+00:00", "2026-09-18T01:43:00+00:00"])
        result = pp.builder_instance_reuse(self.work, manifest)
        self.assertIsNotNone(result)
        self.assertEqual(2, result["instances"][0]["repair_rounds_spanned"])
        self.assertIn("NEW", result["advice"])

    def test_an_instance_serving_one_round_is_not_reported(self) -> None:
        self.write_instance("2026-09-17T20:50:00+00:00", "2026-09-17T21:10:00+00:00")
        manifest = self.manifest_with_rounds(["2026-09-17T21:00:00+00:00", "2026-09-18T01:43:00+00:00"])
        self.assertIsNone(pp.builder_instance_reuse(self.work, manifest))

    def test_another_workspace_instance_is_ignored(self) -> None:
        (self.guard / "builder-agent2.json").write_text(
            json.dumps({
                "agent_id": "agent2", "first_write_at": "2026-09-17T19:00:00+00:00",
                "last_write_at": "2026-09-18T02:00:00+00:00", "writes": 9,
                "work_ids": ["some-other-deck"],
            }),
            encoding="utf-8",
        )
        manifest = self.manifest_with_rounds(["2026-09-17T21:00:00+00:00", "2026-09-18T01:43:00+00:00"])
        self.assertIsNone(pp.builder_instance_reuse(self.work, manifest))


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
        published = self.manifest()["published"]["pptx"]
        self.assertEqual(Path(published["path"]), self.work.parent.parent / "work-01-presentation.pptx")
        self.assertTrue(pp.binding_is_current(published))
        mirrored = json.loads(self.workflow_state.read_text(encoding="utf-8"))
        self.assertEqual(mirrored["state"], "complete")

    def test_complete_refuses_conflicting_published_filename(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        destination = self.work.parent.parent / "work-01-presentation.pptx"
        destination.write_bytes(b"someone else's file")
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)
        self.assertEqual(self.manifest()["state"], "qa")
        self.assertEqual(destination.read_bytes(), b"someone else's file")

    def test_complete_publishes_requested_revision_manifest(self) -> None:
        spec = json.loads(self.files["spec"].read_text(encoding="utf-8"))
        spec["meta"]["deliverables"] = ["pptx", "revision-manifest"]
        spec["revision"] = {"revision_id": "r1"}
        self.files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        self.state_qa(ok=True, delivery_checked=True)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)
        published = self.manifest()["published"]["revision-manifest"]
        payload = json.loads(Path(published["path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["revision"]["revision_id"], "r1")
        self.assertEqual(payload["delivered_pptx"]["sha256"], pp.bind(self.files["pptx"])["sha256"])

    def test_pptx_only_complete_does_not_invent_speaker_notes(self) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files)
        (self.work / "speaker-notes.md").unlink()
        pp.main([
            "qa", "--work-dir", str(self.work),
            "--visual-review", str(self.files["visual_review"]),
        ])
        manifest = self.manifest()
        self.assertIsNone(manifest["qa"]["notes"])
        self.assertFalse((self.work / "speaker-notes.md").exists())
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)

    def test_complete_with_degraded_critic_receipt_succeeds(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        manifest = self.manifest()
        manifest["qa"]["critic_execution"] = None
        manifest["qa"]["critic_receipt"] = "missing-allowed"
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)
        self.assertEqual(self.manifest()["state"], "complete")

    def test_complete_with_unmarked_missing_critic_execution_is_refused(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        manifest = self.manifest()
        manifest["qa"]["critic_execution"] = None
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)

    def test_complete_with_blockers_is_refused(self) -> None:
        self.state_qa(ok=False, delivery_checked=True)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)

    def test_complete_without_delivery_is_refused(self) -> None:
        self.state_qa(ok=True, delivery_checked=False)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)

    def test_complete_rejects_changed_dynamic_visual_report(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        self.files["vgr"].write_text('{"round": 2}', encoding="utf-8")
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)

    def test_published_record_carries_verified_page_counts(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)
        published = self.manifest()["published"]
        self.assertEqual(published["pptx"]["pages"], 1)
        self.assertTrue(pp.binding_is_current(published["pptx"]))

    def test_complete_refuses_a_slide_count_mismatch(self) -> None:
        self.state_qa(ok=True, delivery_checked=True)
        # The delivered package must cover the frozen Slide Spec: a 0-slide
        # package is exactly the "content check by hash only" hole this closes.
        (self.work / "deck.pptx").write_bytes(minimal_pptx_zip_bytes(0))
        manifest = self.manifest()
        manifest["build"]["pptx"] = pp.bind(self.work / "deck.pptx")
        manifest["render"]["pptx_sha256"] = pp.sha256_file(self.work / "deck.pptx")
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 2)
        self.assertEqual(self.manifest()["state"], "qa")


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


class ParallelBuilderShardTests(PipelineTestCase):
    """Wall clock is turns x per-turn latency; every gate in the suite costs ~2.5s total.

    2026-09-18 measured the whole gate set at 150s (1.7% of a 147-minute pipeline) against
    519 model round-trips, so sharding the page work across isolated builders is the only
    wall-clock lever that does not touch a gate.
    """

    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def write_spec(self, count: int) -> None:
        slides = [
            {"id": n, "title": f"Slide {n}", "kind": "cover" if n == 1 else "content"}
            for n in range(1, count + 1)
        ]
        self.files["spec"].write_text(
            json.dumps({"meta": {"slide_count": count, "topic": "test"}, "slides": slides}),
            encoding="utf-8",
        )

    def next_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_shards_are_disjoint_and_cover_every_page(self) -> None:
        self.write_spec(9)
        self.plan(self.files)
        plan = pp.builder_shards(pp.remaining_scaffold_slides(self.work), self.work)
        self.assertIsNotNone(plan)
        # Complexity-aware sizing: 9 simple pages weigh 9 -> ceil(9/6) = 2 shards
        # instead of always MAX_PARALLEL_BUILDERS.
        self.assertEqual(2, plan["parallel"])
        assigned = [slide for shard in plan["shards"] for slide in shard["slides"]]
        self.assertEqual(sorted(assigned), list(range(1, 10)), "every page exactly once")
        self.assertEqual(len(assigned), len(set(assigned)), "no page in two shards")
        for shard in plan["shards"]:
            self.assertEqual(len(shard["slides"]), len(shard["pages"]))
        self.assertIn("ONE message", plan["spawn"])

    def test_shards_balance_the_page_count(self) -> None:
        self.write_spec(9)
        self.plan(self.files)
        plan = pp.builder_shards(pp.remaining_scaffold_slides(self.work), self.work)
        sizes = [len(shard["slides"]) for shard in plan["shards"]]
        self.assertLessEqual(max(sizes) - min(sizes), 1, sizes)

    def test_below_the_threshold_a_single_builder_is_used(self) -> None:
        self.write_spec(pp.PARALLEL_MIN_PAGES - 1)
        self.plan(self.files)
        self.assertIsNone(pp.builder_shards(pp.remaining_scaffold_slides(self.work), self.work))

    def test_implemented_pages_are_not_sharded_again(self) -> None:
        self.write_spec(9)
        self.plan(self.files)
        self.implement_scaffolded_pages()
        self.assertEqual([], pp.remaining_scaffold_slides(self.work))
        self.assertIsNone(pp.builder_shards([], self.work))

    def test_page_files_map_back_to_their_slides(self) -> None:
        self.write_spec(9)
        self.plan(self.files)
        plan = pp.builder_shards([1, 2, 3, 4, 5, 6, 7, 8, 9], self.work)
        self.assertIsNotNone(plan)
        for shard in plan["shards"]:
            for slide, page in zip(shard["slides"], shard["pages"], strict=True):
                self.assertTrue(
                    page.startswith(f"p{slide:02d}-"),
                    f"{page} does not belong to slide {slide}",
                )

    def test_multi_slide_blocker_runs_name_their_pages(self) -> None:
        """Closure: `repetitive_structure_pair/run` findings name a RUN of pages
        (`slides: [4, 5, 6]`), not one slide. They must project into repair
        packets page-by-page instead of collapsing into a deck-level blocker
        whose projection loses the specific pages."""
        self.write_spec(9)
        self.plan(self.files)
        (self.work / "pipeline-qa.json").write_text(
            json.dumps({"problems": [
                {
                    "gate": "quality", "severity": "major",
                    "code": "repetitive_structure_run", "message": "three equal-card pages",
                    "slides": [4, 5, 6],
                },
            ]}),
            encoding="utf-8",
        )
        slides = pp.slides_named_in_reports(self.work, ("pipeline-qa.json",))
        self.assertEqual([4, 5, 6], slides)
        packet = pp._packet.build_packet(self.work, "repair", slides, qa_reports=["pipeline-qa.json"])
        blockers = {blocker["code"] for s in packet["slides"] for blocker in s["blockers"]}
        self.assertIn("repetitive_structure_run", blockers)
        # every page of the run carries the same span in its projection
        run = [blocker["slides"] for s in packet["slides"] for blocker in s["blockers"] if "slides" in blocker]
        self.assertEqual([[4, 5, 6]] * 3, run)

    def test_deck_level_blockers_yield_no_shard_plan(self) -> None:
        """A blocker without a slide number is deck-wide; sharding would aim builders wrong."""
        self.write_spec(9)
        self.plan(self.files)
        (self.work / "pipeline-qa.json").write_text(
            json.dumps({"problems": [
                {"gate": "quality", "severity": "major", "code": "visual_average_low", "message": "deck"},
            ]}),
            encoding="utf-8",
        )
        slides = pp.slides_named_in_reports(self.work, ("pipeline-qa.json",))
        self.assertEqual([], slides)
        self.assertIsNone(pp.builder_shards(slides, self.work))





    """`next --json` must hand the builder's packet over with the spawn it names.

    v0.15 Batch 2: the packet is the builder's complete task input; if dispatch
    routes to a builder spawn but emits no packet, the main session falls back to
    the old re-read-everything flow and the projection is dead code.
    """

    def write_rich_spec(self, count: int) -> None:
        slides = [
            {
                "id": n,
                "title": f"Slide {n}",
                "claim": f"Claim {n}",
                "layout": "cover" if n == 1 else "content",
                "content": [],
                "slide_copy": [f"Copy {n}"],
            }
            for n in range(1, count + 1)
        ]
        self.files["spec"].write_text(
            json.dumps({"meta": {"slide_count": count, "topic": "test"}, "slides": slides}),
            encoding="utf-8",
        )

    def write_art(self, leverage: list[int]) -> None:
        self.files["art"].write_text(
            "typography:" + "\n"
            + "  body_pt: 19" + "\n"
            "high_leverage_slides: [" + ", ".join(str(n) for n in leverage) + "]\n",
            encoding="utf-8",
        )

    def next_dispatch_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["next", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_next_emits_a_calibration_packet_for_the_default_set(self) -> None:
        self.quality_level = "rigorous"
        self.files = self.write_inputs()
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        payload = self.next_dispatch_payload()
        self.assertIn("builder_packet", payload)
        self.assertEqual("calibration", payload["builder_packet"]["mode"])
        self.assertEqual([1, 3, 4], payload["builder_packet"]["slides"])
        packet = json.loads(
            Path(payload["builder_packet"]["packet"]).read_text(encoding="utf-8")
        )
        self.assertEqual([1, 3, 4], packet["assigned_slides"])
        self.assertEqual("calibration.json", Path(payload["builder_packet"]["packet"]).name)
        self.assertTrue(all(item.get("requirements") for item in packet["slides"]))

    def test_next_preserves_an_atomic_calibration_override(self) -> None:
        """The CLI override and builder_guard round are one transaction.

        0.15.3 wrote calibration.json for [1,7,9] but left active-round.json at
        [1,2,3]; the builder was then refused. A later `next` also recreated the
        default packet. Neither half of that split-brain may recur.
        """
        self.quality_level = "rigorous"
        self.files = self.write_inputs()
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                pp._packet.main(
                    [
                        "--work-dir", str(self.work),
                        "--mode", "calibration",
                        "--slides", "1", "2", "5",
                        "--force", "--json",
                    ]
                ),
            )
        overridden = json.loads(output.getvalue())
        self.assertEqual([1, 2, 5], overridden["slides"])

        first_round = json.loads(
            (self.work / "builder-packets" / "active-round.json").read_text(encoding="utf-8")
        )
        payload = self.next_dispatch_payload()
        second_round = json.loads(
            (self.work / "builder-packets" / "active-round.json").read_text(encoding="utf-8")
        )
        self.assertEqual([1, 2, 5], payload["builder_packet"]["slides"])
        self.assertEqual(first_round, second_round)

    def test_next_survives_a_missing_art_direction_with_a_spec_driven_packet(self) -> None:
        """Packet generation must never break the dispatch answer — and under
        archetype coverage (Batch 4.1) a missing art-direction no longer prevents
        a default sample: the spec alone drives it."""
        self.quality_level = "rigorous"
        self.files = self.write_inputs()
        self.plan(self.files)
        payload = self.next_dispatch_payload()
        self.assertIn("builder_packet", payload)
        self.assertEqual([1], payload["builder_packet"]["slides"])
        self.assertEqual("student-presentation-suite:presentation-builder", payload.get("agent"))

    def test_initial_packets_are_prepared_per_shard_for_a_large_deck(self) -> None:
        self.files = self.write_inputs()
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        packets = pp._packet.prepare_packets(self.work, "initial")
        self.assertEqual(2, len(packets), "9 simple pages weigh 9 -> two complexity-capped shards")
        assigned: list[int] = []
        for descriptor in packets:
            packet = json.loads(Path(descriptor["packet"]).read_text(encoding="utf-8"))
            assigned.extend(packet["assigned_slides"])
        self.assertEqual(sorted(assigned), list(range(1, 10)), "every page exactly once")

    def test_shard_policy_is_owned_by_the_contract_not_the_packet_module(self) -> None:
        """Batch 2.1: a second hardcoded copy of the shard numbers would let the
        pipeline's shards and the packet's shards silently diverge."""
        self.assertEqual(pp.PARALLEL_MIN_PAGES, pp._packet.PARALLEL_MIN_PAGES)
        self.assertEqual(pp.MAX_PARALLEL_BUILDERS, pp._packet.MAX_PARALLEL_BUILDERS)
        contract = pp.CONTRACT
        self.assertEqual(
            max(2, int(contract["parallel_builder_min_pages"])),
            pp._packet.PARALLEL_MIN_PAGES,
        )

    def test_packet_generation_failure_is_observable_not_silent(self) -> None:
        """Dispatch survives a packet failure, but the payload must say the builder
        fell back to the legacy full-read path — otherwise the cost optimization
        quietly turns off and no benchmark can tell."""
        self.quality_level = "rigorous"
        self.files = self.write_inputs()
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        with patch.object(pp._packet, "write_packet", side_effect=RuntimeError("schema drift")):
            payload = self.next_dispatch_payload()
        self.assertEqual("failed", payload.get("builder_packet_status"))
        self.assertIn("schema drift", payload.get("builder_packet_error") or "")
        self.assertNotIn("builder_packet", payload)
        log = json.loads(
            (self.work / "builder-packets" / "fallbacks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(1, len(log))
        self.assertEqual("calibration", log[0]["mode"])
        # The count in every later payload reflects the log.
        payload = self.next_dispatch_payload()
        self.assertEqual(1, payload["packet_fallback_count"])

    def test_next_reports_zero_packet_fallbacks_when_green(self) -> None:
        self.quality_level = "rigorous"
        self.files = self.write_inputs()
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        payload = self.next_dispatch_payload()
        self.assertIn("builder_packet", payload)
        self.assertEqual(0, payload["packet_fallback_count"])
        self.assertNotIn("builder_packet_status", payload)

    def test_slide_level_blockers_are_sharded(self) -> None:
        self.write_spec(9)
        self.plan(self.files)
        (self.work / "pipeline-qa.json").write_text(
            json.dumps({"problems": [
                {"gate": "quality", "severity": "major", "code": "visual_score_low", "slide": number,
                 "message": f"s{number}"}
                for number in range(1, 10)
            ]}),
            encoding="utf-8",
        )
        slides = pp.slides_named_in_reports(self.work, ("pipeline-qa.json",))
        self.assertEqual(list(range(1, 10)), slides)
        plan = pp.builder_shards(slides, self.work)
        self.assertIsNotNone(plan)
        self.assertEqual(
            sorted(s for shard in plan["shards"] for s in shard["slides"]),
            list(range(1, 10)),
        )

    def test_build_assembles_speaker_note_shards_in_order(self) -> None:
        """Parallel builders cannot each write speaker-notes.md without losing the others'."""
        self.write_spec(4)
        self.plan(self.files)
        self.implement_scaffolded_pages()
        (self.work / "speaker-notes-shard-2.md").write_text("SECOND half\n", encoding="utf-8")
        (self.work / "speaker-notes-shard-1.md").write_text("FIRST half\n", encoding="utf-8")
        used = pp.merge_speaker_note_shards(self.work)
        self.assertEqual(2, len(used))
        merged = (self.work / "speaker-notes.md").read_text(encoding="utf-8")
        self.assertTrue(merged.startswith("FIRST half"), merged)
        self.assertIn("SECOND half", merged)

    def test_speaker_note_repair_shard_replaces_older_page_section(self) -> None:
        old = self.work / "speaker-notes-shard-1.md"
        new = self.work / "speaker-notes-shard-3.md"
        old.write_text(
            "# old\n\n## 第 1 页 · 开场\n\n第一页。\n\n## 第 10 页 · 环境\n\n旧讲稿。\n",
            encoding="utf-8",
        )
        new.write_text("## 第 10 页 · 环境\n\n新讲稿。\n", encoding="utf-8")
        old_time = old.stat().st_mtime_ns
        new_time = max(new.stat().st_mtime_ns, old_time + 1_000_000)
        os.utime(new, ns=(new_time, new_time))
        pp.merge_speaker_note_shards(self.work)
        merged = (self.work / "speaker-notes.md").read_text(encoding="utf-8")
        self.assertEqual(merged.count("## 第 10 页"), 1)
        self.assertIn("新讲稿。", merged)
        self.assertNotIn("旧讲稿。", merged)
        self.assertLess(merged.index("## 第 1 页"), merged.index("## 第 10 页"))

    def test_overwritten_repair_shard_preserves_untouched_pages_from_previous_merge(self) -> None:
        shard = self.work / "speaker-notes-shard-1.md"
        shard.write_text(
            "## 第 1 页 · 开场\n\n第一页。\n\n"
            "## 第 5 页 · 数据\n\n旧第五页。\n\n"
            "## 第 9 页 · 结尾\n\n第九页。\n",
            encoding="utf-8",
        )
        pp.merge_speaker_note_shards(self.work)
        previous = (self.work / "speaker-notes.md").stat().st_mtime_ns
        shard.write_text("## 第 5 页 · 数据\n\n新第五页。\n", encoding="utf-8")
        fresh = max(shard.stat().st_mtime_ns, previous + 1_000_000)
        os.utime(shard, ns=(fresh, fresh))
        pp.merge_speaker_note_shards(self.work)
        merged = (self.work / "speaker-notes.md").read_text(encoding="utf-8")
        self.assertIn("第一页。", merged)
        self.assertIn("第九页。", merged)
        self.assertIn("新第五页。", merged)
        self.assertNotIn("旧第五页。", merged)
        self.assertEqual(merged.count("## 第 5 页"), 1)

    def test_a_single_builder_run_writes_no_merge(self) -> None:
        self.write_spec(4)
        self.plan(self.files)
        self.implement_scaffolded_pages()
        self.assertEqual([], pp.merge_speaker_note_shards(self.work))
        self.assertFalse((self.work / "speaker-notes.md").exists())

    def test_merge_refuses_fragments_that_drop_pages(self) -> None:
        self.write_spec(4)
        self.plan(self.files)
        self.implement_scaffolded_pages()
        shard = self.work / "speaker-notes-shard-1.md"
        shard.write_text(
            "## 第 1 页 · Slide 1\n\n第一页。\n\n"
            "## 第 2 页 · Slide 2\n\n第二页。\n\n"
            "## 第 4 页 · Slide 4\n\n第四页。\n",
            encoding="utf-8",
        )
        with self.assertRaises(pp.RefusedError):
            pp.merge_speaker_note_shards(self.work)
        self.assertFalse((self.work / "speaker-notes.md").exists())
        shard.write_text(
            shard.read_text(encoding="utf-8") + "\n## 第 3 页 · Slide 3\n\n第三页。\n",
            encoding="utf-8",
        )
        self.assertTrue(pp.merge_speaker_note_shards(self.work))
        merged = (self.work / "speaker-notes.md").read_text(encoding="utf-8")
        for number in range(1, 5):
            self.assertIn(f"## 第 {number} 页", merged)

    def test_plan_records_deck_rhythm_failure_instead_of_hiding_it(self) -> None:
        """Closure: a deck-rhythm regression is recorded in the manifest as
        status=failed (and reported), never silently absorbed — otherwise pages
        repeat and nobody can tell whether rhythm planning even ran."""
        self.write_rich_spec(6)
        self.write_art([1])

        def broken(work_dir: object) -> object:
            raise RuntimeError("rhythm regression")

        from unittest.mock import patch as _patch

        import deck_rhythm

        plan_args = [
            "plan", "--work-dir", str(self.work),
            "--workflow-state", str(self.workflow_state),
            "--slide-spec", str(self.files["spec"]),
            "--validation-report", str(self.files["spec_report"]),
            "--art-direction", str(self.files["art"]),
            "--visual-generation-report", str(self.files["vgr"]),
        ]
        pp._core._runner = FakeRunner(self.work)
        with _patch.object(deck_rhythm, "ensure_rhythm", broken):
            rc = pp.main(plan_args)
        self.assertEqual(rc, 0)
        rhythm = self.manifest()["deck_rhythm"]
        self.assertEqual("failed", rhythm["status"])
        self.assertIn("rhythm regression", rhythm["error"])

    def test_next_offers_shards_for_the_full_build(self) -> None:
        """The plan must reach the main session, or the gain never happens."""
        self.quality_level = "rigorous"
        self.write_spec(9)
        self.plan(self.files)
        calibration = self.work / "calibration"
        (calibration / "render").mkdir(parents=True, exist_ok=True)
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"version": "1.0", "slides": [1, 5, 9], "pptx": {"sha256": "cal"}}),
            encoding="utf-8",
        )
        (calibration / "render" / "calibration-1.png").write_bytes(b"png")
        calibration_review = calibration / "calibration-visual-review.json"
        calibration_review.write_text(
            json.dumps({
                "pptx_sha256": "cal",
                "slides": [
                    {"slide": 1, "visual_structure": "cover", "issues": []},
                    {"slide": 5, "visual_structure": "chart", "issues": []},
                    {"slide": 9, "visual_structure": "compare", "issues": []},
                ],
            }),
            encoding="utf-8",
        )
        self.write_calibration_receipt(calibration_review)
        # Green requires the calibration builder's style summary (closure invariant).
        (calibration / "style-summary.json").write_text(
            json.dumps({
                "established": {"title_treatment": "left-aligned 34pt, hairline rule"},
                "do_not_repeat": ["no equal-card grids as a default mapping"],
            }),
            encoding="utf-8",
        )
        payload = self.next_dispatch_payload()
        self.assertEqual("student-presentation-suite:presentation-builder", payload["agent"])
        self.assertIn("mode=initial", payload["notes"])
        self.assertIn("builder_shards", payload)
        self.assertEqual(2, payload["builder_shards"]["parallel"])


class AdvanceTests(PipelineTestCase):
    """Batch 3: advance runs every deterministic step and stops only at boundaries
    that need intelligence. It never spawns or calls a model agent — the result is
    a status (needs_agent / needs_user / complete) plus the dispatch payload the
    main session already knows how to act on."""

    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()

    def write_rich_spec(self, count: int) -> None:
        slides = [
            {
                "id": n,
                "title": f"Slide {n}",
                "claim": f"Claim {n}",
                "layout": "cover" if n == 1 else "content",
                "content": [],
                "slide_copy": [f"Copy {n}"],
            }
            for n in range(1, count + 1)
        ]
        self.files["spec"].write_text(
            json.dumps({"meta": {"slide_count": count, "topic": "test"}, "slides": slides}),
            encoding="utf-8",
        )

    def write_art(self, leverage: list[int]) -> None:
        self.files["art"].write_text(
            "typography:" + "\n"
            + "  body_pt: 19" + "\n"
            "high_leverage_slides: [" + ", ".join(str(n) for n in leverage) + "]\n",
            encoding="utf-8",
        )

    def use_fake_runtime(self) -> None:
        base = FakeRunner(self.work)

        def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
            joined = " ".join(argv)
            if "pptx_tool.py" in joined and " render " in f" {joined} ":
                from PIL import Image

                out_dir = Path(argv[argv.index("--output-dir") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                page = out_dir / "slide-1.png"
                Image.new("RGB", (64, 48), "white").save(page)
                pdf = out_dir / "slide.pdf"
                pdf.write_bytes(b"%PDF-1.4\n")
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=json.dumps({"pages": [str(page)], "pdf": str(pdf)}),
                    stderr="",
                )
            if "calibration_preview.py" in joined:
                render_dir = self.work / "calibration" / "render"
                render_dir.mkdir(parents=True, exist_ok=True)
                for number in (1, 3, 4):
                    (render_dir / f"calibration-{number}.png").write_bytes(b"PNG")
                return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")
            return base(argv)

        pp._core._runner = runner

    def state_qa(self, *, ok: bool) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files)
        pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(self.files["visual_review"])])
        manifest = self.manifest()
        manifest["qa"]["ok"] = ok
        manifest["qa"]["blockers"] = 0 if ok else 2
        pp.save_manifest(self.work, manifest)

    def advance(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.main(["advance", "--work-dir", str(self.work), "--json"])
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_brief_advance_omits_repeated_stage_rules(self) -> None:
        self.quality_level = "rigorous"
        self.plan(self.files)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(0, pp.main(["advance", "--work-dir", str(self.work), "--brief-json"]))
        result = json.loads(buffer.getvalue())
        self.assertEqual("needs_agent", result["status"])
        self.assertNotIn("dispatch", result)
        self.assertNotIn("contract", result)
        self.assertIn("packet", result)

    def test_without_a_manifest_it_needs_the_user(self) -> None:
        result = self.advance()
        self.assertEqual("needs_user", result["status"])
        self.assertEqual([], result["actions"])
        self.assertIn("reason", result)

    def test_a_planned_deck_needs_the_calibration_builder_with_its_packet(self) -> None:
        self.quality_level = "rigorous"
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual([], result["actions"])
        self.assertEqual(pp.BUILDER_AGENT, result["dispatch"]["agent"])
        self.assertEqual("calibration", result["dispatch"]["builder_mode"])
        self.assertIn("builder_packet", result["dispatch"])

    def test_advance_runs_the_calibration_preview_itself_then_needs_the_critic(self) -> None:
        self.quality_level = "rigorous"
        self.write_rich_spec(9)
        self.write_art([1, 3, 4])
        self.plan(self.files)
        calibration = self.work / "calibration"
        calibration.mkdir()
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"slides": [1, 3, 4]}), encoding="utf-8"
        )
        (calibration / "calibration.pptx").write_bytes(b"PK\x03\x04 fake")
        self.use_fake_runtime()
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(["calibration_preview"], result["actions"])
        self.assertEqual(pp.CRITIC_AGENT, result["dispatch"]["agent"])
        self.assertTrue(list((self.work / "calibration" / "render").glob("calibration-*.png")))

    def test_advance_renders_a_built_deck_then_needs_the_critic(self) -> None:
        self.plan(self.files)
        self.use_fake_runtime()
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(["render"], result["actions"])
        self.assertEqual(pp.CRITIC_AGENT, result["dispatch"]["agent"])

    def test_advance_consumes_current_critic_review_once_then_runs_qa(self) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files)
        result = self.advance()
        self.assertEqual("complete", result["status"])
        self.assertIn("qa", result["actions"])
        self.assertEqual(1, result["actions"].count("qa"))
        self.assertNotIn("agent", result["dispatch"])

    def test_advance_waits_for_critic_receipt(self) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files, write_receipt=False)
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(pp.CRITIC_AGENT, result["agent"])

    def test_advance_waits_when_critic_review_binds_old_render(self) -> None:
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(self.files)
        review_path = self.files["visual_review"]
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["pptx_sha256"] = "old-render"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(pp.CRITIC_AGENT, result["agent"])
        self.assertNotIn("qa", result["actions"])

    def test_advance_records_the_repair_and_needs_the_repair_builder(self) -> None:
        self.state_qa(ok=False)
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(["repair"], result["actions"])
        self.assertEqual(pp.BUILDER_AGENT, result["agent"])
        self.assertEqual("repair", result["mode"])
        self.assertIsInstance(result["packets"], list)
        manifest = self.manifest()
        self.assertEqual("producing", manifest["state"])
        self.assertTrue(manifest["build"]["pending_repair"])

    def test_advance_completes_a_green_deck(self) -> None:
        self.state_qa(ok=True)
        result = self.advance()
        self.assertEqual("complete", result["status"])
        self.assertIn("complete", result["actions"])
        self.assertEqual("complete", self.manifest()["state"])

    def test_advance_reports_pending_repair_without_repeating_the_repair(self) -> None:
        self.state_qa(ok=False)
        self.advance()  # first call records the repair and stops at the builder
        result = self.advance()  # second call must not repair again
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual([], result["actions"])
        self.assertEqual("repair", result["mode"])

    def test_repair_boundary_is_the_unified_dispatch_envelope(self) -> None:
        """The QA→repair boundary must be the SAME dispatch payload `next` answers
        with — repair_budget, contract, builder_shards ride along — not a hand-built
        envelope that bypasses the dispatch resolver."""
        self.state_qa(ok=False)
        (self.work / "pipeline-qa.json").write_text(
            json.dumps({"ok": False, "problems": [
                {"gate": "quality", "severity": "major", "code": "overflow", "slide": 1, "message": "x"},
            ]}),
            encoding="utf-8",
        )
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual("repair", result["mode"])
        dispatch = result["dispatch"]
        self.assertIn("repair_budget", dispatch)
        self.assertIn("contract", dispatch)
        self.assertIn("notes", dispatch)

    def test_advance_surfaces_packet_generation_failure_instead_of_silently_dropping(self) -> None:
        """Batch 2.1's rule — a packet fallback is observable, never silent — must
        also hold on advance's repair path. A packet generator crash has to land in
        builder-packets/fallbacks.json AND in the result's packet_fallback_count."""
        self.state_qa(ok=False)
        (self.work / "pipeline-qa.json").write_text(
            json.dumps({"ok": False, "problems": [
                {"gate": "quality", "severity": "major", "code": "overflow", "slide": 2, "message": "x"},
            ]}),
            encoding="utf-8",
        )

        def broken_prepare(*args: object, **kwargs: object) -> list:
            raise RuntimeError("schema drift")

        original = pp._packet.prepare_packets
        pp._packet.prepare_packets = broken_prepare
        try:
            result = self.advance()
        finally:
            pp._packet.prepare_packets = original
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual("repair", result["mode"])
        self.assertEqual([], result["packets"])
        self.assertGreaterEqual(result["packet_fallback_count"], 1)
        fallbacks = json.loads((self.work / "builder-packets" / "fallbacks.json").read_text(encoding="utf-8"))
        self.assertTrue(fallbacks)

    def green_calibration_review(self, slides: list[int]) -> None:
        """Independent calibration evidence that satisfies calibration_review()."""
        calibration = self.work / "calibration"
        calibration.mkdir(exist_ok=True)
        pptx_sha = "calibration-pptx-sha"
        (calibration / "calibration-manifest.json").write_text(
            json.dumps({"slides": slides, "pptx": {"sha256": pptx_sha}}), encoding="utf-8"
        )
        render_dir = calibration / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        for number in slides:
            (render_dir / f"calibration-{number}.png").write_bytes(b"PNG")
        calibration_review = calibration / "calibration-visual-review.json"
        calibration_review.write_text(
            json.dumps({"pptx_sha256": pptx_sha, "slides": [{"slide": n} for n in slides]}),
            encoding="utf-8",
        )
        self.write_calibration_receipt(calibration_review)
        # Green now REQUIRES the calibration builder's style summary (closure).
        (calibration / "style-summary.json").write_text(
            json.dumps(
                {
                    "established": {
                        "title_treatment": "34pt left-aligned, hairline under-rule",
                        "rhythm": "dense evidence pages alternate with sparse statements",
                    },
                    "do_not_repeat": ["no equal-card grids as a default mapping"],
                }
            ),
            encoding="utf-8",
        )

    def test_advance_builds_then_renders_once_all_pages_are_implemented(self) -> None:
        """Batch 3.1: the first build is deterministic too. With calibration green and
        no scaffold stubs left, advance runs build AND render before the critic
        boundary instead of handing a raw build command back to the model."""
        self.write_rich_spec(3)
        self.write_art([1])
        self.plan(self.files)
        self.green_calibration_review([1])
        self.entry()  # strips the stub markers: the initial builders are done
        self.use_fake_runtime()
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(["build", "render"], result["actions"])
        self.assertEqual(pp.CRITIC_AGENT, result["dispatch"]["agent"])

    def test_advance_rebuilds_when_the_repair_builder_changed_the_generator(self) -> None:
        """After the repair builder edits pages the fingerprint moves: advance must
        rebuild and render in ONE call instead of asking the model to run build by
        hand between two advance calls. An unchanged fingerprint keeps the repair
        builder boundary (tested above)."""
        self.state_qa(ok=False)
        self.advance()  # records the repair and stops at the repair builder
        entry = self.entry()
        entry.write_text(entry.read_text(encoding="utf-8") + "// repair edits landed\n", encoding="utf-8")
        self.use_fake_runtime()
        result = self.advance()
        self.assertEqual("needs_agent", result["status"])
        self.assertEqual(["build", "render"], result["actions"])
        self.assertEqual(pp.CRITIC_AGENT, result["dispatch"]["agent"])
        manifest = self.manifest()
        self.assertFalse(manifest["build"]["pending_repair"])

    def test_edit_mode_first_build_needs_the_user_not_a_silent_auto_build(self) -> None:
        """An edit-mode build before the main session applied the edit intent would
        package the unchanged source deck — that is the one build advance must not
        decide by itself, so it stops with a named reason instead of running it."""
        self.write_rich_spec(3)
        self.plan(self.files)
        manifest = self.manifest()
        manifest["mode"] = "edit_ooxml"
        pp.save_manifest(self.work, manifest)
        result = self.advance()
        self.assertEqual("needs_user", result["status"])
        self.assertIn("edit_ooxml", result["reason"])
        self.assertEqual([], result["actions"])
        self.assertNotIn("agent", result.get("dispatch", {}))

    def test_advance_calls_are_ledgered_for_the_report(self) -> None:
        """Batch 3.1 observability: every advance call lands in the manifest history
        so pipeline_report.py can report collapsed round-trips without transcripts."""
        self.state_qa(ok=True)
        result = self.advance()
        self.assertEqual("complete", result["status"])
        entries = [h for h in self.manifest()["history"] if h.get("command") == "advance"]
        self.assertEqual(1, len(entries))
        self.assertEqual("complete", entries[0]["status"])
        self.assertIn("complete", entries[0]["actions"])
        self.assertFalse(entries[0]["step_cap"])

    def test_initial_packet_embeds_the_calibration_style_contract(self) -> None:
        """Batch 4.2: once calibration is green, the initial builder's packet carries
        the style contract — the visual reference system — instead of the builder
        inferring style from calibration page JS it must not read."""
        self.write_rich_spec(6)
        self.write_art([1])
        self.plan(self.files)
        self.green_calibration_review([1])
        packet = pp._packet.build_packet(self.work, "initial")
        style = packet.get("calibration_style")
        self.assertIsInstance(style, dict)
        self.assertEqual("green", style["status"])
        self.assertEqual([1], style["calibration_slides"])
        self.assertIn("calibration_style_note", packet)
        self.assertIn("do NOT read calibration page modules", packet["calibration_style_note"])
        # the contract file is on disk where `next`/advance and a rerun can find it
        self.assertTrue((self.work / "calibration-style-contract.json").is_file())
        # context minimisation: the AD style sections are NOT duplicated per shard
        self.assertNotIn("typography", packet["art_direction"])
        self.assertIn("art_direction_note", packet)

    def test_calibration_packet_keeps_the_full_art_direction(self) -> None:
        self.write_rich_spec(6)
        self.write_art([1])
        self.plan(self.files)
        packet = pp._packet.build_packet(self.work, "calibration")
        self.assertIn("typography", packet["art_direction"])  # full AD until green
        self.assertIn("style_summary_schema", packet)
        self.assertIn("calibration/style-summary.json", packet["allowed_files"])

    def test_initial_packet_without_green_calibration_has_no_style_contract(self) -> None:
        self.write_rich_spec(6)
        self.write_art([1])
        self.plan(self.files)
        packet = pp._packet.build_packet(self.work, "initial")
        self.assertNotIn("calibration_style", packet)
        self.assertNotIn("calibration_style_note", packet)


class ReceiptPolicyTests(PipelineTestCase):
    """Degradation applies ONLY to a truly absent receipt file; a present file
    that is empty, corrupt or identity-mismatched is always a hard refusal,
    and the policy is work-id state that later stages inherit."""

    def test_execution_receipt_degrades_only_on_missing_file(self) -> None:
        artifact = self.work / "research-pack.json"
        artifact.write_text("{}", encoding="utf-8")
        receipt = pp.execution_receipt(self.work, "research", artifact, policy="allow-missing")
        self.assertFalse(receipt["spawn_verified"])
        self.assertEqual(receipt["degraded"], "receipt-missing-allowed")
        with self.assertRaises(pp.RefusedError):
            pp.execution_receipt(self.work, "research", artifact)
        (self.work / "research-execution.json").write_text(
            json.dumps({"agent": "wrong-agent"}), encoding="utf-8"
        )
        with self.assertRaises(pp.RefusedError):
            pp.execution_receipt(self.work, "research", artifact, policy="allow-missing")

    def test_present_but_empty_or_corrupt_receipt_never_degrades(self) -> None:
        """2026-09-20 review: load_json(...) or {} conflated corrupt with missing."""
        artifact = self.work / "research-pack.json"
        artifact.write_text("{}", encoding="utf-8")
        (self.work / "research-execution.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(pp.RefusedError):
            pp.execution_receipt(self.work, "research", artifact, policy="allow-missing")
        (self.work / "research-execution.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(pp.RefusedError):
            pp.execution_receipt(self.work, "research", artifact, policy="allow-missing")
        (self.work / "research-execution.json").unlink()
        receipt = pp.execution_receipt(self.work, "research", artifact, policy="allow-missing")
        self.assertEqual(receipt["degraded"], "receipt-missing-allowed")

    def degraded_research_plan(self, files: dict[str, Path]) -> None:
        spec = json.loads(files["spec"].read_text(encoding="utf-8"))
        spec["research_scope"] = "A"
        files["spec"].write_text(json.dumps(spec), encoding="utf-8")
        (self.work / "research-pack.json").write_text("{}", encoding="utf-8")
        (self.work / "research-pack-validation.json").write_text("{}", encoding="utf-8")
        self.plan(files, extra_args=["--receipt-policy", "allow-missing"])
        self.assertEqual(self.manifest()["research"]["receipt_policy"], "allow-missing")

    def test_scope_c_no_research_degraded_policy_reaches_complete(self) -> None:
        """2026-09-20 review #1: plan --receipt-policy allow-missing on a deck
        with NO researcher (scope C, no pack) must still record the policy and
        let qa/complete inherit — manifest["research"] is never created here."""
        files = self.write_inputs()
        self.plan(files, extra_args=["--receipt-policy", "allow-missing"])
        manifest = self.manifest()
        self.assertEqual(manifest["receipt_policy"], "allow-missing")
        self.assertNotIn("research", manifest)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(files, write_receipt=False)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            pp.cmd_next(ns("next", self.work, json=True))
        payload = json.loads(buffer.getvalue())
        self.assertIn("--receipt-policy allow-missing", payload["next_command"])
        pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(files["visual_review"])])
        manifest = self.manifest()
        self.assertEqual(manifest["qa"]["critic_receipt"], "missing-allowed")
        manifest["qa"]["ok"] = True
        manifest["qa"]["blockers"] = 0
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.main(["complete", "--work-dir", str(self.work)]), 0)
        self.assertEqual(self.manifest()["state"], "complete")

    def test_qa_and_next_command_inherit_degraded_policy(self) -> None:
        """2026-09-20 review: the policy must be work-id state — qa without the
        flag inherits it, and next_command carries it verbatim."""
        files = self.write_inputs()
        self.degraded_research_plan(files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(files, write_receipt=False)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            pp.cmd_next(ns("next", self.work, json=True))
        payload = json.loads(buffer.getvalue())
        self.assertIn("--receipt-policy allow-missing", payload["next_command"])
        self.assertTrue(payload["visual_evidence_reused"])
        self.assertNotIn("agent", payload)
        pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(files["visual_review"])])
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "qa")
        self.assertEqual(manifest["qa"]["critic_receipt"], "missing-allowed")

    def test_qa_without_degraded_state_still_requires_receipt(self) -> None:
        files = self.write_inputs()
        self.plan(files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        self.render_evidence(files, write_receipt=False)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            pp.cmd_next(ns("next", self.work, json=True))
        payload = json.loads(buffer.getvalue())
        self.assertNotIn("--receipt-policy", payload["next_command"])
        self.assertIn("Wait for critic-execution.json before QA.", payload["notes"])
        self.assertEqual(pp.main(["qa", "--work-dir", str(self.work), "--visual-review", str(files["visual_review"])]), 2)


if __name__ == "__main__":
    unittest.main()
