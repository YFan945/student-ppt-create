"""Editable cross-template copying, local lookup and student review contracts."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches

from shared.deck_expression_review import review_expression
from shared.hashing import file_sha256
from shared.student_design_review import planning_review, reference_comparisons, review_actual
from shared.template_library import assemble, build_catalog, inspect_template, search_catalog

ROOT = Path(__file__).resolve().parents[1]


class TemplateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def source(self, name, text, width=10):
        path = self.directory / name
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(width), Inches(5.625)
        page = prs.slides.add_slide(prs.slide_layouts[6])
        page.shapes.add_textbox(Inches(1), Inches(1), Inches(7), Inches(1)).text = text
        table = page.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
        table.cell(0, 0).text = "证据表"
        data = CategoryChartData()
        data.categories = ["A", "B"]
        data.add_series("得分", [64, 78])
        page.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5), Inches(2), Inches(4), Inches(2), data)
        page.notes_slide.notes_text_frame.text = "先讲主图，再解释差别。"
        prs.save(path)
        return path

    def test_catalog_matches_unicode_preview_and_finds_page_role(self):
        path = self.source("成果（1）.pptx", "成果证据与数据")
        (self.directory / "成果(1).jpg").write_bytes(b"preview path only")
        catalog = build_catalog([self.directory], [self.directory])
        self.assertEqual(catalog["errors"], [])
        found = search_catalog(catalog, "成果", "evidence")
        self.assertEqual(found[0]["path"], str(path))
        self.assertTrue(found[0]["preview"].endswith("成果(1).jpg"))
        self.assertEqual(found[0]["tables"], 1)

    def test_assembly_keeps_order_editable_charts_notes_and_sources(self):
        first = self.source("first.pptx", "机制关系")
        second = self.source("second.pptx", "成果比较")
        hashes = [file_sha256(path) for path in (first, second)]
        output = self.directory / "combined.pptx"
        assemble([{"path": str(second), "slide": 1}, {"path": str(first), "slide": 1},
                  {"path": str(second), "slide": 1}], output)
        prs = Presentation(output)
        self.assertEqual(len(prs.slides), 3)
        for index, expected in enumerate(["成果比较", "机制关系", "成果比较"]):
            page = prs.slides[index]
            self.assertIn(expected, [s.text for s in page.shapes if s.has_text_frame])
            chart = next(s.chart for s in page.shapes if s.has_chart)
            self.assertEqual(list(chart.series[0].values), [64.0, 78.0])
            self.assertIn("先讲主图", page.notes_slide.notes_text_frame.text)
            self.assertEqual(next(s.table for s in page.shapes if s.has_table).cell(0, 0).text, "证据表")
        self.assertEqual(hashes, [file_sha256(path) for path in (first, second)])
        self.assertTrue(output.with_suffix(".template-sources.json").is_file())
        # Repeated pages need independent chart parts, so later edits cannot
        # silently mutate both copies.
        self.assertNotEqual(prs.slides[0].shapes[-1].chart.part.partname,
                            prs.slides[2].shapes[-1].chart.part.partname)

    def test_reject_mismatched_canvas_or_overwriting_original(self):
        first = self.source("wide.pptx", "wide")
        second = self.source("different.pptx", "different", width=12)
        with self.assertRaisesRegex(ValueError, "sizes differ"):
            assemble([{"path": str(first), "slide": 1}, {"path": str(second), "slide": 1}], self.directory / "bad.pptx")
        with self.assertRaisesRegex(ValueError, "separate"):
            assemble([{"path": str(first), "slide": 1}], first)
        with self.assertRaisesRegex(ValueError, "invalid slide"):
            assemble([{"path": str(first), "slide": 2}], self.directory / "bad.pptx")

    def test_inspection_uses_presentation_order_and_not_filename_guessing(self):
        path = self.source("one.pptx", "实验结果")
        self.assertEqual(inspect_template(path)["slides"][0]["text"], "实验结果 证据表")

    def test_review_exposes_specific_focus_support_and_readability(self):
        spec = {"slides": [{"title": "实验结果", "content": ["对照组64分，方案78分"],
                            "semantic_requirements": {"must_convey": [{"text": "方案在相同测试中高14分"}]}}]}
        review = review_actual(spec, {"slides": [{"slide": 1, "headline": "实验结果", "text_runs": ["对照组64分，方案78分"]}]},
                               {"warnings": [{"code": "text_size_review", "minSize": 9}]})
        self.assertEqual(review["pages"][0]["core_information"], ["方案在相同测试中高14分"])
        self.assertTrue(review["readability_findings"])
        self.assertIn("topic_title_review", [f["code"] for f in review["findings"]])
        self.assertNotIn("score", review)
        self.assertTrue(planning_review(spec)["pages"][0]["questions"])

    def test_reference_check_pairs_real_reference_and_final_page_without_approval_score(self):
        spec = {"template_sources": [{"id": "blue", "path": "builtin:award-blue"}], "slides": [
            {"template_refs": [{"source_id": "blue", "slide": 7, "reason": "指标和表格"}]},
            {"title": "未选择参考的正文"}]}
        pairs = reference_comparisons(spec, [{"path": "final-1.png"}, {"path": "final-2.png"}])
        self.assertEqual(pairs[0]["actual_render"], "final-1.png")
        self.assertTrue(Path(pairs[0]["reference_preview"]).is_file())
        self.assertEqual(pairs[0]["reference_page"], 7)
        self.assertFalse(pairs[0]["verified"])
        self.assertIn("template_adaptation_unmapped", [p["code"] for p in planning_review(spec)["findings"]])

    def test_planned_production_caveats_remain_actionable_but_quotes_are_preserved(self):
        spec = {"slides": [{"content": ["缺出处的数字就不写"]}]}
        actual = {"slides": [{"slide": 1, "text_runs": ["缺出处的数字就不写"]}]}
        self.assertEqual(review_expression(spec, actual)["findings"][0]["severity"], "advisory")
        spec["slides"][0]["semantic_requirements"] = {"must_show_exact": ["缺出处的数字就不写"]}
        self.assertEqual(review_expression(spec, actual)["findings"], [])

    def test_role_defaults_have_hierarchy_and_allow_author_overrides(self):
        script = """const H=require('./scripts/pptx-helpers.js');const t={model_led:true,typography:{}};
