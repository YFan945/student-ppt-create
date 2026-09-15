"""Cost-discipline guards: PreToolUse hook, research envelope, golden page split."""

from __future__ import annotations

import importlib.util
import io
import json
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

    def test_researcher_teammate_is_blocked(self) -> None:
        rc = self.run_guard(self.event("Agent", name="researcher", prompt="find papers"))
        self.assertEqual(rc, 2)

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
