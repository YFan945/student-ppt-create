from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.work = self.project / "outputs/.pptx-work/test"
        self.work.mkdir(parents=True)
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)
        self.event = {
            "cwd": str(self.project),
            "session_id": "parent",
            "agent_id": "child",
            "agent_type": runtime.CRITIC,
        }

    def event_call(self, event, **extra):
        return runtime.handle({**self.event, "hook_event_name": event, **extra})

    def prepare_render(self, page_count: int = 2) -> tuple[Path, list[Path]]:
        render_dir = self.work / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        pages: list[Path] = []
        for index in range(1, page_count + 1):
            page = render_dir / f"slide-{index}.png"
            Image.new("RGB", (1920, 1080), "white").save(page)
            pages.append(page)
        contact = self.work / "contact-sheet.png"
        Image.new("RGB", (1440, 810), "white").save(contact)
        manifest = {
            "work_id": self.work.name,
            "render": {
                "pptx_sha256": "pptx-test-sha",
                "contact_sheet": {"path": str(contact), "sha256": runtime.digest(contact)},
                "pages": [
                    {"path": str(page), "sha256": runtime.digest(page)} for page in pages
                ],
            },
        }
        (self.work / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return contact, pages

    def critic_spawn(self, *, prompt: str | None = None, **extra) -> int:
        tool_input = {
            "subagent_type": runtime.CRITIC,
            "prompt": prompt if prompt is not None else f"Review work directory {self.work.resolve()}",
            **extra,
        }
        return runtime.handle(
            {
                "cwd": str(self.project),
                "session_id": "parent",
                "hook_event_name": "PreToolUse",
                "tool_name": "Agent",
                "tool_input": tool_input,
            }
        )

    def test_receipt_requires_start_successful_read_and_write(self):
        review = self.work / "visual-review.json"
        review.write_text("{}")
        self.event_call("SubagentStop")
        self.assertFalse((self.work / "critic-execution.json").exists())
        self.event_call("SubagentStart")
        page = self.work / "slide-1.png"
        page.write_bytes(b"test-image")
        self.event_call("PostToolUse", tool_name="Read", tool_input={"file_path": str(page)})
        self.event_call("PostToolUse", tool_name="Write", tool_input={"file_path": str(review)})
        self.event_call("SubagentStop")
        receipt = json.loads((self.work / "critic-execution.json").read_text())
        self.assertEqual(receipt["reads"][str(page)], runtime.digest(page))
        self.assertEqual(receipt["artifact"]["sha256"], runtime.digest(review))
        self.assertEqual(receipt["agent_id"], "child")

    def test_bash_script_writes_are_receipted_via_snapshot(self):
        """2026-09-17: json.dump edits bypassed Write-tool receipts and plan refused a healthy pack."""
        work = self.project / "outputs/.pptx-work/research-job"
        work.mkdir(parents=True)
        event = {**self.event, "agent_type": runtime.RESEARCHER}

        def call(event_kind, **extra):
            return runtime.handle({**event, "hook_event_name": event_kind, **extra})

        pack = work / "research-pack.json"
        pack.write_text('{"round": 1}')
        call("SubagentStart")
        # every round-2 edit arrives through Bash python json.dump, never the Write tool
        pack.write_text('{"round": 2}')
        call("PostToolUse", tool_name="Bash", tool_input={"command": "python -c 'json.dump(...)'"})
        call("SubagentStop")
        receipt = json.loads((work / "research-execution.json").read_text())
        self.assertTrue(receipt["spawn_verified"])
        self.assertEqual(receipt["artifact"]["sha256"], runtime.digest(pack))

    def test_pre_existing_artifact_is_not_credited_without_a_change(self):
        work = self.project / "outputs/.pptx-work/research-job"
        work.mkdir(parents=True)
        event = {**self.event, "agent_type": runtime.RESEARCHER}

        def call(event_kind, **extra):
            return runtime.handle({**event, "hook_event_name": event_kind, **extra})

        pack = work / "research-pack.json"
        pack.write_text('{"round": 1}')
        call("SubagentStart")
        call("PostToolUse", tool_name="Bash", tool_input={"command": "ls"})
        call("SubagentStop")
        self.assertFalse((work / "research-execution.json").exists())

    def test_critic_cannot_write_generator_or_other_work_area(self):
        self.assertEqual(
            self.event_call("PreToolUse", tool_name="Write", tool_input={"file_path": str(self.work / "deck.js")}),
            2,
        )
        self.assertEqual(
            self.event_call(
                "PreToolUse",
                tool_name="Write",
                tool_input={"file_path": str(self.work / "visual-review.json")},
            ),
            0,
        )

    def test_critic_preview_artifacts_are_hook_owned(self):
        preview = self.work / runtime.critic_preview.PREVIEW_DIR_NAME / "p01.jpg"
        preview.parent.mkdir(parents=True)
        preview.write_bytes(b"preview")
        mapping = self.work / runtime.critic_preview.MAP_NAME
        mapping.write_text("{}")
        for path in (preview, mapping):
            with self.subTest(path=path.name):
                self.assertEqual(
                    self.event_call(
                        "PreToolUse", tool_name="Write", tool_input={"file_path": str(path)}
                    ),
                    2,
                )

    def test_critic_spawn_materializes_hash_bound_previews(self):
        contact, pages = self.prepare_render()
        self.assertEqual(self.critic_spawn(), 0)
        mapping = json.loads((self.work / runtime.critic_preview.MAP_NAME).read_text())
        self.assertEqual(mapping["work_id"], self.work.name)
        self.assertEqual(len(mapping["entries"]), 3)
        page_entries = [entry for entry in mapping["entries"] if entry["kind"] == "page"]
        self.assertEqual(
            [entry["source_sha256"] for entry in page_entries],
            [runtime.digest(page) for page in pages],
        )
        overview = next(entry for entry in mapping["entries"] if entry["kind"] == "overview")
        self.assertEqual(overview["source_sha256"], runtime.digest(contact))
        for entry in mapping["entries"]:
            preview = Path(entry["preview_path"])
            self.assertTrue(preview.is_file())
            self.assertEqual(runtime.digest(preview), entry["preview_sha256"])

    def test_critic_spawn_without_absolute_work_dir_is_refused(self):
        self.prepare_render()
        self.assertEqual(self.critic_spawn(prompt="Review the current deck"), 2)
        self.assertFalse((self.work / runtime.critic_preview.MAP_NAME).exists())

    def test_critic_preview_read_is_credited_to_current_source_render(self):
        _contact, pages = self.prepare_render(page_count=1)
        self.assertEqual(self.critic_spawn(), 0)
        mapping = json.loads((self.work / runtime.critic_preview.MAP_NAME).read_text())
        preview_entry = next(entry for entry in mapping["entries"] if entry["kind"] == "page")
        preview = Path(preview_entry["preview_path"])

        self.event_call("SubagentStart")
        self.event_call("PostToolUse", tool_name="Read", tool_input={"file_path": str(preview)})
        review = self.work / "visual-review.json"
        review.write_text("{}")
        self.event_call("PostToolUse", tool_name="Write", tool_input={"file_path": str(review)})
        self.event_call("SubagentStop")

        receipt = json.loads((self.work / "critic-execution.json").read_text())
        self.assertEqual(receipt["reads"][str(preview.resolve())], runtime.digest(preview))
        self.assertEqual(receipt["reads"][str(pages[0].resolve())], runtime.digest(pages[0]))

    def test_research_scope_blocks_parent_web_but_not_unrelated_sessions(self):
        base = {"cwd": str(self.project), "session_id": "parent", "hook_event_name": "PreToolUse"}
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 0)
        runtime.handle(
            {
                **base,
                "tool_name": "Skill",
                "tool_input": {"skill": "student-presentation-suite:sp-research"},
            }
        )
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 2)
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "tool_name": "WebSearch",
                    "agent_type": runtime.RESEARCHER,
                    "agent_id": "research-child",
                }
            ),
            0,
        )
        self.assertEqual(
            runtime.handle({**base, "tool_name": "WebSearch", "session_id": "unrelated"}), 0
        )

    def test_stop_clears_main_session_research_scope(self):
        base = {"cwd": str(self.project), "session_id": "parent"}
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Skill",
                    "tool_input": {"skill": "student-presentation-suite:sp-deck"},
                }
            ),
            0,
        )
        self.assertEqual(
            runtime.handle({**base, "hook_event_name": "PreToolUse", "tool_name": "WebSearch"}), 2
        )
        active = self.project / "outputs/.pptx-work/.guard/research-active-parent.json"
        self.assertTrue(active.is_file())
        self.assertEqual(runtime.handle({**base, "hook_event_name": "Stop"}), 0)
        self.assertFalse(active.exists())
        self.assertEqual(
            runtime.handle({**base, "hook_event_name": "PreToolUse", "tool_name": "WebSearch"}), 0
        )

    def test_named_evidence_agent_spawn_is_blocked(self):
        self.prepare_render()
        base = {"cwd": str(self.project), "session_id": "parent", "hook_event_name": "PreToolUse"}
        for agent_type in (runtime.RESEARCHER, runtime.CRITIC):
            valid_input = {"subagent_type": agent_type}
            if agent_type == runtime.CRITIC:
                valid_input["prompt"] = f"Review {self.work.resolve()}"
            with self.subTest(agent=agent_type):
                rc = runtime.handle(
                    {
                        **base,
                        "tool_name": "Agent",
                        "tool_input": {**valid_input, "name": f"named-{agent_type}"},
                    }
                )
                self.assertEqual(2, rc)
                rc = runtime.handle({**base, "tool_name": "Agent", "tool_input": valid_input})
                self.assertEqual(0, rc)

    def test_nested_evidence_agent_spawn_is_blocked(self):
        base = {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "agent_id": "outer-teammate",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": runtime.RESEARCHER},
        }
        self.assertEqual(2, runtime.handle(base))

    def test_sp_deck_skill_arms_websearch_block_for_the_main_session(self):
        base = {"cwd": str(self.project), "session_id": "deck", "hook_event_name": "PreToolUse"}
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 0)
        runtime.handle(
            {
                **base,
                "tool_name": "Skill",
                "tool_input": {"skill": "student-presentation-suite:sp-deck"},
            }
        )
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 2)
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "tool_name": "WebSearch",
                    "agent_type": runtime.RESEARCHER,
                    "agent_id": "research-child",
                }
            ),
            0,
        )

    def test_parallel_image_events_do_not_lose_read_hashes(self):
        self.event_call("SubagentStart")
        paths = [self.work / f"page-{index}.png" for index in range(8)]
        for path in paths:
            path.write_bytes(path.name.encode())

        def record(path):
            with runtime.event_lock(self.event):
                self.event_call("PostToolUse", tool_name="Read", tool_input={"file_path": str(path)})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(record, paths))
        review = self.work / "visual-review.json"
        review.write_text("{}")
        self.event_call("PostToolUse", tool_name="Write", tool_input={"file_path": str(review)})
        self.event_call("SubagentStop")
        receipt = json.loads((self.work / "critic-execution.json").read_text())
        self.assertEqual(receipt["reads"], {str(path): runtime.digest(path) for path in paths})

    def test_fileexists_collision_can_disappear_before_retry(self):
        original_open = os.open
        calls = 0

        def racing_open(path, flags, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FileExistsError(17, "simulated disappearing lock", str(path))
            return original_open(path, flags, *args, **kwargs)

        with patch.object(runtime.os, "open", side_effect=racing_open), patch.object(
            runtime.time, "sleep", return_value=None
        ):
            with runtime.event_lock(self.event):
                pass
        self.assertGreaterEqual(calls, 2)

    def test_event_lock_recovers_abandoned_stale_lock(self):
        guard = self.project / "outputs/.pptx-work/.guard"
        guard.mkdir(parents=True, exist_ok=True)
        lock = guard / "lock-parent-child"
        lock.write_text('{"pid": 999999}')
        stale = time.time() - runtime.LOCK_STALE_SECONDS - 5
        os.utime(lock, (stale, stale))
        with runtime.event_lock(self.event):
            self.assertTrue(lock.is_file())
            payload = json.loads(lock.read_text())
            self.assertEqual(payload["pid"], os.getpid())
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