console.log(JSON.stringify(['title','body','caption','label'].map(r=>H.rolePolicy(t,'chinese',r).fontSize)
.concat([H.rolePolicy(t,'chinese','body',{fontSize:8}).fontSize,
H.rolePolicy({model_led:true,typography:{slide_title_pt:35}},'chinese','title').fontSize])));"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
        values = json.loads(result.stdout)
        self.assertGreater(values[0], values[1])
        self.assertGreater(values[1], values[2])
        self.assertEqual(values[-2:], [8, 35])

    def test_rich_fitting_text_and_multiple_colors_are_not_automatic_density_risks(self):
        from pptx.dml.color import RGBColor
        from pptx.util import Pt

        from shared.pptx_static_core import inspect_pptx
        from shared.presentation_quality import analyze_spec

        path = self.directory / "rich.pptx"
        prs = Presentation()
        page = prs.slides.add_slide(prs.slide_layouts[6])
        box = page.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4))
        for color in ["17324D", "2469C9", "087F8C", "7550A3", "BB4936", "986600"]:
            run = box.text_frame.paragraphs[0].add_run()
            run.text = "解释保留对象、条件、过程和证据，围绕同一个核心信息形成可浏览的内容组。" * 2
            run.font.size, run.font.color.rgb = Pt(14), RGBColor.from_string(color)
        prs.save(path)
        findings = inspect_pptx(path)["findings"]
        risks = {risk for finding in findings for risk in finding["risk"]}
        self.assertFalse(risks & {"high-text-density-overflow-risk", "paragraph-heavy-slide-text", "many-colors-in-shape"})
        self.assertNotIn("text-vertical-overflow", risks)
        for version in ["1.0", "2.1"]:
            analysis = analyze_spec({"schema_version": version, "meta": {}, "slides": [
                {"id": 1, "title": "机制", "claim": "原件与结果对应", "content": box.text} ]})
            self.assertFalse({f["code"] for f in analysis["findings"]} & {"chinese-density", "word-density"})
