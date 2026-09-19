from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
guard = load_module(ROOT / "scripts/builder_guard.py")
builder_packet = load_module(ROOT / "skills/sp-deck/scripts/builder_packet.py")


class BuilderGuardFixture:
    """Shared fixture for the guard test classes.

    A plain mixin (NOT a unittest.TestCase): inheriting tests from a TestCase
    subclass re-executes every parent test on the child, which silently doubles
    runs without adding scenarios (Batch 5.1 cleanup).
    """

    def install_fixture(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.work = self.project / "outputs/.pptx-work/demo"
        self.page = self.work / "pages/p01-cover.js"
        self.page.parent.mkdir(parents=True)
        self.page.write_text("// page", encoding="utf-8")
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)

    def event(self, tool: str, **extra):
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"file_path": str(self.page)},
            **extra,
        }

    def shell_event(self, command: str, **extra):
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            **extra,
        }

    def builder(self, path: Path, tool: str = "Read", agent_id: str = "builder-shard-1") -> dict:
        event = self.event(tool)
        event["tool_input"] = {"file_path": str(path)}
        event["agent_type"] = guard.BUILDER
        event["agent_id"] = agent_id
        return event


class BuilderGuardTests(BuilderGuardFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.install_fixture()

    def test_main_session_cannot_read_edit_or_write_page_modules(self) -> None:
        for tool in ("Read", "Edit", "Write"):
            with self.subTest(tool=tool):
                self.assertEqual(2, guard.handle(self.event(tool)))

    def test_only_isolated_builder_can_access_page_modules(self) -> None:
        event = self.event(
            "Edit",
            agent_type=guard.BUILDER,
            agent_id="builder-child",
        )
        self.assertEqual(0, guard.handle(event))
        self.assertEqual(
            2,
            guard.handle(self.event("Edit", agent_type=guard.BUILDER)),
            "agent_type without a child id is still the parent context",
        )

    def test_non_page_work_artifacts_are_untouched(self) -> None:
        manifest = self.project / "outputs/.pptx-work/demo/build-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        event = self.event("Read")
        event["tool_input"] = {"file_path": str(manifest)}
        self.assertEqual(0, guard.handle(event))

    def test_builder_inline_json_extraction_is_redirected(self) -> None:
        """2026-09-17 live: 19-46 inline scripts per repair round, each one a full context
        round-trip at ~150K resident context. page_brief.py answers the same question once."""
        command = (
            "cd \"$WD\" && node -e \" const q=require('./qa-quality.json');"
            " const s=JSON.stringify(q); console.log(s.slice(0,3000)); \""
        )
        event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(2, guard.handle(event))

    def test_builder_keeps_legitimate_node_commands(self) -> None:
        for command in (
            "node --check pages/p07-s07.js",
            "node deck.js /tmp/check.pptx",
            "node -e \"console.log(1+1)\"",
            "node \"$CLAUDE_PLUGIN_ROOT/scripts/pptx-helpers.js\" --describe",
        ):
            with self.subTest(command=command):
                event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
                self.assertEqual(0, guard.handle(event))

    def test_parent_session_inline_node_is_not_policed(self) -> None:
        command = "node -e \"console.log(require('./build-manifest.json').state)\""
        self.assertEqual(0, guard.handle(self.shell_event(command)))

    def test_the_heredoc_form_of_the_same_digging_is_also_refused(self) -> None:
        """2026-09-18: after `node -e` was refused the builder switched to `python - <<'PY'`
        and did it 111 times, using the projection tool it was pointed at only 5 times."""
        heredoc = (
            "cd \"$WD\" && python - <<'PY'\n"
            "import json, io\n"
            "d = json.load(io.open('build-manifest.json', encoding='utf-8'))\n"
            "print(d.keys())\n"
            "PY"
        )
        event = self.shell_event(heredoc, agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(2, guard.handle(event))

    def test_python_c_over_work_dir_json_is_refused(self) -> None:
        command = (
            "cd \"$WD\" && python -c \"import json;q=json.load(open('qa-quality.json'));"
            "print(json.dumps(q['counts']))\""
        )
        event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(2, guard.handle(event))

    def test_rewriting_page_modules_from_a_heredoc_is_refused(self) -> None:
        heredoc = (
            "python - <<'PY'\n"
            "import io\n"
            "p = 'pages/p07-s07.js'\n"
            "s = io.open(p, encoding='utf-8').read().replace('0.30', '0.42')\n"
            "io.open(p, 'w', encoding='utf-8').write(s)\n"
            "PY"
        )
        event = self.shell_event(heredoc, agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(2, guard.handle(event))

    def test_rendering_and_the_calibration_preview_belong_to_the_main_session(self) -> None:
        """2026-09-18: the builder called calibration_preview.py 38 times in its own context."""
        for command in (
            "python \"$CLAUDE_PLUGIN_ROOT/skills/sp-deck/scripts/calibration_preview.py\""
            " --work-dir \"$WD\" --slides 1 5 7 --json",
            "python \"$CLAUDE_PLUGIN_ROOT/scripts/pptx_tool.py\" render \"$WD/deck.pptx\""
            " --output-dir \"$WD/render\"",
            "soffice --headless --convert-to pdf deck.pptx",
        ):
            with self.subTest(command=command[:60]):
                event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
                self.assertEqual(2, guard.handle(event))

    def test_measuring_rendered_pixels_is_still_allowed(self) -> None:
        """Refusing every heredoc would take away the geometry check the builder needs."""
        for command in (
            "python - <<'PY'\nfrom PIL import Image\nprint(Image.open('render/slide-07.png').size)\nPY",
            "python -c \"from PIL import Image; print(Image.open('a.png').size)\"",
            "python - <<'PY'\nimport io\nprint(len(io.open('deck.js', encoding='utf-8').read()))\nPY",
        ):
            with self.subTest(command=command[:50]):
                event = self.shell_event(command, agent_type=guard.BUILDER, agent_id="builder-child")
                self.assertEqual(0, guard.handle(event))

    def test_builder_page_writes_record_the_instance_window(self) -> None:
        """The pipeline cross-references this with the repair rounds to detect a reused
        instance — the largest measured cost driver. (No active packet round here, so
        page access needs no binding.)"""
        event = self.event("Edit", agent_type=guard.BUILDER, agent_id="builder-child")
        self.assertEqual(0, guard.handle(event))
        records = list((self.project / "outputs/.pptx-work/.guard").glob("builder-*.json"))
        self.assertEqual(1, len(records), records)
        data = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual("builder-child", data["agent_id"])
        self.assertEqual(1, data["writes"])
        self.assertEqual(["demo"], data["work_ids"])
        guard.handle(event)
        self.assertEqual(2, json.loads(records[0].read_text(encoding="utf-8"))["writes"])


class BuilderPacketScopeTests(BuilderGuardFixture, unittest.TestCase):
    """Batch 1-4 closure + Batch 5.1: the packet boundary is enforced with model
    tools, not just prose. With an active packet round (builder-packets/
    active-round.json) a builder may not re-read the frozen inputs the contract
    lists, and its page access is confined to the shard bound to its agent_id.

    Registration is EXPLICIT: reading the instance's own Builder Packet — its task
    input — binds agent_id → packet. Page access before that read is refused, so
    the scope can never be inferred from whichever page was touched first."""

    def setUp(self) -> None:
        self.install_fixture()
        self.art = self.work / "art-direction.yaml"
        self.art.write_text("style_seed: x\n", encoding="utf-8")
        self.other_page = self.work / "pages/p02-plain.js"
        self.other_page.write_text("// other shard", encoding="utf-8")
        self.packet_dir = self.work / "builder-packets"
        self.packet_dir.mkdir(parents=True)
        self.own_packet = self.packet_dir / "initial-shard-01.json"
        self.own_packet.write_text("{}", encoding="utf-8")
        self.other_packet = self.packet_dir / "initial-shard-02.json"
        self.other_packet.write_text("{}", encoding="utf-8")
        self.write_round()

    def write_round(self, at: str = "2026-09-19T10:00:00+00:00") -> None:
        (self.packet_dir / "active-round.json").write_text(
            json.dumps({
                "at": at,
                "mode": "initial",
                "packets": [
                    {"packet": str(self.own_packet), "assigned_slides": [1, 4, 7]},
                    {"packet": str(self.other_packet), "assigned_slides": [2, 5, 8]},
                ],
            }),
            encoding="utf-8",
        )

    def binding(self, agent_id: str = "builder-shard-1") -> dict | None:
        path = self.project / "outputs/.pptx-work/.guard" / f"packet-binding-{agent_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def test_no_reread_artifact_is_refused_for_a_packed_builder(self) -> None:
        self.assertEqual(2, guard.handle(self.builder(self.art, "Read")))

    def test_main_session_still_reads_the_same_artifact(self) -> None:
        event = self.event("Read")
        event["tool_input"] = {"file_path": str(self.art)}
        self.assertEqual(0, guard.handle(event))

    def test_page_access_before_registration_is_refused(self) -> None:
        """5.1: the shard scope is bound by reading the packet, never inferred from
        whichever page the instance touched first."""
        result = guard.handle(self.builder(self.page, "Edit"))
        self.assertEqual(2, result)
        self.assertIsNone(self.binding())

    def test_reading_the_own_packet_registers_the_shard(self) -> None:
        self.assertEqual(0, guard.handle(self.builder(self.own_packet, "Read")))
        binding = self.binding()
        self.assertEqual([1, 4, 7], binding["allowed_slides"])
        self.assertEqual("initial-shard-01.json", Path(binding["packet"]).name)
        # own pages allowed after registration
        self.assertEqual(0, guard.handle(self.builder(self.page, "Edit")))

    def test_other_shard_page_is_refused_after_registration(self) -> None:
        guard.handle(self.builder(self.own_packet, "Read"))
        self.assertEqual(2, guard.handle(self.builder(self.other_page)))

    def test_pages_outside_every_packet_stay_refused_after_registration(self) -> None:
        guard.handle(self.builder(self.own_packet, "Read"))
        orphan = self.work / "pages/p11-extra.js"
        orphan.write_text("// nobody assigned", encoding="utf-8")
        self.assertEqual(2, guard.handle(self.builder(orphan)))

    def test_a_binding_from_a_previous_round_is_expired(self) -> None:
        """5.1: bindings are round-scoped. A new spawn round must never inherit the
        previous round's shard scope — the stale binding is dropped and the
        instance has to re-register by reading its (new) packet."""
        guard.handle(self.builder(self.own_packet, "Read"))
        self.assertIsNotNone(self.binding())
        self.write_round(at="2026-09-19T11:00:00+00:00")
        self.assertEqual(2, guard.handle(self.builder(self.page, "Edit")))
        self.assertIsNone(self.binding())
        # re-registering against the new round works
        self.assertEqual(0, guard.handle(self.builder(self.own_packet, "Read")))
        self.assertEqual(0, guard.handle(self.builder(self.page, "Edit")))

    def test_reading_another_shards_packet_binds_to_it_fail_closed(self) -> None:
        """Reading the wrong packet registers the wrong scope; every own-page access
        is then refused. Fail-closed beats fail-open for a misdirected builder."""
        self.assertEqual(0, guard.handle(self.builder(self.other_packet, "Read")))
        binding = self.binding()
        self.assertEqual([2, 5, 8], binding["allowed_slides"])
        self.assertEqual(2, guard.handle(self.builder(self.page, "Edit")))

    def test_repeated_identical_dispatch_preserves_the_round_stamp(self) -> None:
        """Dispatch idempotency (Batch 5.1 follow-up): the SAME state, the SAME page
        assignment and the SAME packet content must produce the SAME effective
        authorization. A re-dispatch that only rotates the active-round timestamp
        would invalidate every in-flight builder's binding — the scheduler bug the
        live repro confirmed before this fix."""
        packets = [{"packet": str(self.own_packet), "slides": [1, 4, 7]}]
        builder_packet.record_active_round(self.work, "initial", packets)
        first = json.loads((self.packet_dir / "active-round.json").read_text(encoding="utf-8"))
        builder_packet.record_active_round(self.work, "initial", packets)
        second = json.loads((self.packet_dir / "active-round.json").read_text(encoding="utf-8"))
        self.assertEqual(first["at"], second["at"])

    def test_repeated_dispatch_preserves_active_builder_authorization(self) -> None:
        """The main session may call next/advance again while shards are in flight
        (inspection, a staggered spawn, a SubagentStop racing the batch). When that
        re-dispatch carries unchanged packets, the working builders must keep their
        binding — mid-flight page edits keep working without a re-read."""
        packets = [{"packet": str(self.own_packet), "slides": [1, 4, 7]}]
        builder_packet.record_active_round(self.work, "initial", packets)
        self.assertEqual(0, guard.handle(self.builder(self.own_packet, "Read")))
        self.assertEqual(0, guard.handle(self.builder(self.page, "Edit")))
        # the main session re-dispatches with UNCHANGED packets while builders work
        builder_packet.record_active_round(self.work, "initial", packets)
        self.assertEqual(
            0, guard.handle(self.builder(self.page, "Edit")),
            "an idempotent re-dispatch must not invalidate in-flight builders",
        )

    def test_a_genuine_reshard_still_rotates_the_round(self) -> None:
        """The reservation only covers UNCHANGED dispatches. When the pipeline
        genuinely re-shards (different assigned slides — e.g. a resume after an
        interrupted session), the round rotates by design and the previous
        binding expires: the old scope must not leak into the new round."""
        packets = [{"packet": str(self.own_packet), "slides": [1, 4, 7]}]
        builder_packet.record_active_round(self.work, "initial", packets)
        self.assertEqual(0, guard.handle(self.builder(self.own_packet, "Read")))
        self.assertEqual(0, guard.handle(self.builder(self.page, "Edit")))
        builder_packet.record_active_round(self.work, "initial", [
            {"packet": str(self.own_packet), "slides": [2, 5]},
            {"packet": str(self.other_packet), "slides": [3, 6]},
        ])
        self.assertEqual(2, guard.handle(self.builder(self.page, "Edit")))
        self.assertIsNone(self.binding())

    def test_without_an_active_round_the_fallback_path_stays_open(self) -> None:
        (self.packet_dir / "active-round.json").unlink()
        self.assertEqual(0, guard.handle(self.builder(self.art, "Read")))
        self.assertEqual(0, guard.handle(self.builder(self.other_page)))
        self.assertIsNone(self.binding())


if __name__ == "__main__":
    unittest.main()
