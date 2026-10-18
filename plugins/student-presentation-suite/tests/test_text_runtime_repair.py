"""Opt-in mixed-text positioning, real-metric line heights, small-text review.

Regression coverage for the 2026-10 live incident: a single addFittedText call
with mixed CJK/Latin copy silently split into positioned fragments (viewer
anti-rewrap default), the box-level switch was ignored, the 1.18 line-height
factor did not match real font metrics, and the registry never reviewed small
text. measure now declares its coverage scope instead of implying full QA.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_node(body: str) -> dict:
    script = (
        "const path=require('node:path');"
        f"const SCRIPTS={json.dumps(str(SCRIPTS))};"
        "function mock(){const calls=[];const rec=(k)=>(...a)=>{calls.push({k,a});return {};};"
        "return {calls,addText:rec('text'),addShape:rec('shape'),addImage:rec('image'),"
        "addChart:rec('chart'),addTable:rec('table'),addNotes:rec('notes')};}"
        + body
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NODE_PATH": str(SCRIPTS)},
    )
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr}")
    return json.loads(result.stdout)


class MixedTextGateTests(unittest.TestCase):
    """positionMixedText is opt-in: only an explicit true splits a text block."""

    def test_default_keeps_one_single_frame_rich_text(self):
        out = run_node(
            """
            const H=require(path.join(SCRIPTS,'pptx-helpers.js'));
            const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}};
            const texts=[];const slide={addText:(t,o)=>texts.push({t,o})};
            H.addFittedText(slide,'含2021年数字的中文',{x:0,y:0,w:4,h:1},tokens,'chinese','body',{fontSize:18,margin:0});
            console.log(JSON.stringify({calls:texts.length,runs:Array.isArray(texts[0].t)?texts[0].t.length:1,named:/^sps-line:/.test(String(texts[0].o.objectName||''))}));
            """
        )
        self.assertEqual(1, out["calls"])
        self.assertGreater(out["runs"], 1)  # run-level fontFace, one text object
        self.assertFalse(out["named"])

    def test_options_layer_true_splits_into_positioned_fragments(self):
        out = run_node(
            """
            const H=require(path.join(SCRIPTS,'pptx-helpers.js'));
            const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}};
            const texts=[];const slide={addText:(t,o)=>texts.push({t,o})};
            H.addFittedText(slide,'含2021年数字的中文',{x:0,y:0,w:4,h:1},tokens,'chinese','body',{fontSize:18,margin:0,positionMixedText:true});
            console.log(JSON.stringify({calls:texts.length,allNamed:texts.every(x=>/^sps-line:/.test(String(x.o.objectName||'')))}));
            """
        )
        self.assertGreater(out["calls"], 1)
        self.assertTrue(out["allNamed"])

    def test_box_layer_true_also_enables_the_split(self):
        out = run_node(
            """
            const H=require(path.join(SCRIPTS,'pptx-helpers.js'));
            const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}};
            const texts=[];const slide={addText:(t,o)=>texts.push({t,o})};
            H.addFittedText(slide,'含2021年数字的中文',{x:0,y:0,w:4,h:1,positionMixedText:true},tokens,'chinese','body',{fontSize:18,margin:0});
            console.log(JSON.stringify({calls:texts.length}));
            """
        )
        self.assertGreater(out["calls"], 1)

    def test_box_layer_false_is_no_longer_a_silent_split_suppressor(self):
        # The 2026-10 live bug: positionMixedText:false in the box argument was
        # read by the old options-level gate. Under opt-in semantics a box-level
        # false simply means "not requested" — the text stays one frame.
        out = run_node(
            """
            const H=require(path.join(SCRIPTS,'pptx-helpers.js'));
            const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}};
            const texts=[];const slide={addText:(t,o)=>texts.push({t,o})};
            H.addFittedText(slide,'含2021年数字的中文',{x:0,y:0,w:4,h:1,positionMixedText:false},tokens,'chinese','body',{fontSize:18,margin:0});
            console.log(JSON.stringify({calls:texts.length}));
            """
        )
        self.assertEqual(1, out["calls"])

    def test_bare_slide_add_text_wrapper_matches_opt_in(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-page-runtime.js'));
            const texts=[];const slide={addText:(t,o)=>texts.push({t,o}),addShape(){},addImage(){},addChart(){}};
            const ctx={slide,tokens:{model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}},registry:{register(){},options:{}},n:1};
            R.captureSlide(ctx);
            slide.addText('含2021年数字的中文',{x:0,y:0,w:4,h:1,fontSize:18,margin:0});
            const defaultCalls=texts.length;
            slide.addText('含2022年数字的中文',{x:0,y:2,w:4,h:1,fontSize:18,margin:0,positionMixedText:true});
            console.log(JSON.stringify({defaultCalls, splitCalls:texts.length-defaultCalls}));
            """
        )
        self.assertEqual(1, out["defaultCalls"])
        self.assertGreater(out["splitCalls"], 1)


