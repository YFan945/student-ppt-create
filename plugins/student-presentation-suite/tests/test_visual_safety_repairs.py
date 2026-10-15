"""Regression cases from the visual audit: paint order, contrast and metric identity."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'skills/sp-deck/scripts')]
import pptx_actual_content_check as content  # noqa: E402

from shared.content_requirements import fact_binding_present  # noqa: E402
from shared.pptx_text_readback import fact_blocks  # noqa: E402
from shared.slide_spec_contract import validate_spec_data  # noqa: E402


class VisualSafetyTests(unittest.TestCase):
    def registry(self, statements):
        source = "const {SlideElementRegistry}=require(process.argv[1]); const r=new SlideElementRegistry({capture:true,designPreferencesAdvisory:true});" + statements + ';console.log(JSON.stringify(r.analyzeDeck()));'
        process = subprocess.run(['node', '-e', source, str(ROOT / 'scripts/pptx-element-registry.js')], capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(process.stdout)

    def test_decorative_foreground_cannot_hide_text(self):
        for flag in ('decorative:true', 'allowOverlap:true'):
            report = self.registry("r.text(1,'fact',{x:1,y:1,w:2,h:1,fontSize:20});" + f"r.shape(1,{{x:.9,y:.9,w:2.2,h:1.2,fill:{{color:'FFFFFF'}},{flag}}});")
            self.assertFalse(report['ok'])
            self.assertIn('text_overlap', [item['code'] for item in report['errors']])

    def test_background_and_transparent_foreground_are_allowed(self):
        report = self.registry("r.shape(1,{x:.9,y:.9,w:2.2,h:1.2,fill:{color:'FFFFFF'},decorative:true});r.text(1,'fact',{x:1,y:1,w:2,h:1,fontSize:20});r.shape(1,{x:.9,y:.9,w:2.2,h:1.2,fill:{color:'FFFFFF',transparency:100},decorative:true});")
        self.assertTrue(report['ok'])

    def test_solid_contrast_uses_top_surface_and_rich_run_colors(self):
        base = "r.backgrounds.set(1,{color:'000000'});r.shape(1,{shapeType:'rect',x:0,y:0,w:10,h:5.625,fill:{color:'FFFFFF'}});"
        failed = self.registry(base + "r.text(1,'fact',{x:1,y:1,w:2,h:1,fontSize:20,textColors:['000000','FFFFFF']});")
        self.assertIn('text_low_contrast', [item['code'] for item in failed['errors']])
        passed = self.registry(base + "r.text(1,'fact',{x:1,y:1,w:2,h:1,fontSize:20,color:'111111'});")
        self.assertTrue(passed['ok'])
        self.assertEqual(passed['slides'][0]['contrast']['checked'], 1)

    def test_image_partial_and_translucent_backgrounds_are_unresolved(self):
        for surface in ("r.image(1,{x:0,y:0,w:10,h:5.625});", "r.shape(1,{shapeType:'rect',x:1,y:1,w:1,h:1,fill:{color:'FFFFFF'}});", "r.shape(1,{shapeType:'rect',x:0,y:0,w:10,h:5.625,fill:{color:'FFFFFF',transparency:40}});"):
            report = self.registry("r.backgrounds.set(1,{color:'000000'});" + surface + "r.text(1,'fact',{x:1,y:1,w:2,h:1,fontSize:20,color:'000000'});")
            self.assertEqual(report['slides'][0]['contrast']['unresolved'], 1)
            self.assertNotIn('text_low_contrast', [item['code'] for item in report['errors']])


class FactBindingTests(unittest.TestCase):
    def spec(self):
        return {'schema_version': '2.1', 'research_scope': 'C', 'meta': {'topic': '合成测试', 'language': 'Chinese', 'slide_count': 1, 'duration_min': 1}, 'slides': [{'id': 1, 'title': '合成数据', 'content': ['参与人数233人，训练人数86人'], 'timing_sec': 60, 'owner': 'Individual', 'semantic_requirements': {'must_convey': [{'id': 'n', 'text': '参与人数233人，训练人数86人'}], 'must_show_exact': ['233', '86'], 'fact_bindings': [{'id': 'participants', 'label': '参与人数', 'value': '233', 'unit': '人'}, {'id': 'trained', 'label': '训练人数', 'value': '86', 'unit': '人'}]}}]}

    def test_swapped_metrics_and_wrong_units_fail(self):
        spec = self.spec()
        self.assertTrue(content.check(spec, ['参与人数：233人，训练人数86人'])['ok'])
        for text in ('参与人数86人，训练人数233人', '参与人数233小时，训练人数86人', '参与人数1233人，训练人数86人'):
            self.assertFalse(content.check(spec, [text])['ok'])

    def test_fact_cannot_be_assembled_from_unrelated_boxes(self):
        fact = self.spec()['slides'][0]['semantic_requirements']['fact_bindings'][0]
        self.assertFalse(fact_binding_present(fact, ['参与人数', '233人']))
        self.assertTrue(fact_binding_present(fact, ['参与人数\n233人']))
        self.assertTrue(fact_binding_present(fact, ['233人\n参与人数']))
        fact['context'] = '2026年'
        self.assertFalse(fact_binding_present(fact, ['参与人数233人', '2026年']))
        self.assertTrue(fact_binding_present(fact, ['2026年参与人数233人']))

    def test_real_ooxml_blocks_preserve_text_object_boundaries(self):
        xml = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>{}</p:spTree></p:cSld></p:sld>'
        def shape(paragraphs):
            return '<p:sp><p:txBody>' + ''.join('<a:p><a:r><a:t>' + text + '</a:t></a:r></a:p>' for text in paragraphs) + '</p:txBody></p:sp>'
        fact = self.spec()['slides'][0]['semantic_requirements']['fact_bindings'][0]
        separate = ET.fromstring(xml.format(shape(['参与人数']) + shape(['233人'])))
        together = ET.fromstring(xml.format(shape(['参与人数', '233人'])))
        self.assertFalse(fact_binding_present(fact, fact_blocks(separate)))
        self.assertTrue(fact_binding_present(fact, fact_blocks(together)))

    def test_schema_and_scaffold_requirements_keep_bindings(self):
        spec = self.spec()
        self.assertEqual(validate_spec_data(spec), [])
        self.assertEqual(content.planned_requirements(spec['slides'][0])['fact_bindings'], spec['slides'][0]['semantic_requirements']['fact_bindings'])
        spec['slides'][0]['semantic_requirements']['fact_bindings'][0]['value'] = 'many'
        self.assertTrue(validate_spec_data(spec))
