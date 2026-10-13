"""Behavioral coverage for design freedom, semantic fidelity and measured text."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "sp-deck" / "scripts"))

import pptx_actual_content_check as content
from page_copy_fidelity_check import missing_fragments

from shared.content_requirements import exact_present, numbers, semantic_binding, semantic_review_issues
from shared.design_policy import design_mode
from shared.slide_spec_contract import validate_spec_data


def slide():
    return {"id": 1, "title": "过去一年我们通过组织竞赛提供科研机会", "layout": "claim-focus", "content": ["规划内容"], "timing_sec": 60, "owner": "speaker", "claim": "这段规划描述不要求逐字上屏", "semantic_requirements": {
        "must_convey": [{"id": "research", "text": "为低年级提供科研实践机会"}],
        "must_show_exact": ["233", "国家奖学金"],
    }}


class SemanticTests(unittest.TestCase):
    def test_copy_preflight_cli_runs_without_pythonpath_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec = directory / 'spec.json'
            spec.write_text(json.dumps({'schema_version': '2.1', 'slides': [slide()]}), encoding='utf-8')
            env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
            process = subprocess.run([sys.executable, str(ROOT / 'skills/sp-deck/scripts/copy_fit_preflight.py'), '--slide-spec', str(spec), '--json'], cwd=directory, env=env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(json.loads(process.stdout)['ok'])

    def test_presentation_copy_must_record_complete_actual_notes(self):
        import argparse
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pptx, spec = directory / 'deck.pptx', directory / 'spec.json'
            pptx.write_bytes(b'fixture')
            spec.write_text(json.dumps({'schema_version': '2.1', 'slides': [slide()]}), encoding='utf-8')
            copy = {'pptx_sha256': content.sha256_file(pptx), 'slides': [{'slide': 1, 'headline': '国家奖学金', 'visual_labels': ['233'], 'speaker_notes': '', 'text_runs': ['国家奖学金233']}]}
            sidecar = directory / 'presentation-copy.json'
            args = argparse.Namespace(pptx=pptx, slide_spec=spec, output=directory / 'check.json', json=False, strict=True)
            with patch.object(content, 'extract_pptx_text', return_value=['国家奖学金233']), patch.object(content, 'extract_pptx_notes', return_value={1: '完整讲稿'}), redirect_stdout(io.StringIO()):
                sidecar.write_text(json.dumps(copy), encoding='utf-8')
                self.assertEqual(content.run(args), 2)
                copy['slides'][0]['speaker_notes'] = '完整讲稿'
                sidecar.write_text(json.dumps(copy), encoding='utf-8')
                self.assertEqual(content.run(args), 0)

    def test_modelled_delivery_keeps_hash_binding_without_optional_gallery_files(self):
        from pptx_delivery_check_v08 import validate_visual_generation_report

        from shared.hashing import file_sha256

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec, art, report = (directory / name for name in ('spec.json', 'art.json', 'report.json'))
            spec.write_text(json.dumps({'schema_version': '2.1', 'slides': [slide()]}), encoding='utf-8')
            art.write_text('{}', encoding='utf-8')
            data = {'ok': True, 'generation_core_version': '0.8', 'slide_spec_sha256': file_sha256(spec), 'art_direction_sha256': file_sha256(art), 'high_leverage_slides': [1], 'evidence': [{'slide': 1}], 'quality': 'standard'}
            report.write_text(json.dumps(data), encoding='utf-8')
            self.assertTrue(validate_visual_generation_report(report, spec, art)['valid'])
            art.write_text('{"changed":true}', encoding='utf-8')
            self.assertFalse(validate_visual_generation_report(report, spec, art)['valid'])
            data['art_direction_sha256'] = file_sha256(art)
            spec.write_text(json.dumps({'schema_version': '2.0', 'slides': []}), encoding='utf-8')
            data['slide_spec_sha256'] = file_sha256(spec)
            report.write_text(json.dumps(data), encoding='utf-8')
            self.assertFalse(validate_visual_generation_report(report, spec, art)['valid'])

    def test_visual_factual_encoding_blocks_even_when_critic_calls_it_style(self):
        from pptx_quality_gate_v071 import (
            apply_modelled_findings,
            validate_visual_report,
            visual_finding_category_issues,
        )

        findings = [{'code': 'bar-height-implies-unstated-ratio', 'category': 'design_preference', 'severity': 'minor'}, {'code': 'changed-achievement', 'category': 'fact', 'severity': 'minor'}]
        apply_modelled_findings(findings)
        self.assertTrue(all(item['severity'] == 'major' for item in findings))
        subjective = [{'code': 'no-information-design', 'category': 'structure', 'severity': 'major'}]
        apply_modelled_findings(subjective)
        self.assertEqual(subjective[0]['severity'], 'advisory')
        self.assertTrue(visual_finding_category_issues({'slides': [{'slide': 1, 'issues': [{'code': 'unknown'}]}]}))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pptx, report = directory / 'deck.pptx', directory / 'review.json'
            pptx.write_bytes(b'fixture')
            report.write_text(json.dumps({'pptx_sha256': content.sha256_file(pptx), 'slides': [{'slide': 1, 'visual_structure': 'chart', 'scores': dict.fromkeys(('hierarchy', 'focal_point', 'composition', 'visual_interest', 'whitespace'), 8), 'issues': [{'code': 'unsupported_visual_ratio', 'severity': 'minor', 'category': 'fact', 'message': 'Invented bar ratio', 'element': 'bar', 'fix': 'Use a neutral illustration', 'repair_level': 'composition'}]}]}), encoding='utf-8')
            projected = validate_visual_report(report, pptx, 1, modelled=True)['issues']
            apply_modelled_findings(projected)
            self.assertEqual(next(item['severity'] for item in projected if item['code'] == 'unsupported_visual_ratio'), 'major')

    def test_asset_projection_uses_actual_dimensions_and_keeps_protected_region(self):
        from direct_production import measured_assets
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            Image.new('RGB', (37, 21)).save(directory / 'figure.png')
            region = {'x': 0, 'y': 0, 'w': 1, 'h': 1}
            (directory / 'asset-manifest.json').write_text(json.dumps({'assets': [{'path': 'figure.png', 'width': 999, 'height': 999, 'preserve_region': region, 'content_focus': '全部流程'}]}), encoding='utf-8')
            projected = measured_assets(directory)[0]
            self.assertEqual((projected['width'], projected['height']), (37, 21))
            self.assertEqual(projected['preserve_region'], region)
            self.assertEqual(len(projected['sha256']), 64)


    def test_subjective_advice_does_not_override_brand_or_actual_readability(self):
        from pptx_quality_gate_v071 import apply_modelled_findings

        findings=[{'code':'visual_score_low','severity':'major'},{'code':'panel_alternative','severity':'major','category':'design_preference'},{'code':'text_crossed_by_line','severity':'minor','category':'readability','critic_severity':'major'},{'code':'logo_missing','severity':'minor','category':'design_preference'}]
        apply_modelled_findings(findings)
        self.assertEqual([finding['severity'] for finding in findings],['advisory','advisory','major','major'])
    def test_positioned_readback_joins_only_bound_adjacent_spans(self):
        from xml.etree import ElementTree as ET

        from shared.pptx_text_readback import slide_text

        def shape(text, x, name='sps-line:paragraph:0', y=0):
            return f'<p:sp><p:nvSpPr><p:cNvPr name="{name}"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="100000" cy="100000"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'

        def read(second):
            xml = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + shape('1,', 0) + second + '</p:sld>'
            return slide_text(ET.fromstring(xml))

        self.assertTrue(exact_present('1,233', read(shape('233', 100000))))
        self.assertFalse(exact_present('1,233', read(shape('233', 100000, 'ordinary'))))
        self.assertFalse(exact_present('1,233', read(shape('233', 100000, y=100000))))
        self.assertFalse(exact_present('233', read(shape('233', 100000))))
    def test_semantic_input_binding_changes_even_when_images_do_not(self):
        before = semantic_binding("a" * 64, ["233小时"], {1: "解释"})
        self.assertNotEqual(before, semantic_binding("b" * 64, ["233小时"], {1: "解释"}))
        self.assertNotEqual(before, semantic_binding("a" * 64, ["1233小时"], {1: "解释"}))
        self.assertNotEqual(before, semantic_binding("a" * 64, ["233小时"], {1: "改写讲稿"}))

    def test_visual_semantics_requires_actual_registered_element(self):
        spec = {"slides": [slide()]}
        review = {"slides": [{"slide": 1, "semantic_coverage": [{"id": "research", "status": "covered", "placement": "slide", "visual_elements": ["s1-e1"]}]}]}
        self.assertEqual(semantic_review_issues(spec, review, [""], {}, {1: {"s1-e1"}}), [])
        self.assertTrue(semantic_review_issues(spec, review, [""], {}, {1: {"s1-e2"}}))

    def test_exact_user_brand_cannot_be_rewritten(self):
        from shared.handoff_validation import handoff_errors

        self.assertEqual(handoff_errors({'brand': '学院品牌', 'logo': 'logo.svg', 'template': 'deck.pptx'}, {'schema_version': '2.1', 'meta': {'brand': '学院品牌', 'logo': 'logo.svg', 'template': 'deck.pptx'}}), [])
        self.assertTrue(handoff_errors({'brand': '学院品牌'}, {'schema_version': '2.1', 'meta': {'brand': '另一品牌'}}))
        planned = slide()
        self.assertTrue(content.check({"slides": [planned]}, ["国家奖学金 233"])["ok"])
        self.assertFalse(content.check({"slides": [planned]}, ["优秀奖励 233"])["ok"])

    def test_editorial_compression_and_exact_fidelity(self):
        spec = {"schema_version": "2.1", "slides": [slide()]}
        self.assertTrue(content.check(spec, ["科研机会抵达低年级；国家奖学金，233h"])["ok"])
        self.assertFalse(content.check(spec, ["科研机会抵达低年级；国家奖学金，1233h"])["ok"])
        self.assertEqual(missing_fragments(slide(), "科研机会国家奖学金233h"), [])

    def test_numeric_boundaries_and_chinese_adjacency(self):
        self.assertFalse(exact_present('233小时', '累计1233小时；参与233人'))
        self.assertFalse(exact_present('233小时', '累计3,233小时；参与233人'))
        self.assertTrue(exact_present('233小时', '时长,233小时'))
        self.assertTrue(exact_present('233小时', '12\n233\n小时'))
        self.assertEqual(numbers("志愿233小时，提升9分贝，完成1,233项，比例12.5%"), ["1,233", "12.5%", "233", "9"])
        for actual in ["1233", "2330", "233.1", "1,233", "-233", "+233"]:
            self.assertFalse(exact_present("233", actual))
        self.assertTrue(exact_present("9 分贝", "9\n分贝"))

    def test_independent_semantic_decision_binds_actual_location(self):
        spec = {"slides": [slide()]}
        actual = ["科研机会抵达低年级"]
        review = {"slides": [{"slide": 1, "semantic_coverage": [{"id": "research", "status": "covered", "placement": "slide", "actual_excerpt": actual[0]}]}]}
        self.assertEqual(semantic_review_issues(spec, review, actual, {}), [])
        self.assertTrue(semantic_review_issues(spec, review, ["完全不同的内容"], {}))
        self.assertTrue(semantic_review_issues(spec, {"slides": []}, actual, {}))
        review["slides"][0]["semantic_coverage"][0]["status"] = "contradicted"
        self.assertTrue(semantic_review_issues(spec, review, actual, {}))

    def test_schema_requires_semantics_without_migrating_legacy(self):
        self.assertEqual(validate_spec_data({"schema_version": "2.1", "slides": [slide()]}), [])
        old = {"schema_version": "2.0", "slides": [slide()]}
        self.assertTrue(validate_spec_data(old))
        self.assertTrue(validate_spec_data({"schema_version": "2.1", "slides": [{"id": 1, "title": "缺契约"}]}))


class DesignTests(unittest.TestCase):
    def test_defaults_and_independent_mode(self):
        self.assertEqual(design_mode({"schema_version": "2.1"}), "auto")
        self.assertEqual(design_mode({"schema_version": "2.0"}), "guided")
        self.assertEqual(design_mode({"meta": {"design_freedom": "deterministic", "quality_level": "rigorous"}}), "deterministic")

    def test_module_selfcheck_reads_positioned_spans_without_partial_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'pages').mkdir()
            tokens = {'model_led': True, 'design_freedom': 'auto', 'typography': {}, 'palette': {'canvas': 'FFFFFF', 'primary_text': '111111'}}
            (directory / 'deck.js').write_text('const TOKENS = ' + json.dumps(tokens) + ';', encoding='utf-8')
            page = directory / 'pages/p01-test.js'
            for actual, expected, passes in [('训练场次12，覆盖233人', '训练场次12，覆盖233人', True), ('累计3,233小时', '233小时', False)]:
                source = "module.exports=function(ctx){ctx.H.addFittedText(ctx.slide,ACTUAL,{x:1,y:1,w:4,h:1},ctx.tokens,'chinese','body',{fontSize:20,margin:0});};module.exports.slots={claim:EXPECTED};module.exports.presentation_copy={headline:ACTUAL,visual_labels:[ACTUAL]};module.exports.notes='演示说明';"
                page.write_text(source.replace('ACTUAL', json.dumps(actual)).replace('EXPECTED', json.dumps(expected)), encoding='utf-8')
                process = subprocess.run(['node', str(ROOT / 'scripts/check_page_module.js'), '--work-dir', str(directory), '--pages', 'pages/p01-test.js'], cwd=directory, capture_output=True, text=True, encoding='utf-8')
                report = json.loads(process.stdout)
                self.assertFalse(any(item['kind'] == 'throw' for item in report['findings']), process.stdout)
                missing = any(item['kind'] == 'slot-not-rendered' for item in report['findings'])
                self.assertEqual(missing, not passes, process.stdout)

    def node(self, body):
        process = subprocess.run(["node", "-e", body], cwd=ROOT, env=os.environ, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_guided_figure_preserves_actual_aspect_and_rejects_protected_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image

            figure = Path(tmp) / 'figure.png'
            Image.new('RGB', (1200, 300)).save(figure)
            result = self.node("""
