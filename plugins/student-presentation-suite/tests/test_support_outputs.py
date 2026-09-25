from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_support_outputs.py"


class SupportOutputTests(unittest.TestCase):
    def test_builds_teleprompter_cards_and_references(self) -> None:
        module = load_module(SCRIPT)
        data = {
            "meta": {"topic": "Demo", "citation_style": "APA"},
            "evidence_ledger": [
                {
                    "id": "e1",
                    "title": "Source",
                    "locator": "https://example.test",
                    "confidence": "high",
                }
            ],
            "slides": [
                {
                    "id": 1,
                    "title": "Claim",
                    "claim": "Main point",
                    "supporting_points": ["Reason"],
                    "speaker_notes": "Explain it.",
                    "transition": "Continue.",
                    "timing_sec": 30,
                }
            ],
        }
        teleprompter = module.teleprompter_html(data)
        cards = module.training_cards(data)
        references = module.references_markdown(data)
        self.assertIn("Explain it.", teleprompter)
        self.assertIn("Likely question", cards)
        self.assertIn("https://example.test", references)

    def test_cli_generates_only_confirmed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "meta": {
                            "topic": "Demo",
                            "output_prefix": "demo",
                            "deliverables": ["speaker-notes", "references"],
                        },
                        "slides": [
                            {
                                "id": 1,
                                "title": "Claim",
                                "layout": "claim-focus",
                                "content": "Evidence",
                                "timing_sec": 30,
                                "owner": "A",
                                "speaker_notes": "Explain the evidence.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "outputs"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(spec), "--output-dir", str(output), "--json"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual({"speaker-notes", "references"}, set(payload["outputs"]))
            self.assertFalse((output / "demo-teleprompter.html").exists())

            only = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(spec),
                    "--output-dir",
                    str(output),
                    "--only",
                    "teleprompter",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(2, only.returncode, only.stdout + only.stderr)
            self.assertFalse(json.loads(only.stdout)["ok"])
            self.assertFalse((output / "demo-teleprompter.html").exists())

    def test_full_script_and_teleprompter_use_builder_authored_notes(self) -> None:
        module = load_module(SCRIPT)
        data = {
            "meta": {"topic": "Demo"},
            "slides": [
                {"id": 1, "title": "Opening", "note_goal": "Introduce the topic."},
                {"id": 2, "title": "Evidence", "note_goal": "Explain the chart."},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = Path(tmp) / "speaker-notes.md"
            notes_path.write_text(
                "# 演讲稿\n\n## 1 — Opening\n这是 Builder 写出的开场正文。\n\n"
                "## 2 — Evidence\n这里逐项解释实验结果与方法局限。\n",
                encoding="utf-8",
            )
            notes = module.actual_speaker_notes(data, notes_path, None)
            actual = module.with_actual_speaker_notes(data, notes)
            script = module.full_script_markdown(actual)
            teleprompter = module.teleprompter_html(actual)
        self.assertIn("Builder 写出的开场正文", script)
        self.assertIn("方法局限", teleprompter)
        self.assertNotIn("Introduce the topic", script)
        self.assertNotIn("Explain the chart", teleprompter)

    def test_planning_note_goal_cannot_stand_in_for_full_script(self) -> None:
        module = load_module(SCRIPT)
        data = {
            "slides": [
                {"id": 1, "title": "Opening", "note_goal": "Introduce the topic."},
            ]
        }
        with self.assertRaisesRegex(ValueError, "substantive per-slide speaker prose"):
            module.actual_speaker_notes(data, None, None)

    def test_pptx_placeholder_text_is_not_a_complete_script(self) -> None:
        module = load_module(SCRIPT)
        data = {"slides": [{"id": 1, "title": "Opening"}]}
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = Path(tmp) / "speaker-notes.md"
            notes_path.write_text("## 1 — Opening\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or too short: 1"):
                module.actual_speaker_notes(data, notes_path, None)

    def test_chinese_dot_separator_format_is_recognized(self) -> None:
        """Regression test: '## 第 N 页 · 标题' format must be parsed."""
        module = load_module(SCRIPT)
        data = {
            "slides": [
                {"id": 1, "title": "开场"},
                {"id": 10, "title": "环境"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = Path(tmp) / "speaker-notes.md"
            notes_path.write_text(
                "# 演讲稿\n\n## 第 1 页 · 开场\n\n这是开场白的完整正文内容。\n\n"
                "## 第 10 页 · 环境\n\n这是环境分析的完整正文内容。\n",
                encoding="utf-8",
            )
            notes = module.actual_speaker_notes(data, notes_path, None)
            self.assertEqual(notes[1], "这是开场白的完整正文内容。")
            self.assertEqual(notes[10], "这是环境分析的完整正文内容。")

    def test_body_subheadings_never_split_page_sections(self) -> None:
        """Regression: `### 3. 方法` used to truncate page 3 and drop its body."""
        module = load_module(SCRIPT)
        data = {"slides": [{"id": 3, "title": "方法"}]}
        with tempfile.TemporaryDirectory() as tmp:
            notes_path = Path(tmp) / "speaker-notes.md"
            notes_path.write_text(
                "## 第 3 页 · 方法\n\n开头一句。\n\n### 3. 方法\n细节说明仍在同一页。\n\n"
                "## 2. 这不是页标题\n子标题正文也在页内。\n",
                encoding="utf-8",
            )
            notes = module.actual_speaker_notes(data, notes_path, None)
        self.assertIn("细节说明仍在同一页", notes[3])
        self.assertIn("子标题正文也在页内", notes[3])

    def test_partial_render_refuses_to_write(self) -> None:
        """One emitted section per slide; partial scripts never reach disk."""
        module = load_module(SCRIPT)
        data = {"slides": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]}
        with self.assertRaisesRegex(ValueError, "refusing to write a partial deliverable"):
            module._assert_page_sections(
                "full-script", "# Full Presentation Script\n\n## Slide 1: A\n\n正文。\n", data
            )
        module._assert_page_sections(
            "full-script",
            "# Full Presentation Script\n\n## Slide 1: A\n\n正文。\n\n## Slide 2: B\n\n正文。\n",
            data,
        )


if __name__ == "__main__":
    unittest.main()
