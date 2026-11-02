"""Regressions for semantic, visual and delivery checks that overclaimed certainty."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "skills/sp-deck/scripts")]

import pptx_actual_content_check as content  # noqa: E402
import test_direct_production as fixture  # noqa: E402
import test_text_runtime_repair as node  # noqa: E402

from shared.content_requirements import exact_present, fact_binding_present, numeric_present  # noqa: E402
from shared.deck_expression_review import review_expression  # noqa: E402
from shared.pptx_text_readback import fact_blocks  # noqa: E402
from shared.slide_spec_contract import validate_spec_data  # noqa: E402
from shared.student_design_review import planning_review, review_actual  # noqa: E402


def spec():
    return {"schema_version": "2.1", "meta": {"format": "group", "quality_level": "rigorous"},
            "slides": [{"id": 7, "title": "比较方案", "content": [], "visual": {"type": "comparison"},
                        "semantic_requirements": {"must_convey": [{"id": "compare", "text": "比较3种方案"}],
                                                  "must_show_exact": []}}]}


class ContentFlexibilityTests(unittest.TestCase):
    def test_semantic_digit_does_not_require_a_visible_digit(self):
        report = content.check(spec(), ["方案甲 方案乙 方案丙"])
        self.assertTrue(report["ok"], report)
        planned = spec()
        planned["slides"][0]["semantic_requirements"]["must_show_exact"] = ["3"]
        report = content.check(planned, ["方案甲 方案乙 方案丙"])
        self.assertEqual([item["code"] for item in report["issues"]], ["exact_content_missing"])

    def test_numeric_formatting_and_literal_quotes_are_distinct(self):
        for actual in ("2383.2", "２３８３.２", "2,383.20"):
            self.assertTrue(numeric_present("2,383.2", actual))
        self.assertFalse(exact_present("2,383.2", "2383.2"))
        for expected, actual in (("94%", "94.3%"), ("94%", "94"), ("233", "1233"), ("233", "-233")):
            self.assertFalse(numeric_present(expected, actual))

    def test_natural_fact_sentence_without_accepting_negation(self):
        fact = {"label": "装机容量", "value": "820", "unit": "MW"}
        self.assertTrue(fact_binding_present(fact, ["装机容量达到820 MW"]))
        for text in ("装机容量不是820MW", "装机容量低于820MW", "装机容量820MWh", "其他容量820MW"):
            self.assertFalse(fact_binding_present(fact, [text]), text)

    def test_spatial_pairing_does_not_join_unrelated_cards(self):
        from pptx import Presentation
        from pptx.util import Inches

        fact = {"label": "装机容量", "value": "820", "unit": "MW"}
        def blocks(gap, competing=False):
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            for text, x, y, w in [("装机容量", 1, 1, 2), ("820MW", 3 + gap, 1, 2)]:
                slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(.4)).text = text
            if competing:
                slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(.4)).text = "备用容量"
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "deck.pptx"
                deck.save(path)
                with zipfile.ZipFile(path) as package:
                    return fact_blocks(ET.fromstring(package.read("ppt/slides/slide1.xml")))
        self.assertTrue(fact_binding_present(fact, blocks(.2)))
        self.assertFalse(fact_binding_present(fact, blocks(2)))
        self.assertFalse(fact_binding_present(fact, blocks(.2, competing=True)))

    def test_planning_metadata_is_optional_and_stable_ids_are_preserved(self):
        data = spec()
        data["meta"].update(slide_count=20, duration_min=10)
        data["slides"][0]["timing_sec"] = 5
        self.assertEqual(validate_spec_data(data), [])
        self.assertEqual(data["slides"][0]["id"], 7)
        self.assertEqual(data["slides"][0]["owner"], "shared")
        data["slides"].append(dict(data["slides"][0]))
        self.assertTrue(validate_spec_data(data))  # Duplicate identity is still invalid.

    def test_metadata_equality_and_icon_reuse_do_not_invent_defects(self):
        data = spec()
        data["slides"][0]["claim"] = "具体结论"
        actual = {"slides": [{"slide": 1, "headline": "具体结论", "text_runs": ["具体结论"],
                              "visual_usage": [{"kind": "icon", "key": "school"}]},
                             {"slide": 2, "visual_usage": [{"kind": "icon", "key": "school"}]}]}
        self.assertEqual(planning_review(data)["findings"], [])
        self.assertFalse(any(item["code"] == "title_claim_repetition_review" for item in review_actual(data, actual, {})["findings"]))
        self.assertFalse(any(item["code"] == "reused_icon" for item in review_expression(data, actual)["findings"]))
        actual["slides"][0]["text_runs"].append("具体结论")
        self.assertTrue(any(item["code"] == "title_claim_repetition_review" for item in review_actual(data, actual, {})["findings"]))


class AuthoringFlexibilityTests(unittest.TestCase):
    def test_native_merged_table_and_notes_need_no_shadow_metadata(self):
        out = node.run_node("""
          const R=require(path.join(SCRIPTS,'pptx-page-runtime.js'));
          const E=require(path.join(SCRIPTS,'pptx-element-registry.js'));
          const slide=mock(); const registry=new E.SlideElementRegistry();
          const ctx={slide,registry,n:1,presentationCopy:[],tokens:{model_led:true,palette:{},typography:{}}};
          const page=({slide})=>{slide.addTable([[{text:'合并',options:{colSpan:2}}]],{});slide.addNotes('实际备注');};
          page.notes='实际备注'; R.renderPage(ctx,page);
          console.log(JSON.stringify({tables:slide.calls.filter(x=>x.k==='table').length,
          notes:slide.calls.filter(x=>x.k==='notes').length,copy:ctx.presentationCopy}));
        """)
        self.assertEqual(out["tables"], 1)
        self.assertEqual(out["notes"], 1)
        self.assertEqual(len(out["copy"]), 1)

    def test_predictions_allow_a_candidate_and_preserve_intent(self):
        out = node.run_node("""
          const R=require(path.join(SCRIPTS,'pptx-page-runtime.js'));
          const E=require(path.join(SCRIPTS,'pptx-element-registry.js'));
          const slide=mock(), registry=new E.SlideElementRegistry();
          const ctx={slide,registry,n:1,tokens:{model_led:true,palette:{},typography:{}}};
          R.renderPage(ctx,({slide})=>{
            slide.addText('很长的文字'.repeat(20),{x:1,y:1,w:.5,h:.1,fontSize:24,allowOverlap:true});
            slide.addImage({path:'not-read-by-mock',x:-1,y:0,w:3,h:3,decorative:true,bleed:true});
          });
          const report=registry.analyzeDeck();
          console.log(JSON.stringify({report,intent:registry._slide(1)[0].allowOverlap}));
        """)
        self.assertTrue(out["report"]["ok"], out)
        self.assertTrue(out["intent"])
        self.assertTrue(any(item["code"] in {"text_overflow", "text_may_overflow"} for item in out["report"]["warnings"]))
        self.assertFalse(any(item["code"] == "out_of_canvas" for item in out["report"]["warnings"]))

    def test_text_uses_real_metrics_and_threshold_warnings_are_opt_in(self):
        out = node.run_node("""
          const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
          const E=require(path.join(SCRIPTS,'pptx-element-registry.js'));
          const font=T.resolveFont('Calibri');
          const layout=T.layoutText('ABC',{w:4,h:1},{fontSize:18,fontFace:'Calibri',role:'body'});
          const r=new E.SlideElementRegistry();
          r.text(1,'ABC',{x:1,y:1,w:3,h:1,fontSize:9});
          console.log(JSON.stringify({height:layout.lineGeometry[0].h,
          real:(font.ascent-font.descent+font.lineGap)/font.unitsPerEm*18/72,
          warnings:r.analyzeDeck().warnings}));
        """)
        self.assertAlmostEqual(out["height"], out["real"])
        self.assertFalse(any(item["code"] == "text_size_review" for item in out["warnings"]))


class InputAndDeliveryFlexibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.MainSessionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.production = fixture.production

    def test_revision_and_replanning_preserve_authored_pages(self):
        f, p = self.fixture, self.production
        p.plan(f.args)
        f.author()
        page = next((f.work / "pages").glob("p*.js"))
        before = page.read_bytes()
        data = p.load(f.spec)
        data["slides"][0]["title"] = "修改后的标题"
        p.write(f.spec, data)
        result = p.plan(f.args)
        self.assertTrue(result["preserved_authoring"])
        self.assertEqual(page.read_bytes(), before)
        self.assertIn("slide_spec", result["input_changes"])

    def test_formatting_is_not_a_new_approval_but_summary_content_is(self):
        f, p = self.fixture, self.production
        p.plan(f.args)
        f.spec.write_text(json.dumps(p.load(f.spec), separators=(",", ":")), encoding="utf-8")
        p.authorized(f.work)
        summary = f.project / "summary.md"
        summary.write_text("changed scope", encoding="utf-8")
        with self.assertRaisesRegex(p.ProductionError, "same work-id"):
            p.authorized(f.work)
        workflow = p.load(f.work / "workflow-state.json")
        workflow["summary_sha256"] = p.file_sha256(summary)
        p.write(f.work / "workflow-state.json", workflow)
        p.authorized(f.work)

    def test_exported_user_edits_are_modified_not_incomplete(self):
        p, f = self.production, self.fixture
        output = f.project / "notes.md"
        output.write_text("initial", encoding="utf-8")
        published = {"speaker-notes": p.bind(output)}
        output.write_text("user revised", encoding="utf-8")
        health = p.publication_health(published)
        self.assertTrue(health["ok"])
        self.assertEqual(len(health["modified"]), 1)
        output.unlink()
        self.assertFalse(p.publication_health(published)["ok"])

    def test_delivery_refreshes_reports_without_rebuilding_or_rerendering(self):
        f, p = self.fixture, self.production
        p.plan(f.args)
        f.author()
        self.assertTrue(p.run(f.args)["ok"])
        for name in ("production-check.json", "content-check.json", "presentation-copy.json", "preview.png"):
            (f.work / name).unlink(missing_ok=True)
        (f.work / "render/deck.pdf").unlink()
        (f.work / "deck.js").write_text((f.work / "deck.js").read_text(encoding="utf-8") + "\n// comment only\n", encoding="utf-8")
        with patch.object(p, "execute", side_effect=AssertionError("must not rebuild")), \
                patch("shared.pptx_runtime.render.render_pptx", side_effect=AssertionError("must reuse current pages")):
            finished = p.complete(f.args)
        self.assertTrue(finished["ok"])
        self.assertTrue((f.work / "presentation-copy.json").is_file())
        # Notes-only edits must refresh actual scripts without invalidating images.
        pptx = f.work / "deck.pptx"
        with zipfile.ZipFile(pptx) as package:
            parts = {name: package.read(name) for name in package.namelist()}
        notes = "ppt/notesSlides/notesSlide1.xml"
        parts[notes] = parts[notes].replace("不代表".encode(), "不等于".encode())
        with zipfile.ZipFile(pptx, "w") as package:
            for name, data in parts.items():
                package.writestr(name, data)
        with patch("shared.pptx_runtime.render.render_pptx", side_effect=AssertionError("notes do not change visuals")):
            finished = p.complete(f.args)
        self.assertIn("不等于", Path(finished["outputs"]["speaker-notes"]["path"]).read_text(encoding="utf-8"))
        # A stale 'ok' report cannot hide an actual changed exact fact.
        parts["ppt/slides/slide1.xml"] = parts["ppt/slides/slide1.xml"].replace(b"78.4%", b"79.4%")
        with zipfile.ZipFile(pptx, "w") as package:
            for name, data in parts.items():
                package.writestr(name, data)
        with self.assertRaisesRegex(p.ProductionError, "factual errors"):
            p.complete(f.args)

    def test_source_snapshot_survives_external_original_changes(self):
        from pptx import Presentation

        f, p = self.fixture, self.production
        original = f.project / "original.pptx"
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[6])
        deck.save(original)
        snapshot = p.preserve_input(f.work, original)
        before = Path(snapshot["path"]).read_bytes()
        original.write_bytes(b"externally replaced")
        self.assertEqual(Path(snapshot["path"]).read_bytes(), before)
        self.assertTrue(p.current(snapshot))

    def test_no_render_iteration_returns_diagnostics_instead_of_keyerror(self):
        f, p = self.fixture, self.production
        data = p.load(f.spec)
        data["meta"]["slide_count"] = 999
        for slide, identity in zip(data["slides"], (20, 7), strict=True):
            slide["id"] = identity
            slide.pop("timing_sec")
            slide.pop("owner")
        p.write(f.spec, data)
        p.plan(f.args)
        f.author()
        f.args.no_render = True
        result = p.run(f.args)
        self.assertTrue(result["render_skipped"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_pages"], [])

    def test_real_native_merged_table_and_direct_notes_build(self):
        f, p = self.fixture, self.production
        p.plan(f.args)
        f.author()
        first = p.load(f.work / "build-manifest.json")["scaffold"]["pages"][0]
        (f.work / "pages" / first).write_text("""'use strict';
