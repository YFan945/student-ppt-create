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


class BuilderGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.page = self.project / "outputs/.pptx-work/demo/pages/p01-cover.js"
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

    def shell_event(self, command: str, **extra):
        return {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            **extra,
        }

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
        instance — the largest measured cost driver."""
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




class BuilderPacketScopeTests(BuilderGuardTests):
    """Batch 1-4 closure: the packet boundary is enforced with model tools, not
    just prose. An active packet round (builder-packets/active-round.json) bans
    re-reading the frozen inputs it projects and confines page access to the
    instance's own shard."""

    def setUp(self) -> None:
        super().setUp()
        self.art = self.project / "outputs/.pptx-work/demo/art-direction.yaml"
        self.art.write_text("style_seed: x\n", encoding="utf-8")
        self.other_page = self.project / "outputs/.pptx-work/demo/pages/p02-plain.js"
        self.other_page.write_text("// other shard", encoding="utf-8")
        packets = {"packets": [
            {"packet": "builder-packets/initial-shard-01.json", "assigned_slides": [1, 4, 7]},
            {"packet": "builder-packets/initial-shard-02.json", "assigned_slides": [2, 5, 8]},
        ]}
        active = self.project / "outputs/.pptx-work/demo/builder-packets"
        active.mkdir(parents=True)
        (active / "active-round.json").write_text(json.dumps(packets), encoding="utf-8")

    def builder_event(self, path: Path, tool: str = "Read") -> dict:
        event = self.event(tool)
        event["tool_input"] = {"file_path": str(path)}
        event["agent_type"] = guard.BUILDER
        event["agent_id"] = "builder-shard-1"
        return event

    def test_no_reread_artifact_is_refused_for_a_packed_builder(self) -> None:
        self.assertEqual(2, guard.handle(self.builder_event(self.art, "Read")))

    def test_main_session_still_reads_the_same_artifact(self) -> None:
        event = self.event("Read")
        event["tool_input"] = {"file_path": str(self.art)}
        self.assertEqual(0, guard.handle(event))

    def test_first_page_access_binds_the_instance_to_its_shard(self) -> None:
        self.assertEqual(0, guard.handle(self.builder_event(self.page, "Edit")))
        binding = json.loads(
            (self.project / "outputs/.pptx-work/.guard/packet-binding-builder-shard-1.json").read_text(encoding="utf-8")
        )
        self.assertEqual([1, 4, 7], binding["allowed_slides"])

    def test_other_shard_page_is_refused_after_binding(self) -> None:
        self.assertEqual(0, guard.handle(self.builder_event(self.page)))
        self.assertEqual(2, guard.handle(self.builder_event(self.other_page)))

    def test_page_outside_every_packet_is_refused_on_first_access(self) -> None:
        orphan = self.project / "outputs/.pptx-work/demo/pages/p11-extra.js"
        orphan.write_text("// nobody assigned", encoding="utf-8")
        self.assertEqual(2, guard.handle(self.builder_event(orphan)))

    def test_without_an_active_round_the_fallback_path_stays_open(self) -> None:
        (self.project / "outputs/.pptx-work/demo/builder-packets/active-round.json").unlink()
        self.assertEqual(0, guard.handle(self.builder_event(self.art, "Read")))
        self.assertEqual(0, guard.handle(self.builder_event(self.other_page)))


if __name__ == "__main__":
    unittest.main()
