"""Cost-discipline guards: PreToolUse hook, research envelope, golden page split."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cost_guard = load("cost_guard", "scripts/cost_guard.py")
envelope = load("assert_research_envelope", "scripts/assert_research_envelope.py")


class CostGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self, tool: str, **tool_input) -> dict:
        return {"tool_name": tool, "tool_input": tool_input, "cwd": self.cwd}

    def run_guard(self, payload: dict) -> int:
        buffer = io.StringIO()
        stdin = io.StringIO(json.dumps(payload))
        with redirect_stdout(buffer), redirect_stderr(buffer):
            original = sys.stdin
            sys.stdin = stdin
            try:
                return cost_guard.main([])
            finally:
                sys.stdin = original

    def test_first_png_read_is_allowed(self) -> None:
        png = Path(self.cwd) / "slide.png"
        png.write_bytes(b"png-bytes-1")
        rc = self.run_guard(self.event("Read", file_path=str(png)))
        self.assertEqual(rc, 0)

    def test_same_hash_png_is_blocked(self) -> None:
        png = Path(self.cwd) / "slide.png"
        png.write_bytes(b"png-bytes-1")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(png))))
        self.assertEqual(2, self.run_guard(self.event("Read", file_path=str(png))))

    def test_changed_hash_png_is_allowed(self) -> None:
        png = Path(self.cwd) / "slide.png"
        png.write_bytes(b"png-bytes-1")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(png))))
        png.write_bytes(b"png-bytes-2")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(png))))

    def test_plugin_source_grep_is_blocked(self) -> None:
        rc = self.run_guard(
            self.event("Bash", command="grep -n plan plugins/student-presentation-suite/scripts/ppt_pipeline.py")
        )
        self.assertEqual(rc, 2)

    def test_agent_execution_integrity_is_out_of_scope(self) -> None:
        """runtime_evidence.py, not cost_guard.py, owns spawn integrity."""
        named = self.event("Agent", name="researcher-carbon-pv-wind", prompt="find papers")
        nested = {
            **self.event(
                "Agent",
                subagent_type="student-presentation-suite:presentation-researcher",
                prompt="research",
            ),
            "agent_id": "outer-teammate",
        }
        self.assertEqual(0, self.run_guard(named))
        self.assertEqual(0, self.run_guard(nested))

    def test_production_bypass_integrity_is_out_of_scope(self) -> None:
        """production_entry_guard.py, not cost_guard.py, owns production script entrypoints."""
        commands = [
            "python plugins/student-presentation-suite/scripts/research_pack_to_evidence.py pack.json --output map.json",
            "node plugins/student-presentation-suite/scripts/run_with_pptxgenjs.js --output out.pptx deck.js",
            "python plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py --json",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_listing_plugin_cache_is_blocked(self) -> None:
        rc = self.run_guard(self.event(
            "Bash",
            command='ls "C:/Users/28603/.claude/plugins/cache/claude-personal/student-presentation-suite/0.13.1/references/"',
        ))
        self.assertEqual(rc, 2)

    def test_pipeline_commands_survive_the_plugin_cache_path(self) -> None:
        """2026-09-17 live: the skills require `python "…/ppt_pipeline.py" next --work-dir <wd>`
        and the guard refused that exact string — the quoted path defeated the PIPELINE_RUN
        allow-list, while `--work-dir` matched the `dir` verb from the inspect pattern. Six
        cost_guard refusals that session, half of them this shape."""
        command = (
            'python "C:/Users/u/.claude/plugins/cache/claude-personal/student-presentation-suite/0.13.4'
            '/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir "E:/x/outputs/.pptx-work/carbon" --json'
        )
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_run_gates_with_work_dir_is_not_blocked(self) -> None:
        command = (
            'bash "C:/Users/u/.claude/plugins/cache/claude-personal/student-presentation-suite/0.13.4'
            '/skills/sp-deck/scripts/run_gates.sh" --work-dir "E:/x/outputs/.pptx-work/carbon"'
        )
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_piped_head_is_not_a_plugin_inspection(self) -> None:
        """Piping into head is how the output is kept small; refusing it pushes more text
        into the context, which is the opposite of the guard's purpose."""
        command = (
            'cd "E:/x" && python "C:/Users/u/.claude/plugins/cache/claude-personal/'
            'student-presentation-suite/0.13.4/scripts/workflow_guard.py" init --work-id carbon 2>&1 | head -40'
        )
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_scaffold_marker_check_is_not_a_plugin_path(self) -> None:
        """The scaffold marker string begins with the plugin's name; scanning the work
        directory for it is a page check, not an attempt to read plugin source."""
        command = 'grep -l "student-presentation-suite-scaffold" *.js || echo none'
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_pipeline_cli_help_is_allowed(self) -> None:
        """--help on the agent's own operating surface is cheaper than the trial-and-error
        it replaces: on 2026-09-17 one --help refusal led to two more chained --help probes,
        same round trips but producing failures instead of information."""
        base = "C:/Users/u/.claude/plugins/cache/claude-personal/student-presentation-suite/0.13.4"
        for command in (
            f'python "{base}/skills/sp-deck/scripts/ppt_pipeline.py" --help',
            f'python "{base}/skills/sp-deck/scripts/ppt_pipeline.py" build --help',
        ):
            with self.subTest(command=command[-40:]):
                self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    def test_validate_research_pack_help_is_blocked(self) -> None:
        rc = self.run_guard(self.event(
            "Bash",
            command="python plugins/student-presentation-suite/scripts/validate_research_pack.py --help",
        ))
        self.assertEqual(rc, 2)

    def test_refusals_point_to_a_resolvable_pipeline_path(self) -> None:
        """裸脚本名会诱导 agent 用错路径；提示必须带可执行的绝对路径。"""
        messages = [
            cost_guard.check_bash("grep -n plan /x/student-presentation-suite/scripts/ppt_pipeline.py"),
            cost_guard.check_bash("python ppt_pipeline.py --help --work-dir x"),
        ]
        for message in messages:
            self.assertIsNotNone(message)
            match = re.search(r'"([^"]+ppt_pipeline\.py)"', message or "")
            self.assertIsNotNone(match, message)
            self.assertTrue(Path(str(match.group(1))).is_file(), match.group(1))

    def test_builder_child_refusal_points_at_builder_surface(self) -> None:
        """子 builder 被 ppt_pipeline 拒之门外；它的拒绝文案不能把 pipeline 当出路（死胡同）。"""
        message = cost_guard.check_bash(
            'ls "C:/Users/me/.claude/plugins/cache/claude-personal/student-presentation-suite/0.13.4/scripts/"',
            builder=True,
        )
        self.assertIsNotNone(message)
        self.assertIn("isolated builder", message)
        self.assertIn("pptx-helpers.js", message)
        self.assertNotIn("ppt_pipeline.py next", message)

    def test_repeated_inspection_command_is_blocked_on_the_third_run(self) -> None:
        """`ls critic-execution.json` 连跑 5 次的实测浪费：第 3 次起拒绝并指向 next。"""
        event = self.event("Bash", command="ls -la outputs/.pptx-work/demo/critic-execution.json")
        self.assertEqual(0, self.run_guard(event))
        self.assertEqual(0, self.run_guard(event))
        self.assertEqual(2, self.run_guard(event))
        # 变体（不同命令）不受影响
        other = self.event("Bash", command="cat outputs/.pptx-work/demo/visual-review.json")
        self.assertEqual(0, self.run_guard(other))
        # 动作命令（build/gates）不受巡检限流影响
        action = self.event("Bash", command="python ppt_pipeline.py build --work-dir wd")
        self.assertEqual(0, self.run_guard(action))

    def test_main_session_big_image_budget_is_enforced(self) -> None:
        """主会话读 >150KB 的图超过 6 张即拒绝；缩略图与子代理不受限。"""
        big = 200 * 1024
        results = []
        for index in range(7):
            page = Path(self.cwd) / f"slide-{index}.png"
            page.write_bytes(b"\x00" * big)
            results.append(self.run_guard(self.event("Read", file_path=str(page))))
        self.assertEqual([0] * 6, results[:6])
        self.assertEqual(2, results[6])
        # 子代理（带 agent_id）不受预算限制
        with_agent = {**self.event("Read", file_path=str(Path(self.cwd) / "slide-7.png")), "agent_id": "child"}
        self.assertEqual(0, self.run_guard(with_agent))

    def test_small_images_are_not_budget_limited(self) -> None:
        small = 64 * 1024
        for index in range(9):
            page = Path(self.cwd) / f"thumb-{index}.png"
            page.write_bytes(b"\x00" * small)
            self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(page))))

    def test_second_full_reference_read_is_blocked(self) -> None:
        ref = Path(self.cwd) / "references" / "cost-discipline.md"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("# CD\n", encoding="utf-8")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(ref))))
        self.assertEqual(2, self.run_guard(self.event("Read", file_path=str(ref))))

    def test_seen_state_is_scoped_to_the_session(self) -> None:
        """One task must not silence the next task's first reference read."""
        ref = Path(self.cwd) / "references" / "cost-discipline.md"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("# CD\n", encoding="utf-8")
        first = self.run_guard({**self.event("Read", file_path=str(ref)), "session_id": "task-a"})
        second = self.run_guard({**self.event("Read", file_path=str(ref)), "session_id": "task-b"})
        self.assertEqual(0, first)
        self.assertEqual(0, second)
        again = self.run_guard({**self.event("Read", file_path=str(ref)), "session_id": "task-a"})
        self.assertEqual(2, again)

    def test_same_named_references_in_different_dirs_do_not_collide(self) -> None:
        one = Path(self.cwd) / "references" / "cost-discipline.md"
        two = Path(self.cwd) / "other" / "references" / "cost-discipline.md"
        for path, body in ((one, "# one\n"), (two, "# two\n")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(one))))
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(two))))

    def test_updated_reference_may_be_read_again(self) -> None:
        ref = Path(self.cwd) / "references" / "cost-discipline.md"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("# CD v1\n", encoding="utf-8")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(ref))))
        ref.write_text("# CD v2\n", encoding="utf-8")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(ref))))

    def test_seen_store_lives_under_the_work_root_guard_dir(self) -> None:
        ref = Path(self.cwd) / "references" / "cost-discipline.md"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("# CD\n", encoding="utf-8")
        rc = self.run_guard(
            {**self.event("Read", file_path=str(ref)), "session_id": "task-a"}
        )
        self.assertEqual(0, rc)
        store = cost_guard.seen_store(self.cwd, "task-a")
        self.assertTrue(store.is_file())
        self.assertEqual(store.name, "seen-task-a.json")
        self.assertIn(".guard", store.parts)


