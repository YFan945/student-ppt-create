"""Resolve actual packages, then load them from an unrelated production child."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / 'scripts' / 'pptx-runtime-paths.js'


class ResolutionTests(unittest.TestCase):
    def test_mixed_size_units_share_measured_baseline_and_accurate_geometry(self):
        code = """
const H=require(process.argv[2]+'/scripts/pptx-helpers.js'),T=require(process.argv[2]+'/scripts/pptx-text-layout.js');
const tokens={model_led:true,typography:{cjk_body_font:'DengXian',body_font:'Calibri'}};
const calls=[];const slide={addText:(text,options)=>calls.push({text,...options})};
H.addPositionedText(slide,[{text:'12',options:{fontSize:46,bold:true}},{text:' 场',options:{fontSize:15}}],
 {x:0,y:0,w:4,h:1},tokens,'chinese','body',{fontSize:46,color:'111827'});
calls.forEach(c=>{const f=T.resolveFont(c.fontFace,Boolean(c.bold),Boolean(c.italic));c.baseline=c.y+f.ascent/f.unitsPerEm*c.fontSize/72;});
console.log(JSON.stringify(calls));
"""
        calls = self.run_node(code, ROOT, cwd=ROOT)
        value = next(item for item in calls if item['text'] == '12')
        unit = next(item for item in calls if '场' in item['text'])
        self.assertGreater(unit['y'], value['y'])
        self.assertAlmostEqual(unit['baseline'], value['baseline'])
        self.assertEqual(unit['_textLayout']['lineGeometry'][0]['y'], unit['y'])
        self.assertEqual(unit['logicalBox'], value['logicalBox'])

    def test_runtime_rejects_no_draw_function_even_when_it_has_metadata(self):
        code = """
const R=require(process.argv[2]+'/scripts/pptx-page-runtime.js');
const {SlideElementRegistry}=require(process.argv[2]+'/scripts/pptx-element-registry.js');
const page=()=>{};page.presentation_copy={headline:'fake',visual_labels:[]};page.notes='notes';
let message='';try{R.renderPage({n:1,tokens:{model_led:true},registry:new SlideElementRegistry(),slide:{addNotes:()=>{}}},page);}catch(e){message=e.message;}
console.log(JSON.stringify({message}));
"""
        result = self.run_node(code, ROOT, cwd=ROOT)
        self.assertIn('no drawable objects', result['message'])

    def package(self, root, name, value):
        package = root / 'node_modules' / name
        package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'name': name, 'version': '1.0.0', 'main': 'index.js'}))
        (package / 'index.js').write_text('module.exports=' + json.dumps(value) + ';')

    def run_node(self, code, *args, cwd):
        env = dict(os.environ)
        env.pop('NODE_PATH', None)
        result = subprocess.run(['node', '-e', code, str(RESOLVER), *map(str, args)], cwd=cwd, env=env,
                                capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_ancestor_install_resolves_actual_search_root_for_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plugin = base / 'cache' / 'plugin'
            plugin.mkdir(parents=True)
            project = base / 'unrelated' / 'project'
            project.mkdir(parents=True)
            self.package(base / 'cache', 'fixture-runtime', 'loaded')
            data = self.run_node("""
const R=require(process.argv[1]),cp=require('node:child_process');
const result=R.resolveModule('fixture-runtime',process.argv[2],process.argv[3]);
R.installSearchPaths([result]);
const child=cp.spawnSync(process.execPath,['-e',"console.log(JSON.stringify(require('fixture-runtime')))"],
 {cwd:process.argv[2],env:process.env,encoding:'utf8'});
console.log(JSON.stringify({...result,childStatus:child.status,childValue:JSON.parse(child.stdout)}));
""", project, plugin, cwd=project)
            self.assertEqual(data['source'], 'plugin')
            self.assertEqual(Path(data['moduleRoot']), base / 'cache' / 'node_modules')
            self.assertEqual(data['childStatus'], 0)
            self.assertEqual(data['childValue'], 'loaded')

    def test_project_install_precedes_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project, plugin = base / 'project', base / 'plugin'
            self.package(project, 'fixture-runtime', 'project')
            self.package(plugin, 'fixture-runtime', 'plugin')
            result = self.run_node("const R=require(process.argv[1]);console.log(JSON.stringify(R.resolveModule('fixture-runtime',process.argv[2],process.argv[3])));",
                                   project, plugin, cwd=project)
            self.assertEqual(result['source'], 'project')
            self.assertEqual(Path(result['moduleRoot']), project / 'node_modules')

    def test_chinese_quote_face_matches_context_and_inline_emphasis_survives(self):
        code = """
const H=require(process.argv[2]+'/scripts/pptx-helpers.js');
const tokens={model_led:true,typography:{cjk_body_font:'DengXian',body_font:'Calibri'}};
const text=[{text:'“科研机会”'},{text:'重点',options:{bold:true,color:'2563EB'}}];
const result=H.fitText(text,{x:0,y:0,w:8,h:1},H.rolePolicy(tokens,'chinese','body',{fontSize:24}));
console.log(JSON.stringify(result.richText));
"""
        result = self.run_node(code, ROOT, cwd=ROOT)
        self.assertEqual({item['options']['fontFace'] for item in result}, {'DengXian'})
        self.assertTrue(any(item['options'].get('bold') and item['options'].get('color') == '2563EB' for item in result))

    def test_filtered_help_gives_usage_and_example(self):
        result = subprocess.run(['node', str(ROOT / 'scripts/pptx-helpers.js'), '--describe', '--function', 'addFittedText'],
                                capture_output=True, text=True, encoding='utf-8', check=True)
        data = json.loads(result.stdout)
        self.assertEqual(len(data['entries']), 1)
        self.assertIn('Returns the slide', data['entries'][0]['description'])
        self.assertIn('fontSize', data['entries'][0]['example'])
