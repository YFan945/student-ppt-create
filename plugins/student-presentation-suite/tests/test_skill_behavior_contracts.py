from __future__ import annotations

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
MARKETPLACE_CHECK = REPO_ROOT / "scripts" / "check_marketplace_release.py"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


def load_marketplace_check():
    spec = importlib.util.spec_from_file_location(
        "check_marketplace_release", MARKETPLACE_CHECK
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SkillBehaviorContractTests(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_manifest_and_marketplace_are_claude_specific(self) -> None:
        manifest = json.loads(self.read(".claude-plugin/plugin.json"))
        marketplace = json.loads(
            (REPO_ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        entry = marketplace["plugins"][0]
        self.assertEqual("claude-personal", marketplace["name"])
        self.assertEqual(manifest["name"], entry["name"])
        self.assertEqual(
            [], manifest["dependencies"],
            "manifest 依赖列表应为空（pptx skill 已内嵌）",
        )
        for field in ("homepage", "repository", "license", "keywords"):
            self.assertTrue(manifest[field])
            self.assertTrue(entry[field])
        self.assertFalse((ROOT / ".codex-plugin").exists())
        self.assertFalse(any(ROOT.glob("skills/*/agents/openai.yaml")))

    def test_marketplace_release_accepts_prs_targeting_claude_code(self) -> None:
        check = load_marketplace_check()
        self.assertIsNone(
            check.release_branch_error(
                "codex/claude-plugin-0.4.0",
                "codex/claude-plugin-0.4.0",
                "claude-code",
                "1/merge",
            )
        )
        self.assertIn(
            "must target claude-code",
            check.release_branch_error("feature", "feature", "main", "1/merge"),
        )
        self.assertIsNone(check.release_branch_error("claude-code", "", "", ""))
        self.assertIn(
            "must be released from claude-code",
            check.release_branch_error("main", "", "", ""),
        )

    def test_skill_frontmatter_has_distinct_intents(self) -> None:
        planning = frontmatter(ROOT / "skills/sp-outline/SKILL.md")
        ppt = frontmatter(ROOT / "skills/sp-deck/SKILL.md")
        review = frontmatter(ROOT / "skills/sp-review/SKILL.md")
        self.assertIn("outline", planning["description"])
        self.assertIn("editable", ppt["description"])
        self.assertIn("review", review["description"])

    def test_skill_versions_match_plugin_version(self) -> None:
        version = json.loads(self.read(".claude-plugin/plugin.json"))["version"]
        for path in ROOT.glob("skills/*/SKILL.md"):
            self.assertEqual(version, str(frontmatter(path).get("version")), path)

    def test_runtime_and_output_contracts_are_portable(self) -> None:
        planning = self.read("skills/sp-outline/SKILL.md")
        ppt = self.read("skills/sp-deck/SKILL.md")
        production = self.read("skills/sp-deck/references/pptx-production.md")
        review = self.read("skills/sp-review/SKILL.md")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", ppt)
        self.assertIn("${CLAUDE_PROJECT_DIR}", ppt)
        self.assertIn("run_with_pptxgenjs.js", production)
        self.assertIn("pptx_tool.py", ppt)
        self.assertIn("blocked", ppt)
        self.assertIn("incomplete", ppt)
        self.assertIn("不得写入 `${CLAUDE_PLUGIN_ROOT}`", planning)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", review)
        self.assertIn("${CLAUDE_PROJECT_DIR}", review)

    def test_create_flow_is_first_pass_and_reuses_package_evidence(self) -> None:
        production = self.read(
            "skills/sp-deck/references/pptx-production.md"
        )
        qa = self.read("skills/sp-deck/references/pptx-qa.md")
        self.assertIn("pptxgenjs-safety.md", production)
        self.assertIn("adaptive-freeform", production)
        self.assertIn("deterministic fallback", production)
        self.assertNotIn('**默认**\n   `require("pptx-composer")`', production)
        self.assertIn("safety preflight", production)
        self.assertIn("QA 和 delivery 绑定", production)
        self.assertIn("package validation", qa)
        self.assertIn("四个阶段", qa)
        self.assertIn("slide_spec_guard.py", qa)
        self.assertIn("pptx_quality_gate_v071.py", qa)
        self.assertIn("pptx_delivery_check_v071.py", qa)
        self.assertIn("Advanced evidence mode", qa)

    def test_cross_skill_handoff_is_deterministic(self) -> None:
        shared = self.read("references/shared-standards.md")
        self.assertIn("Outline-only work never creates", shared)
        self.assertIn('“看看问题” means review only', shared)
        self.assertIn('“直接改好” means review diagnosis followed by PPTX editing', shared)
        review = self.read("skills/sp-review/SKILL.md")
        self.assertIn("先诊断，再交接给 `sp-deck`", review)
        self.assertIn("不得覆盖原始 deck", review)

    def test_pptx_intake_is_a_hard_gate(self) -> None:
        intake = self.read("references/presentation-intake.md")
        ppt = self.read("skills/sp-deck/SKILL.md")
        production = self.read(
            "skills/sp-deck/references/pptx-production.md"
        )
        for field in (
            "Topic",
            "Course/context",
            "Presentation type",
            "Audience",
            "Language",
            "Duration",
            "Slide count",
            "Format",
            "Rubric/required sections",
            "Source material",
            "Template/branding",
            "Image strategy",
            "Visual style",
            "Deliverables",
        ):
            self.assertIn(f"| {field} |", intake)
        self.assertIn("Never ask for a confirmed item again", intake)
        self.assertIn("Do not run environment checks", intake)
        self.assertIn("Delegation does NOT itself move the state", intake)
        self.assertIn("完整 Production Summary", ppt)
        self.assertIn("confirm --summary-file", ppt)
        self.assertIn("生产前必须具备", production)

    def test_workflow_states_are_consistent(self) -> None:
        intake = self.read("references/presentation-intake.md")
        ppt = self.read("skills/sp-deck/SKILL.md")
        states = (
            "intake_pending → intake_confirmed → planned → producing → qa → complete"
        )
        self.assertIn(states, intake)
        self.assertIn(states, ppt)
        for terminal in ("incomplete", "blocked"):
            self.assertIn(terminal, intake)
            self.assertIn(terminal, ppt)

    def test_missing_preview_never_qualifies_for_complete(self) -> None:
        qa = self.read("skills/sp-deck/references/pptx-qa.md")
        self.assertIn("缺预览", qa)
        self.assertIn("状态只能是 `incomplete`", qa)
        self.assertNotIn("代码允许 complete", qa)
        self.assertIn("quality gate", qa)

    def test_review_and_outline_use_intake_without_overreaching(self) -> None:
        planning = self.read("skills/sp-outline/SKILL.md")
        review = self.read("skills/sp-review/SKILL.md")
        self.assertIn("outline-only 模式", planning)
        self.assertIn("review-only 模式", review)
        self.assertIn("不修改文件", review)
        self.assertIn("完整 intake 门禁", planning)

    def test_skill_files_stay_compact_and_reference_canonical_rules(self) -> None:
        paths = [
            ROOT / "skills/sp-outline/SKILL.md",
            ROOT / "skills/sp-deck/SKILL.md",
            ROOT / "skills/sp-review/SKILL.md",
        ]
        for path in paths:
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(
                len(lines), 80, f"{path.name} should stay as a compact entrypoint"
            )
            self.assertIn(
                "references/presentation-intake.md",
                path.read_text(encoding="utf-8"),
            )
        shared = self.read("references/shared-standards.md")
        self.assertIn("`presentation-intake.md` owns clarification", shared)
        self.assertNotIn("## Confirmed Constraints", shared)

    def test_style_selection_contract(self) -> None:
        menu = self.read("skills/sp-deck/references/visual-style-menu.md")
        styles = sorted(
            (ROOT / "skills/sp-deck/references/visual-styles").glob("*.md")
        )
        self.assertEqual(12, len(styles))
        self.assertIn("Step A shows exactly three categories plus `Other`", menu)
        self.assertIn("Step B shows all four styles", menu)
        self.assertIn("visual_style_custom", menu)
        self.assertNotIn("Berry Cream", menu.split("## Compatibility", 1)[0])
        self.assertNotIn("Sage Calm", menu.split("## Compatibility", 1)[0])
        intake = self.read("references/presentation-intake.md")
        for category in ("学术与专业类", "商务与科技类", "创意与人文类"):
            self.assertIn(category, intake)
        self.assertNotIn("显示全部 14", intake)

    def test_six_scenario_examples_exist(self) -> None:
        names = {
            "chinese-coursework.md",
            "english-class-report.md",
            "thesis-defense.md",
            "group-presentation.md",
            "review-only.md",
            "existing-deck-improvement.md",
        }
        self.assertTrue(names.issubset({path.name for path in (ROOT / "examples").glob("*.md")}))
        self.assertTrue((ROOT / "examples/high-score-research-brief.yaml").is_file())
        self.assertTrue((ROOT / "examples/high-score-research-slide-spec.yaml").is_file())

    def test_readmes_use_new_install_id(self) -> None:
        for path in (REPO_ROOT / "README.md", REPO_ROOT / "README-zh.md", ROOT / "README.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("student-presentation-suite@claude-personal", text)
            old_id = "student-presentation-suite@personal"
            offset = 0
            while (index := text.find(old_id, offset)) >= 0:
                context = text[max(0, index - 120):index + len(old_id) + 120].lower()
                self.assertTrue(
                    any(marker in context for marker in ("obsolete", "migrate", "旧", "迁移", "remove")),
                    f"{path}: legacy install id is allowed only in migration/removal documentation",
                )
                offset = index + len(old_id)

    def test_install_script_has_safe_migration_contract(self) -> None:
        script = (REPO_ROOT / "scripts/install_claude_plugin.ps1").read_text(encoding="utf-8")
        self.assertIn("$Marketplace = \"claude-personal\"", script)
        self.assertIn("$OldPluginId = \"$Plugin@personal\"", script)
        self.assertIn("plugin marketplace remove personal", script)
        self.assertIn("Remove-PluginCache -MarketplaceName \"personal\"", script)
        self.assertNotIn("Remove-Item -LiteralPath $InstallRoot", script)
        self.assertNotIn("anthropic-agent-skills", script)
        manifest = json.loads(self.read(".claude-plugin/plugin.json"))
        self.assertEqual([], manifest["dependencies"])

    def test_review_edit_handoff_requires_separate_outputs(self) -> None:
        review = self.read("skills/sp-review/SKILL.md")
        ppt = self.read("skills/sp-deck/SKILL.md")
        editing = self.read("skills/sp-deck/references/pptx-editing.md")
        self.assertIn("先诊断", review)
        self.assertIn("独立改进版", review)
        self.assertIn("禁止覆盖 source deck", ppt)
        self.assertIn("source 始终只读", editing)

    def test_v04_control_quality_and_revision_contracts_exist(self) -> None:
        brief_schema = json.loads(self.read("references/presentation-brief.schema.json"))
        slide_schema = json.loads(self.read("references/slide-spec.schema.json"))
        self.assertEqual("1.0", brief_schema["properties"]["brief_version"]["const"])
        for scenario in ("coursework", "defense", "competition", "club-showcase", "research"):
            self.assertIn(scenario, brief_schema["properties"]["scenario"]["enum"])
        meta = slide_schema["properties"]["meta"]["properties"]
        slide_properties = slide_schema["properties"]["slides"]["items"]["properties"]
        self.assertEqual("boolean", slide_properties["layout_lock"]["type"])
        self.assertFalse(slide_properties["layout_lock"]["default"])
        for field in (
            "scenario",
            "audience_type",
            "audience_depth",
            "structure_mode",
            "interaction_mode",
            "quality_level",
            "max_words_per_slide",
            "visual_text_ratio",
            "citation_style",
            "export_formats",
            "versioning",
        ):
            self.assertIn(field, meta)
        slide = slide_schema["properties"]["slides"]["items"]["properties"]
        for field in (
            "role",
            "claim",
            "supporting_points",
            "slide_copy",
            "speaker_notes",
            "evidence_refs",
            "locked",
            "lock_reason",
        ):
            self.assertIn(field, slide)
        self.assertIn("evidence_ledger", slide_schema["properties"])
        self.assertIn("revision", slide_schema["properties"])
        self.assertIn("revision_operation", slide_schema["properties"])
        self.assertIn("target_slides", slide_schema["properties"])

    def test_other_visual_style_requires_complete_custom_reference(self) -> None:
        brief_schema = json.loads(self.read("references/presentation-brief.schema.json"))
        slide_schema = json.loads(self.read("references/slide-spec.schema.json"))
        brief = yaml.safe_load(self.read("examples/high-score-research-brief.yaml"))
        spec = yaml.safe_load(self.read("examples/high-score-research-slide-spec.yaml"))
        brief["visual_style"] = "Other"
        spec["meta"]["visual_style"] = "Other"
        self.assertTrue(list(Draft202012Validator(brief_schema).iter_errors(brief)))
        self.assertTrue(list(Draft202012Validator(slide_schema).iter_errors(spec)))
        custom = {
            "style_character": "Quiet scientific field notes",
            "palette": {
                "canvas": "FFFFFF",
                "surface": "F5F5F5",
                "primary_text": "111111",
                "secondary_text": "555555",
                "primary_accent": "2563EB",
                "secondary_accent": "93C5FD",
            },
            "backgrounds": {
                "cover": "Blue field",
                "content": "White canvas",
                "section": "Pale blue field",
                "closing": "Blue field",
            },
            "svg_reference": {"name": "none", "usage": "No recurring motif"},
        }
        brief["visual_style_custom"] = deepcopy(custom)
        spec["meta"]["visual_style_custom"] = deepcopy(custom)
        self.assertEqual([], list(Draft202012Validator(brief_schema).iter_errors(brief)))
        self.assertEqual([], list(Draft202012Validator(slide_schema).iter_errors(spec)))

    def test_skills_route_through_layered_quality_workflow(self) -> None:
        planning = self.read("skills/sp-outline/SKILL.md")
        production = self.read("skills/sp-deck/references/pptx-production.md")
        revision = self.read("references/revision-training-export.md")
        review = self.read("skills/sp-review/SKILL.md")
        self.assertIn("目录→每页主张", planning)
        self.assertIn("analyze_presentation_spec.py", planning)
        self.assertIn("build_support_outputs.py", planning)
        self.assertIn("build_support_outputs.py", production)
        self.assertIn("create_revision_manifest.py", revision)
        self.assertIn("可能的问题", review)

    def test_handoff_artifacts_and_completion_contract(self) -> None:
        outline = self.read("skills/sp-outline/SKILL.md")
        review = self.read("skills/sp-review/SKILL.md")
        ppt = self.read("skills/sp-deck/SKILL.md")
        # outline 交接工件：转 PPTX 时必写 slide-spec.yaml 与 brief.yaml
        self.assertIn("<topic>-slide-spec.yaml", outline)
        self.assertIn("<topic>-brief.yaml", outline)
        # review 报告文件名与编辑交接件
        self.assertIn("<topic>-review.md", review)
        self.assertIn("<topic>-slide-spec.yaml", review)
        # review 状态词汇是结论标签，不写 workflow_guard 状态
        self.assertIn("不调用 `workflow_guard.py`", review)
        self.assertIn("评审结论标签", review)
        # ppt 完成命令不再要求 --package-report
        self.assertNotIn("--package-report", ppt)


if __name__ == "__main__":
    unittest.main()
