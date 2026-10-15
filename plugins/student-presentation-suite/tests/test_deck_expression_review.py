"""Actual usage/copy advisories and editable prompt placeholders, without editing decks."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from shared.asset_contract import validate_assets
from shared.deck_expression_review import review_expression

ROOT = Path(__file__).resolve().parents[1]


class ExpressionReviewTests(unittest.TestCase):
    def test_reused_icon_and_actual_body_notes_are_reported_without_gate(self):
        actual = {"slides": [
            {"slide": 1, "text_runs": ["这不是资料堆积，而是知识组织"], "speaker_notes": "此图仅供参考",
             "visual_usage": [{"kind": "icon", "key": "paper", "box": {"x": 1}}]},
            {"slide": 2, "text_runs": ["有依据的解释"], "visual_usage": [{"kind": "icon", "key": "paper"}]},
        ]}
        result = review_expression({"slides": [{}, {}]}, actual)
        codes = {item['code'] for item in result['findings']}
        self.assertEqual(codes, {'reused_icon', 'defensive_contrast', 'defensive_disclaimer'})
        self.assertEqual(next(item['slides'] for item in result['findings'] if item['code'] == 'reused_icon'), [1, 2])
        self.assertNotIn('ok', result)

    def test_frozen_quotation_is_preserved_and_unregistered_icons_are_not_claimed_absent(self):
        quote = '不是全部，而是部分'
        spec = {'slides': [{'semantic_requirements': {'must_show_exact': [quote]}}]}
        result = review_expression(spec, {'slides': [{'text_runs': [quote, '样本覆盖三个班级'], 'speaker_notes': '方法及条件'}]})
        self.assertFalse(result['findings'])
        self.assertIn('未登记', result['limitation'])

    def node(self, code):
        result = subprocess.run(['node', '-e', code, str(ROOT)], cwd=ROOT, capture_output=True,
                                text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def test_registered_glyph_usage_reaches_runtime_presentation_copy(self):
        result = self.node("""
const root=process.argv[1];
const R=require(root+'/scripts/pptx-page-runtime.js');
const {SlideElementRegistry}=require(root+'/scripts/pptx-element-registry.js');
const {subjectIcon}=require(root+'/examples/main-session-visuals/subject-visuals.js');
const page=ctx=>subjectIcon(ctx,'information',{x:1,y:1,w:1,h:1},'2563EB');
page.presentation_copy={headline:'信息'};
const ctx={n:1,tokens:{model_led:true},registry:new SlideElementRegistry(),
  slide:{addShape:()=>{},addNotes:()=>{}},presentationCopy:[]};
R.renderPage(ctx,page);
console.log(JSON.stringify(ctx.presentationCopy[0].visual_usage));
""")
        self.assertEqual(result[0]['key'], 'example:subject:information')
        self.assertEqual(result[0]['box'], {'x': 1, 'y': 1, 'w': 1, 'h': 1})

    def test_prompt_placeholder_writes_full_prompt_and_returns_valid_asset_record(self):
        result = self.node("""
const {promptPlaceholder}=require(process.argv[1]+'/examples/main-session-visuals/rich-pages.js');
const lines=[];
const ctx={n:1,slide:{addShape:()=>{}},tokens:{palette:{surface:'FFFFFF',primary_accent:'2563EB',secondary_text:'4B5563'}},
  H:{addFittedText:(_slide,text)=>lines.push(text)}};
const record=promptPlaceholder(ctx,{prompt:'蓝白配色的资料整理概念插画，右侧留白，无文字',replacement:'资料整理概念图',reason:'图片待生成'},
 {x:1,y:1,w:5,h:3});
console.log(JSON.stringify({record,text:lines.join('\\n')}));
""")
        record = result['record']
        self.assertIn(record['prompt'], result['text'])
        manifest = {'deck': 'test', 'placeholder_policy': 'allow', 'assets': [record]}
        self.assertTrue(validate_assets(manifest, ROOT, [result['text']])['ok'])
        self.assertFalse(validate_assets(manifest, ROOT, ['素材待替换'])['ok'])
        record['prompt'] = ' '
        self.assertFalse(validate_assets(manifest, ROOT, ['素材待替换'])['ok'])
