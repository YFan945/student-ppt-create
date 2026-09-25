"""CD-8 runtime cost brake: live usage, threshold breaches, handoff, rotation."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for entry in (str(ROOT / "scripts"), str(ROOT / "skills" / "sp-deck" / "scripts"), str(TESTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import session_cost  # noqa: E402
import test_ppt_pipeline as tpp  # noqa: E402
from pipeline import handoff  # noqa: E402


def model_io_row(input_tokens: int, cache_read: int = 0, output: int = 0) -> str:
    return json.dumps({
        "startedAt": "2026-09-22T08:00:00.000Z",
        "completedAt": "2026-09-22T08:00:10.000Z",
        "model": {"modelId": "mimo-v2.6-flash"},
        "response": {"usage": {
            "inputTokens": input_tokens,
            "cacheReadTokens": cache_read,
            "outputTokens": output,
            "totalTokens": input_tokens + output,
        }},
    })


def usage_snapshot(**over):
    snapshot = {
        "source": "C:/fake/rollout/model-io-sess-a.jsonl",
        "source_kind": "model-io",
        "requests": 120,
        "fresh_input": 500_000,
        "cache_read": 25_000_000,
        "output": 125_000,
        "peak_context": 287_000,
        "elapsed_s": 12_600.0,
        "elapsed_minutes": 210.0,
        "task_total_tokens": 34_300_000,
        "subagent_tokens": 8_700_000,
        "subagent_files": 13,
    }
    snapshot.update(over)
    return snapshot


class ScanModelIoTests(unittest.TestCase):
    def test_scan_totals_requests_and_peak_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "model-io-sess-x.jsonl"
            log.write_text(
                model_io_row(38_000, cache_read=32_000, output=100) + "\n"
                + model_io_row(287_000, cache_read=280_000, output=80) + "\n",
                encoding="utf-8",
            )
            data = session_cost.scan_model_io(log)
        self.assertEqual(data["requests"], 2)
        self.assertEqual(data["peak_input_tokens"], 287_000)
        self.assertEqual(data["usage"]["inputTokens"], 325_000)
        self.assertEqual(data["usage"]["outputTokens"], 180)
        self.assertEqual(data["elapsed_seconds"], 10.0)

    def test_current_session_usage_discovers_zcode_and_folds_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as empty:
            rollout = Path(tmp)
            (rollout / "model-io-sess_a.jsonl").write_text(
                model_io_row(100_000, cache_read=90_000, output=10) + "\n", encoding="utf-8"
            )
            (rollout / "model-io-sess_subagent_agent_z.jsonl").write_text(
                model_io_row(50_000, cache_read=1, output=5) + "\n", encoding="utf-8"
            )
            snapshot = session_cost.current_session_usage(
                zcode_rollout=rollout, claude_root=Path(empty)
            )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["source_kind"], "model-io")
        self.assertEqual(snapshot["requests"], 1)
        self.assertEqual(snapshot["peak_context"], 100_000)
        self.assertEqual(snapshot["fresh_input"], 10_000)
        self.assertEqual(snapshot["subagent_files"], 1)
        self.assertEqual(snapshot["task_total_tokens"], 100_010 + 50_005)

    def test_no_sources_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertIsNone(
                session_cost.current_session_usage(
                    zcode_rollout=Path(a), claude_root=Path(b)
                )
            )


class BrakeStateTests(unittest.TestCase):
    def test_clean_usage_passes(self) -> None:
        status, detail = handoff.brake_state({}, usage_snapshot(
            peak_context=120_000, elapsed_minutes=30, task_total_tokens=1_000_000
        ))
        self.assertEqual(status, "ok")
        self.assertEqual(detail["breaches"], [])

    def test_every_threshold_is_named(self) -> None:
        status, detail = handoff.brake_state({}, usage_snapshot())
        self.assertEqual(status, "rotate")
        joined = "\n".join(detail["breaches"])
        self.assertIn("peak context", joined)
        self.assertIn("session ran", joined)
        self.assertIn("task total", joined)

    def test_missing_usage_degrades_to_ok(self) -> None:
        self.assertEqual(handoff.brake_state({}, None)[0], "ok")

    def test_new_transcript_source_releases_the_brake(self) -> None:
        manifest = {"session_brake": {"status": "breached", "source": "sess-a", "breaches": ["x"]}}
        status, detail = handoff.brake_state(manifest, usage_snapshot(source="sess-b"))
        self.assertEqual(status, "ok")
        self.assertEqual(detail["released"], "new-session")

    def test_ack_flag_releases_on_the_same_source(self) -> None:
        manifest = {
            "session_brake": {"status": "breached", "source": "sess-a", "ack": True},
        }
        status, detail = handoff.brake_state(manifest, usage_snapshot(source="sess-a"))
        self.assertEqual(status, "ok")
        self.assertEqual(detail["released"], "resume-after-handoff")

    def test_still_breached_on_the_same_source(self) -> None:
        manifest = {"session_brake": {"status": "breached", "source": "sess-a"}}
        status, _ = handoff.brake_state(manifest, usage_snapshot(source="sess-a"))
        self.assertEqual(status, "rotate")


class SessionBrakeIntegrationTests(tpp.PipelineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.files = self.write_inputs()
        self.plan(self.files)

    def run_advance(self, usage, extra: list[str] | None = None):
        stdout, stderr = io.StringIO(), io.StringIO()
        flags = ["--json"] if extra is None else extra
        with (
            patch("pipeline.dispatch.current_usage", return_value=usage),
            patch("pipeline.advance.current_usage", return_value=usage),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = tpp.pp.main([
                "advance", "--work-dir", str(self.work), *flags,
            ])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_breach_blocks_advance_and_writes_the_handoff(self) -> None:
        code, out, _ = self.run_advance(usage_snapshot())
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual(result["status"], "session_rotate")
        self.assertTrue(result["breaches"])
        handoff_md = Path(result["handoff"]["path"])
        self.assertTrue(handoff_md.is_file())
        body = handoff_md.read_text(encoding="utf-8")
        self.assertIn("work-01", body)
        self.assertIn("resume", body)
        self.assertIn("peak context", body)
        manifest = self.manifest()
        self.assertEqual(manifest["session_brake"]["status"], "breached")
        self.assertEqual(
            [h["status"] for h in manifest["history"] if h.get("command") == "advance"],
            ["session_rotate"],
        )
        report = self.collect_report()
        self.assertEqual(report["advance_session_rotations"], 1)

    def collect_report(self) -> dict:
        import pipeline_report  # noqa: PLC0415

        return pipeline_report.collect(self.manifest(), self.work)

    def test_a_real_new_session_releases_automatically(self) -> None:
        self.assertEqual(self.run_advance(usage_snapshot())[0], 2)
        clean = usage_snapshot(
            source="C:/fake/rollout/model-io-sess-b.jsonl",
            peak_context=100_000, elapsed_minutes=5, task_total_tokens=100_000,
        )
        code, out, _ = self.run_advance(clean)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "needs_agent")
        self.assertEqual(self.manifest()["session_brake"]["status"], "released")

    def test_resume_after_handoff_unlocks_explicitly(self) -> None:
        self.assertEqual(self.run_advance(usage_snapshot())[0], 2)
        code, out, _ = self.run_advance(
            usage_snapshot(), ["--json", "--resume-after-handoff"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "needs_agent")
        self.assertEqual(self.manifest()["session_brake"]["status"], "acked")

    def test_advance_defaults_to_the_brief(self) -> None:
        code, out, err = self.run_advance(
            usage_snapshot(
                peak_context=100_000, elapsed_minutes=5, task_total_tokens=100_000
            ),
            ["--brief-json"],
        )
        self.assertEqual(code, 0)
        brief = json.loads(out)
        self.assertEqual(brief["status"], "needs_agent")
        self.assertIn("state", brief)
        self.assertIn("usage", brief)
        self.assertIn("estimate_minutes_remaining", brief["usage"])
        self.assertNotIn("dispatch", brief)
        self.assertIn("advance →", err)

    def test_brief_json_flag_still_accepted_as_an_alias(self) -> None:
        clean = usage_snapshot(
            peak_context=100_000, elapsed_minutes=5, task_total_tokens=100_000
        )
        code, out, _ = self.run_advance(clean, ["--brief-json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "needs_agent")
        code, out, _ = self.run_advance(clean, [])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "needs_agent")


class HandoffContentTests(tpp.PipelineTestCase):
    def test_handoff_json_carries_the_resume_recipe(self) -> None:
        self.files = self.write_inputs()
        self.plan(self.files)
        usage = usage_snapshot()
        paths = handoff.write_session_handoff(self.work, self.manifest(), usage)
        payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["work_id"], "work-01")
        self.assertEqual(payload["state"], "planned")
        self.assertIsInstance(payload["next_command"], str)
        self.assertIn("--resume-after-handoff", payload["resume_command"])
        self.assertTrue(payload["usage"]["breaches"])
        self.assertTrue(payload["estimate"]["remaining_stages"])


if __name__ == "__main__":
    unittest.main()