const C=require('./scripts/pptx-composition.js');
const images=[];const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',surface:'FFFFFF',primary_text:'111111',secondary_text:'333333',primary_accent:'2255AA',secondary_accent:'777777'},visual_language:{}};
const ctx={slideNumber:1,lang:'chinese',tokens,slide:{addShape(){},addText(){},addImage(o){images.push(o);}}};
const visual={type:'image',asset:FIGURE,details:{image_width:999,image_height:999,preserve_region_x:0,preserve_region_y:0,preserve_region_w:1,preserve_region_h:1}};
C.renderMove(ctx,{move:'figure',slots:{visual}},{x:.6,y:1,w:10,h:4});
visual.details.crop={x:.2,y:0,w:.8,h:1};let rejected=false;
try{C.renderMove(ctx,{move:'figure',slots:{visual}},{x:.6,y:1,w:10,h:4});}catch(e){rejected=e.message.includes('asset_crop_invalid');}
process.stdout.write(JSON.stringify([images[0].w/images[0].h,rejected,images.length]));
""".replace('FIGURE', json.dumps(str(figure))))
        self.assertEqual(result, [4, True, 1])

    def test_guided_cover_balances_orphan_and_chinese_terms_stay_together(self):
        result = self.node("""
const C=require('./scripts/pptx-composition.js'),T=require('./scripts/pptx-text-layout.js');
const drawn=[];const tokens={model_led:true,typography:{stat_pt:60,body_font:'Calibri',cjk_body_font:'SimSun'},palette:{canvas:'FFFFFF',surface:'FFFFFF',primary_text:'111111',secondary_text:'333333',primary_accent:'2255AA',secondary_accent:'777777'},visual_language:{}};
const ctx={slideNumber:1,lang:'chinese',tokens,slide:{addShape(){},addText(t,o){drawn.push(o._textLayout?.lineGeometry);}}};
C.renderMove(ctx,{move:'thesis',slots:{claim:'合成论文 · 课堂演示',body:['不是真实发表结果']}},{x:.6,y:1,w:7.325,h:3.65});
const cover=drawn.find(lines=>lines?.some(line=>line.text.includes('合成'))).map(line=>line.text);
const text='示意流程依次包含查询、检索、重排、回答；见配图';
const narrow=T.layoutText(text,{x:0,y:0,w:1.95,h:4},{fontSize:20,fontFace:'Calibri',cjkFontFace:'SimSun'});
process.stdout.write(JSON.stringify([cover,narrow.lineGeometry.map(line=>line.text),narrow.fits]));
""")
        self.assertGreaterEqual(len(result[0][-1].strip()), 3)
        self.assertEqual(''.join(result[0]), '合成论文 · 课堂演示')
        self.assertTrue(result[2])
        for term in ('查询', '检索', '重排', '回答'):
            self.assertTrue(any(term in line for line in result[1]))

    def test_guided_fit_failure_does_not_silently_switch_to_template(self):
        result = self.node("""
