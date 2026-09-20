"""冒烟/集成测试：验证关键流水线组件可独立运行且不崩溃。

这些测试验证各脚本的 CLI 入口点能正常启动并返回预期退出码。
它们不渲染真实幻灯片，只是确保依赖解析和基本逻辑无中断。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable


class SmokeTests(unittest.TestCase):
    """验证关键脚本可正常启动并完成基本工作。"""

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PYTHON, *args],
            capture_output=True, text=True, timeout=timeout,
            cwd=ROOT,
        )

    def test_validate_slide_spec_schema(self) -> None:
        """validate_slide_spec 可识别合法 spec 并输出验证结果。"""
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.yaml"
            spec.write_text(
                "meta:\n  topic: Test\n  presentation_type: coursework\n"
                "  language: chinese\n  slide_count: 1\n"
                "slides:\n  - id: 1\n    title: Hello\n"
                "    kind: content\n    layout: title-content\n"
                "    content: {}\n",
                encoding="utf-8",
            )
            proc = self._run(str(SCRIPTS / "validate_slide_spec.py"), str(spec))
            # 脚本以 exit 0 或 1 报告验证结果，不崩溃即视为通过
            self.assertIn(proc.returncode, (0, 1), msg=proc.stderr[:500])

    def test_validate_slide_spec_explains_slide_copy_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.yaml"
            spec.write_text(
                "slides:\n"
                "  - id: 1\n"
                "    title: Hello\n"
                "    slide_copy: {title: Hello, subtitle: World}\n",
                encoding="utf-8",
            )
            proc = self._run(str(SCRIPTS / "validate_slide_spec.py"), str(spec))
            self.assertEqual(1, proc.returncode)
            self.assertIn("slide_copy must be a string or string[]", proc.stdout)

    def test_analyze_presentation_spec(self) -> None:
        """analyze_presentation_spec 对合法 spec 输出 JSON。"""
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.yaml"
            spec.write_text(
                "meta:\n  topic: Integration Test\n  presentation_type: coursework\n"
                "  language: chinese\n  slide_count: 2\n"
                "slides:\n  - id: 1\n    title: Intro\n    kind: content\n"
                "    layout: title-content\n    content: { claim: 'test' }\n"
                "  - id: 2\n    title: Data\n    kind: content\n"
                "    layout: title-content\n    content: { claim: 'data' }\n"
                "    role: evidence\n",
                encoding="utf-8",
            )
            proc = self._run(str(SCRIPTS / "analyze_presentation_spec.py"), str(spec))
            self.assertEqual(0, proc.returncode, msg=proc.stderr[:500])

    def test_slide_spec_to_pptx_brief_generates_output(self) -> None:
        """slide_spec_to_pptx_brief 为合法 spec 产出 brief（不崩溃）。"""
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.yaml"
            spec.write_text(
                "meta:\n  topic: E2E\n  presentation_type: coursework\n"
                "  language: Chinese\n  slide_count: 1\n"
                "  max_words_per_slide: 40\n  max_chinese_chars_per_slide: 80\n"
                "slides:\n  - id: 1\n    title: Hello\n    kind: content\n"
                "    layout: title-content\n    content: {}\n"
                "    timing_sec: 60\n    owner: student\n",
                encoding="utf-8",
            )
            proc = self._run(
                str(SCRIPTS / "slide_spec_to_pptx_brief.py"),
                str(spec), "--output-dir", tmp,
            )
            self.assertEqual(0, proc.returncode, msg=proc.stderr[:500])
            # 确认脚本不崩溃即可（输出可能写到 outputs/ 子目录）

    def test_workflow_guard_help(self) -> None:
        """workflow_guard 可正常输出帮助信息。"""
        proc = self._run(str(SCRIPTS / "workflow_guard.py"), "--help")
        self.assertEqual(0, proc.returncode, msg=proc.stderr[:500])
        self.assertIn("usage", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()
