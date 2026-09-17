"""Every command the instructions mandate must survive the guard that polices it.

Instructions (SKILL / spawn templates), refusal hints and guard allow-lists are
three copies of one fact, and they drift silently — the agent only finds out by
losing a round.

2026-09-17 live: cost_guard refused the pipeline's own recommended invocation
(`--work-dir` matched the `dir` verb, quoted `.py` paths missed the allow-list)
and pointed the isolated builder at `ppt_pipeline.py next`, which the builder may
not run. The builder hit that dead end 14 times, hand-wrote composition evidence
instead, and produced 31 gate blockers.

2026-09-18: the same class reappeared as `page_brief.py` — mandated by
spawn-templates.md *and* by builder_guard's refusal text, absent from
production_entry_guard's allow-list, refused on the first call.

So the comparison is mechanical now: parse the commands out of the templates and
out of the refusals, then run them through the guards as the agent that is told
to run them.
"""

from __future__ import annotations

import io
import re
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "references" / "spawn-templates.md"
SCRIPT_DIR = ROOT / "scripts"

cost_guard = load_module(SCRIPT_DIR / "cost_guard.py")
entry_guard = load_module(SCRIPT_DIR / "production_entry_guard.py")
builder_guard = load_module(SCRIPT_DIR / "builder_guard.py")

BUILDER = "student-presentation-suite:presentation-builder"
RESEARCHER = "student-presentation-suite:presentation-researcher"
CRITIC = "student-presentation-suite:visual-critic"

PLUGIN_ROOT_TEXT = str(ROOT).replace("\\", "/")
# 数据槽在模板里是尖括号占位符；守卫只看路径形态与动词位置，填一个像样的值即可。
SLOTS = {
    "<wd>": "outputs/.pptx-work/demo",
    "<work-dir>": "outputs/.pptx-work/demo",
    "<absolute work-dir>": "outputs/.pptx-work/demo",
    "<work-id>": "demo",
    "<N>": "3",
    "<id>": "c1",
    "<role>": "cover",
    "<grammar>": "bar",
    "<strategy>": "typography_led",
    "<visual-strategy>": "typography_led",
    "<output>": "outputs/.pptx-work/demo/composition/c1.json",
    "<pack>": "outputs/.pptx-work/demo/research-pack.json",
    "<summary>": "outputs/production-summary.md",
    "<slide-spec>": "outputs/.pptx-work/demo/slide-spec-compiled.yaml",
    "<entry>": "outputs/.pptx-work/demo/deck.js",
    "<reason>": "blockers 4 -> 2",
}
COMMAND_RE = re.compile(
    r'(?P<interp>python3?|node|sh|bash)\s+"(?P<path>[^"]+\.(?:py|js|sh))"(?P<rest>[^\n`;]*)',
    re.I,
)


def fill_slots(text: str) -> str:
    for slot, value in SLOTS.items():
        text = text.replace(slot, value)
    # 剩下的占位符（<slide ids> 之类）不该出现在命令里；出现即模板写错，用哨兵暴露。
    return re.sub(r"<[^<>\n]{0,40}>", "X", text)


def commands_in(text: str) -> list[str]:
    """命令是散文里的一段文本；切到句号为止，避免把解释句当成参数。"""
    text = fill_slots(text.replace("<CLAUDE_PLUGIN_ROOT>", PLUGIN_ROOT_TEXT))
    found: list[str] = []
    for match in COMMAND_RE.finditer(text):
        rest = match.group("rest").split(". ", 1)[0]
        command = f'{match.group("interp")} "{match.group("path")}"{rest}'.rstrip("`. ")
        if command not in found:
            found.append(command)
    return found


def section(text: str, heading_startswith: str) -> str:
    """模板里某个 agent 的固定段。"""
    blocks = re.split(r"^## ", text, flags=re.M)
    for block in blocks:
        if block.startswith(heading_startswith):
            return block
    raise AssertionError(f"spawn-templates.md 里找不到 {heading_startswith} 段")


def assert_allowed(case: unittest.TestCase, command: str, agent_type: str) -> None:
    case.assertIsNone(
        cost_guard.check_bash(command, builder=agent_type == BUILDER),
        f"cost_guard 拒绝了指令要求的命令（{agent_type}）：{command}",
    )
    case.assertIsNone(
        entry_guard.check_bash(command, builder=agent_type == BUILDER),
        f"production_entry_guard 拒绝了指令要求的命令（{agent_type}）：{command}",
    )


class TemplateCommandConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.templates = TEMPLATES.read_text(encoding="utf-8")

    def test_templates_use_the_placeholder_form_not_shell_variables(self) -> None:
        """`${CLAUDE_PLUGIN_ROOT}` depends on the subagent's shell inheriting the variable;
        a command that does not expand is the same dead end as a blocked one."""
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", self.templates)
        self.assertIn("<CLAUDE_PLUGIN_ROOT>", self.templates)

    def test_builder_commands_survive_both_guards(self) -> None:
        commands = commands_in(section(self.templates, "builder"))
        self.assertTrue(commands, "builder 段应当至少给出一条可执行命令")
        self.assertTrue(
            any("page_brief.py" in command for command in commands),
            "builder 段必须保留 page_brief.py 投影读取",
        )
        for command in commands:
            with self.subTest(command=command):
                assert_allowed(self, command, BUILDER)

    def test_researcher_commands_survive_both_guards(self) -> None:
        for command in commands_in(section(self.templates, "researcher")):
            with self.subTest(command=command):
                assert_allowed(self, command, RESEARCHER)

    def test_critic_commands_survive_both_guards(self) -> None:
        for command in commands_in(section(self.templates, "critic")):
            with self.subTest(command=command):
                assert_allowed(self, command, CRITIC)