class RealMetricLineHeightTests(unittest.TestCase):
    """layoutText derives line height from fontkit metrics, falling back to 1.18."""

    def test_mixed_line_height_matches_fontkit_formula(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const policy={fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'body'};
            const mixed=T.layoutText('含2021年数字的中文文本',{x:0,y:0,w:4,h:1},policy);
            const cjk=T.layoutText('中文文本',{x:0,y:0,w:4,h:1},policy);
            const latin=T.layoutText('ABC 123',{x:0,y:0,w:4,h:1},policy);
            const ratio=(name)=>{const f=T.resolveFont(name);const gap=Number.isFinite(f.lineGap)?f.lineGap:0;return (f.ascent-f.descent+gap)/f.unitsPerEm*18/72;};
            // Classroom floor: no line renders tighter than 1.3× its size.
            const simSun=Math.max(ratio('SimSun'),1.3*18/72),calibri=Math.max(ratio('Calibri'),1.3*18/72);
            console.log(JSON.stringify({mixed:mixed.lineGeometry[0].h,cjk:cjk.lineGeometry[0].h,latin:latin.lineGeometry[0].h,simSun,calibri,emitted:mixed.lineHeightPt}));
            """
        )
        # Each line's height equals the tallest run's real-metric line height,
        # floored at 1.3× size.
        self.assertAlmostEqual(out["simSun"], out["cjk"], places=9)
        self.assertAlmostEqual(out["calibri"], out["latin"], places=9)
        self.assertAlmostEqual(max(out["simSun"], out["calibri"]), out["mixed"], places=9)
        self.assertAlmostEqual(out["emitted"], max(out["simSun"], out["calibri"]) * 72, places=6)

    def test_explicit_line_spacing_in_points_still_wins(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('中文文本',{x:0,y:0,w:4,h:1},{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',lineSpacing:40});
            console.log(JSON.stringify({h:r.lineGeometry[0].h}));
            """
        )
        self.assertAlmostEqual(40 / 72, out["h"], places=9)


class TextSizeReviewTests(unittest.TestCase):
    """The registry flags sub-10pt runs as a review warning, never a blocker."""

    def test_nine_pt_body_text_warns_but_stays_ok(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'小字正文',{x:1,y:1,w:3,h:1,fontSize:9});
            const report=r.analyzeDeck();
            console.log(JSON.stringify({ok:report.ok,warnings:report.warnings}));
            """
        )
        self.assertTrue(out["ok"])
        review = [w for w in out["warnings"] if w["code"] == "text_size_review"]
        self.assertEqual(1, len(review))
        self.assertIn("minSize", review[0])
        self.assertLess(review[0]["minSize"], 10)

    def test_ten_pt_and_above_do_not_warn(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'常规正文',{x:1,y:1,w:3,h:1,fontSize:10});
            r.text(1,'页脚来源',{x:1,y:2,w:3,h:1,fontSize:11});
            console.log(JSON.stringify({warnings:r.analyzeDeck().warnings.map(w=>w.code)}));
            """
        )
        self.assertNotIn("text_size_review", out["warnings"])

    def test_decorative_small_text_is_exempt(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'装饰小字',{x:1,y:1,w:3,h:1,fontSize:9,decorative:true});
            r.text(1,'允许重叠小字',{x:1,y:2,w:3,h:1,fontSize:9,allowOverlap:true});
            console.log(JSON.stringify({warnings:r.analyzeDeck().warnings.map(w=>w.code)}));
            """
        )
        self.assertNotIn("text_size_review", out["warnings"])

    def test_captured_rich_runs_report_the_smallest_run_size(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-page-runtime.js'));
            const {SlideElementRegistry}=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const registry=new SlideElementRegistry();
            const slide={addText(){},addShape(){},addImage(){},addChart(){}};
            const ctx={slide,tokens:{model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}},registry,n:1};
            R.captureSlide(ctx);
            slide.addText([{text:'常规',options:{}},{text:'小字',options:{fontSize:8}}],{x:0,y:0,w:4,h:1,fontSize:12,margin:0});
            const report=registry.analyzeDeck();
            console.log(JSON.stringify({ok:report.ok,reviews:report.warnings.filter(w=>w.code==='text_size_review')}));
            """
        )
        self.assertTrue(out["ok"])
        self.assertEqual(1, len(out["reviews"]))
        self.assertEqual(8, out["reviews"][0]["minSize"])


