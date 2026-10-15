"""Preset colors, editable information fidelity and configurable composition."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.design_tokens import resolve_design_tokens  # noqa: E402


class PresetQualityTests(unittest.TestCase):
    def node(self, body):
        tokens = resolve_design_tokens("Creative Student")
        tokens["model_led"] = True
        code = "const H=require('./scripts/pptx-helpers.js'),V=require('./scripts/pptx-visuals.js'),C=require('./scripts/pptx-composition.js');"
        code += "const tokens=" + json.dumps(tokens) + ";"
        code += "const calls=[];const slide={addText(t,o){calls.push({type:'text',text:H.plainText(t),options:o});},addShape(t,o){calls.push({type:'shape',shape:t,options:o});},addImage(o){calls.push({type:'image',options:o});},addChart(t,d,o){calls.push({type:'chart',options:o});}};const area={x:.5,y:1,w:9,h:4};"
        result = subprocess.run(["node", "-e", code + body], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_new_source_contains_no_legacy_layout_or_size_inputs(self):
        import importlib.util

        from shared.design_tokens import authoring_tokens
        module_path=ROOT/'skills/sp-deck/scripts/generator_scaffold.py'
        loader=importlib.util.spec_from_file_location('unrestricted_scaffold',module_path)
        module=importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        for mode in ('auto','guided','deterministic'):
            tokens=json.loads(module.inline_tokens_json({'schema_version':'2.1','meta':{'visual_style':'Academic Rigorous','design_freedom':mode}},None))
            for key in ('geometry','lines','effects','backgrounds','background_directives','visual_language','svg_reference'):
                self.assertNotIn(key,tokens)
            self.assertTrue(all(key.endswith('_font') for key in tokens['typography']))
            import tempfile

            with tempfile.TemporaryDirectory() as temp:
                work=Path(temp)
                spec={'schema_version':'2.1','meta':{'visual_style':'Academic Rigorous','design_freedom':mode},
                      'slides':[{'id':1,'title':'Topic','slide_copy':['Supporting detail preserved'],
                                 'speaker_notes':'Explanation preserved'}]}
                source=work/'spec.json'
                source.write_text(json.dumps(spec),encoding='utf-8')
                module.scaffold_generator(work,source)
                page=next((work/'pages').glob('*.js')).read_text(encoding='utf-8')
                self.assertIn('module.exports = function',page)
                self.assertIn('Supporting detail preserved',page)
                self.assertIn('Explanation preserved',page)
                self.assertNotIn('move:',page)
        from unittest.mock import patch

        with patch('shared.design_tokens.LEGACY_TOKEN_FILE',ROOT/'missing-legacy.json'):
            resolve_design_tokens('Academic Rigorous',authoring=True)
        clean=authoring_tokens(resolve_design_tokens('Academic Rigorous'),{'body_pt':13})
        self.assertEqual(clean['typography']['body_pt'],13)
        catalog=json.loads((ROOT/'references/design-tokens.json').read_text(encoding='utf-8'))
        self.assertNotIn('defaults',catalog)

    def test_all_modes_accept_free_functions_without_automatic_paint_or_zones(self):
        out=self.node("const R=require('./scripts/pptx-page-runtime.js'),Registry=require('./scripts/pptx-element-registry.js').SlideElementRegistry;slide.addNotes=()=>{};const results=[];for(const mode of ['auto','guided','deterministic']){calls.length=0;const mod=()=>slide.addShape('rect',{x:.5,y:.5,w:.3,h:.3,fill:{color:'2563EB'}});mod.kind='cover';mod.presentation_copy={headline:'Authored'};const registry=new Registry();R.renderPage({slide,tokens,registry,n:1,presentationCopy:[],designMode:mode},mod);results.push(calls.length);}console.log(JSON.stringify([results,H.contentArea(tokens,'cover'),H.safeArea(10,5.625,tokens,{reserveTitle:true})]));")
        self.assertEqual(out[0],[1,1,1])
        self.assertEqual(out[1],{'x':0,'y':0,'w':10,'h':5.625})
        self.assertEqual(out[2],out[1])

    def test_captured_background_order_and_removal_of_design_grammar(self):
        out=self.node("const Registry=require('./scripts/pptx-element-registry.js').SlideElementRegistry;function check(front){const r=new Registry({capture:true,designPreferencesAdvisory:true});const rect={type:'shape',x:.1,y:.1,w:4,h:2,fill:{color:'FFFFFF'}};const text={type:'text',text:'Visible',x:.2,y:.2,w:2,h:.5,fontSize:14};r.register(1,front?text:rect);r.register(1,front?rect:text);return r.analyzeDeck();}console.log(JSON.stringify([check(false),check(true)]));")
        self.assertTrue(out[0]['ok'])
        self.assertFalse(out[1]['ok'])
        self.assertIn('text_overlap',[x['code'] for x in out[1]['errors']])
        self.assertFalse(any(x['code'] in ('near_miss_alignment','decorative_stripe','dead_zone') for x in out[0]['warnings']))

    def test_presets_have_available_group_colors_and_overridable_type(self):
        styles = json.loads((ROOT / "references/design-tokens.json").read_text())["styles"]
        for style in styles.values():
            tokens = resolve_design_tokens(style["name"])
            colors = [v for k, v in tokens["palette"].items() if k.startswith("category_")]
            self.assertEqual(len(set(colors)), 4)
            self.assertTrue(set(tokens["palette"]).issubset(tokens["dark_palette"]))
        out = self.node("const p=H.rolePolicy(tokens,'chinese','body',{fontSize:13});console.log(JSON.stringify([p.fontSize,H.categoryColors(tokens,['123456','654321'])]));")
        self.assertEqual(out, [13, ["123456", "654321"]])

    def test_summary_and_comparison_preserve_all_labels_and_details(self):
        out = self.node("V.addSummary(slide,{items:Array.from({length:7},(_,i)=>({label:'Group '+i,detail:'Evidence '+i}))},area,tokens,'english');const summary=calls.filter(x=>x.type==='text').map(x=>x.text);calls.length=0;V.addComparison(slide,{items:[{label:'A',points:['Detail A']},{label:'B',points:['Detail B']},{label:'C',points:['Detail C']}]},area,tokens,'english');console.log(JSON.stringify([summary,calls.filter(x=>x.type==='text').map(x=>x.text)]));")
        for i in range(7):
            self.assertIn('Group '+str(i), out[0])
            self.assertIn('Evidence '+str(i), out[0])
        for label in ['Detail A','Detail B','Detail C']:
            self.assertIn(label, out[1])

    def test_annotation_does_not_truncate_after_third_item(self):
        out = self.node("V.addAnnotatedVisual(slide,{title:'Diagram',annotations:Array.from({length:5},(_,i)=>'Note '+i)},{...area,h:5},tokens,'english');console.log(JSON.stringify(calls.filter(x=>x.type==='text').map(x=>x.text)));")
        self.assertIn('Note 4', out)

    def test_chart_and_matrix_use_category_colors(self):
        out = self.node("V.addChartWithTakeaway(slide,{kind:'bar',takeaway:'Synthetic example',series:[{name:'Count',labels:['A','B','C','D','E'],values:[1,2,3,4,5]}]},area,tokens,'english');console.log(JSON.stringify(calls.find(x=>x.type==='chart').options.chartColors));")
        self.assertEqual(len(set(out)), 5)

    def test_background_can_be_enabled_or_disabled(self):
        out = self.node("H.renderBackground(slide,tokens,{kind:'cover'});const enabled=calls.length;calls.length=0;H.renderBackground(slide,tokens,{kind:'cover',motif:true});const explicit=calls.length;calls.length=0;H.renderBackground(slide,tokens,{kind:'cover',decorations:false});console.log(JSON.stringify([enabled,calls.length,explicit]));")
        self.assertGreater(out[0], 0)
        self.assertEqual(out[1], 0)
        self.assertGreater(out[2],out[0])

    def test_figure_accepts_smaller_visual_and_thesis_keeps_supports(self):
        out = self.node("C.renderMove({slide,tokens,lang:'english',slideNumber:1},{move:'figure',params:{primaryShare:.3},slots:{visual:{type:'comparison',details:{items:[{label:'A'},{label:'B'}]}}}},area);calls.length=0;C.renderMove({slide,tokens,lang:'english',slideNumber:1},{move:'thesis',slots:{claim:'Core',body:['Evidence one','Evidence two','Evidence three']}},area);console.log(JSON.stringify(calls.filter(x=>x.type==='text').map(x=>x.text)));")
        self.assertTrue(any('Evidence three' in text for text in out))

    def test_six_step_sequence_and_two_stage_timeline_are_not_count_blocked(self):
        out = self.node("C.renderMove({slide,tokens,lang:'english',slideNumber:1},{move:'sequence',slots:{title:'Process',body:['One','Two','Three','Four','Five','Six']}},area);const labels=calls.filter(x=>x.type==='text').map(x=>x.text);calls.length=0;V.addTimeline(slide,{stages:['Prepare','Deliver']},area,tokens,'english');console.log(JSON.stringify([labels,calls.filter(x=>x.type==='text').map(x=>x.text)]));")
        self.assertTrue(any('Six' in text for text in out[0]))
        self.assertIn('Process',out[0])
        self.assertIn('Deliver',out[1])

    def test_sequence_claim_and_key_line_are_not_silently_dropped(self):
        out = self.node("C.renderMove({slide,tokens,lang:'english',slideNumber:1},{move:'sequence',slots:{title:'Process',claim:'Distinct conclusion',body:['One','Two','Three']}},area);console.log(JSON.stringify(calls.filter(x=>x.type==='text').map(x=>x.text)));")
        self.assertIn('Distinct conclusion',out)
        out = self.node("let failed=false;try{C.renderMove({slide,tokens,lang:'english',slideNumber:1},{move:'thesis',slots:{claim:'Core',key_line:'Very long conclusion '.repeat(100)}},area);}catch(e){failed=true;}console.log(JSON.stringify(failed));")
        self.assertTrue(out)

    def test_styled_tables_preserve_zero_and_honor_type_and_alignment(self):
        out = self.node("V.addStyledTable(slide,{columns:['Category','Count'],rows:[['Alpha',0],['Beta',12]],font_size:13,header_font_size:14},area,tokens,'english');console.log(JSON.stringify(calls.filter(x=>x.type==='text').map(x=>[x.text,x.options.fontSize,x.options.align])));")
        self.assertIn(['0',13,'right'],out)
        self.assertIn(['Category',14,'left'],out)
        self.assertEqual(len(out),6)
        values=self.node("V.addMetricDashboard(slide,{metrics:[0,12]},area,tokens,'english');console.log(JSON.stringify(calls.filter(x=>x.type==='text').map(x=>x.text)));")
        self.assertIn('0',values)

    def test_runtime_table_uses_header_banding_and_keeps_cell_values(self):
        out = self.node("const R=require('./scripts/pptx-page-runtime.js');slide.addTable=()=>{};const registry={register(){}};R.captureSlide({slide,tokens,registry,n:1});slide.addTable([[{text:'Group',options:{bold:true}},'Value'],['Alpha',0],['Beta',12]],{x:.5,y:1,w:9,h:3,colW:[6,3],rowH:1,fontSize:13});console.log(JSON.stringify([calls.filter(x=>x.type==='text').map(x=>[x.text,x.options.align]),calls.filter(x=>x.type==='shape'&&x.shape==='rect').map(x=>x.options)]));")
        self.assertIn(['0','right'],out[0])
        self.assertEqual(out[1][0]['fill']['color'],'C4510B')
        self.assertEqual(out[1][0]['line']['type'],'none')
        self.assertNotEqual(out[1][2]['fill'],out[1][4]['fill'])

    def test_display_language_policy_and_examples_do_not_embed_delivery_caveats(self):
        policy=(ROOT/'references/shared-standards.md').read_text(encoding='utf-8')
        self.assertIn('Audience-facing Content — Required',policy)
        self.assertIn('交付对话或独立质量报告',policy)
        preview=(ROOT/'scripts/style_preview_deck.js').read_text(encoding='utf-8')
        self.assertNotIn('不能推导真实课程成效',preview)
        self.assertNotIn('此图仅用于',preview)

    def test_guided_runtime_does_not_register_phantom_visual_occluder(self):
        out=self.node("const R=require('./scripts/pptx-page-runtime.js'),Registry=require('./scripts/pptx-element-registry.js').SlideElementRegistry;slide.addNotes=()=>{};const registry=new Registry({slideW:10,slideH:5.625});tokens.design_freedom='guided';R.renderPage({slide,tokens,registry,n:1,slideNumber:1,lang:'english',presentationCopy:[]},{kind:'content',move:'proof',slots:{title:'Findings',claim:'Counts',visual:{type:'table',details:{columns:['Group','Count'],rows:[['A',0],['B',12]],font_size:13}}},notes:'Records'});console.log(JSON.stringify(registry.analyzeDeck()));")
        self.assertTrue(out['ok'],out['errors'])

    def test_research_schemas_do_not_require_budget_metadata(self):
        for name in ['research-task.schema.json','research-pack.schema.json']:
            schema=json.loads((ROOT/'references'/name).read_text(encoding='utf-8'))
            self.assertNotIn('budget',schema['required'])

    def test_real_overflow_and_invalid_share_still_fail(self):
        out = self.node("let badShare=false,overflow=false;try{C.renderMove({slide,tokens,lang:'english'}, {move:'figure',params:{primaryShare:0},slots:{visual:{type:'comparison',details:{items:['A','B']}}}},area);}catch(e){badShare=e.message.includes('primaryShare');}try{V.addSummary(slide,{items:[{label:'Title',detail:'Long evidence '.repeat(500)}]},area,tokens,'english');}catch(e){overflow=e.message.includes('overflow')||e.message.includes('fit');}console.log(JSON.stringify([badShare,overflow]));")
        self.assertEqual(out, [True, True])


if __name__ == '__main__':
    unittest.main()
