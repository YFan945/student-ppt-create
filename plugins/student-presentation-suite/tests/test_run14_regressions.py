"""Run-14 live defects (2026-10-04 run, E:\\Daima_Codes\\14) — regression pins.

Six plugin bugs + friction items from the 43-minute rigorous deck run that
ended at the calibration boundary with no deliverable:
hook stdin mojibake, terminal --help refusals, calibration preview glue vs
declarative pages, advance re-requesting a builder after BUILDER_DONE, the
missing research-task rebind path, fetch-text concurrent report clobber, and
the stall timer punishing in-flight parallel retrieval batches.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import test_helpers
from test_helpers import load_module

ROOT = test_helpers.ROOT if hasattr(test_helpers, "ROOT") else Path(__file__).resolve().parents[1]
if not (ROOT / "scripts" / "hook_events.py").is_file():
    ROOT = Path(__file__).resolve().parents[1]

hook_events = load_module(ROOT / "scripts" / "hook_events.py")
entry_guard = load_module(ROOT / "scripts" / "production_entry_guard.py")
cost_guard = load_module(ROOT / "scripts" / "cost_guard.py")
controller = load_module(ROOT / "scripts" / "research_control.py")
fetch_text = load_module(ROOT / "shared" / "pptx_runtime" / "fetch_text.py")


class HookEventUtf8Tests(unittest.TestCase):
    """Guard ledgers recorded mojibake paths on non-ASCII Windows projects."""

    def test_utf8_event_keeps_non_ascii_paths(self):
        payload = json.dumps(
            {"tool_name": "Read", "tool_input": {"file_path": "E:\\1学习资料\\代码\\research-task.json"}},
            ensure_ascii=False,
        ).encode("utf-8")

        class FakeStdin:
            buffer = io.BytesIO(payload)

        stdin_backup = sys.stdin
        sys.stdin = FakeStdin()
        try:
            event = hook_events.read_event()
        finally:
            sys.stdin = stdin_backup
        self.assertEqual("E:\\1学习资料\\代码\\research-task.json", event["tool_input"]["file_path"])

    def test_malformed_or_empty_payload_yields_empty_event(self):
        class FakeStdin:
            buffer = io.BytesIO(b"\xff\xfe not json")

        stdin_backup = sys.stdin
        sys.stdin = FakeStdin()
        try:
            self.assertEqual({}, hook_events.read_event())
            FakeStdin.buffer = io.BytesIO(b"")
            self.assertEqual({}, hook_events.read_event())
        finally:
            sys.stdin = stdin_backup


class TerminalHelpProbeTests(unittest.TestCase):
    """`script --help` is a read-only usage print, not a production invocation."""

    def test_probe_regex_matches_only_terminal_help(self):
        self.assertTrue(hook_events.terminal_help_probe('python "C:/x/copy_fit_preflight.py" --help'))
        self.assertTrue(hook_events.terminal_help_probe('python "C:/x/ppt_pipeline.py" -h'))
        self.assertFalse(hook_events.terminal_help_probe('python "C:/x/copy_fit_preflight.py"'))
        self.assertFalse(hook_events.terminal_help_probe('python "C:/x/build.py" --work-dir w'))

    def test_production_entry_guard_allows_pure_help_probe(self):
        cmd = 'python "C:/cache/student-presentation-suite/0.25.2/skills/sp-deck/scripts/copy_fit_preflight.py" --help'
        self.assertIsNone(entry_guard.check_bash(cmd))
        bare = 'python "C:/cache/student-presentation-suite/0.25.2/skills/sp-deck/scripts/copy_fit_preflight.py"'
        self.assertIsNotNone(entry_guard.check_bash(bare))

    def test_production_entry_guard_allows_ppt_pipeline_help(self):
        cmd = 'python "C:/cache/student-presentation-suite/0.25.2/skills/sp-deck/scripts/ppt_pipeline.py" --help'
        self.assertIsNone(entry_guard.check_bash(cmd))

    def test_cost_guard_allows_terminal_help_for_builder(self):
        cmd = 'python "C:/cache/student-presentation-suite/0.25.2/skills/sp-deck/scripts/check_page_module.js" --help'
        self.assertIsNone(cost_guard.check_bash(cmd, builder=True))


class CalibrationPreviewGlueTests(unittest.TestCase):
    """The preview deck template must run declarative pages like production deck.js."""

    def test_generated_deck_has_dual_branch(self):
        preview = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "calibration_preview.py")
        node = shutil_which("node")
        with TemporaryDirectory() as tmp:
            page = Path(tmp) / "p01-cover.js"
            page.write_text("module.exports = { dark: false, kind: 'content', layout: 'text-two-column', slots: {}, params: {}, notes: '' };", encoding="utf-8")
            target = Path(tmp) / "calibration-deck.js"
            preview.write_calibration_deck(target, [(1, page)], "{}")
            source = target.read_text(encoding="utf-8")
            if node:
                check = subprocess.run([node, "--check", str(target)], capture_output=True, text=True)
                self.assertEqual(0, check.returncode, check.stderr)
        self.assertIn("typeof item.mod === 'function'", source)
        self.assertIn("L.renderDeclaredPage(ctx, item.mod)", source)


class StallTurnaroundTests(unittest.TestCase):
    """Stall is judged after an in-flight batch could have returned, not raw elapsed."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / "research-task.json").write_text(
            json.dumps({"budget": "standard", "stall_timeout_seconds": 60}), encoding="utf-8"
        )

    def test_in_flight_batch_is_not_stalled(self):
        # last progress 80s ago, stall line 60s — but a batch issued seconds ago
        # cannot have produced pack progress yet, so the 30s turnaround applies.
        controller.status(self.work, now=10, retrieval=True)
        decision = controller.status(self.work, now=90)
        self.assertEqual("active", decision["state"])

    def test_persistent_silence_still_stalls(self):
        controller.status(self.work, now=10, retrieval=True)
        decision = controller.status(self.work, now=140)
        self.assertEqual("stop_requested", decision["state"])
        self.assertEqual("no_useful_progress", decision["reason"])


