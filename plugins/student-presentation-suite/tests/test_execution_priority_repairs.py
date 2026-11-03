"""Real regressions from the November research/preview failure, not score forms."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import test_direct_production as fixtures
from test_helpers import load_module

from shared.rendered_layout import inspect_boxes
from shared.research_evidence import evidence_issues
from shared.research_validation import validate_current

ROOT = Path(__file__).resolve().parents[1]
production = fixtures.production
validator = load_module(ROOT / "scripts/validate_research_pack.py")
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


def pack():
    return {"version": "0.10", "topic": "能源比较", "evidence_contract": "source-backed-v1", "findings": [],
        "sources": [{"id": "S01", "title": "官方原始表", "url": "https://example.org/table"}],
        "data_points": [{"id": "D01", "value": "2,383.2 GW", "meaning": "全球光伏装机",
            "confidence": "high", "source_ids": ["S01"]}],
        "evidence": [{"entity_id": "D01", "source_id": "S01", "excerpt": "World 2 383 162", "locator": "表4，单位MW"}]}


class ResearchPriorityTests(unittest.TestCase):
    def test_source_references_need_no_duplicate_binding_table(self):
        data = pack()
        data.pop('evidence')
        report = validator.validate(data)
        self.assertTrue(report['ok'], report['problems'])
        data['evidence'] = [{'entity_id': 'D01', 'source_id': 'S01'}]
        self.assertTrue(validator.validate(data)['ok'])
        data['data_points'][0]['source_ids'] = ['MISSING']
        self.assertFalse(validator.validate(data)['ok'])
    def test_single_primary_source_does_not_trigger_source_collection(self):
        report = validator.validate(pack())
        self.assertTrue(report["ok"], report["problems"])
        self.assertNotIn("high_confidence_needs_cross_check", [p["code"] for p in report["problems"]])

    def test_table_conversion_and_multiple_operands_need_no_literal_binder(self):
        data = pack()
        entity = data["data_points"][0]
        entity.update(source_value="2 383 162 MW", transformation="MW除以1000，保留一位小数")
        self.assertEqual(evidence_issues(data, None, None), [])
        entity.update(value="17", source_value="820、48", transformation="820 / 48，约17倍")
        data["evidence"][0]["excerpt"] = "煤电820；光伏48；单位见表头。"
        self.assertEqual(evidence_issues(data, None, None), [])
        entity["support_check"] = {"verdict": "unsupported"}
        self.assertIn("evidence_support_review_rejected", [p["code"] for p in evidence_issues(data, None, None)])

    def test_unused_candidate_does_not_block_adopted_evidence_or_poison_full_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research-pack.json"
            data = pack()
            data["quotes"] = [{"id": "Q01", "text": "尚未采用的引文", "source_id": "S01"}]
            data['evidence'].append({'entity_id': 'Q01', 'source_id': 'S01', 'excerpt': '另一段文字'})
            production.write(path, data)
            _, whole = validate_current(path, validator=validator)
            self.assertFalse(whole["ok"])
            _, adopted = validate_current(path, validator=validator, used_entities={"D01"})
            self.assertTrue(adopted["ok"], adopted["problems"])
            _, whole_again = validate_current(path, validator=validator)
            self.assertFalse(whole_again["ok"])

    def test_generic_cleanup_cannot_compete_with_live_researcher(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            work = project / "outputs/.pptx-work/energy"
            work.mkdir(parents=True)
            production.write(work / "research-task-binding.json", {"active_agent_id": "live-child"})
            event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "parent",
                "cwd": str(project), "tool_input": {"subagent_type": "general-purpose", "prompt": f"Clean {work}/research-pack.json"}}
            with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": str(project)}), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runtime.handle(event), 2)

    def test_resuming_the_owner_does_not_create_a_competing_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            work = project / "outputs/.pptx-work/energy"
            work.mkdir(parents=True)
            brief = project / 'brief.json'
            brief.write_text('{}', encoding='utf-8')
            production.write(work / 'research-task.json', {'work_id': 'energy', 'work_dir': str(work),
                'brief_path': str(brief), 'materials_path': None, 'scope': 'A', 'budget': 'standard',
                'background': '能源比较', 'claims': [{'id': 'C01', 'claim': '装机', 'acceptance': '来源直接支撑', 'verification': 'source'}]})
            production.write(work / 'research-task-binding.json', {'active_agent_id': 'live-child', 'scope': 'A'})
            event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Agent', 'session_id': 'parent',
                'cwd': str(project), 'tool_input': {'subagent_type': runtime.RESEARCHER, 'resume': 'live-child', 'prompt': str(work)}}
            with patch.dict('os.environ', {'CLAUDE_PROJECT_DIR': str(project)}):
                self.assertEqual(runtime.handle(event), 0)
            self.assertEqual(production.load(work / 'research-task-binding.json')['active_agent_id'], 'live-child')


class RenderPriorityTests(unittest.TestCase):
    def test_failed_compilation_preserves_the_valid_draft(self):
        fixture = fixtures.MainSessionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        data = production.load(fixture.spec)
        data['research_scope'] = 'A'
        production.write(fixture.spec, data)
        production.write(fixture.work / 'research-pack.json', pack())
        broken = fixture.work / 'bad-compiled.json'
        production.write(broken, {'slides': []})
        with patch.object(production, 'compile_research', return_value=broken):
            result = production.plan(fixture.args)
        self.assertTrue(result['draft'])
        self.assertEqual(result['research']['status'], 'pending')
        self.assertEqual(len(result['pages']), 2)

    def test_real_text_collision_is_not_confused_with_adjacent_lines(self):
        xml = '<doc><page><line><word xMin="10" yMin="10" xMax="80" yMax="20">正文</word></line><line><word xMin="20" yMin="12" xMax="90" yMax="22">来源</word></line></page></doc>'
        root = ET.fromstring(xml)
        self.assertEqual(len(inspect_boxes(root)["errors"]), 1)
        self.assertEqual(inspect_boxes(root, {1: [(0, 0, 100, 100)]})["errors"], [])
        root.findall('.//word')[1].set('yMin', '19')
        root.findall('.//word')[1].set('yMax', '29')
        self.assertEqual(inspect_boxes(root)["errors"], [])

    def test_measured_collisions_survive_advisory_and_still_allow_candidate_render(self):
        code = """