const C=require('./scripts/pptx-composition.js'),L=require('./scripts/pptx-layouts.js');
let attempts=0;C.renderMove=()=>{attempts++;const e=new Error('metric geometry failed');e.layoutFit=true;throw e;};
const ctx={slide:{addShape(){},addText(){}},tokens:{model_led:true,palette:{canvas:'FFFFFF'},visual_language:{}}};
let failure='';try{L.renderDeclaredPage(ctx,{move:'metric',slots:{title:'数据',claim:'233'}});}catch(e){failure=e.message;}
process.stdout.write(JSON.stringify([attempts,failure]));
""")
        self.assertEqual(result, [1, 'metric geometry failed'])

    def test_signed_units_and_windows_explicit_newline(self):
        result = self.node("""
const T=require('./scripts/pptx-text-layout.js');
const text='降低-9 分贝，达到12.5％。\\r\\n保持3.14与1,233不变。';
const r=T.layoutText(text,{x:0,y:0,w:2,h:4},{fontSize:18,fontFace:'Arial',cjkFontFace:'Microsoft YaHei'});
process.stdout.write(JSON.stringify([r.lines,r.lineGeometry.map(l=>l.text),r.richText.map(run=>run.text).join('')]));
""")
        self.assertTrue(any('-9 分贝' in line for line in result[1]))
        self.assertTrue(any('12.5％' in line for line in result[1]))
        self.assertEqual(result[2], '降低-9 分贝，达到12.5％。保持3.14与1,233不变。')

    def test_units_punctuation_explicit_break_and_runs(self):
        result = self.node("""
