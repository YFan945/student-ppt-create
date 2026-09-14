"""Tests for ppt_pipeline render orchestration without LibreOffice."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