class MeasureCoverageTests(unittest.TestCase):
    """pptx-measure declares that it only covers text overflow/tight fit."""

    COVERAGE = "text overflow/tight only; color contrast, overlap and alignment are checked only by run"

    def test_measure_report_and_stdout_declare_coverage(self):
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            deck = work / "deck.js"
            deck.write_text(
                "const H = require(process.env.PPTX_HELPERS_DIR + '/pptx-helpers.js');\n"
                "const tokens = {model_led:true, typography:{}, palette:{canvas:'FFFFFF',primary_text:'111111'}};\n"
                "H.addFittedText({addText(){}}, '含2021年数字的中文文本', {x:0,y:0,w:4,h:1}, tokens, 'chinese', 'body', {fontSize:18, margin:0});\n",
                encoding="utf-8",
            )
            report_path = work / "report.json"
            env = {
                **os.environ,
                "CLAUDE_PLUGIN_ROOT": str(ROOT),
                "PPTX_HELPERS_DIR": str(SCRIPTS),
            }
            proc = subprocess.run(
                ["node", str(SCRIPTS / "pptx-measure.js"), str(deck), str(report_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=120,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(self.COVERAGE, report["coverage"])
            self.assertIn(f"coverage: {self.COVERAGE}", proc.stdout)


class ParagraphSpacingTests(unittest.TestCase):
    """Multi-paragraph blocks default to 0.4× paragraph-size space after each
    real paragraph; measurement and the written runs carry the same value."""

    POLICY = "{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'body'}"

    def test_default_space_after_each_real_paragraph(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('第一段内容\\n第二段内容',{x:0,y:0,w:4,h:2},POLICY);
            const lineH=1.3*18/72, space=0.4*18/72;
            const annotated=r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).map(x=>[x.text,x.options.paraSpaceAfter]);
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4)),requiredH:+r.requiredH.toFixed(4),annotated,expected:+(lineH+space).toFixed(4)}));
            """.replace(
                "POLICY", self.POLICY
            )
        )
        self.assertEqual([out["expected"]] * 2, out["hs"])
        self.assertAlmostEqual(2 * out["expected"], out["requiredH"], places=4)
        self.assertEqual(2, len(out["annotated"]))
        self.assertTrue(all(abs(value - 7.2) < 1e-9 for _, value in out["annotated"]))

    def test_explicit_zero_disables_the_default(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('第一段内容\\n第二段内容',{x:0,y:0,w:4,h:2},{...POLICY,paraSpaceAfter:0});
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4)),annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).length}));
            """.replace(
                "POLICY", self.POLICY
            )
        )
        self.assertEqual([round(1.3 * 18 / 72, 4)] * 2, out["hs"])
        self.assertEqual(0, out["annotated"])

    def test_explicit_value_applies_per_wrapped_line_like_pptxgenjs(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('第一段内容\\n第二段内容',{x:0,y:0,w:4,h:2},{...POLICY,paraSpaceAfter:12});
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4))}));
            """.replace(
                "POLICY", self.POLICY
            )
        )
        expected = round(1.3 * 18 / 72 + 12 / 72, 4)
        self.assertEqual([expected] * 2, out["hs"])

    def test_single_paragraph_gets_no_default_space(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('单一自然段内容',{x:0,y:0,w:4,h:1},POLICY);
            console.log(JSON.stringify({h:+r.lineGeometry[0].h.toFixed(4),annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).length}));
            """.replace(
                "POLICY", self.POLICY
            )
        )
        self.assertEqual(round(1.3 * 18 / 72, 4), out["h"])
        self.assertEqual(0, out["annotated"])