module.exports = ({slide}) => {
  slide.addTable([[{text:'准确率 78.4%',options:{colSpan:2}}],['组别','比例'],['A',0]],
    {x:.5,y:.5,w:9,colW:[4.5,4.5],fontSize:18,autoPage:false});
  slide.addNotes('原生表格与原生备注，合成测试。');
};
""", encoding="utf-8")
        f.args.no_render = True
        result = p.run(f.args)
        self.assertTrue(result["ok"], result)
        pptx = f.work / "deck.pptx"
        with zipfile.ZipFile(pptx) as package:
            slide_xml = package.read("ppt/slides/slide1.xml").decode()
        self.assertIn('gridSpan="2"', slide_xml)
        rows = ET.fromstring(slide_xml).iter("{http://schemas.openxmlformats.org/drawingml/2006/main}tr")
        self.assertTrue(all(int(row.attrib["h"]) > 0 for row in rows))
        self.assertIn("原生表格", content.extract_pptx_notes(pptx)[1])


class OptionalHeuristicTests(unittest.TestCase):
    def test_color_change_requests_review_without_failing_quality(self):
        from PIL import Image

        from shared.pptx_runtime.visual_baseline import compare_baseline, record_baseline

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            image = directory / "page.png"
            Image.new("RGB", (10, 10), "red").save(image)
            record_baseline(directory, directory / "baseline.json")
            Image.new("RGB", (10, 10), "blue").save(image)
            report = compare_baseline(directory, directory / "baseline.json")
            self.assertTrue(report["ok"])
            self.assertFalse(report["matches"])
            self.assertTrue(report["review_required"])

    def test_result_first_and_similar_experiment_pages_are_not_major(self):
        import test_presentation_quality as quality_tests

        from shared.presentation_quality import analyze_spec

        data = quality_tests.PresentationQualityTests().complete_spec()
        data["slides"][0]["role"] = "result"
        data["slides"][1]["role"] = "background"
        data["slides"][2] = {**data["slides"][1], "id": 3}
        report = analyze_spec(data)
        findings = [item for item in report["findings"] if item["code"] in {"role-order-regression", "duplicate-slide"}]
        self.assertEqual({item["code"] for item in findings}, {"role-order-regression", "duplicate-slide"})
        self.assertTrue(all(item["severity"] == "Minor" for item in findings))
