"""Tests for ppt_pipeline render orchestration without LibreOffice."""

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

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("pipeline_render_test_module", PIPELINE)
pp = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = pp
assert _SPEC.loader is not None
_SPEC.loader.exec_module(pp)


class RenderRunner:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.calls = 0

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        prefix = argv[argv.index("--prefix") + 1]
        out_dir.mkdir(parents=True, exist_ok=True)
        pages = []
        for index in (1, 2):
            page = out_dir / f"{prefix}-{index}.png"
            Image.new("RGB", (160, 90), "white").save(page)
            pages.append(str(page))
        return subprocess.CompletedProcess(
            argv, 0,
            stdout=json.dumps({"ok": True, "pages": pages, "slide_count": 2, "rendered_page_count": 2}),
            stderr="",
        )


class PipelineRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()
        self.summary = self.work / "summary.md"
        self.summary.write_text("approved", encoding="utf-8")
        self.state = self.work / "state.json"
        self.state.write_text(
            json.dumps({
                "state": "producing",
                "work_id": "work",
                "summary_file": str(self.summary),
                "summary_sha256": pp.sha256_file(self.summary),
            }), encoding="utf-8",
        )
        self.pptx = self.work / "deck.pptx"
        self.pptx.write_bytes(b"PK fake")
        pp.save_manifest(self.work, {
            "manifest_version": pp.MANIFEST_VERSION,
            "work_id": "work",
            "work_dir": str(self.work),
            "state": "producing",
            "workflow": {
                "state_file": str(self.state),
                "summary_file": str(self.summary),
                "summary_sha256": pp.sha256_file(self.summary),
            },
            "inputs": {},
            "build": {"pptx": pp.bind(self.pptx), "build_count": 1, "repair_count": 0},
            "render": {},
            "qa": {},
            "history": [],
        })
        self.original_runner = pp._runner

    def tearDown(self) -> None:
        pp._runner = self.original_runner
        self.tmp.cleanup()

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(work_dir=self.work, prefix="slide", cols=2)

    def test_render_creates_contact_sheet_and_hash_bindings(self) -> None:
        runner = RenderRunner(self.work)
        pp._runner = runner
        self.assertEqual(pp.cmd_render(self.args()), 0)
        manifest = pp.load_manifest(self.work)
        assert manifest is not None
        render = manifest["render"]
        self.assertEqual(render["page_count"], 2)
        self.assertEqual(len(render["pages"]), 2)
        self.assertTrue(Path(render["contact_sheet"]["path"]).is_file())
        self.assertTrue(render["contact_sheet"]["sha256"])
        self.assertEqual(runner.calls, 1)

    def test_identical_pptx_reuses_render_without_subprocess(self) -> None:
        runner = RenderRunner(self.work)
        pp._runner = runner
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertEqual(runner.calls, 1)

    def test_changed_pptx_invalidates_render_cache(self) -> None:
        runner = RenderRunner(self.work)
        pp._runner = runner
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.pptx.write_bytes(b"PK changed")
        manifest = pp.load_manifest(self.work)
        assert manifest is not None
        manifest["build"]["pptx"] = pp.bind(self.pptx)
        pp.save_manifest(self.work, manifest)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertEqual(runner.calls, 2)

    def test_render_reuse_is_recorded_for_observability(self) -> None:
        """Cache hits must be visible, otherwise cost reports show only spend."""
        runner = RenderRunner(self.work)
        pp._runner = runner
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertEqual(runner.calls, 1)
        manifest = pp.load_manifest(self.work)
        assert manifest is not None
        reuses = [
            entry for entry in manifest["history"]
            if entry.get("command") == "render" and entry.get("reused")
        ]
        self.assertEqual(1, len(reuses))


class NextRoutingTests(unittest.TestCase):
    """`next` must route on the manifest, never on leftover PNGs (the 0.11.1 bug)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()
        self.summary = self.work / "summary.md"
        self.summary.write_text("approved", encoding="utf-8")
        self.state = self.work / "state.json"
        self.state.write_text(
            json.dumps({
                "state": "producing",
                "work_id": "work",
                "summary_file": str(self.summary),
                "summary_sha256": pp.sha256_file(self.summary),
            }), encoding="utf-8",
        )
        self.pptx = self.work / "deck.pptx"
        self.pptx.write_bytes(b"PK fake")
        pp.save_manifest(self.work, {
            "manifest_version": pp.MANIFEST_VERSION,
            "work_id": "work",
            "work_dir": str(self.work),
            "state": "producing",
            "workflow": {
                "state_file": str(self.state),
                "summary_file": str(self.summary),
                "summary_sha256": pp.sha256_file(self.summary),
            },
            "inputs": {},
            "build": {"pptx": pp.bind(self.pptx), "build_count": 1, "repair_count": 0},
            "render": {},
            "qa": {},
            "history": [],
        })
        self.original_runner = pp._runner

    def tearDown(self) -> None:
        pp._runner = self.original_runner
        self.tmp.cleanup()

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(work_dir=self.work, prefix="slide", cols=2)

    def next_payload(self) -> dict:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = pp.cmd_next(argparse.Namespace(work_dir=self.work, json=True))
        self.assertEqual(rc, 0)
        return json.loads(buffer.getvalue())

    def test_next_points_at_render_without_render_evidence(self) -> None:
        payload = self.next_payload()
        self.assertIn(" render", payload["next_command"])
        self.assertEqual([], payload["read_images"])

    def test_next_points_at_qa_once_render_matches_the_pptx(self) -> None:
        pp._runner = RenderRunner(self.work)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        payload = self.next_payload()
        self.assertIn(" qa", payload["next_command"])
        self.assertEqual(2, len(payload["read_images"]))

    def test_stale_contact_sheet_is_not_treated_as_render_evidence(self) -> None:
        """Reproduces the repair loop: rebuild clears the manifest, PNG stays."""
        pp._runner = RenderRunner(self.work)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        self.assertTrue((self.work / "contact-sheet.png").is_file())
        self.pptx.write_bytes(b"PK rebuilt")
        manifest = pp.load_manifest(self.work)
        assert manifest is not None
        manifest["build"]["pptx"] = pp.bind(self.pptx)
        manifest["render"] = {}
        pp.save_manifest(self.work, manifest)

        self.assertTrue((self.work / "contact-sheet.png").is_file())
        payload = self.next_payload()
        self.assertIn(" render", payload["next_command"])
        self.assertEqual([], payload["read_images"])

    def test_build_archives_render_evidence_of_the_previous_pptx(self) -> None:
        pp._runner = RenderRunner(self.work)
        self.assertEqual(pp.cmd_render(self.args()), 0)
        contact = self.work / "contact-sheet.png"
        manifest = pp.load_manifest(self.work)
        assert manifest is not None

        moved = pp.archive_stale_render(self.work, manifest)
        self.assertEqual(3, len(moved))  # 2 page PNGs + the contact sheet
        self.assertFalse(contact.is_file())
        for path in moved:
            self.assertTrue(Path(path).is_file())
            self.assertIn("stale", Path(path).parts)

    def test_archiving_without_render_evidence_is_a_noop(self) -> None:
        manifest = pp.load_manifest(self.work)
        assert manifest is not None
        self.assertEqual([], pp.archive_stale_render(self.work, manifest))


if __name__ == "__main__":
    unittest.main()