const T = require('./scripts/pptx-text-layout.js');
const policy = {fontSize:18,fontFace:'Arial',cjkFontFace:'Microsoft YaHei'};
const inputs = ['提升9 分贝，效果明显。', '值为1,233与12.5%。', '首行\\n第二行', [{text:'强调',options:{bold:true}},{text:'9 分贝，与其他内容并排。'}]];
process.stdout.write(JSON.stringify(inputs.map(input => T.layoutText(input,{x:0,y:0,w:1.5,h:4},policy))));
""")
        self.assertTrue(all(item["fits"] for item in result))
        self.assertTrue(any("9 分贝" in line["text"] for line in result[0]["lineGeometry"]))
        self.assertEqual([line["text"] for line in result[2]["lineGeometry"]], ["首行", "第二行"])
        self.assertTrue(any(run["options"].get("bold") for run in result[3]["richText"]))
        for item in result:
            for line in item["lineGeometry"]:
                self.assertFalse(line["text"].startswith(("，", "。", "）")))

    def test_no_loss_duplicate_or_zero_width_character(self):
        result = self.node("""
const T=require('./scripts/pptx-text-layout.js');
const texts=['提升9 分贝（条件一致），达到12.5%。','1,233个样本，English words不能断开。','小数3.14与标点；最后一个字。'];
const results=texts.map(text=>T.layoutText(text,{x:0,y:0,w:2,h:4},{fontSize:18,fontFace:'Arial',cjkFontFace:'Microsoft YaHei'}));
process.stdout.write(JSON.stringify(results.map((r,i)=>[r.richText.map(run=>run.text).join('')===texts[i],r.richText.some(run=>/[\\u200b-\\u200d]/.test(run.text)),r.fits])));
""")
        self.assertEqual(result, [[True, False, True]] * 3)

    def test_count_units_remain_attached_across_rich_runs(self):
        result = self.node("""