class ResearchEnvelopeTests(unittest.TestCase):
    def test_compact_done_envelope_passes(self) -> None:
        text = "\n".join(
            [
                "RESEARCH_DONE",
                "pack: outputs/.pptx-work/demo/research-pack.json",
                "validation: outputs/.pptx-work/demo/research-pack-validation.json",
                "findings: 4",
                "data_points: 2",
                "quotes: 1",
                "unresolved: 0",
                "status: ok",
            ]
        )
        self.assertEqual([], envelope.check_text(text))

    def test_extra_prose_is_rejected(self) -> None:
        text = "RESEARCH_DONE\nstatus: ok\nHere is a long literature review..."
        problems = envelope.check_text(text)
        self.assertTrue(problems)

    def test_main_transcript_must_not_contain_websearch(self) -> None:
        self.assertTrue(envelope.check_main_transcript("called WebSearch for IEA data"))
        self.assertEqual([], envelope.check_main_transcript("RESEARCH_DONE\nstatus: ok"))


class GoldenSampleSplitTests(unittest.TestCase):
    def test_deck_requires_nine_page_modules(self) -> None:
        golden = ROOT / "examples" / "golden-sample"
        deck = (golden / "deck.js").read_text(encoding="utf-8")
        self.assertNotIn("lineSpacingMultiple", deck)
        pages = sorted((golden / "pages").glob("p*.js"))
        self.assertEqual(9, len(pages))
        for path in pages:
            self.assertIn(f"./pages/{path.name}", deck)
            self.assertNotIn("lineSpacingMultiple", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