class RefusalHintConsistencyTests(unittest.TestCase):
    """Refusals must not send the agent to a command that another guard refuses."""

    def test_page_brief_and_helpers_are_callable_by_the_builder(self) -> None:
        for command in (
            f'python "{ROOT}/skills/sp-deck/scripts/page_brief.py" --work-dir outputs/.pptx-work/demo --slide 3 --json',
            f'python "{ROOT}/skills/sp-deck/scripts/page_brief.py" --work-dir outputs/.pptx-work/demo --json',
            f'node "{ROOT}/scripts/pptx-helpers.js" --describe',
            f'python "{ROOT}/skills/sp-deck/scripts/visual_reference_select.py" '
            "--role cover --grammar bar --visual-strategy typography_led "
            "--output outputs/.pptx-work/demo/composition/c1.json --json",
        ):
            with self.subTest(command=command):
                assert_allowed(self, command, BUILDER)
                assert_allowed(self, command, CRITIC)

    def test_production_entry_guard_builder_hint_is_self_consistent(self) -> None:
        refusal = entry_guard.check_bash(
            f'python "{ROOT}/skills/sp-deck/scripts/composition_candidate_check.py" --help',
            builder=True,
        )
        self.assertIsNotNone(refusal)
        hinted = commands_in(refusal)
        self.assertTrue(hinted, "拒绝消息必须给出可运行命令，而不是只说不许")
        for command in hinted:
            with self.subTest(command=command):
                assert_allowed(self, command, BUILDER)

    def test_builder_guard_hint_is_self_consistent(self) -> None:
        event = {
            "cwd": str(ROOT),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "agent_type": BUILDER,
            "agent_id": "builder-child",
            "tool_input": {"command": "node -e \"console.log(require('./qa-quality.json'))\""},
        }
        captured = io.StringIO()
        with redirect_stderr(captured):
            self.assertEqual(2, builder_guard.handle(event))
        hinted = commands_in(captured.getvalue())
        self.assertTrue(hinted, "builder_guard 的拒绝消息必须给出 page_brief.py 调用")
        for command in hinted:
            with self.subTest(command=command):
                assert_allowed(self, command, BUILDER)

    def test_cost_guard_hints_survive_their_own_guards(self) -> None:
        main_hint = cost_guard.pipeline_hint() + " or " + cost_guard.helpers_hint()
        for command in commands_in(main_hint):
            with self.subTest(command=command):
                assert_allowed(self, command, CRITIC)
        builder_hint = cost_guard.builder_hint()
        for command in commands_in(builder_hint):
            with self.subTest(command=command):
                assert_allowed(self, command, BUILDER)


class ProductionEntryCallabilityTests(unittest.TestCase):
    """command the workflow steps name explicitly, in the form the docs give it."""

    def test_documented_entrypoints_are_runnable(self) -> None:
        for command in (
            f'python "{ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" next --work-dir outputs/.pptx-work/demo',
            f'python "{ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir outputs/.pptx-work/demo',
            f'python "{ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" repair --work-dir outputs/.pptx-work/demo --reason "blockers 4 -> 2"',
            f'python "{ROOT}/skills/sp-deck/scripts/calibration_preview.py" --work-dir outputs/.pptx-work/demo --slides 1 2 3 --json',
            f'sh "{ROOT}/skills/sp-deck/scripts/run_gates.sh" --evidence-dir outputs/.pptx-work/demo',
            f'python "{ROOT}/skills/sp-deck/scripts/run_gates.py" --evidence-dir outputs/.pptx-work/demo',
            f'python "{ROOT}/scripts/workflow_guard.py" confirm --summary-file outputs/production-summary.md --work-id demo',
            f'python "{ROOT}/scripts/validate_research_pack.py" outputs/.pptx-work/demo/research-pack.json --output outputs/.pptx-work/demo/validation.json',
        ):
            with self.subTest(command=command):
                assert_allowed(self, command, CRITIC)

    def test_real_refusals_are_still_refused(self) -> None:
        """放行面扩大不能把真正的护栏一起放掉。"""
        for command in (
            f'cat "{ROOT}/scripts/cost_guard.py"',
            f'ls -la "{ROOT}/skills/sp-deck/scripts"',
            f'grep -n "def check_bash" "{ROOT}/scripts/builder_guard.py"',
            f'python "{ROOT}/scripts/research_pack_to_evidence.py" --work-dir demo',
        ):
            with self.subTest(command=command):
                refused = (
                    cost_guard.check_bash(command)
                    or entry_guard.check_bash(command)
                    or cost_guard.check_read(command, str(ROOT), "s", is_main=True)
                )
                self.assertIsNotNone(refused, f"应当仍然拒绝：{command}")


if __name__ == "__main__":
    unittest.main()
