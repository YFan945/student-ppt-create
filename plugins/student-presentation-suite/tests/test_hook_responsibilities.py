"""hooks.json 注册形状 + dispatcher 路由表与旧逐脚本 matcher 的等价性。

v0.21.2 之前 hooks.json 为每个 guard 单独注册：Bash 一次调用要起 4 个 python
进程（PostToolUse 还有第 5 个），而非管线会话里这些 guard 全部立即 exit 0——
阻塞边界 v0.19.1 已作用域化，执行边界没有。现在 PreToolUse 只注册一个
hook_dispatcher，路由发生在进程内；本测试把"路由表与旧 matcher 逐工具等价"
钉住，防止合并时静默丢失某个 guard 的管辖工具。
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "hooks.json"
sys.path.insert(0, str(ROOT / "scripts"))

import hook_dispatcher  # noqa: E402

# 旧 hooks.json 的逐脚本 matcher（v0.21.1 及之前）。
LEGACY_MATCHERS = {
    "production_entry_guard": {"Bash"},
    "cost_guard": {"Bash", "Read", "Grep"},
    "hook_health": {"Bash"},
    "builder_guard": {"Read", "Write", "Edit", "Bash", "PowerShell"},
    "runtime_evidence": {"Skill", "WebSearch", "WebFetch", "Agent", "SendMessage", "Write", "Edit"},
}


class HookResponsibilityTests(unittest.TestCase):
    def test_pretooluse_registers_a_single_dispatcher(self) -> None:
        data = json.loads(HOOKS.read_text(encoding="utf-8"))
        entries = data["hooks"]["PreToolUse"]
        self.assertEqual(1, len(entries))
        self.assertIn("hook_dispatcher.py", entries[0]["hooks"][0]["command"])
        self.assertEqual(
            {
                "Bash", "Read", "Grep", "Write", "Edit", "PowerShell",
                "Skill", "WebSearch", "WebFetch", "Agent", "SendMessage",
            },
            set(entries[0]["matcher"].split("|")),
        )

    def test_routes_cover_exactly_the_legacy_matchers(self) -> None:
        for guard_name, tools in LEGACY_MATCHERS.items():
            routed = {
                tool
                for tool, guards in hook_dispatcher.ROUTES.items()
                if any(guard.__name__ == guard_name for guard in guards)
            }
            self.assertEqual(tools, routed, guard_name)

    def test_dispatch_first_refusal_wins(self) -> None:
        calls: list[str] = []
        refuse = types.SimpleNamespace(handle=lambda _event: calls.append("refuse") or 2)
        never = types.SimpleNamespace(handle=lambda _event: calls.append("never") or 0)
        original = hook_dispatcher.ROUTES
        hook_dispatcher.ROUTES = {"Bash": (refuse, never)}
        try:
            self.assertEqual(2, hook_dispatcher.dispatch({"tool_name": "Bash"}))
            self.assertEqual(["refuse"], calls)
        finally:
            hook_dispatcher.ROUTES = original

    def test_guard_crash_does_not_block_the_rest(self) -> None:
        calls: list[str] = []
        boom = types.SimpleNamespace(
            handle=lambda _event: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        ok = types.SimpleNamespace(handle=lambda _event: calls.append("ok") or 0)
        original = hook_dispatcher.ROUTES
        hook_dispatcher.ROUTES = {"Bash": (boom, ok)}
        try:
            self.assertEqual(0, hook_dispatcher.dispatch({"tool_name": "Bash"}))
            self.assertEqual(["ok"], calls)
        finally:
            hook_dispatcher.ROUTES = original


if __name__ == "__main__":
    unittest.main()
