"""Unit tests for pipeline_report: manifest aggregation and table rendering."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pipeline_report.py"

_SPEC = importlib.util.spec_from_file_location("pipeline_report", SCRIPT)
br = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("pipeline_report", br)
_SPEC.loader.exec_module(br)


class PipelineReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ".pptx-work"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_manifest(self, work_id: str, **overrides: object) -> None:
        manifest: dict[str, object] = {
            "work_id": work_id,
            "state": "complete",
            "build": {"build_count": 2, "repair_count": 1},
            "qa": {"ok": True, "blockers": 0},
            "history": [
                {"command": "plan", "at": "2026-09-15T10:00:00+08:00"},
                {"command": "complete", "at": "2026-09-15T10:17:30+08:00"},
            ],
        }
        manifest.update(overrides)
        work = self.root / work_id
        work.mkdir(parents=True)
        (work / br.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    def test_collect_reads_counts_and_minutes(self) -> None:
        self.write_manifest("deck-a")
        rows = [br.collect(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(self.root.glob("*/build-manifest.json"))]
        self.assertEqual(rows[0]["builds"], 2)
        self.assertEqual(rows[0]["repairs"], 1)
        self.assertEqual(rows[0]["minutes"], 17.5)
        self.assertTrue(rows[0]["qa_ok"])

    def test_render_totals_all_decks(self) -> None:
        self.write_manifest("deck-a")
        self.write_manifest("deck-b", build={"build_count": 3, "repair_count": 0}, qa={"ok": False, "blockers": 4})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = br.main(["--work-root", str(self.root)])
        out = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("TOTAL (2 decks)", out)
        self.assertIn(" 5", out)  # builds total
        self.assertIn(" 4", out)  # blockers total

    def test_no_manifests_fails(self) -> None:
        with redirect_stdout(io.StringIO()) as _:
            pass
        import contextlib

        with contextlib.redirect_stderr(io.StringIO()):
            rc = br.main(["--work-root", str(self.root)])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
