"""Batch 6.1 — Hook Scope Isolation acceptance tests.

The plugin's guards must only constrain managed PPT production. Every test here
pins one side of that boundary:

TEST 01-04, 09  non-PPT sessions and non-plugin subagents pass through;
TEST 05-08      PPT builder constraints keep working under packet scope;
TEST 07         direct production-entry protection survives everywhere;
TEST 10         parallel tasks (different sessions / work-dirs) never share state.

Deterministic signals only: agent identity from the hook event, task activation
from plugin-written state files, resource scope from the `.pptx-work` path
shape. No keyword/LLM intent detection.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module  # dataclasses resolves types via sys.modules
    spec.loader.exec_module(module)
    return module


cost_guard = load("cost_guard_scope", "scripts/cost_guard.py")
runtime = load("runtime_evidence_scope", "scripts/runtime_evidence.py")
entry_guard = load("entry_guard_scope", "scripts/production_entry_guard.py")
builder_guard = load("builder_guard_scope", "scripts/builder_guard.py")
pipeline_context = load("pipeline_context_scope", "scripts/pipeline_context.py")

BUILDER = "student-presentation-suite:presentation-builder"
RESEARCHER = "student-presentation-suite:presentation-researcher"
OTHER_SUBAGENT = "general-purpose"


class ScopeFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)

    def event(self, tool: str, **tool_input) -> dict:
        return {
            "tool_name": tool,
            "tool_input": tool_input,
            "cwd": str(self.project),
            "session_id": "normal-session",
            "hook_event_name": "PreToolUse",
        }


class CostGuardScopeTests(ScopeFixture):
    """cost_guard routes through pipeline_context; non-PPT calls are unmanaged."""

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

    # TEST 01 — a plain repeated `ls` is a legitimate poll (watching a builder
    # for new files), not wasted cost. Same command, any number of runs.
    def test_normal_session_may_repeat_the_same_inspection(self) -> None:
        command = "ls -la src/modules/"
        for _ in range(4):
            self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))

    # TEST 02 — image dedup (CD-9) exists for render evidence, not for normal
    # work; a plain session may read the same PNG as often as it needs.
    def test_normal_session_may_reread_the_same_png(self) -> None:
        png = self.project / "assets" / "figure.png"
        png.parent.mkdir(parents=True)
        png.write_bytes(b"png-bytes")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(png))))
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(png))))

    # TEST 03 — plugin-source archaeology is the maintainer's day job. Only the
    # isolated builder is kept away from plugin source (packet rules).
    def test_normal_session_may_read_plugin_source(self) -> None:
        source = self.project / "plugins" / "student-presentation-suite" / "scripts" / "layout_helper.py"
        source.parent.mkdir(parents=True)
        source.write_text("# source\n", encoding="utf-8")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(source))))

    def test_builder_is_still_kept_away_from_plugin_source(self) -> None:
        source = self.project / "plugins" / "student-presentation-suite" / "scripts" / "layout_helper.py"
        source.parent.mkdir(parents=True)
        source.write_text("# source\n", encoding="utf-8")
        event = {
            **self.event("Read", file_path=str(source)),
            "agent_type": BUILDER,
            "agent_id": "builder-1",
        }
        self.assertEqual(2, self.run_guard(event))

    # PPT-side regression: work-dir inspection discipline and render-image
    # dedup keep working once the call IS pipeline-scoped.
    def test_work_dir_inspections_are_still_budgeted(self) -> None:
        command = "ls -la outputs/.pptx-work/demo/critic-execution.json"
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))
        self.assertEqual(0, self.run_guard(self.event("Bash", command=command)))
        self.assertEqual(2, self.run_guard(self.event("Bash", command=command)))

    def test_render_image_dedup_still_applies_inside_the_work_dir(self) -> None:
        render = self.project / "outputs" / ".pptx-work" / "demo" / "render"
        render.mkdir(parents=True)
        page = render / "slide-1.png"
        page.write_bytes(b"render-bytes")
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(page))))
        self.assertEqual(2, self.run_guard(self.event("Read", file_path=str(page))))

    def test_reference_reread_needs_a_managed_session(self) -> None:
        reference = self.project / "references" / "cost-discipline.md"
        reference.parent.mkdir(parents=True)
        reference.write_text("# CD\n", encoding="utf-8")
        # unmanaged: re-reads are free (maintenance / normal development)
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(reference))))
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(reference))))
        # managed: the first read records, the re-read is refused (CD-3)
        pipeline_context.mark_research_active(self.project, {"session_id": "normal-session"})
        self.assertEqual(0, self.run_guard(self.event("Read", file_path=str(reference))))
        self.assertEqual(2, self.run_guard(self.event("Read", file_path=str(reference))))


class RuntimeEvidenceScopeTests(ScopeFixture):
    def runtime_event(self, tool: str, **extra) -> dict:
        return {**self.event(tool), **extra}

    def arm_research(self) -> None:
        pipeline_context.mark_research_active(self.project, {"session_id": "normal-session"})

    # TEST 04 — subagents from other plugins / user workflows are nobody's
    # business: they may search even while THIS session runs PPT research.
    def test_non_plugin_subagent_websearch_is_allowed_even_when_research_is_active(self) -> None:
        self.arm_research()
        event = {
            **self.runtime_event("WebSearch"),
            "agent_type": OTHER_SUBAGENT,
            "agent_id": "some-other-plugins-child",
        }
        self.assertEqual(0, runtime.handle(event))

    def test_builder_and_critic_children_still_cannot_search(self) -> None:
        for agent_type in (BUILDER, "student-presentation-suite:visual-critic"):
            event = {
                **self.runtime_event("WebSearch"),
                "agent_type": agent_type,
                "agent_id": "plugin-child",
            }
            with self.subTest(agent=agent_type):
                self.assertEqual(2, runtime.handle(event))

    def test_researcher_child_still_may_search(self) -> None:
        self.arm_research()
        event = {
            **self.runtime_event("WebSearch"),
            "agent_type": RESEARCHER,
            "agent_id": "research-child",
        }
        self.assertEqual(0, runtime.handle(event))

    def test_plain_session_websearch_is_allowed(self) -> None:
        self.assertEqual(0, runtime.handle(self.runtime_event("WebSearch")))

    def test_stale_research_state_expires_without_a_stop_event(self) -> None:
        """Stop is a cleanup fallback, not the only validity signal: a crashed
        session must not leave research scope armed forever."""
        self.arm_research()
        active = pipeline_context.research_active_path(self.project, "normal-session")
        stale = time.time() - pipeline_context.RESEARCH_ACTIVE_TTL_SECONDS - 10
        os.utime(active, (stale, stale))
        self.assertEqual(0, runtime.handle(self.runtime_event("WebSearch")))
        self.assertFalse(active.exists())

    # TEST 09 — after the task ends (Stop), the session is a normal session again.
    def test_stop_releases_the_session_back_to_normal(self) -> None:
        self.arm_research()
        self.assertEqual(2, runtime.handle(self.runtime_event("WebSearch")))
        runtime.handle({**self.runtime_event("WebSearch"), "hook_event_name": "Stop"})
        self.assertEqual(0, runtime.handle(self.runtime_event("WebSearch")))


class ProductionEntryScopeTests(ScopeFixture):
    # TEST 07 — bypassing the pipeline is refused regardless of session type;
    # this protection is deliberately NOT scoped to managed PPT sessions.
    def test_direct_production_entry_is_refused_outside_ppt_work(self) -> None:
        command = (
            "node plugins/student-presentation-suite/scripts/run_with_pptxgenjs.js "
            "--output out.pptx deck.js"
        )
        self.assertEqual(2, entry_guard.handle(self.event("Bash", command=command)))

    def test_normal_dev_commands_are_not_production_entry(self) -> None:
        for command in ("pytest -q", "git status", "python scripts/serve.py"):
            with self.subTest(command=command):
                self.assertEqual(0, entry_guard.handle(self.event("Bash", command=command)))


class BuilderPacketScopeTests(ScopeFixture):
    """TEST 05/06/08 — the v0.15 packet boundary must survive scope isolation."""

    def setUp(self) -> None:
        super().setUp()
        self.work = self.project / "outputs" / ".pptx-work" / "demo"
        self.packet_dir = self.work / "builder-packets"
        self.packet_dir.mkdir(parents=True)
        self.packet = self.packet_dir / "packet-shard-1.json"
        self.packet.write_text(json.dumps({"assigned_slides": [1]}), encoding="utf-8")
        (self.packet_dir / "active-round.json").write_text(
            json.dumps(
                {
                    "at": "2026-09-19T00:00:00+00:00",
                    "packets": [
                        {
                            "packet": str(self.packet),
                            "packet_sha256": builder_guard._sha256(self.packet),
                            "assigned_slides": [1],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.page_one = self.work / "pages" / "p01-cover.js"
        self.page_one.parent.mkdir(parents=True)
        self.page_one.write_text("// page 1", encoding="utf-8")
        self.page_two = self.work / "pages" / "p02-body.js"
        self.page_two.write_text("// page 2", encoding="utf-8")

    def builder_event(self, path: Path, tool: str = "Read") -> dict:
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"file_path": str(path)},
            "agent_type": BUILDER,
            "agent_id": "builder-shard-1",
        }

    # TEST 05 — a builder bound to shard 1 may not touch another shard's page.
    def test_builder_cannot_read_another_shards_page(self) -> None:
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.packet)))
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.page_one)))
        self.assertEqual(2, builder_guard.handle(self.builder_event(self.page_two)))

    # TEST 06 — with an active packet round, frozen inputs may not be re-read.
    def test_builder_cannot_reread_packet_projected_inputs(self) -> None:
        manifest = self.work / "build-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.packet)))
        self.assertEqual(2, builder_guard.handle(self.builder_event(manifest)))

    # TEST 08 — an identical re-dispatch keeps the binding: same round, same
    # shard scope; only a NEW round (different `at`) expires old bindings.
    def test_same_round_redispatch_keeps_the_binding(self) -> None:
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.packet)))
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.packet)))
        self.assertEqual(0, builder_guard.handle(self.builder_event(self.page_one)))

        round_at = "2026-09-19T00:00:00+00:00"
        binding = builder_guard._load_binding(
            self.project, "builder-shard-1", self.work, round_at
        )
        self.assertIsNotNone(binding)
        self.assertEqual(binding.get("allowed_slides"), [1])

        self.assertIsNone(
            builder_guard._load_binding(self.project, "builder-shard-1", self.work, "new-round")
        )


class ParallelScopeTests(ScopeFixture):
    # TEST 10 — two PPT tasks in different sessions are fully independent:
    # separate inspection budgets, separate research-active state.
    def test_parallel_sessions_do_not_share_budgets_or_state(self) -> None:
        def guard_event(session: str, command: str) -> dict:
            return {**self.event("Bash", command=command), "session_id": session}

        command = "ls outputs/.pptx-work/demo/"

        def run_guard(payload: dict) -> int:
            buffer = io.StringIO()
            stdin = io.StringIO(json.dumps(payload))
            with redirect_stdout(buffer), redirect_stderr(buffer):
                original = sys.stdin
                sys.stdin = stdin
                try:
                    return cost_guard.main([])
                finally:
                    sys.stdin = original

        self.assertEqual(0, run_guard(guard_event("task-a", command)))
        self.assertEqual(0, run_guard(guard_event("task-a", command)))
        self.assertEqual(0, run_guard(guard_event("task-b", command)))
        self.assertEqual(2, run_guard(guard_event("task-a", command)))

        pipeline_context.mark_research_active(self.project, {"session_id": "task-a"})
        self.assertEqual(2, runtime.handle({**self.event("WebSearch"), "session_id": "task-a"}))
        self.assertEqual(0, runtime.handle({**self.event("WebSearch"), "session_id": "task-b"}))


if __name__ == "__main__":
    unittest.main()
