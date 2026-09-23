"""session_cost.py 的成本画像契约。

成本复盘的价值全在数字准不准：乘法模型（请求数 × 平均常驻上下文）、整文件重写
检测、以及"哪些问题项被算出来"必须可回归。这里用一份合成 transcript 把口径钉住。
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_helpers import load_module  # noqa: E402

SESSION_COST = load_module(ROOT / "scripts" / "session_cost.py")

T0 = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
DECK = "C:/work/deck.js"


def tool_use(uid: str, name: str, target: str) -> dict:
    return {"type": "tool_use", "id": uid, "name": name, "input": {"file_path": target}}


def assistant(step: int, context: int, content: list[dict], message_id: str | None = None) -> dict:
    message: dict = {
        "usage": {
            "input_tokens": 1_000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": context - 1_000,
            "output_tokens": 100,
        },
        "content": content,
    }
    if message_id:
        message["id"] = message_id
    return {
        "type": "assistant",
        "timestamp": (T0 + timedelta(seconds=step * 4)).isoformat(),
        "message": message,
    }


def tool_result(uid: str, text: str, step: int) -> dict:
    return {
        "type": "user",
        "timestamp": (T0 + timedelta(seconds=step * 4 + 1)).isoformat(),
        "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]},
    }


def build_transcript(path: Path) -> None:
    records = [
        assistant(0, 10_000, [tool_use("t1", "Write", DECK)]),
        tool_result("t1", "written", 0),
        assistant(1, 250_000, [tool_use("t2", "Write", DECK), tool_use("t3", "Edit", DECK)]),
        tool_result("t2", "written", 1),
        tool_result("t3", "edited", 1),
        assistant(2, 300_000, []),
    ]
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


class SessionCostTests(unittest.TestCase):
    def test_model_io_stream_reports_cache_and_tool_counts(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model-io.jsonl"
            rows = [
                {"startedAt": "2026-09-22T08:00:00Z", "completedAt": "2026-09-22T08:00:05Z",
                 "model": {"modelId": "test"}, "response": {"usage": {
                     "inputTokens": 100, "cacheReadTokens": 80, "outputTokens": 10, "totalTokens": 110,
                 }, "toolCalls": [{"name": "WebFetch"}]}},
                {"startedAt": "2026-09-22T08:00:05Z", "completedAt": "2026-09-22T08:00:10Z",
                 "model": {"modelId": "test"}, "response": {"usage": {
                     "inputTokens": 120, "cacheReadTokens": 100, "outputTokens": 5, "totalTokens": 125,
                 }, "toolCalls": []}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            summary = SESSION_COST.profile_model_io(path)
            self.assertEqual(235, summary["usage"]["totalTokens"])
            self.assertEqual(180, summary["usage"]["cacheReadTokens"])
            self.assertEqual(120, summary["peak_input_tokens"])
            self.assertEqual(10.0, summary["elapsed_seconds"])
            self.assertEqual(1, summary["tool_calls"]["WebFetch"])
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.transcript = Path(self._tmp.name) / "session.jsonl"
        build_transcript(self.transcript)
        self.summary = SESSION_COST.profile(SESSION_COST.read_records(self.transcript))

    def invoke(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = SESSION_COST.main(argv)
        return code, buffer.getvalue()

    def test_request_and_token_ledger(self) -> None:
        tokens = self.summary["tokens"]
        self.assertEqual(3, self.summary["requests"])
        self.assertEqual(3, self.summary["tool_calls"])
        self.assertEqual(3_000, tokens["fresh_input"])
        self.assertEqual(557_000, tokens["cache_read"])
        self.assertEqual(300, tokens["output"])
        self.assertEqual(560_300, tokens["total"])

    def test_context_statistics_and_buckets(self) -> None:
        context = self.summary["context"]
        self.assertEqual(186_667, context["average"])
        self.assertEqual(250_000, context["median"])
        self.assertEqual(300_000, context["peak"])
        self.assertEqual(2, context["heavy_requests"])
        self.assertEqual({"<40K": 1, "200K+": 2}, context["buckets"])
        self.assertEqual(2.67, self.summary["per_request_sec"])

    def test_multiplication_model_matches_the_measured_total(self) -> None:
        predicted = self.summary["requests"] * self.summary["context"]["average"]
        self.assertAlmostEqual(self.summary["tokens"]["total"], predicted, delta=1_000)

    def test_whole_file_rewrite_is_detected_but_in_place_edits_are_not(self) -> None:
        self.assertEqual([{"file": DECK, "writes": 2}], self.summary["rewritten_files"])
        self.assertEqual({DECK: 1}, self.summary["in_place_edits"])
        self.assertEqual(1, self.summary["written_files"])
        notes = SESSION_COST.warnings(self.summary)
        self.assertTrue(any("整文件重写" in note for note in notes), notes)
        self.assertTrue(any("上下文 ≥20 万" in note for note in notes), notes)

    def test_tool_aggregate_keeps_per_tool_byte_and_time_costs(self) -> None:
        self.assertIn("Write", self.summary["by_tool"])
        self.assertEqual(2, self.summary["by_tool"]["Write"]["calls"])
        self.assertEqual(1, self.summary["by_tool"]["Edit"]["calls"])
        self.assertEqual([1, 2, 3], [point["request"] for point in self.summary["context_curve"]])
        self.assertEqual(10_000, self.summary["context_curve"][0]["context"])

    def test_json_mode_is_machine_readable(self) -> None:
        code, stdout = self.invoke(["--session", str(self.transcript), "--json"])
        self.assertEqual(0, code)
        payload = json.loads(stdout)
        self.assertEqual(3, payload["requests"])
        self.assertEqual(560_300, payload["tokens"]["total"])
        self.assertIn("warnings", payload)

    def test_markdown_mode_reports_headline_and_warnings(self) -> None:
        code, stdout = self.invoke(["--session", str(self.transcript)])
        self.assertEqual(0, code)
        self.assertIn("# Session cost report", stdout)
        self.assertIn("乘法模型", stdout)
        self.assertIn("## Warnings", stdout)
        self.assertIn("整文件重写", stdout)

    def test_list_mode_survives_an_empty_root(self) -> None:
        with TemporaryDirectory() as empty:
            code, stdout = self.invoke(["--list", "--sessions-root", empty])
            self.assertEqual(0, code)
            self.assertEqual("", stdout)

    def test_recent_session_is_picked_from_a_sessions_root(self) -> None:
        code, stdout = self.invoke(["--sessions-root", self._tmp.name, "--last", "1"])
        self.assertEqual(0, code)
        self.assertIn("requests: **3**", stdout)

    def test_streaming_partials_of_one_call_count_as_one_turn(self) -> None:
        """Claude Code writes one API call as several rows; only the last carries the prompt.

        2026-09-18: reading the first row instead reported a subagent as 480 requests where
        261 were sent, and inflated every per-turn figure derived from it by ~1.8x.
        """
        path = Path(self._tmp.name) / "partials.jsonl"
        records = [
            assistant(0, 68_666, [{"type": "thinking", "thinking": "x" * 40}], "msg_one"),
            assistant(1, 699_497, [tool_use("t1", "Bash", DECK)], "msg_one"),
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(1, summary["turns"], "one API call, one turn")
        self.assertEqual(699_497, summary["context"]["peak"])
        self.assertEqual(699_497 + 100, summary["tokens"]["total"])

    def test_parallel_calls_split_across_rows_still_count_as_one_batch(self) -> None:
        """A batching session must not be reported as "one call per turn".

        The rows of one message carry DISJOINT content blocks, so summing per row caps at 1:
        an earlier version reported max 1 call/turn where the transcript actually contained
        batches of up to 8, which would have sent a time-budget decision the wrong way.
        """
        path = Path(self._tmp.name) / "batched-rows.jsonl"
        records = [
            assistant(0, 50_000, [tool_use("p1", "Read", DECK)], "msg_b"),
            assistant(1, 50_100, [tool_use("p2", "Read", DECK)], "msg_b"),
            assistant(2, 50_200, [tool_use("p3", "Read", DECK)], "msg_b"),
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(1, summary["turns"])
        self.assertEqual(3.0, summary["tool_calls_per_turn"])
        self.assertEqual(3, summary["largest_batch"])
        self.assertEqual(1, summary["batched_turns"])

    def test_turn_economy_is_reported(self) -> None:
        """Wall clock is turns x round-trip latency, so this is the time-budget metric."""
        self.assertEqual(3, self.summary["turns"])
        self.assertEqual(1.0, self.summary["tool_calls_per_turn"])
        self.assertIn("median", self.summary["turn_seconds"])
        self.assertIsNotNone(self.summary["turns_under_20min"]["at_median"])

    def test_batching_is_visible_in_the_per_turn_ratio(self) -> None:
        path = Path(self._tmp.name) / "batched.jsonl"
        records = [
            assistant(0, 10_000, [tool_use("b1", "Read", DECK), tool_use("b2", "Read", DECK),
                                  tool_use("b3", "Read", DECK)], "msg_batch"),
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(3.0, summary["tool_calls_per_turn"])

    def test_a_slow_batching_session_is_flagged(self) -> None:
        """A 3-turn fixture is not worth flagging; a real run is."""
        path = Path(self._tmp.name) / "many-turns.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for step in range(45):
                stream.write(
                    json.dumps(
                        assistant(step, 60_000, [tool_use(f"c{step}", "Read", DECK)], f"msg_{step}"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(45, summary["turns"])
        self.assertEqual(1.0, summary["tool_calls_per_turn"])
        notes = " ".join(SESSION_COST.warnings(summary))
        self.assertIn("回合经济", notes)

    def test_a_batching_session_is_not_flagged(self) -> None:
        path = Path(self._tmp.name) / "many-batched.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for step in range(45):
                stream.write(
                    json.dumps(
                        assistant(step, 60_000, [
                            tool_use(f"d{step}a", "Read", DECK),
                            tool_use(f"d{step}b", "Read", DECK),
                            tool_use(f"d{step}c", "Read", DECK),
                        ], f"msg_b{step}"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(3.0, summary["tool_calls_per_turn"])
        self.assertNotIn("回合经济", " ".join(SESSION_COST.warnings(summary)))

    def test_deterministic_roundtrips_are_counted_per_turn(self) -> None:
        """Batch 0 metric: turns whose every call just drives a deterministic pipeline
        command are the population `ppt_pipeline.py advance` should absorb."""
        def bash(uid: str, command: str) -> dict:
            return {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": command}}

        path = Path(self._tmp.name) / "det.jsonl"
        records = [
            # Turn 1: pure pipeline driving -> counts.
            assistant(0, 50_000, [bash("d1", 'python "x/ppt_pipeline.py" next --work-dir w')], "m1"),
            tool_result("d1", "next: spawn builder", 0),
            # Turn 2: pipeline command mixed with a Read -> not purely deterministic.
            assistant(1, 60_000, [
                bash("d2", 'python "x/ppt_pipeline.py" render --work-dir w'),
                {"type": "tool_use", "id": "d3", "name": "Read", "input": {"file_path": "w/qa.json"}},
            ], "m2"),
            tool_result("d2", "rendered", 1),
            tool_result("d3", "report", 1),
            # Turn 3: unrelated work -> does not count.
            assistant(2, 70_000, [bash("d4", "node deck.js out.pptx")], "m3"),
            tool_result("d4", "built", 2),
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(1, summary["deterministic_agent_roundtrips"])
        self.assertAlmostEqual(1 / 3, summary["deterministic_roundtrip_share"], places=3)

    def test_shared_context_duplication_counts_repeats_only(self) -> None:
        """Batch 0 metric: re-reads of the same shared artifact are the duplication
        the Builder Packet (Batch 2) must remove; first reads are not duplication."""
        path = Path(self._tmp.name) / "dup.jsonl"
        spec = "w/slide-spec-compiled.yaml"
        records = [
            assistant(0, 50_000, [tool_use("s1", "Read", spec)], "m1"),
            tool_result("s1", "x" * 400, 0),  # first read: no duplication
            assistant(1, 60_000, [tool_use("s2", "Read", spec)], "m2"),
            tool_result("s2", "x" * 400, 1),  # same file again -> duplication
            assistant(2, 70_000, [tool_use("s3", "Read", "w/other-file.txt")], "m3"),
            tool_result("s3", "y" * 400, 2),  # not a shared artifact
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        # Two 400-byte reads of the same artifact -> 800 * (2-1)/2 = 400 bytes -> 100 tokens.
        self.assertEqual(100, summary["shared_context_duplication_tokens"])
        self.assertEqual(["read:" + spec.lower()], list(summary["shared_context_duplication_reads"]))
        self.assertIn("shared_context_duplication_tokens", summary)

    def test_shared_context_duplication_tracks_page_brief_work_dirs(self) -> None:
        def bash(uid: str, command: str) -> dict:
            return {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": command}}

        path = Path(self._tmp.name) / "pb.jsonl"
        cmd = 'python "x/page_brief.py" --work-dir W:/decks/demo --json'
        records = [
            assistant(0, 50_000, [bash("p1", cmd)], "m1"),
            tool_result("p1", "x" * 200, 0),
            assistant(1, 60_000, [bash("p2", cmd)], "m2"),
            tool_result("p2", "x" * 200, 1),
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        key = next(iter(summary["shared_context_duplication_reads"]))
        self.assertTrue(key.startswith("page_brief:w:/decks/demo"))
        # Two 200-byte page_brief reads of one work-dir -> 400 * 1/2 = 200 bytes -> 50 tokens.
        self.assertEqual(50, summary["shared_context_duplication_tokens"])

    def test_markdown_reports_batch0_metrics(self) -> None:
        code, stdout = self.invoke(["--session", str(self.transcript)])
        self.assertEqual(0, code)
        self.assertIn("## Batch 0 baseline metrics", stdout)
        self.assertIn("deterministic agent round-trips", stdout)
        self.assertIn("shared-context duplication", stdout)


        path = Path(self._tmp.name) / "triple.jsonl"
        stamp = T0.isoformat()
        usage = {
            "input_tokens": 500,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 99_500,
            "output_tokens": 40,
        }
        records = [
            {
                "type": "assistant",
                "timestamp": stamp,
                "message": {"usage": usage, "content": []},
            },
            {
                "type": "assistant",
                "timestamp": stamp,
                "message": {"usage": usage, "content": []},
            },
            {
                "type": "assistant",
                "timestamp": stamp,
                "message": {
                    "usage": usage,
                    "content": [tool_use("t9", "Bash", DECK)],
                },
            },
        ]
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = SESSION_COST.profile(SESSION_COST.read_records(path))
        self.assertEqual(1, summary["requests"])
        self.assertEqual(1, summary["tokens"]["fresh_input"] // 500)
        self.assertEqual(100_040, summary["tokens"]["total"])
        self.assertEqual(1, summary["tool_calls"])


if __name__ == "__main__":
    unittest.main()