const T=require('./scripts/pptx-text-layout.js');
const rich=[{text:'共计1,',options:{bold:true}},{text:'233个样本，小数3.14保持完整。'}];
const fit=T.layoutText(rich,{x:0,y:0,w:2.8,h:3},{fontSize:24,fontFace:'Calibri',cjkFontFace:'SimSun'});
process.stdout.write(JSON.stringify([fit.lineGeometry.map(line=>line.text),fit.richText.map(run=>run.text).join(''),fit.fits]));
""")
        self.assertTrue(result[2])
        self.assertTrue(any('1,233个' in line for line in result[0]))
        self.assertEqual(result[1], '共计1,233个样本，小数3.14保持完整。')

    def test_shared_harness_registers_free_elements_and_copy(self):
        result = self.node("""
const R=require('./scripts/pptx-page-runtime.js'),H=require('./scripts/pptx-helpers.js');
const {SlideElementRegistry}=require('./scripts/pptx-element-registry.js');
const notes=[];const slide={addText(){},addShape(){},addImage(){},addChart(){},addNotes(n){notes.push(n);}};
const ctx={slide,n:1,H,registry:new SlideElementRegistry(),presentationCopy:[],tokens:{model_led:true,design_freedom:'auto',typography:{},palette:{canvas:'FFFFFF',primary_text:'111111'}}};
const mod=c=>{c.slide.addText('国家奖学金233小时',{x:.5,y:.5,w:4,h:1,fontSize:8});c.slide.addShape('rect',{x:5,y:.5,w:1,h:1});c.slide.addImage({path:'certificate.png',x:7,y:.5,w:1,h:1});c.slide.addChart('bar',[],{x:.5,y:2,w:2,h:1});};
mod.presentation_copy={headline:'国家奖学金',visual_labels:['233小时']};mod.notes='补充解释';R.renderPage(ctx,mod);
process.stdout.write(JSON.stringify([ctx.registry._slide(1).filter(e=>e.type!=='text').map(e=>e.type),ctx.presentationCopy[0].text_runs.join(''),notes,ctx.registry.analyzeDeck().ok]));
""")
        self.assertEqual(result, [["shape", "image", "chart"], "国家奖学金233小时", ["补充解释"], True])

    def test_protected_asset_and_invalid_run_size_fail(self):
        result = self.node("""