const {SlideElementRegistry:R}=require('./scripts/pptx-element-registry.js');
const r=new R({capture:true,designPreferencesAdvisory:true});
for(const text of ['正文','来源'])r.text(1,text,{x:1,y:1,w:3,h:.4,fontSize:18,lineGeometry:[{text,x:1,y:1,w:2,h:.3}]});
const report=r.assertSafe();process.stdout.write(JSON.stringify(report));
"""
        result = subprocess.run(['node', '-e', code], cwd=ROOT, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertFalse(report['ok'])
        self.assertEqual(report['errors'][0]['basis'], 'measured-text')
        self.assertEqual(production.layout_attention(report)['pages'], [1])

    def test_pending_research_can_preview_but_cannot_deliver(self):
        fixture = fixtures.MainSessionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        spec = production.load(fixture.spec)
        spec['research_scope'] = 'A'
        production.write(fixture.spec, spec)
        result = production.plan(fixture.args)
        self.assertTrue(result['draft'])
        fixture.author()
        preview = production.preview(argparse.Namespace(work_dir=fixture.work, slides='1'))
        self.assertEqual(len(preview['pages']), 1)
        run = production.run(argparse.Namespace(work_dir=fixture.work))
        self.assertTrue(run['ok'], run['check_summary'])
        self.assertTrue(run['draft'])
        with self.assertRaisesRegex(production.ProductionError, 'Research Pack is pending'):
            production.complete(argparse.Namespace(work_dir=fixture.work))
        production.write(fixture.work / 'research-pack.json', pack())
        completed = production.complete(argparse.Namespace(work_dir=fixture.work))
        self.assertTrue(completed['ok'])

    def test_actual_collision_blocks_delivery_without_failing_the_build(self):
        fixture = fixtures.MainSessionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        production.plan(fixture.args)
        fixture.author()
        manifest = production.load(fixture.work / 'build-manifest.json')
        page = fixture.work / 'pages' / manifest['scaffold']['pages'][0]
        source = page.read_text(encoding='utf-8').replace('y:2,', 'y:.6,')
        page.write_text(source, encoding='utf-8')
        result = production.run(argparse.Namespace(work_dir=fixture.work))
        self.assertFalse(result['ok'])
        self.assertTrue(result['previews']['pages'])
        self.assertIn(1, result['check_summary']['layout_attention']['pages'])
        self.assertIn('rendered_text_overlap', [e['code'] for e in result['geometry']['errors']])
        from shared.artifact_validation import validate_artifact
        with patch('shared.pptx_runtime.validate_pptx') as package_check:
            unified = validate_artifact(fixture.work / 'deck.pptx', fixture.spec, cache=fixture.work / '_tmp/artifact-validation.json')
            self.assertFalse(unified['ok'])
            self.assertTrue(unified['reused'])
            package_check.assert_not_called()
        with self.assertRaises(production.ProductionError):
            production.complete(argparse.Namespace(work_dir=fixture.work))

    def test_explicit_intentional_overlap_remains_supported(self):
        fixture = fixtures.MainSessionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        production.plan(fixture.args)
        fixture.author()
        manifest = production.load(fixture.work / 'build-manifest.json')
        page = fixture.work / 'pages' / manifest['scaffold']['pages'][0]
        text = page.read_text(encoding='utf-8').replace('y:2,', 'y:.6,').replace('fontSize:32', 'allowOverlap:true,fontSize:32').replace('fontSize:24', 'allowOverlap:true,fontSize:24')
        page.write_text(text, encoding='utf-8')
        result = production.run(argparse.Namespace(work_dir=fixture.work))
        self.assertTrue(result['ok'], result['check_summary'])
        with patch('shared.rendered_layout.inspect_pdf') as inspect:
            second = production.run(argparse.Namespace(work_dir=fixture.work))
            self.assertTrue(second['build_reused'])
            inspect.assert_not_called()
