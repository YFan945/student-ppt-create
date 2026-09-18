"""agent-behavior-contract.json is the single canonical machine source of agent behavior.

Batch 1 of the v0.15 pipeline-simplification series: rules move from scattered prose
(SKILL / agent definitions / spawn templates / guard refusal texts) to one machine
contract. These tests enforce the projections, so a prose file that contradicts the
contract — the `page_brief` "one call per page" vs "whole deck once" conflict measured
on 2026-09-18 — fails CI instead of costing a live round.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "references" / "agent-behavior-contract.json"
PIPELINE_CONTRACT = ROOT / "references" / "pipeline-contract.json"
BUILDER_MD = ROOT / "agents" / "presentation-builder.md"
TEMPLATES_MD = ROOT / "references" / "spawn-templates.md"
PAGE_BRIEF = ROOT / "skills" / "sp-deck" / "scripts" / "page_brief.py"

builder_guard = load_module(ROOT / "scripts" / "builder_guard.py")

BUILDER = "student-presentation-suite:presentation-builder"

SPEC = """\
meta:
  citation_style: classroom
slides:
  - id: 1
    title: 封面页
    claim: 交叉点不等于替代时点
    layout: cover
    content: []
    timing_sec: 30
    owner: deck
    slide_copy:
      - 2024 年公用事业级光伏 LCOE 降至 0.044 美元每千瓦时
  - id: 7
    title: 数据页
    claim: 储能时长从 4 小时走到 10 小时，度电成本才追平
    layout: chart
    content: []
    timing_sec: 40
    owner: deck
    slide_copy:
      - 85% 的新增装机来自光伏