const H=require('./scripts/pptx-helpers.js'),T=require('./scripts/pptx-text-layout.js');let failures=[];
try{H.addPlannedImage({addImage(){}},{path:'figure.png',width:1200,height:300,preserve_region:{x:0,y:0,w:1,h:1},crop:{x:.2,y:0,w:.8,h:1}},{x:0,y:0,w:4,h:2});}catch(e){failures.push(e.message.includes('asset_crop_invalid'));}
try{T.layoutText([{text:'无效字号',options:{fontSize:0}}],{x:0,y:0,w:2,h:1},{fontSize:18,fontFace:'Arial'});}catch(e){failures.push(e.message.includes('positive'));}
process.stdout.write(JSON.stringify(failures));
""")
        self.assertEqual(result, [True, True])

    def test_positioned_alignment_table_and_explicit_rich_font(self):
        result = self.node("""
const H=require('./scripts/pptx-helpers.js'),R=require('./scripts/pptx-page-runtime.js'),T=require('./scripts/pptx-text-layout.js');
const {SlideElementRegistry}=require('./scripts/pptx-element-registry.js');
const drawn=[];const slide={addText(t,o){drawn.push(o);},addShape(){},addNotes(){},addTable(){throw new Error('unmeasured table');}};
const tokens={model_led:true,typography:{},palette:{canvas:'FFFFFF',primary_text:'111111',secondary_text:'555555'}};
const ctx={slide,n:1,H,tokens,registry:new SlideElementRegistry(),presentationCopy:[]};
const mod=c=>{const fit=H.addPositionedText(slide,'9 分贝',{x:.5,y:.5,w:3,h:1},tokens,'chinese','body',{fontSize:18,align:'center',margin:0});c.firstX=fit.lineGeometry[0].x;slide.addTable([['数据','233']],{x:.5,y:2,w:4,h:1,fontSize:18,margin:0});};
mod.presentation_copy={headline:'9 分贝',visual_labels:['数据','233']};R.renderPage(ctx,mod);
const rich=T.layoutText([{text:'中文强调',options:{fontFace:'KaiTi',bold:true}}],{x:0,y:0,w:3,h:1},{fontSize:18,fontFace:'Arial',cjkFontFace:'Microsoft YaHei'});
process.stdout.write(JSON.stringify([Math.abs(drawn[0].x-ctx.firstX)<1e-6,ctx.registry._slide(1).filter(e=>e.type==='text').map(e=>e.text).join(''),rich.richText.every(run=>run.options.fontFace==='KaiTi')]));
""")
        self.assertEqual(result[:2], [True, '9 分贝数据233'])
        if os.name == 'nt':
            self.assertTrue(result[2])

    def test_no_product_font_floor_and_real_overflow(self):
        result = self.node("""
const H=require('./scripts/pptx-helpers.js');
const tokens={model_led:true,typography:{},palette:{primary_text:'111111'}};
const policy=H.rolePolicy(tokens,'chinese','body',{fontSize:8});
process.stdout.write(JSON.stringify([policy.min,H.fitText('小字仍可编辑',{x:0,y:0,w:2,h:1},policy).fits,H.fitText('装不下的内容',{x:0,y:0,w:.01,h:.01},policy).fits]));
""")
        self.assertEqual(result, [8, True, False])


if __name__ == "__main__":
    unittest.main()