class SizeTierAndFontMixTests(unittest.TestCase):
    """Slide-level typography review warnings: size tiers and family pairs."""

    def test_five_size_tiers_warn_but_stay_ok(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            for (const [i,size] of [9,12,14,18,22].entries()) r.text(1,'内容'+i,{x:1,y:1+i,w:3,h:.5,fontSize:size});
            const report=r.analyzeDeck();
            console.log(JSON.stringify({ok:report.ok,tiers:report.warnings.filter(w=>w.code==='text_size_tiers')}));
            """
        )
        self.assertTrue(out["ok"])
        self.assertEqual(1, len(out["tiers"]))
        self.assertEqual([9, 12, 14, 18, 22], out["tiers"][0]["tiers"])

    def test_four_size_tiers_do_not_warn(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            for (const [i,size] of [12,14,18,22].entries()) r.text(1,'内容'+i,{x:1,y:1+i,w:3,h:.5,fontSize:size});
            console.log(JSON.stringify({codes:r.analyzeDeck().warnings.map(w=>w.code)}));
            """
        )
        self.assertNotIn("text_size_tiers", out["codes"])

    def test_decorative_sizes_are_not_counted(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'正文一',{x:1,y:1,w:3,h:.5,fontSize:12});
            r.text(1,'正文二',{x:1,y:2,w:3,h:.5,fontSize:14});
            r.text(1,'装饰',{x:1,y:3,w:3,h:.5,fontSize:8,decorative:true});
            console.log(JSON.stringify({codes:r.analyzeDeck().warnings.map(w=>w.code)}));
            """
        )
        self.assertNotIn("text_size_tiers", out["codes"])

    def test_more_than_two_font_pairs_warns(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'甲',{x:1,y:1,w:3,h:.5,fontSize:14,fontFace:'DengXian',cjkFontFace:'DengXian',textFonts:['DengXian']});
            r.text(1,'乙',{x:1,y:2,w:3,h:.5,fontSize:14,fontFace:'Calibri',cjkFontFace:'Microsoft YaHei',textFonts:['Calibri']});
            r.text(1,'丙',{x:1,y:3,w:3,h:.5,fontSize:14,fontFace:'Arial',cjkFontFace:'Microsoft YaHei',textFonts:['Arial']});
            const report=r.analyzeDeck();
            console.log(JSON.stringify({ok:report.ok,mix:report.warnings.filter(w=>w.code==='font_family_mix')}));
            """
        )
        self.assertTrue(out["ok"])
        self.assertEqual(1, len(out["mix"]))
        self.assertEqual(3, len(out["mix"][0]["pairs"]))

    def test_two_font_pairs_are_allowed(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            r.text(1,'标题',{x:1,y:1,w:3,h:.5,fontSize:20,fontFace:'DengXian',cjkFontFace:'DengXian',textFonts:['DengXian']});
            r.text(1,'正文',{x:1,y:2,w:3,h:.5,fontSize:14,fontFace:'DengXian',cjkFontFace:'DengXian',textFonts:['DengXian']});
            console.log(JSON.stringify({codes:r.analyzeDeck().warnings.map(w=>w.code)}));
            """
        )
        self.assertNotIn("font_family_mix", out["codes"])


class DefaultFontSourceTests(unittest.TestCase):
    """Runs without an explicit fontFace resolve to the tokens body/title
    families — a bare Arial fallback must never reach the deliverable."""

    def build_deck(self, body_font: str, cjk_body_font: str, font_face: str | None) -> str:
        import re
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fonts.pptx"
            face = f"fontFace: {font_face!r},".replace("'", '"') if font_face else ""
            code = (
                "const path=require('node:path');\n"
                f"const SCRIPTS={json.dumps(str(SCRIPTS))};\n"
                "const PptxGenJS=require("
                + json.dumps(str(ROOT / "node_modules" / "pptxgenjs"))
                + ");\n"
                + "const H=require(path.join(SCRIPTS,'pptx-helpers.js'));\n"
                + "const tokens={model_led:true,typography:{body_font:BODYFont,cjk_body_font:CJKFont},palette:{canvas:'FFFFFF',primary_text:'111111'}};\n"
                + "const pptx=new PptxGenJS();\n"
                + "H.applyTokens(pptx,tokens,'chinese');\n"
                + "const slide=pptx.addSlide();\n"
                + "H.addFittedText(slide,'含2021年数字的中文文本',{x:.5,y:.5,w:6,h:1.5},tokens,'chinese','body',{fontSize:18,margin:0,FACE});\n"
                + "pptx.writeFile({fileName:OUTPUT}).then(()=>console.log('done'));\n"
            )
            code = (
                code.replace("BODYFont", json.dumps(body_font))
                .replace("CJKFont", json.dumps(cjk_body_font))
                .replace("FACE", face)
                .replace("OUTPUT", json.dumps(str(output)))
            )
            result = subprocess.run(
                ["node", "-e", code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "NODE_PATH": str(SCRIPTS)},
                timeout=120,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            xml = zipfile.ZipFile(output).read("ppt/slides/slide1.xml").decode()
            return sorted(set(re.findall(r'<a:latin typeface="([^"]+)"', xml)))

    def test_runs_default_to_tokens_body_font(self):
        self.assertEqual(["DengXian"], self.build_deck("DengXian", "DengXian", None))

    def test_unresolvable_requested_face_is_kept_not_aliased_to_arial(self):
        faces = self.build_deck("DengXian", "DengXian", "NotInstalled Sans XYZ")
        self.assertIn("NotInstalled Sans XYZ", faces)
        self.assertNotIn("Arial", faces)


class ParagraphEndAnnotationTests(unittest.TestCase):
    """spcAft must land on the LAST visual line's last run of each real
    paragraph — never on a wrapped line inside a paragraph (2026-10 regression:
    the annotation used to ride the paragraph's first visual line)."""

    def test_wrapped_first_paragraph_annotates_only_its_final_line(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const long='研究团队在2021年至2023年间对全国十二个省份的二百四十所中小学校开展了为期三年的跟踪调查，覆盖学生超过十二万人；'.repeat(2);
            const r=T.layoutText(long+'\\n第二段结论：差异显著。',{x:0,y:0,w:3.2,h:6},{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'body'});
            const annotated=r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).map(x=>x.text);
            const inner=r.lineGeometry.slice(0,-2).map(l=>+l.h.toFixed(4));
            const sumH=r.lineGeometry.reduce((s,l)=>s+l.h,0);
            console.log(JSON.stringify({lines:r.lines,annotated,inner,lastTwo:r.lineGeometry.slice(-2).map(l=>+l.h.toFixed(4)),sumH:+sumH.toFixed(4),requiredH:+r.requiredH.toFixed(4)}));
            """
        )
        self.assertGreater(out["lines"], 3)
        self.assertEqual(2, len(out["annotated"]))
        # Only the real paragraph-final visual lines carry the space.
        self.assertTrue(out["annotated"][0].endswith("十二万人；"))
        self.assertEqual("第二段结论：差异显著。", out["annotated"][1])
        # Wrapped lines inside paragraph one stay pure line height.
        self.assertEqual([round(1.3 * 18 / 72, 4)] * len(out["inner"]), out["inner"])
        self.assertEqual([round(1.3 * 18 / 72 + 7.2 / 72, 4)] * 2, out["lastTwo"])
        self.assertAlmostEqual(out["sumH"], out["requiredH"], places=6)

    def test_single_line_paragraphs_annotate_each_paragraph(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('第一段\\n第二段\\n第三段',{x:0,y:0,w:4,h:2},{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'body'});
            console.log(JSON.stringify({annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).map(x=>x.text),hs:r.lineGeometry.map(l=>+l.h.toFixed(4))}));
            """
        )
        self.assertEqual(["第一段", "第二段", "第三段"], out["annotated"])

    def test_trailing_newline_leaves_no_orphan_annotation(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('第一段\\n第二段\\n',{x:0,y:0,w:4,h:2},{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'body'});
            console.log(JSON.stringify({annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).map(x=>x.text)}));
            """
        )
        self.assertEqual(["第一段", "第二段"], out["annotated"])

    def test_explicit_alias_applies_to_display_roles_too(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('标题第一段\\n标题第二段',{x:0,y:0,w:6,h:2},{fontSize:30,fontFace:'Calibri',cjkFontFace:'SimSun',role:'title',paraSpaceAfterPt:6});
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4))}));
            """
        )
        # Explicit spacing overrides the role-scoped default even for title.
        self.assertEqual([round(30 * 1.140625 / 72 + 6 / 72, 4)] * 2, out["hs"])

    def test_real_pptx_spcaft_lands_only_on_paragraph_final_paragraphs(self):
        import re
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "para.pptx"
            code = (
                "const path=require('node:path');\n"
                f"const SCRIPTS={json.dumps(str(SCRIPTS))};\n"
                "const PptxGenJS=require("
                + json.dumps(str(ROOT / "node_modules" / "pptxgenjs"))
                + ");\n"
                "const H=require(path.join(SCRIPTS,'pptx-helpers.js'));\n"
                "const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}};\n"
                "const pptx=new PptxGenJS();\n"
                "H.applyTokens(pptx,tokens,'chinese');\n"
                "const slide=pptx.addSlide();\n"
                "const long='研究团队在2021年至2023年间对全国十二个省份的二百四十所中小学校开展了为期三年的跟踪调查，覆盖学生超过十二万人；'.repeat(2);\n"
                "H.addFittedText(slide,long+'\\n第二段结论：差异显著。',{x:.5,y:.5,w:3.2,h:6},tokens,'chinese','body',{fontSize:18,margin:0});\n"
                "pptx.writeFile({fileName:OUTPUT}).then(()=>console.log('done'));\n".replace(
                    "OUTPUT", json.dumps(str(output))
                )
            )
            result = subprocess.run(
                ["node", "-e", code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "NODE_PATH": str(SCRIPTS)},
                timeout=120,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            xml = zipfile.ZipFile(output).read("ppt/slides/slide1.xml").decode()
            paragraphs = re.findall(r"<a:p>.*?</a:p>", xml, re.S)
            with_spcaft = [p for p in paragraphs if "<a:spcAft>" in p]
            without_spcaft = [p for p in paragraphs if "<a:spcAft>" not in p]
            self.assertGreater(len(paragraphs), 3)
            self.assertEqual(2, len(with_spcaft))
            self.assertEqual(len(paragraphs) - 2, len(without_spcaft))
            self.assertEqual(
                {"720"}, set(re.findall(r"<a:spcAft><a:spcPts val=\"(\d+)\"", xml))
            )


class RoleScopedDefaultsTests(unittest.TestCase):
    """1.3 line floor and default paragraph spacing apply to body/list only."""

    def test_caption_uses_real_metrics_without_floor(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('图注文本',{x:0,y:0,w:4,h:1},{fontSize:11,fontFace:'Calibri',cjkFontFace:'SimSun',role:'caption'});
            const f=T.resolveFont('SimSun');const gap=Number.isFinite(f.lineGap)?f.lineGap:0;
            const metric=(f.ascent-f.descent+gap)/f.unitsPerEm*11/72;
            console.log(JSON.stringify({h:r.lineGeometry[0].h,metric}));
            """
        )
        self.assertAlmostEqual(out["metric"], out["h"], places=9)
        self.assertLess(out["h"], 1.3 * 11 / 72)

    def test_title_multi_paragraph_gets_no_default_space(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('主标题行\\n副标题行',{x:0,y:0,w:6,h:2},{fontSize:30,fontFace:'Calibri',cjkFontFace:'SimSun',role:'title'});
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4)),annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).length}));
            """
        )
        self.assertEqual([round(30 * 1.140625 / 72, 4)] * 2, out["hs"])
        self.assertEqual(0, out["annotated"])

    def test_list_role_gets_floor_and_default_space(self):
        out = run_node(
            """
            const T=require(path.join(SCRIPTS,'pptx-text-layout.js'));
            const r=T.layoutText('要点一\\n要点二',{x:0,y:0,w:4,h:2},{fontSize:18,fontFace:'Calibri',cjkFontFace:'SimSun',role:'list'});
            console.log(JSON.stringify({hs:r.lineGeometry.map(l=>+l.h.toFixed(4)),annotated:r.richText.filter(x=>x.options.paraSpaceAfter!==undefined).length}));
            """
        )
        self.assertEqual([round(1.3 * 18 / 72 + 7.2 / 72, 4)] * 2, out["hs"])
        self.assertEqual(2, out["annotated"])


class TextRolePlumbingTests(unittest.TestCase):
    """addFittedText carries the resolved role into registry metadata without
    leaking role/textRole keys into the pptxgenjs call."""

    def test_role_reaches_registry_and_never_reaches_pptxgenjs(self):
        out = run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-page-runtime.js'));
            const {SlideElementRegistry}=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const received=[];
            const slide={addText:(t,o)=>{received.push({...o});},addShape(){},addImage(){},addChart(){}};
            const registry=new SlideElementRegistry();
            const ctx={slide,tokens:{model_led:true,typography:{cjk_body_font:'DengXian'},palette:{canvas:'FFFFFF',primary_text:'111111'}},registry,n:1};
            R.captureSlide(ctx);
            const H=require(path.join(SCRIPTS,'pptx-helpers.js'));
            H.addFittedText(slide,'含2021年数字的正文',{x:0,y:0,w:4,h:1},ctx.tokens,'chinese','body',{fontSize:18,margin:0});
            slide.addText('裸文本无角色',{x:0,y:2,w:4,h:1,fontSize:18,margin:0});
            slide.addText('显式角色',{x:0,y:3,w:4,h:1,fontSize:18,margin:0,textRole:'caption'});
            const roles=registry._slide(1).map(e=>e.textRole);
            const eaFaces=registry._slide(1).map(e=>e.cjkFontFace);
            const leaked=received.some(o=>'role' in o||'textRole' in o);
            console.log(JSON.stringify({roles,eaFaces,leaked}));
            """
        )
        self.assertEqual(["body", "unknown", "caption"], out["roles"])
        # The ea face rides through the _textLayout skip so font-mix counting
        # sees the real pair instead of an empty ea side.
        self.assertEqual(["DengXian", "DengXian", "DengXian"], out["eaFaces"])
        self.assertFalse(out["leaked"])


class RoleAwareWarningTests(unittest.TestCase):
    """Thresholds and counting follow the element's text role."""

    def registry(self, statements):
        return run_node(
            """
            const R=require(path.join(SCRIPTS,'pptx-element-registry.js'));
            const r=new R.SlideElementRegistry();
            STATEMENTS
            const report=r.analyzeDeck();
            console.log(JSON.stringify({ok:report.ok,warnings:report.warnings}));
            """.replace(
                "STATEMENTS", statements
            )
        )

    def test_body_run_below_12pt_warns(self):
        out = self.registry(
            "r.text(1,'正文',{x:1,y:1,w:3,h:1,fontSize:11,textRole:'body'});"
        )
        review = [w for w in out["warnings"] if w["code"] == "text_size_review"]
        self.assertEqual(1, len(review))
        self.assertEqual("body", review[0]["role"])
        self.assertEqual(12, review[0]["threshold"])

    def test_caption_run_at_9_5pt_does_not_warn(self):
        out = self.registry(
            "r.text(1,'图注',{x:1,y:1,w:3,h:1,fontSize:9.5,textRole:'caption'});"
        )
        self.assertNotIn("text_size_review", [w["code"] for w in out["warnings"]])

    def test_kpi_and_stat_sizes_do_not_count_as_tiers(self):
        out = self.registry(
            "r.text(1,'正文',{x:1,y:1,w:3,h:.5,fontSize:12,textRole:'body'});"
            "r.text(1,'结论',{x:1,y:2,w:3,h:.5,fontSize:14,textRole:'body'});"
            "r.text(1,'大数字',{x:6,y:1,w:3,h:1,fontSize:60,textRole:'kpi'});"
            "r.text(1,'统计',{x:6,y:2,w:3,h:1,fontSize:46,textRole:'stat'});"
            "r.text(1,'标签',{x:6,y:3,w:3,h:.5,fontSize:16,textRole:'label'});"
            "r.text(1,'节点',{x:6,y:4,w:3,h:.5,fontSize:18,textRole:'node'});"
        )
        self.assertNotIn("text_size_tiers", [w["code"] for w in out["warnings"]])

    def test_unknown_role_still_counts_toward_tiers(self):
        out = self.registry(
            "for (const [i,size] of [12,14,18,22,26].entries()) r.text(1,'旧页'+i,{x:1,y:1+i,w:3,h:.5,fontSize:size});"
        )
        self.assertIn("text_size_tiers", [w["code"] for w in out["warnings"]])

    def test_same_role_two_pairs_warns(self):
        out = self.registry(
            "r.text(1,'正文甲',{x:1,y:1,w:3,h:.5,fontSize:14,fontFace:'Calibri',cjkFontFace:'Microsoft YaHei',textFonts:['Calibri'],textRole:'body'});"
            "r.text(1,'正文乙',{x:1,y:2,w:3,h:.5,fontSize:14,fontFace:'Arial',cjkFontFace:'Microsoft YaHei',textFonts:['Arial'],textRole:'body'});"
        )
        mix = [w for w in out["warnings"] if w["code"] == "font_family_mix"]
        self.assertEqual(1, len(mix))
        self.assertEqual("body", mix[0]["role"])

    def test_title_body_different_pairs_are_legal(self):
        out = self.registry(
            "r.text(1,'标题',{x:1,y:1,w:3,h:.5,fontSize:22,fontFace:'Cambria',cjkFontFace:'SimHei',textFonts:['Cambria'],textRole:'title'});"
            "r.text(1,'正文',{x:1,y:2,w:3,h:.5,fontSize:14,fontFace:'Microsoft YaHei',cjkFontFace:'Microsoft YaHei',textFonts:['Microsoft YaHei'],textRole:'body'});"
        )
        self.assertNotIn("font_family_mix", [w["code"] for w in out["warnings"]])

    def test_unknown_role_keeps_two_pair_fallback(self):
        out = self.registry(
            "r.text(1,'甲',{x:1,y:1,w:3,h:.5,fontSize:14,fontFace:'Calibri',cjkFontFace:'Microsoft YaHei',textFonts:['Calibri']});"
            "r.text(1,'乙',{x:1,y:2,w:3,h:.5,fontSize:14,fontFace:'Arial',cjkFontFace:'Microsoft YaHei',textFonts:['Arial']});"
            "r.text(1,'丙',{x:1,y:3,w:3,h:.5,fontSize:14,fontFace:'Cambria',cjkFontFace:'SimHei',textFonts:['Cambria']});"
        )
        self.assertIn("font_family_mix", [w["code"] for w in out["warnings"]])

    def test_symbol_only_runs_do_not_count_as_pairs(self):
        out = self.registry(
            "r.text(1,'正文与图标',{x:1,y:1,w:3,h:.5,fontSize:14,fontFace:'Calibri',cjkFontFace:'Microsoft YaHei',textFonts:['Calibri','Arial'],textScriptFlags:[true,false],textRole:'body'});"
        )
        self.assertNotIn("font_family_mix", [w["code"] for w in out["warnings"]])


if __name__ == "__main__":
    unittest.main()