evidence_ledger: []
"""


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def shell_event(command: str, project: Path) -> dict:
    return {
        "cwd": str(project),
        "session_id": "parent",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "agent_type": BUILDER,
        "agent_id": "builder-child",
    }


def captured_refusal(event: dict) -> str:
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        code = builder_guard.handle(event)
    return buffer.getvalue() if code == 2 else ""


class ContractShapeTests(unittest.TestCase):
    def test_contract_exists_and_has_required_sections(self) -> None:
        contract = load_contract()
        for section in ("presentation_builder", "visual_critic", "presentation_researcher"):
            self.assertIn(section, contract)

    def test_builder_forbidden_actions_match_the_guard_and_the_agent_frontmatter(self) -> None:
        builder = load_contract()["presentation_builder"]
        self.assertFalse(builder["production_build_allowed"])
        self.assertFalse(builder["render_allowed"])
        self.assertFalse(builder["qa_allowed"])
        self.assertFalse(builder["research_allowed"])
        self.assertEqual(["calibration", "initial", "repair"], builder["allowed_modes"])
        # The guard actually refuses what the contract forbids.
        self.assertTrue(builder_guard.RENDER_OWNED.search("calibration_preview.py --work-dir w"))
        self.assertTrue(builder_guard.RENDER_OWNED.search("ppt_pipeline.py render"))

    def test_builder_contract_matches_pipeline_repeat_policy(self) -> None:
        contract = load_contract()["presentation_builder"]
        pipeline = json.loads(PIPELINE_CONTRACT.read_text(encoding="utf-8"))["repeat_policy"]
        self.assertEqual(
            not contract["builder_instance_reuse"],
            pipeline["one_builder_instance_per_round"],
            "instance-reuse rules must not disagree between the two contracts",
        )
        # Shards are allowed; a builder just may not read outside its own shard.
        self.assertTrue(pipeline["parallel_builder_shards_allowed"])
        self.assertFalse(contract["read_other_shard_page_modules"])

    def test_edit_scope_covers_every_allowed_mode(self) -> None:
        builder = load_contract()["presentation_builder"]
        for mode in builder["allowed_modes"]:
            self.assertIn(mode, builder["edit_scope"])


class PageBriefStrategyProjectionTests(unittest.TestCase):
    """The 2026-09-18 conflict: builder.md said "one call per page" and
    "do not call it once per page" in the same file. The contract picks one
    strategy per mode; the prose must project exactly that."""

    def test_builder_definition_carries_no_per_page_contradiction(self) -> None:
        text = BUILDER_MD.read_text(encoding="utf-8")
        self.assertNotIn("one call per page", text)
        self.assertIn("--slides <ids>", text, "calibration/repair need the target-pages form")
        self.assertIn("--work-dir <wd> --json", text, "initial needs the whole-deck form")

    def test_packet_and_legacy_reading_are_conditional_not_contradictory(self) -> None:
        """Batch 2.1: the packet section says 'do not re-read the frozen inputs'
        while the Scope used to say 'read the frozen inputs' unconditionally —
        the same contradiction shape as the page_brief conflict. The Scope steps
        must be explicitly fallback-only."""
        text = BUILDER_MD.read_text(encoding="utf-8")
        self.assertIn("Conditional on the task input", text)
        self.assertGreaterEqual(text.count("fallback-only"), 4,
            "every unconditional 'read the frozen inputs' step must be marked fallback-only")
        # The repair report read is projected into repair packets too.
        self.assertIn("its `slides[].blockers` / `deck_blockers` ARE the report projection", text)

    def test_spawn_templates_project_the_same_strategy(self) -> None:
        text = TEMPLATES_MD.read_text(encoding="utf-8")
        blocks = re.split(r"^## ", text, flags=re.M)
        builder_block = next(block for block in blocks if block.startswith("builder"))
        self.assertNotIn("one call per page", builder_block)
        self.assertIn("--slides <ids>", builder_block)
        self.assertIn("绝不逐页调用", builder_block)
        self.assertIn("--work-dir <wd> --json", builder_block)

    def test_page_brief_is_fallback_only_when_a_packet_is_present(self) -> None:
        """Batch 2.2: 'packet = complete task input' while Hard boundaries still
        mandated one page_brief call per round was the same contradiction shape
        again — the model would pay one extra context round-trip per round."""
        builder = load_contract()["presentation_builder"]
        self.assertEqual(
            0, builder["page_brief_calls_per_round"]["with_packet"],
            "a packet projects everything page_brief would answer; the call must be zero",
        )
        self.assertEqual(
            1, builder["page_brief_calls_per_round"]["legacy_fallback_max"],
            "the legacy fallback path stays one call per round",
        )
        text = BUILDER_MD.read_text(encoding="utf-8")
        self.assertIn("do not call `page_brief.py` at all", text)
        self.assertIn("never combine it with a packet", text)
        templates = TEMPLATES_MD.read_text(encoding="utf-8")
        self.assertIn("仅在未提供 packet 时", templates)
        self.assertIn("不要再调 page_brief.py", templates)

    def test_every_projected_file_mention_in_spawn_templates_is_fallback_gated(self) -> None:
        """Batch 2.3: three prose surfaces (先读冻结契约 / 要上下文就用 page_brief /
        请自行读报告原文) kept telling the builder to read inputs the packet
        projects — the same drift found three times by hand. This test makes CI
        catch it: the contract owns the no-reread list, and ANY mention of one of
        those artifacts in the builder template must sit either inside the packet
        entry (which enumerates and forbids them) or inside a fallback-gated
        bullet. A new unconditional '先读 slide-spec' fails here, not in a live run."""
        packet_contract = load_contract()["presentation_builder"]["packet"]
        tokens = packet_contract["no_reread_files"]
        gates = ("未提供 packet", "有 packet", "已拿到", "fallback")
        text = TEMPLATES_MD.read_text(encoding="utf-8")
        blocks = re.split(r"^## ", text, flags=re.M)
        builder_block = next(block for block in blocks if block.startswith("builder"))
        fenced = re.search(r"```text\n(.*?)```", builder_block, flags=re.S)
        self.assertIsNotNone(fenced, "builder 段必须包含 ```text 模板块")
        bullets: list[str] = []
        for line in fenced.group(1).splitlines():
            if line.startswith("- "):
                bullets.append(line)
            elif bullets and (line.startswith("  ") or not line.strip()):
                bullets[-1] += "\n" + line
        entry = next((b for b in bullets if "唯一任务输入" in b), "")
        self.assertTrue(entry, "builder 模板必须有 packet 任务输入条目")
        for token in tokens:
            self.assertIn(token, entry, f"packet 条目必须点名禁重读对象：{token}")
        for bullet in bullets:
            if bullet is entry:
                continue
            for token in tokens:
                if token in bullet:
                    self.assertTrue(
                        any(gate in bullet for gate in gates),
                        f"builder 模板里提到 '{token}' 的条目必须是 fallback-gated（有 packet 时不得重读）：\n{bullet}",
                    )

    def test_guard_refusals_cite_the_contract_not_their_own_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            refusal = captured_refusal(
                shell_event(
                    "python \"$CLAUDE_PLUGIN_ROOT/skills/sp-deck/scripts/calibration_preview.py\""
                    " --work-dir w --slides 1 5 --json",
                    project,
                )
            )
        self.assertTrue(refusal, "render by the builder must be refused")
        self.assertIn("agent-behavior-contract.json", refusal)

    def test_inline_dig_refusal_hands_back_both_command_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            refusal = captured_refusal(
                shell_event(
                    "python - <<'PY'\nimport json\nprint(json.load(open('build-manifest.json')))\nPY",
                    project,
                )
            )
        self.assertTrue(refusal, "inline digging must be refused")
        self.assertIn("agent-behavior-contract.json", refusal)
        self.assertIn("--slides <ids>", refusal)
        self.assertNotIn("--slide <N>", refusal, "the debug form must not be the mandated hint")


class PageBriefTargetPagesTests(unittest.TestCase):
    """`--slides 2 5 8` must return every target page in ONE call — the mechanism that
    makes `page_brief_strategy: target_pages` executable instead of aspirational."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "demo"
        (self.work / "pages").mkdir(parents=True)
        self.brief = load_module(PAGE_BRIEF)
        (self.work / "slide-spec-compiled.yaml").write_text(SPEC, encoding="utf-8")
        (self.work / "build-manifest.json").write_text(
            json.dumps({"state": "producing", "manifest_version": "2.0"}), encoding="utf-8"
        )
        (self.work / "pipeline-qa.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "failed_stages": ["quality"],
                    "blockers_by_gate": {"quality": ["speaker_notes_missing"]},
                    "derived_problems": [],
                    "problems": [
                        {"gate": "quality", "severity": "major", "code": "overflow",
                         "message": "title overflow", "slide": 7},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.work / "pages" / "p01-cover.js").write_text("// stub", encoding="utf-8")
        (self.work / "pages" / "p07-s07.js").write_text("// stub", encoding="utf-8")

    def test_target_pages_return_in_one_call(self) -> None:
        brief = self.brief.build_brief(self.work, slides=[1, 7])
        self.assertEqual("target_pages", brief["mode"])
        self.assertEqual([1, 7], brief["target_slides"])
        self.assertEqual([1, 7], [item["slide"] for item in brief["slides"]])
        self.assertEqual("pages/p01-cover.js", brief["slides"][0]["page_module"])
        self.assertEqual(["overflow"], [b["code"] for b in brief["slides"][1]["blockers"]])

    def test_target_pages_matches_the_single_page_form_byte_for_byte(self) -> None:
        """The projection must not depend on which form requested it."""
        multi = self.brief.build_brief(self.work, slides=[7])["slides"][0]
        single = self.brief.build_brief(self.work, 7)
        self.assertEqual(single["on_screen"], multi["on_screen"])
        self.assertEqual(single["blockers"], multi["blockers"])
        self.assertEqual(single["page_module"], multi["page_module"])

    def test_unknown_target_page_is_an_error_not_an_empty_brief(self) -> None:
        with self.assertRaises(SystemExit):
            self.brief.build_brief(self.work, slides=[7, 99])

    def test_slide_and_slides_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            self.brief.build_brief(self.work, 7, slides=[7])


if __name__ == "__main__":
    unittest.main()
