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
        rows = [br.collect(json.loads(p.read_text(encoding="utf-8")), p.parent) for p in sorted(self.root.glob("*/build-manifest.json"))]
        self.assertEqual(rows[0]["builds"], 2)
        self.assertEqual(rows[0]["repairs"], 1)
        self.assertEqual(rows[0]["minutes"], 17.5)
        self.assertTrue(rows[0]["qa_ok"])
        self.assertEqual(rows[0]["packet_fallbacks"], 0)

    def test_advance_ledger_collapses_into_roundtrip_metrics(self) -> None:
        """Batch 3.1: each advance history entry carries the deterministic actions it
        executed. collapsed = actions − calls is the round-trip count the model no
        longer pays; boundaries/refusals/step-caps are reported separately."""
        self.write_manifest(
            "deck-a",
            history=[
                {"command": "plan", "at": "2026-09-15T10:00:00+08:00"},
                {"command": "advance", "status": "needs_agent", "actions": ["build", "render"], "step_cap": False},
                {"command": "advance", "status": "complete", "actions": ["complete"], "step_cap": False},
                {"command": "complete", "at": "2026-09-15T10:17:30+08:00"},
            ],
        )
        self.write_manifest(
            "deck-b",
            history=[
                {"command": "plan", "at": "2026-09-15T10:00:00+08:00"},
                {"command": "advance", "status": "needs_user", "actions": [], "step_cap": False},
                {"command": "advance", "status": "needs_user", "actions": [], "step_cap": True},
                {"command": "advance", "status": "refused", "actions": [], "step_cap": False},
                {"command": "complete", "at": "2026-09-15T10:17:30+08:00"},
            ],
        )
        rows = {row["work_id"]: row for row in (
            br.collect(json.loads(p.read_text(encoding="utf-8")), p.parent)
            for p in sorted(self.root.glob("*/build-manifest.json"))
        )}
        a, b = rows["deck-a"], rows["deck-b"]
        self.assertEqual(2, a["advance_calls"])
        self.assertEqual(3, a["advance_actions"])
        # The build+render call would have cost the model two hand-driven rounds; one
        # advance call replaces both, so collapsed = actions − calls = 1. A call that
        # runs a single action saves nothing, and the metric must not flatter itself.
        self.assertEqual(1, a["advance_collapsed"])
        self.assertEqual(1, a["advance_agent_boundaries"])
        self.assertEqual(0, a["advance_user_boundaries"])
        self.assertEqual(0, a["advance_refusals"])
        self.assertEqual(0, a["advance_step_cap_hits"])
        # Zero-action boundary calls collapse nothing and never go negative.
        self.assertEqual(3, b["advance_calls"])
        self.assertEqual(0, b["advance_collapsed"])
        self.assertEqual(1, b["advance_user_boundaries"])
        self.assertEqual(1, b["advance_step_cap_hits"])
        self.assertEqual(1, b["advance_refusals"])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = br.main(["--work-root", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertIn("adv", buffer.getvalue())
        self.assertIn("col", buffer.getvalue())

    def test_packet_fallbacks_are_counted_per_work_dir(self) -> None:
        """Each fallback entry = one builder that silently gave back Batch 2's
        savings; the report must surface that instead of hiding it."""
        self.write_manifest("deck-a")
        self.write_manifest("deck-b")
        fallbacks = self.root / "deck-b" / "builder-packets"
        fallbacks.mkdir()
        (fallbacks / "fallbacks.json").write_text(
            json.dumps([
                {"at": "2026-09-18T12:00:00+00:00", "mode": "initial", "error": "schema drift"},
                {"at": "2026-09-18T12:01:00+00:00", "mode": "repair", "error": "bad spec"},
            ]),
            encoding="utf-8",
        )
        rows = {row["work_id"]: row for row in (
            br.collect(json.loads(p.read_text(encoding="utf-8")), p.parent)
            for p in sorted(self.root.glob("*/build-manifest.json"))
        )}
        self.assertEqual(0, rows["deck-a"]["packet_fallbacks"])
        self.assertEqual(2, rows["deck-b"]["packet_fallbacks"])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = br.main(["--work-root", str(self.root), "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buffer.getvalue())
        by_id = {row["work_id"]: row["packet_fallbacks"] for row in payload}
        self.assertEqual(2, by_id["deck-b"])

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
