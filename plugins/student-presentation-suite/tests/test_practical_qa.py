"""Regression cases from real production loops: facts, previews and repeated QA."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts", ROOT / "skills/sp-deck/scripts"):
    sys.path.insert(0, str(directory))

import direct_production as production  # noqa: E402
import pptx_actual_content_check as content  # noqa: E402
import pptx_tool  # noqa: E402

from shared.artifact_validation import validate_artifact  # noqa: E402
from shared.chart_readback import displayed_number  # noqa: E402
from shared.content_requirements import fact_binding_present  # noqa: E402
from shared.validation_cli import main as validate_cli  # noqa: E402


class FactReadbackTests(unittest.TestCase):
    def test_page_year_can_scope_a_metric_without_repetition(self):
        fact = {"label": "装机容量", "value": "820", "unit": "MW", "context": "2025年"}
        self.assertTrue(fact_binding_present(fact, ["2025年", "装机容量为820MW"]))
        self.assertFalse(fact_binding_present(fact, ["2024年", "2025年", "装机容量为820MW"]))
        self.assertFalse(fact_binding_present(fact, ["2025年", "装机容量为820MWh"]))
        self.assertFalse(fact_binding_present(fact, ["2025年", "装机容量", "发电量为820MW"]))

    def test_chart_values_are_read_only_when_displayed_and_units_stay_local(self):
        from pptx import Presentation
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.util import Inches

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "charts.pptx"
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            data = CategoryChartData()
            data.categories = ["装机容量"]
            data.add_series("实测", [820])
            chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1), Inches(7), Inches(4), data).chart
            chart.has_title = True
            chart.chart_title.text_frame.text = "2025年 (MW)"
            chart.plots[0].has_data_labels = False
            deck.save(path)
            self.assertNotIn("820", content.extract_pptx_text(path)[0])
            fact = {"label": "装机容量", "value": "820", "unit": "MW", "context": "2025年"}
            self.assertFalse(fact_binding_present(fact, content.extract_fact_blocks(path)[0]))
            chart.plots[0].has_data_labels = True
            chart.plots[0].data_labels.show_value = True
            deck.save(path)
            self.assertIn("820", content.extract_pptx_text(path)[0])
            self.assertTrue(fact_binding_present(fact, content.extract_fact_blocks(path)[0]))
            fact["unit"] = "MWh"
            self.assertFalse(fact_binding_present(fact, content.extract_fact_blocks(path)[0]))

    def test_display_format_is_applied_before_exact_matching(self):
        self.assertEqual(displayed_number("0.943", "0.0%"), "94.3%")
        self.assertEqual(displayed_number("2383.2", "#,##0.0"), "2,383.2")
        self.assertIsNone(displayed_number("820", "dd/mm/yyyy"))
        self.assertEqual(displayed_number("2383000000", "0.0,,"), "2383.0")
        self.assertEqual(displayed_number("2383000000", '#,##0,,"百万"'), "2,383百万")
        self.assertEqual(displayed_number("2", "0.##"), "2")
        self.assertTrue(fact_binding_present({"label": "准确率", "value": "94.3", "unit": "%"}, ["准确率94.3%"] ))

    def test_notes_follow_presentation_order(self):
        from pptx import Presentation
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reordered.pptx"
            deck = Presentation()
            for note in ("first notes", "second notes"):
                slide = deck.slides.add_slide(deck.slide_layouts[6])
                slide.notes_slide.notes_text_frame.text = note
            ids = deck.slides._sldIdLst
            ids.insert(0, ids[1])
            deck.save(path)
            self.assertEqual(content.extract_pptx_notes(path), {1: "second notes", 2: "first notes"})

    def test_chart_context_units_do_not_cross_between_axes(self):
        from xml.etree import ElementTree as ET

        from shared.chart_readback import C, R, chart_regions
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "axes.pptx"
            series = '<c:ser><c:tx><c:v>容量</c:v></c:tx><c:val><c:numLit><c:pt idx="0"><c:v>820</c:v></c:pt></c:numLit></c:val></c:ser>'
            xml = f'<c:chartSpace xmlns:c="{C}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart><c:legend/><c:plotArea><c:barChart>{series}<c:dLbls><c:showVal val="1"/></c:dLbls><c:axId val="1"/></c:barChart><c:valAx><c:axId val="1"/><c:title><a:t>MW</a:t></c:title></c:valAx><c:valAx><c:axId val="2"/><c:title><a:t>MWh</a:t></c:title></c:valAx></c:plotArea></c:chart></c:chartSpace>'
            with ZipFile(path, "w") as package:
                package.writestr("ppt/charts/chart1.xml", xml)
                package.writestr("ppt/slides/_rels/slide1.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="chart" Target="../charts/chart1.xml"/></Relationships>')
            slide = ET.fromstring(f'<s xmlns:c="{C}" xmlns:r="{R}"><c:chart r:id="chart"/></s>')
            with ZipFile(path) as package:
                blocks = chart_regions(package, slide, "ppt/slides/slide1.xml")
            self.assertTrue(fact_binding_present({"label": "容量", "value": "820", "unit": "MW"}, blocks))
            self.assertFalse(fact_binding_present({"label": "容量", "value": "820", "unit": "MWh"}, blocks))


class PracticalProductionTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the real authored fixture, without inheriting its test suite.
        from test_direct_production import MainSessionTests
        self.fixture = MainSessionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        production.plan(self.f.args)

    def test_partial_preview_does_not_load_broken_other_page_or_mutate_full_build(self):
        self.f.author()
        manifest_path = self.f.work / "build-manifest.json"
        before = manifest_path.read_bytes()
        second = production.load(manifest_path)["scaffold"]["pages"][1]
        (self.f.work / "pages" / second).write_text("this is invalid JavaScript !", encoding="utf-8")
        result = production.preview(argparse.Namespace(work_dir=self.f.work, slides="1"))
        self.assertEqual(result["source_slides"], [1])
        self.assertEqual(len(result["pages"]), 1)
        self.assertFalse(result["complete"])
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertFalse((self.f.work / "deck.pptx").exists())
        with self.assertRaises(production.ProductionError):
            production.complete(self.f.args)

    def test_success_then_failure_status_exposes_current_attempt_not_old_success(self):
        self.f.author()
        self.f.args.no_render = True
        production.run(self.f.args)
        first = production.load(self.f.work / "build-manifest.json")["scaffold"]["pages"][0]
        (self.f.work / "pages" / first).write_text("throw new Error('CURRENT_BROKEN_PAGE');", encoding="utf-8")
        with self.assertRaisesRegex(production.ProductionError, "CURRENT_BROKEN_PAGE"):
            production.run(self.f.args)
        result = production.status(self.f.args)
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "inspect_latest_failure")
        report = production.load(Path(result["latest_failure"]["report"]))
        self.assertEqual(report["attempt"], 2)
        self.assertIn("CURRENT_BROKEN_PAGE", report["error"])
        self.assertTrue(report["previous_success_is_not_this_attempt"])
        with self.assertRaisesRegex(production.ProductionError, "latest build failed"):
            production.complete(self.f.args)

    def test_unchanged_run_and_complete_reuse_actual_technical_validation(self):
        from shared.pptx_runtime import validate_pptx
        self.f.author()
        with patch("shared.pptx_runtime.validate_pptx", wraps=validate_pptx) as validator:
            production.run(self.f.args)
            with patch.object(production, "execute", side_effect=AssertionError("unchanged sources rebuilt")):
                result = production.run(self.f.args)
                spec = production.load(self.f.spec)
                self.f.spec.write_text(json.dumps(spec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                self.assertTrue(production.run(self.f.args)["build_reused"])
            self.assertTrue(result["build_reused"])
            production.complete(self.f.args)
            self.assertEqual(validator.call_count, 1)
            bare = validate_artifact(self.f.work / "deck.pptx", cache=self.f.work / "_tmp/artifact-validation.json")
            self.assertTrue(bare["ok"])
            missing = validate_artifact(self.f.work / "deck.pptx", self.f.work / "missing-spec.json",
                                        cache=self.f.work / "_tmp/artifact-validation.json")
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["issues"][0]["code"], "slide_spec_missing")
            # The actual bytes are checked, even if an old passing report remains.
            (self.f.work / "deck.pptx").write_bytes(b"corrupt package")
            report = validate_artifact(self.f.work / "deck.pptx", self.f.spec,
                                       cache=self.f.work / "_tmp/artifact-validation.json")
            self.assertFalse(report["ok"])
            self.assertFalse(report["reused"])
            self.assertEqual(validator.call_count, 4)

    def test_public_routes_do_not_demand_scores_locks_or_receipts(self):
        self.f.author()
        self.f.args.no_render = True
        production.run(self.f.args)
        path = self.f.work / "deck.pptx"
        import delivery_check
        import pptx_delivery_check_v08
        import pptx_rendered_check
        import quality_gate
        import run_gates
        for route in (quality_gate.main, delivery_check.main, run_gates.main,
                      pptx_rendered_check.main, pptx_delivery_check_v08.main):
            argv = ["--pptx", str(path)]
            with self.subTest(route=route.__module__), contextlib.redirect_stdout(io.StringIO()), patch.object(sys, "argv", ["qa", *argv]):
                result = route(argv) if route in (quality_gate.main, delivery_check.main, run_gates.main) else route()
                self.assertEqual(result, 0)
        args = pptx_tool.build_parser().parse_args(["gate-all", "--pptx", str(path), "--output-dir", str(self.f.work / "qa")])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pptx_tool.command_gate_all(args), 0)
            # A requested fact still fails; no visual paperwork can override it.
            spec = production.load(self.f.spec)
            spec["slides"][0]["semantic_requirements"]["must_show_exact"] = ["NOT_IN_DECK"]
            production.write(self.f.spec, spec)
            self.assertEqual(validate_cli("quality", ["--pptx", str(path), "--slide-spec", str(self.f.spec)]), 2)

    def test_sparse_visual_observations_and_many_repairs_are_not_a_gate(self):
        self.f.author()
        self.f.args.no_render = True
        production.run(self.f.args)
        findings = self.f.work / "findings.json"
        production.write(findings, {"pages": [{"slide": 2, "notes": "图例可读"}]})
        output = self.f.work / "observations.json"
        args = argparse.Namespace(pptx=self.f.work / "deck.pptx", preview=[], findings=findings,
                                  repair_cycle=8, output=output)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pptx_tool.command_visual_inspection(args), 0)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["observed_page_count"], 1)
        self.assertEqual(report["checked_page_count"], 0)
        self.assertFalse(report["visual_quality_verified"])

    def test_missing_requested_exports_fail_but_optional_reports_are_not_requested(self):
        path = self.f.work / "deck.pptx"
        with patch("shared.validation_cli.validate_artifact", side_effect=lambda *_a, **_k: {"ok": True, "issues": []}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate_cli("delivery", ["--pptx", str(path)]), 0)
            self.assertEqual(validate_cli("delivery", ["--pptx", str(path), "--deliverables", "outline"]), 2)
            self.assertEqual(validate_cli("delivery", ["--pptx", str(path), "--deliverables", "speaker-notes"]), 2)
            self.assertEqual(validate_cli("delivery", ["--pptx", str(path), "--notes", str(self.f.work / "missing.md")]), 2)

    def test_image_change_rebuilds_even_when_javascript_is_unchanged(self):
        from PIL import Image
        self.f.author()
        assets = self.f.work / "assets"
        assets.mkdir()
        image = assets / "evidence.png"
        Image.new("RGB", (24, 24), "red").save(image)
        page = self.f.work / "pages" / production.load(self.f.work / "build-manifest.json")["scaffold"]["pages"][0]
        source = page.read_text(encoding="utf-8").replace("const {H,slide,tokens}=ctx;", "const {H,slide,tokens}=ctx; slide.addImage({path:" + json.dumps(str(image)) + ",x:9,y:2,w:1,h:1});")
        page.write_text(source, encoding="utf-8")
        self.f.args.no_render = True
        production.run(self.f.args)
        with ZipFile(self.f.work / "deck.pptx") as package:
            before = [package.read(name) for name in package.namelist() if name.startswith("ppt/media/")]
        Image.new("RGB", (24, 24), "blue").save(image)
        result = production.run(self.f.args)
        self.assertFalse(result.get("build_reused", False))
        with ZipFile(self.f.work / "deck.pptx") as package:
            after = [package.read(name) for name in package.namelist() if name.startswith("ppt/media/")]
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