class RebindTests(unittest.TestCase):
    """The sanctioned escape from 'task changed after researcher spawn'."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.task = self.work / "research-task.json"
        self.task.write_text(json.dumps({"budget": "simple", "claims": []}), encoding="utf-8")
        self.binding = self.work / "research-task-binding.json"
        self.old_sha = "f12eef0022791662e42ed78aa4136f853d947bf79a387e5c1c682f8a97708d71"
        self.binding.write_text(json.dumps({"path": str(self.task), "session_id": "s1", "sha256": self.old_sha}), encoding="utf-8")
        self._validate_backup = controller.validate_task
        controller.validate_task = lambda _task, _path: []
        self.addCleanup(setattr, controller, "validate_task", self._validate_backup)

    def test_rebind_archives_old_binding_and_records_history(self):
        controller.rebind(self.work, "spec no longer asserts the unresolved LCOE dimension; demoted C05 to supporting")
        new_sha = controller.hashlib.sha256(self.task.read_bytes()).hexdigest()
        binding = json.loads(self.binding.read_text(encoding="utf-8"))
        self.assertEqual(new_sha, binding["sha256"])
        self.assertEqual(self.old_sha, binding["rebound_from"])
        self.assertEqual("s1", binding["session_id"])
        archive = self.work / f"research-task-binding.superseded-{self.old_sha[:8]}.json"
        self.assertTrue(archive.is_file())
        self.assertEqual(self.old_sha, json.loads(archive.read_text(encoding="utf-8"))["sha256"])
        control = json.loads((self.work / "research-control.json").read_text(encoding="utf-8"))
        self.assertEqual(new_sha, control["task_sha256"])
        self.assertEqual(self.old_sha, control["rebinds"][0]["from"])

    def test_rebind_is_noop_when_hash_already_matches(self):
        import hashlib
        self.binding.write_text(json.dumps({
            "path": str(self.task), "session_id": "s1",
            "sha256": hashlib.sha256(self.task.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        result = json.loads(self._capture_rebind_stdout())
        self.assertFalse(result["rebound"])

    def _capture_rebind_stdout(self) -> str:
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            controller.rebind(self.work, "converged task bytes are already bound; no archive needed")
        return buffer.getvalue()

    def test_rebind_requires_a_concrete_reason(self):
        with self.assertRaises(ValueError):
            controller.rebind(self.work, "short")

    def test_rebind_refuses_without_a_binding(self):
        self.binding.unlink()
        with self.assertRaises(ValueError):
            controller.rebind(self.work, "spec no longer asserts the unresolved LCOE dimension")


class FetchReportDedupTests(unittest.TestCase):
    """Concurrent fetches of one URL must not leave contradictory records."""

    def test_newest_attempt_wins_per_url_and_scope(self):
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fetch_text.write_report({"scope": "A", "records": [
                {"url": "https://a.example/x", "scope": "A", "ok": False, "reason": "http_error", "fetched_at": "t1"},
            ]}, out_dir)
            fetch_text.write_report({"scope": "A", "records": [
                {"url": "https://a.example/x", "scope": "A", "ok": True, "fetched_at": "t2"},
                {"url": "https://b.example/y", "scope": "A", "ok": True, "fetched_at": "t3"},
            ]}, out_dir)
            report = json.loads((out_dir / "fetch-text-report.json").read_text(encoding="utf-8"))
        records = report["records"]
        self.assertEqual(2, len(records), records)
        by_url = {r["url"]: r for r in records}
        self.assertTrue(by_url["https://a.example/x"]["ok"])
        self.assertEqual("t2", by_url["https://a.example/x"]["fetched_at"])


class ValidateResearchTaskJsonFlagTests(unittest.TestCase):
    def test_json_flag_is_accepted(self):
        with TemporaryDirectory() as tmp:
            task = Path(tmp) / "research-task.json"
            task.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_research_task.py"), str(task), "--json"],
                capture_output=True, text=True,
            )
        self.assertIn('"ok": false', result.stdout)  # argparse would print usage instead


def shutil_which(name: str):
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    unittest.main()
