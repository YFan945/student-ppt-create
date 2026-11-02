"""End-to-end regressions for the remaining whole-plugin audit findings."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts", ROOT / "skills/sp-deck/scripts"):
    sys.path.insert(0, str(directory))

import build_support_outputs as support  # noqa: E402
import direct_production as production  # noqa: E402
import pptx_actual_content_check as content  # noqa: E402
import research_handoff  # noqa: E402
import research_pack_to_evidence as compiler  # noqa: E402
import validate_research_pack as research_validator  # noqa: E402
import workflow_guard  # noqa: E402

from shared.asset_contract import validate_assets  # noqa: E402
from shared.presentation_quality import analyze_spec  # noqa: E402
from shared.research_control import status  # noqa: E402
from shared.research_validation import validate_current  # noqa: E402
from shared.slide_spec_contract import validate_spec_data  # noqa: E402


def semantic_spec():
    return {"schema_version": "2.1", "meta": {"topic": "合成案例"}, "slides": [{"id": 1, "title": "容量",
        "content": ["装机容量"], "semantic_requirements": {"must_convey": [{"id": "metric", "text": "容量指标"}],
        "must_show_exact": [], "fact_bindings": [{"id": "capacity", "label": "装机容量", "value": "820", "unit": "MW"}]}}]}


class ContractRepairs(unittest.TestCase):
    def test_approved_plain_language_summary_needs_no_keyword_filling(self):
        summary = "中文课程汇报，老师与同学，5分钟约8页；使用已给材料，不外查；交付PPTX到outputs/course-report。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "approved.md"
            path.write_text(summary, encoding="utf-8")
            args = argparse.Namespace(action="confirm", state_file=root / "state.json", work_id=root.name,
                                      summary_file=path, topic="课程汇报", force=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(workflow_guard.state_command(args), 0)
            self.assertEqual(workflow_guard.load_state(args.state_file)["state"], "intake_confirmed")
            path.write_text("  ", encoding="utf-8")
            with self.assertRaises(SystemExit):
                workflow_guard.state_command(args)

    def test_draft_and_semantic_citations_are_not_invalid_or_unused(self):
        data = semantic_spec()
        data["slides"][0]["evidence_refs"] = ["F01"]
        self.assertEqual(validate_spec_data(data), [])
        self.assertTrue(analyze_spec(data)["ok"])
        del data["slides"][0]["evidence_refs"]
        data["evidence_ledger"] = [{"id": "E01", "title": "材料"}]
        data["slides"][0]["semantic_requirements"]["must_convey"][0]["evidence_refs"] = ["E01"]
        self.assertNotIn("unused-evidence", [item["code"] for item in analyze_spec(data)["findings"]])
        data["slides"][0]["evidence_refs"] = ["MISSING"]
        self.assertFalse(analyze_spec(data)["ok"])

    def test_prose_needs_semantic_review_while_wrong_values_and_negation_fail(self):
        from shared.chart_readback import SlideText
        data = semantic_spec()
        for text in ("装机容量已达到820MW", "装机容量达820MW", "装机容量增至820MW"):
            result = content.check(data, [text], [[text]])
            self.assertTrue(result["ok"], result)
            self.assertIn("fact_binding_needs_semantic_review", [item["code"] for item in result["issues"]])
        for text in ("装机容量820MW的说法不成立", "装机容量不是820MW", "装机容量达940MW", "装机容量820MWh"):
            self.assertFalse(content.check(data, [text], [[text]])["ok"], text)
        for text in ("装机容量为940MW", "装机容量为820MWh", "装机容量820MW的说法不成立"):
            # An unrelated unreadable chart cannot conceal a determinate text error.
            self.assertFalse(content.check(data, [SlideText(text, [{"code": "chart_label_format_unreadable"}])], [[text]])["ok"])

    def test_ready_research_reopens_when_current_evidence_has_core_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "research-task.json"
            task.write_text('{"claims": []}', encoding="utf-8")
            pack = root / "research-pack.json"
            pack.write_text('{"findings": []}', encoding="utf-8")
            report = {"ok": True, "delivery_status": "ready", "research_pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
                      "task": {"sha256": hashlib.sha256(task.read_bytes()).hexdigest()}}
            production.write(root / "research-pack-validation.json", report)
            self.assertEqual(status(root)["reason"], "sufficient_evidence")
            report["delivery_status"] = "insufficient"
            production.write(root / "research-pack-validation.json", report)
            self.assertEqual(status(root)["state"], "active")
            state = production.load(root / "research-control.json")
            state["reason"] = "user_stop"
            production.write(root / "research-control.json", state)
            self.assertEqual(status(root)["reason"], "user_stop")

    def test_existing_asset_does_not_require_an_unused_fallback(self):
        asset = {"slide": 1, "source": "user image", "purpose": "说明", "permission": "user-provided", "alt_text": "示意图"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(validate_assets({"deck": "demo", "assets": [asset]}, root)["ok"])
            asset["path"] = "missing.png"
            self.assertFalse(validate_assets({"deck": "demo", "assets": [asset]}, root)["ok"])

    def test_refreshing_a_report_does_not_cancel_an_explicit_research_resume(self):
        import research_control as controller
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "outputs/.pptx-work/demo"
            root.mkdir(parents=True)
            brief = root / "brief.md"
            brief.write_text("课题", encoding="utf-8")
            production.write(root / "research-task.json", {"work_id": root.name, "work_dir": str(root),
                "brief_path": str(brief), "scope": "B", "materials_path": None, "background": "课题背景",
                "claims": [{"id": "C01", "claim": "待验证事实", "acceptance": "有来源"}]})
            production.write(root / "research-pack.json", {"must_verify": []})
            task, pack = root / "research-task.json", root / "research-pack.json"
            report = {"ok": True, "delivery_status": "ready", "research_pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
                      "task": {"sha256": hashlib.sha256(task.read_bytes()).hexdigest()}}
            production.write(root / "research-pack-validation.json", report)
            self.assertEqual(status(root)["reason"], "sufficient_evidence")
            controller.resume(root, "定向复核现有来源")
            report["validation_reused"] = True
            production.write(root / "research-pack-validation.json", report)
            self.assertEqual(status(root)["state"], "active")

    def test_notes_use_display_order_and_short_closing_is_valid(self):
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reordered.pptx"
            deck = Presentation()
            for body in ("第一页详细讲稿。", "谢谢。"):
                slide = deck.slides.add_slide(deck.slide_layouts[6])
                slide.notes_slide.notes_text_frame.text = body
            ids = deck.slides._sldIdLst
            ids.insert(0, ids[1])
            deck.save(path)
            data = {"slides": [{"id": 10, "title": "结束"}, {"id": 30, "title": "说明"}]}
            notes = support.actual_speaker_notes(data, None, path)
            self.assertEqual(notes, {10: "谢谢。", 30: "第一页详细讲稿。"})
            actual = support.with_actual_speaker_notes(data, notes)
            self.assertEqual([slide["id"] for slide in actual["slides"]], [1, 2])
            script = support.full_script_markdown(actual)
            self.assertLess(script.index("谢谢。"), script.index("第一页详细讲稿。"))
            self.assertNotIn("Slide 10", script)
            actual["slides"][0]["speaker_notes"] = ""
            with self.assertRaises(ValueError):
                support._assert_page_sections("speaker-notes", support.speaker_notes_markdown(actual), actual)

    def test_research_validation_is_reused_across_real_consumers(self):
        from test_validate_research_pack import base_pack
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "research-pack.json"
            production.write(pack, base_pack())
            with patch.object(research_validator, "validate", wraps=research_validator.validate) as validator, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(research_validator.main([str(pack)]), 0)
                self.assertTrue(research_handoff.inspect(root)["ok"])
                self.assertEqual(compiler.main([str(pack), "--output", str(root / "map.json")]), 0)
                self.assertEqual(validator.call_count, 1)
                data = production.load(pack)
                data["topic"] = "updated topic"
                production.write(pack, data)
                _, report = validate_current(pack)
                self.assertFalse(report["validation_reused"])
                self.assertEqual(validator.call_count, 2)

    def test_cached_strict_evidence_is_invalidated_by_document_edits(self):
        from test_research_evidence import TextEvidenceTests
        fixture = TextEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pack = fixture.work / "research-pack.json"
        production.write(pack, fixture.pack)
        production.write(fixture.fetched / "fetch-text-report.json", fixture.report)
        _, report = validate_current(pack)
        self.assertTrue(report["ok"], report["problems"])
        _, report = validate_current(pack)
        self.assertTrue(report["validation_reused"])
        Path(fixture.pack["evidence"][0]["text_path"]).write_text("changed source", encoding="utf-8")
        _, report = validate_current(pack)
        self.assertFalse(report["validation_reused"])
        self.assertFalse(report["ok"])

    def test_scatter_values_are_visible_only_with_enabled_labels(self):
        from pptx import Presentation
        from pptx.chart.data import XyChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.oxml import parse_xml
        from pptx.util import Inches
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scatter.pptx"
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            data = XyChartData()
            data.add_series("capacity").add_data_point(1, 823.7)
            chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, Inches(1), Inches(1), Inches(7), Inches(4), data).chart
            labels = parse_xml('<c:dLbls xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:numFmt formatCode="0.0" sourceLinked="0"/><c:showVal val="1"/></c:dLbls>')
            chart.plots[0]._element.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}axId').addprevious(labels)
            deck.save(path)
            self.assertIn("823.7", content.extract_pptx_text(path)[0])
            labels[1].set("val", "0")
            deck.save(path)
            self.assertNotIn("823.7", content.extract_pptx_text(path)[0])
            labels[1].set("val", "1")
            labels[0].set("formatCode", "0.0E+00")
            deck.save(path)
            spec = semantic_spec()
            spec["slides"][0]["semantic_requirements"].pop("fact_bindings")
            spec["slides"][0]["semantic_requirements"]["must_show_exact"] = ["8.2E+02"]
            report = content.check(spec, content.extract_pptx_text(path))
            self.assertTrue(report["ok"])
            self.assertIn("exact_content_unverified", [item["code"] for item in report["issues"]])
            spec["slides"][0]["semantic_requirements"]["must_show_exact"] = ["Required brand name"]
            self.assertFalse(content.check(spec, content.extract_pptx_text(path))["ok"])


class ProductionRepairs(unittest.TestCase):
    def setUp(self):
        from test_direct_production import MainSessionTests
        self.f = MainSessionTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_renderer_failure_recovers_the_same_candidate_without_rebuilding(self):
        f = self.f
        production.plan(f.args)
        f.author()
        with patch.object(production, "render", side_effect=OSError("temporary renderer failure")), self.assertRaises(production.ProductionError):
            production.run(f.args)
        manifest = production.load(f.work / "build-manifest.json")
        self.assertEqual(manifest["last_failed_stage"], "render")
        self.assertTrue(manifest["check"]["ok"])
        before = (f.work / "deck.pptx").read_bytes()
        with patch.object(production, "execute", side_effect=AssertionError("must not rebuild")):
            result = production.run(f.args)
            self.assertTrue(result["build_reused"])
            self.assertTrue(production.complete(f.args)["ok"])
        self.assertEqual((f.work / "deck.pptx").read_bytes(), before)

    def test_notes_only_edits_reuse_images_and_do_not_request_whole_deck_review(self):
        from shared.pptx_runtime.render import render_pptx
        f = self.f
        production.plan(f.args)
        f.author()
        with patch("shared.pptx_runtime.render.render_pptx", wraps=render_pptx) as renderer:
            production.run(f.args)
            manifest = production.load(f.work / "build-manifest.json")
            page = f.work / "pages" / manifest["scaffold"]["pages"][0]
            text = page.read_text(encoding="utf-8").replace("module.exports.notes=", 'module.exports.notes="Updated explanatory notes."; // previous ')
            page.write_text(text, encoding="utf-8")
            result = production.run(f.args)
            self.assertEqual(renderer.call_count, 1)
        self.assertEqual(result["changed_pages"], [])
        self.assertNotIn("Read every", " ".join(result["review_required"]))

    def test_all_support_exports_work_with_nonsequential_ids(self):
        f = self.f
        spec = production.load(f.spec)
        spec["slides"][0]["id"], spec["slides"][1]["id"] = 10, 30
        spec["meta"]["deliverables"] = ["pptx", "speaker-notes", "full-script", "teleprompter"]
        production.write(f.spec, spec)
        production.plan(f.args)
        f.author()
        f.args.no_render = True
        production.run(f.args)
        result = production.complete(f.args)
        for name in ("speaker-notes", "full-script", "teleprompter"):
            text = Path(result["outputs"][name]["path"]).read_text(encoding="utf-8")
            self.assertIn("这些结果仅用于合成实验", text)
            self.assertNotIn("Slide 10", text)
        with contextlib.redirect_stdout(io.StringIO()):
            args = argparse.Namespace(action="transition", state_file=f.work / "workflow-state.json", work_id=f.work.name,
                                      to="complete", reason=None, qa_manifest=None, pptx=None, delivery_report=None)
            # completion already happened: verify current artifact without old receipt chain.
            self.assertEqual(workflow_guard.validate_completion_manifest(None, Path(result["outputs"]["pptx"]["path"])), [])
            args.to = "blocked"
            workflow_guard.state_command(args)
            args.action = "unblock"
            workflow_guard.state_command(args)
            self.assertEqual(workflow_guard.load_state(args.state_file)["state"], "complete")


if __name__ == "__main__":
    unittest.main()
