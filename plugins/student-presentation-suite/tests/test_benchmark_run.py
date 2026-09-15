"""Unit tests for benchmark_run: deck resolution, invocation, cost aggregation.

The runner spends real money, so every guard that stops a wasted run is tested
here rather than discovered during a paid session.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_run.py"

_SPEC = importlib.util.spec_from_file_location("benchmark_run", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
br = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("benchmark_run", br)
_SPEC.loader.exec_module(br)

DECKS = {
    "benchmark_version": "1.1",
    "decks": [
        {"id": "course-report-zh", "type": "中文课程汇报", "scope": "A",
         "brief": {"topic": "<课程主题>", "scenario": "coursework", "language": "Chinese",
                   "duration_min": 8, "slide_count": 10}},
        {"id": "thesis-defense", "type": "论文答辩", "scope": "D",
         "materials": "<user-paper-path>",
         "brief": {"topic": "<论文题目>", "scenario": "defense", "language": "Chinese",
                   "duration_min": 12, "slide_count": 12}},
    ],
    "live_baseline_0_10": {"target_tokens": 25000000, "target_peak_context": 150000},
}


class PlaceholderGuardTests(unittest.TestCase):
    def test_placeholder_topic_is_refused(self) -> None:
        deck = DECKS["decks"][0]
        with self.assertRaises(br.RefusedError):
            br.resolve_topic(deck, None)

    def test_override_topic_is_accepted(self) -> None:
        deck = DECKS["decks"][0]
        self.assertEqual("光伏与风电对比", br.resolve_topic(deck, "光伏与风电对比"))

    def test_placeholder_materials_resolve_to_none(self) -> None:
        deck = DECKS["decks"][1]
        self.assertIsNone(br.resolve_materials(deck, None))

    def test_missing_materials_path_is_refused(self) -> None:
        deck = DECKS["decks"][1]
        with self.assertRaises(br.RefusedError):
            br.resolve_materials(deck, "does/not/exist.pdf")

    def test_unknown_deck_id_lists_the_known_ones(self) -> None:
        with self.assertRaises(br.RefusedError) as ctx:
            br.deck_by_id(DECKS, "nope")
        self.assertIn("course-report-zh", str(ctx.exception))


class InvocationTests(unittest.TestCase):
    def test_invocation_pins_work_id_and_forbids_clarifying_questions(self) -> None:
        deck = DECKS["decks"][0]
        text = br.build_invocation(deck, "光伏与风电对比", "course-report-zh", None)
        self.assertIn("/student-presentation-suite:sp-deck", text)
        self.assertIn("work-id: course-report-zh", text)
        self.assertIn("slide count: 10", text)
        self.assertIn("evidence scope: A", text)
        self.assertIn("do not ask any", text)
        self.assertIn("ppt_pipeline.py", text)
        self.assertIn("outputs/.pptx-work/course-report-zh/", text)

    def test_invocation_carries_materials_for_scope_d(self) -> None:
        deck = DECKS["decks"][1]
        text = br.build_invocation(deck, "某论文", "thesis-defense", "C:/paper.pdf")
        self.assertIn("C:/paper.pdf", text)
        self.assertIn("evidence scope: D", text)

    def test_invocation_declares_intake_already_confirmed(self) -> None:
        """The first pilot stalled at intake asking for a topic; say it is done."""
        deck = DECKS["decks"][0]
        intake = {"state_file": "C:/proj/outputs/.student-presentation-state.json",
                  "summary_file": "C:/proj/outputs/.pptx-work/x/production-summary.md"}
        text = br.build_invocation(deck, "光伏与风电", "course-report-zh", None, intake)
        self.assertIn("INTAKE IS ALREADY COMPLETE", text)
        self.assertIn("intake_confirmed", text)
        self.assertIn("do NOT run the intake gate again", text)
        self.assertIn(".student-presentation-state.json", text)

    def test_command_is_budget_and_session_pinned(self) -> None:
        command = br.build_command("claude", "hi", 8.0, None, "abc-123")
        self.assertIn("--plugin-dir", command)
        self.assertIn("--max-budget-usd", command)
        self.assertIn("--session-id", command)
        self.assertIn("abc-123", command)
        self.assertEqual("acceptEdits", command[command.index("--permission-mode") + 1])

    def test_resume_swaps_session_id_for_resume_flag(self) -> None:
        """A resumed run must re-attach, not start a fresh session id."""
        command = br.build_command("claude", "hi", 14.0, None, "abc-123", resume=True)
        self.assertIn("--resume", command)
        self.assertNotIn("--session-id", command)
        self.assertIn("abc-123", command)

    def test_resume_invocation_does_not_redo_finished_stages(self) -> None:
        text = br.resume_invocation("course-report-zh")
        self.assertIn("CONTINUE", text)
        self.assertIn("work-id: course-report-zh", text)
        self.assertIn("ppt_pipeline.py next", text)
        self.assertIn("already exist", text)
        self.assertIn("do not ask any", text)


class ResumeTests(unittest.TestCase):
    def test_dry_run_resume_writes_a_continuation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = br.main([
                "--deck", "course-report-zh", "--resume", "sid-1",
                "--project-dir", tmp, "--run-id", "r", "--dry-run",
            ])
            self.assertEqual(0, rc)
            deck_dir = Path(tmp) / "outputs" / ".benchmark" / "r" / "course-report-zh"
            self.assertIn("CONTINUE", (deck_dir / "invocation.md").read_text(encoding="utf-8"))
            record = json.loads((deck_dir / "record.json").read_text(encoding="utf-8"))
            self.assertTrue(record["resumed"])
            self.assertEqual("sid-1", record["session_id"])

    def test_resume_without_a_deck_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(br.RefusedError) as ctx:
                br.main(["--resume", "sid-1", "--project-dir", tmp, "--run-id", "r"])
            self.assertIn("--deck", str(ctx.exception))

    def test_resumed_run_tolerates_the_placeholder_topic(self) -> None:
        """The original run already resolved a topic; resume must not re-validate it."""
        with tempfile.TemporaryDirectory() as tmp:
            rc = br.main([
                "--deck", "course-report-zh", "--resume", "sid-2",
                "--project-dir", tmp, "--run-id", "r2", "--dry-run",
            ])
            self.assertEqual(0, rc)


class IntakePreparationTests(unittest.TestCase):
    def test_prepare_intake_confirms_the_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            intake = br.prepare_intake(
                project, DECKS["decks"][0], "光伏与风电的度电成本对比", "course-report-zh", None
            )
            summary = Path(intake["summary_file"])
            state = Path(intake["state_file"])
            self.assertTrue(summary.is_file())
            self.assertIn("光伏与风电的度电成本对比", summary.read_text(encoding="utf-8"))
            self.assertEqual(
                intake["summary_sha256"],
                hashlib.sha256(summary.read_bytes()).hexdigest(),
            )
            self.assertTrue(state.is_file())
            payload = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual("intake_confirmed", payload["state"])
            self.assertEqual([step["step"] for step in intake["steps"]], ["init", "confirm"])
            self.assertTrue(all(step["exit_code"] == 0 for step in intake["steps"]))

    def test_state_file_matches_the_pipeline_default_location(self) -> None:
        project = Path("C:/proj")
        self.assertEqual(
            project / "outputs" / ".student-presentation-state.json",
            br.state_file_path(project),
        )


class CostMetricTests(unittest.TestCase):
    def test_usage_is_summed_into_a_context_estimate(self) -> None:
        metrics = br.model_metrics({
            "total_cost_usd": 1.25,
            "num_turns": 40,
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50},
            "session_id": "s",
        })
        self.assertEqual(1.25, metrics["total_cost_usd"])
        self.assertEqual(40, metrics["num_turns"])
        self.assertEqual(1000, metrics["token_context_estimate"])

    def test_model_usage_wins_over_the_empty_top_level_usage(self) -> None:
        """The CLI leaves `usage` at zero and reports real numbers per model."""
        metrics = br.model_metrics({
            "total_cost_usd": 0.09,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "modelUsage": {"deepseek-flash": {
                "inputTokens": 737, "outputTokens": 126, "cacheReadInputTokens": 5000,
            }},
        })
        self.assertEqual(["deepseek-flash"], metrics["models"])
        self.assertEqual(737 + 5000, metrics["token_context_estimate"])
        self.assertEqual(126, metrics["token_breakdown"]["output"])
        self.assertEqual(0, metrics["token_breakdown"]["cache_creation"])

    def test_missing_usage_does_not_invent_numbers(self) -> None:
        metrics = br.model_metrics({})
        self.assertEqual(0, metrics["token_context_estimate"])
        self.assertIsNone(metrics["total_cost_usd"])

    def test_npm_cmd_shim_is_not_accepted_as_the_cli(self) -> None:
        """The .cmd wrapper drops --output-format json, so cost metrics go empty."""
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "claude.cmd"
            shim.write_text("@echo off\n", encoding="utf-8")
            previous = os.environ.get("CLAUDE_BIN")
            os.environ["CLAUDE_BIN"] = str(shim)
            try:
                resolved = br.find_claude()
            finally:
                if previous is None:
                    os.environ.pop("CLAUDE_BIN", None)
                else:
                    os.environ["CLAUDE_BIN"] = previous
        resolved = resolved or ""
        self.assertFalse(resolved.lower().endswith((".cmd", ".bat", ".ps1")))

    def test_manifest_metrics_reports_absence_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = br.manifest_metrics(Path(tmp), "deck-x")
        self.assertFalse(metrics["manifest_found"])
        self.assertIn("deck-x", metrics["manifest_path"])

    def test_manifest_metrics_collects_pipeline_and_reuse_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "outputs" / ".pptx-work" / "deck-x"
            work.mkdir(parents=True)
            (work / br.MANIFEST_NAME).write_text(json.dumps({
                "work_id": "deck-x",
                "manifest_version": "1.1",
                "state": "complete",
                "build": {"build_count": 2, "repair_count": 1, "pptx": {"path": "deck.pptx"}},
                "render": {"page_count": 10},
                "qa": {"ok": True, "blockers": 0, "stage_cost_ms": {"package": 1000}},
                "history": [
                    {"command": "plan", "at": "2026-09-15T10:00:00+00:00"},
                    {"command": "build", "at": "2026-09-15T10:05:00+00:00", "stale_render_moved": 3},
                    {"command": "render", "at": "2026-09-15T10:06:00+00:00"},
                    {"command": "render", "at": "2026-09-15T10:07:00+00:00", "reused": True},
                    {"command": "qa", "at": "2026-09-15T10:09:00+00:00"},
                    {"command": "complete", "at": "2026-09-15T10:17:00+00:00"},
                ],
            }), encoding="utf-8")
            metrics = br.manifest_metrics(Path(tmp), "deck-x")
        self.assertTrue(metrics["manifest_found"])
        self.assertEqual(2, metrics["builds"])
        self.assertEqual(1, metrics["repairs"])
        self.assertEqual(1, metrics["render_events"])
        self.assertEqual(1, metrics["render_reused"])
        self.assertEqual(3, metrics["stale_evidence_moved"])
        self.assertEqual(17.0, metrics["minutes"])


class AggregateTests(unittest.TestCase):
    def test_totals_sum_only_real_runs(self) -> None:
        records = [
            {"deck_id": "a", "dry_run": False, "state": "ok", "metrics": {
                "builds": 2, "repairs": 1, "render_events": 2, "render_reused": 1,
                "qa_events": 2, "qa_reused": 1, "stale_evidence_moved": 3,
                "final_blockers": 0, "num_turns": 40, "token_context_estimate": 1000,
                "total_cost_usd": 1.5}},
            {"deck_id": "b", "dry_run": True, "metrics": {}},
        ]
        report = br.aggregate(records, DECKS, "0.11.2")
        self.assertEqual(1, report["decks_run"])
        self.assertEqual(2, report["decks_expected"])
        self.assertEqual(2, report["totals"]["builds"])
        self.assertEqual(1, report["totals"]["render_reused"])
        self.assertEqual(1000, report["totals"]["token_context_estimate"])
        self.assertEqual(1.5, report["totals"]["cost_usd"])
        self.assertEqual(1, report["totals"]["complete_decks"])
        self.assertEqual(0, report["totals"]["truncated_decks"])
        self.assertEqual(25000000, report["targets"]["target_tokens_per_deck"])

    def test_truncated_decks_are_flagged_as_lower_bounds(self) -> None:
        """A budget-truncated run must never be reported as a full-deck figure."""
        records = [
            {"deck_id": "done", "dry_run": False, "state": "ok",
             "metrics": {"total_cost_usd": 2.0, "num_turns": 30, "token_context_estimate": 500}},
            {"deck_id": "cut", "dry_run": False, "state": "attention",
             "metrics": {"total_cost_usd": 8.04, "num_turns": 73, "token_context_estimate": 8948302,
                         "terminal_reason": "budget_exhausted", "state": "producing"}},
        ]
        report = br.aggregate(records, DECKS, "0.11.1")
        self.assertEqual(1, report["totals"]["complete_decks"])
        self.assertEqual(1, report["totals"]["truncated_decks"])
        self.assertFalse(report["comparable"])
        self.assertEqual("cut", report["truncated"][0]["deck_id"])
        self.assertEqual("budget_exhausted", report["truncated"][0]["terminal_reason"])
        self.assertIn("lower bound", report["truncated"][0]["note"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_writes_the_invocation_and_spends_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = br.main([
                "--deck", "course-report-zh", "--topic", "光伏与风电对比",
                "--project-dir", tmp, "--run-id", "dry", "--dry-run",
            ])
            self.assertEqual(0, rc)
            deck_dir = Path(tmp) / "outputs" / ".benchmark" / "dry" / "course-report-zh"
            invocation = (deck_dir / "invocation.md").read_text(encoding="utf-8")
            self.assertIn("光伏与风电对比", invocation)
            record = json.loads((deck_dir / "record.json").read_text(encoding="utf-8"))
            self.assertTrue(record["dry_run"])
            self.assertEqual("dry-run", record["state"])

    def test_all_without_topics_is_refused_before_spending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(br.RefusedError) as ctx:
                br.main(["--all", "--project-dir", tmp, "--run-id", "x"])
            self.assertIn("placeholder", str(ctx.exception))

    def test_report_only_aggregates_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "outputs" / ".benchmark" / "r1" / "deck-x"
            run_dir.mkdir(parents=True)
            (run_dir / "record.json").write_text(json.dumps({
                "deck_id": "deck-x", "dry_run": False,
                "metrics": {"builds": 1, "total_cost_usd": 0.5},
            }), encoding="utf-8")
            self.assertEqual(0, br.main(["--report", "--project-dir", tmp, "--run-id", "r1"]))


if __name__ == "__main__":
    unittest.main()
