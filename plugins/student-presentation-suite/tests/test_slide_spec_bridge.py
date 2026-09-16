from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "slide_spec_to_pptx_brief.py"


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("slide_spec_to_pptx_brief", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SlideSpecBridgeTests(unittest.TestCase):
    def test_production_mode_rejects_pdf_as_ooxml_edit_source(self) -> None:
        bridge = load_bridge_module()
        data = {"source_deck": "reference.pdf", "edit_intent": "review-fix"}
        self.assertEqual("rebuild_from_source", bridge.derive_production_mode(data))
        with self.assertRaises(ValueError):
            bridge.derive_production_mode(data, "edit_ooxml")

    def test_explicit_create_rejects_editable_source_even_without_intent(self) -> None:
        bridge = load_bridge_module()
        with self.assertRaises(ValueError):
            bridge.derive_production_mode({"source_deck": "source.pptx"}, "create")

    def test_production_source_must_be_readable_for_consuming_modes(self) -> None:
        bridge = load_bridge_module()
        with self.assertRaises(ValueError):
            bridge.validate_production_source(
                {"source_deck": "missing.pptx"}, "edit_ooxml"
            )

    def test_builds_claude_pptx_brief_from_valid_spec(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {
                "topic": "Responsible use of generative AI",
                "presentation_type": "coursework report",
                "audience": "Teacher and classmates",
                "language": "Chinese",
                "duration_min": 3,
                "slide_count": 1,
                "format": "individual",
                "image_source": "diagram-only",
                "source_material": ["Course brief", "Student reflection"],
                "visual_style": "Modern Minimal",
                "deliverables": ["pptx", "speaker-notes", "preview"],
                "output_prefix": "ai-class-demo",
            },
            "slides": [
                {
                    "id": 1,
                    "title": "AI 帮助我们更快形成初稿",
                    "layout": "process",
                    "content": {"bullets": ["提出想法", "整理结构", "人工修改"]},
                    "visual": {
                        "type": "three-step-process",
                        "purpose": "Show a responsible AI writing workflow",
                    },
                    "note_goal": "Explain AI as support, not replacement",
                    "transition": "接下来说明边界。",
                    "timing_sec": 180,
                    "owner": "A",
                }
            ],
        }

        brief = bridge.build_brief(data, Path("input.yaml"))

        self.assertIn("Mode: `create`", brief)
        self.assertIn("pptxgenjs-safety.md", brief)
        self.assertIn("pptx_tool.py", brief)
        self.assertIn("ai-class-demo-presentation.pptx", brief)
        self.assertIn("ai-class-demo-delivery-report.json", brief)
        self.assertIn("AI 帮助我们更快形成初稿", brief)
        self.assertIn("Responsible use of generative AI", brief)
        self.assertIn("Teacher and classmates", brief)
        self.assertIn("Modern Minimal", brief)
        self.assertIn("Resolved Design Tokens", brief)
        self.assertIn('"standard_pt": 1.25', brief)
        self.assertIn("Student reflection", brief)
        self.assertIn("Run `pptx_tool.py inspect --text-output` for every final candidate", brief)
        self.assertIn("pptx_tool.py\" validate", brief)
        self.assertIn("Reuse the producing-stage package report when its PPTX hash still matches", brief)

    def test_builds_existing_deck_improvement_brief(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {
                "presentation_type": "coursework report",
                "language": "Chinese",
                "duration_min": 5,
                "format": "individual",
                "output_prefix": "improved-demo",
            },
            "source_deck": "original-demo.pptx",
            "edit_intent": "review-fix",
            "preserve": ["course logo", "approved section order"],
            "change_summary_required": True,
            "review_findings": [
                {
                    "severity": "Major",
                    "target": "Slide 2",
                    "problem": "The title is generic.",
                    "fix": "Rewrite it as a claim-style title.",
                }
            ],
            "slides": [
                {
                    "id": 1,
                    "title": "AI 工具只负责加速初稿",
                    "layout": "process",
                    "content": {"bullets": ["输入目标", "生成初稿", "人工修订"]},
                    "visual": {
                        "type": "three-step-process",
                        "purpose": "Show the corrected workflow",
                    },
                    "note_goal": "Explain the improved message",
                    "transition": "接下来说明边界。",
                    "timing_sec": 300,
                    "owner": "A",
                }
            ],
        }

        errors = bridge.validate_spec(
            data,
            ROOT / "references" / "slide-spec.schema.json",
            __import__("jsonschema"),
        )
        brief = bridge.build_brief(data, Path("input.yaml"))

        self.assertEqual([], errors)
        self.assertIn("Existing Deck Improvement Contract", brief)
        self.assertIn("original-demo.pptx", brief)
        self.assertIn("Mode: `edit_ooxml`", brief)
        self.assertIn("references/pptx-editing.md", brief)
        self.assertIn("improved-demo-change-summary.md", brief)
        self.assertIn("Rewrite it as a claim-style title", brief)
        self.assertIn("## Editing Runtime", brief)
        self.assertIn("## Slide Edit Plan", brief)
        self.assertNotIn("## Production Toolkit (MANDATORY)", brief)
        self.assertNotIn("const pptx = new pptxgen()", brief)

    def test_explicit_clean_rebuild_uses_rebuild_mode(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {"output_prefix": "rebuilt-demo"},
            "source_deck": "broken-source.pptx",
            "edit_intent": "rebuild-clean-copy",
            "slides": [
                {
                    "id": 1,
                    "title": "Rebuilt",
                    "layout": "title",
                    "content": "Recovered content",
                    "timing_sec": 30,
                    "owner": "A",
                }
            ],
        }
        brief = bridge.build_brief(data, Path("input.yaml"))
        self.assertIn("Mode: `rebuild_from_source`", brief)
        self.assertIn("writes a pptxgenjs `deck.js`", brief)
        self.assertIn("Do not overwrite the source deck", brief)

    def test_long_text_warning_builds_without_key_error(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {"output_prefix": "long-copy"},
            "slides": [{
                "id": 1, "title": "Long copy", "layout": "content",
                "content": {"bullets": ["这是需要触发文本适配预警的长文本。" * 30]},
                "timing_sec": 60, "owner": "A",
            }],
        }
        brief = bridge.build_brief(data, Path("input.yaml"))
        self.assertIn("Text Fit Warnings", brief)
        self.assertIn("盒高", brief)

    def test_script_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.yaml"
            output_path = Path(tmp) / "brief.md"
            spec_path.write_text(
                """
meta:
  presentation_type: coursework report
  language: Chinese
  duration_min: 3
  slide_count: 1
  format: individual
  image_source: diagram-only
  output_prefix: demo
slides:
  - id: 1
    title: Demo
    layout: title
    content:
      bullets:
        - Point
    visual:
      type: title-card
      purpose: Introduce the topic
    note_goal: Open naturally
    transition: Continue.
    timing_sec: 180
    owner: A
""",
                encoding="utf-8",
            )

            bridge = load_bridge_module()
            exit_code = None
            try:
                with mock.patch(
                    "sys.argv",
                    ["slide_spec_to_pptx_brief.py", str(spec_path), "--output", str(output_path)],
                ):
                    bridge.main()
            except SystemExit as exc:
                exit_code = exc.code

            self.assertIn(exit_code, (None, 0))
            self.assertTrue(output_path.is_file())
            self.assertIn("demo-presentation.pptx", output_path.read_text(encoding="utf-8"))

    def test_semantic_validation_rejects_cross_field_mismatches(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {
                "duration_min": 5,
                "slide_count": 3,
                "format": "group",
                "members": ["A", "B"],
            },
            "review_findings": [
                {
                    "severity": "Major",
                    "target": "Slide 1",
                    "problem": "Generic title",
                    "fix": "Use a specific title",
                }
            ],
            "slides": [
                {
                    "id": 2,
                    "title": "First",
                    "layout": "content",
                    "content": "Point",
                    "timing_sec": 20,
                    "owner": "C",
                }
            ],
        }

        errors = bridge.validate_spec(
            data,
            ROOT / "references" / "slide-spec.schema.json",
            __import__("jsonschema"),
        )
        messages = "\n".join(error["message"] for error in errors)

        self.assertIn("contiguous", messages)
        self.assertIn("slide_count", messages)
        self.assertIn("inconsistent with duration_min", messages)
        self.assertIn("not listed in meta.members", messages)
        self.assertIn("source_deck is required", messages)

    def test_schema_rejects_unknown_slide_fields(self) -> None:
        bridge = load_bridge_module()
        data = {
            "slides": [
                {
                    "id": 1,
                    "title": "Demo",
                    "layout": "content",
                    "content": "Point",
                    "timing_sec": 30,
                    "owner": "Individual",
                    "timing_seconds": 30,
                }
            ]
        }

        errors = bridge.validate_spec(
            data,
            ROOT / "references" / "slide-spec.schema.json",
            __import__("jsonschema"),
        )

        self.assertTrue(any("Additional properties" in error["message"] for error in errors))

    def test_scenario_story_role_is_advisory_not_blocking(self) -> None:
        bridge = load_bridge_module()
        required_missing = {
            "coursework": "method", "defense": "qa", "competition": "solution",
            "club-showcase": "method", "research": "limitation",
        }
        common_roles = ["opening", "background", "problem", "method", "evidence", "result", "solution", "value", "limitation", "conclusion", "qa", "closing"]
        for scenario, missing in required_missing.items():
            with self.subTest(scenario=scenario):
                roles = [role for role in common_roles if role != missing]
                data = {
                    "meta": {"scenario": scenario, "slide_count": len(roles)},
                    "slides": [
                        {"id": index + 1, "title": role, "layout": "content", "content": role,
                         "role": role, "timing_sec": 30, "owner": "A"}
                        for index, role in enumerate(roles)
                    ],
                }
                errors = bridge.validate_spec(data, ROOT / "references" / "slide-spec.schema.json", __import__("jsonschema"))
                # 场景故事角色完整性为建议性（analyze 输出 Minor），不再硬阻断。
                self.assertEqual([], errors, f"missing {missing} role should not block: {errors}")

    def test_visual_semantics_require_structured_layout_details(self) -> None:
        bridge = load_bridge_module()
        data = {
            "meta": {"visual_text_ratio": "visual-led", "slide_count": 2},
            "slides": [
                {"id": 1, "title": "Timeline", "layout": "timeline", "content": "x", "timing_sec": 30, "owner": "A",
                 "visual": {"type": "timeline", "purpose": "show sequence", "details": {"stages": ["a", "b"]}}},
                {"id": 2, "title": "Visual missing", "layout": "content", "content": "x", "timing_sec": 30, "owner": "A"},
            ],
        }
        errors = bridge.validate_spec(data, ROOT / "references" / "slide-spec.schema.json", __import__("jsonschema"))
        messages = "\n".join(error["message"] for error in errors)
        self.assertIn("timeline requires at least 3 stages", messages)
        self.assertIn("visual-led mode requires a visual", messages)

    def test_chart_visual_requires_complete_evidence_metadata(self) -> None:
        bridge = load_bridge_module()
        data = {
            "slides": [{
                "id": 1, "title": "Chart", "layout": "chart", "content": "x", "timing_sec": 30, "owner": "A",
                "visual": {"type": "chart", "purpose": "show evidence", "details": {"measure": "score"}},
            }],
        }
        errors = bridge.validate_spec(data, ROOT / "references" / "slide-spec.schema.json", __import__("jsonschema"))
        self.assertIn("chart requires: unit, scope, source, takeaway", "\n".join(error["message"] for error in errors))


if __name__ == "__main__":
    unittest.main()
