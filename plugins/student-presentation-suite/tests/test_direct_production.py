"""Artifact-level coverage for main-session production, without agent mocks."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "sp-deck" / "scripts"))

import direct_production as production  # noqa: E402


class MainSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.work = self.project / "outputs" / ".pptx-work" / "direct-test"
        self.work.mkdir(parents=True)
        self.env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        summary = self.project / "summary.md"
        summary.write_text("已确认：两页可编辑 PPT，包含讲稿和预览。", encoding="utf-8")
        production.write(self.work / "workflow-state.json", {
            "state": "intake_confirmed", "work_id": self.work.name,
            "summary_file": str(summary), "summary_sha256": production.file_sha256(summary),
        })
        self.spec = self.work / "slide-spec.json"
        production.write(self.spec, {
            "schema_version": "2.1", "research_scope": "C",
            "meta": {"topic": "实验结果", "language": "Chinese", "design_freedom": "auto",
                     "quality_level": "fast", "citation_style": "none", "include_speaker_notes": True,
                     "duration_min": 2, "slide_count": 2, "deliverables": ["pptx", "speaker-notes", "preview"]},
            "slides": [{"id": index, "title": title, "claim": fact, "content": [fact],
                        "layout": "claim-focus", "timing_sec": 60, "owner": "speaker",
                        "semantic_requirements": {"must_convey": [{"id": f"fact-{index}", "text": fact}],
                                                  "must_show_exact": [exact]}}
                       for index, title, fact, exact in [(1, "合成实验", "准确率 78.4%", "78.4%"),
                                                       (2, "证据边界", "样本量 1,233", "1,233")]],
        })
        self.args = argparse.Namespace(work_dir=self.work, slide_spec=self.spec, art_direction=None,
                                       production_mode=None, research_pack=None, repair_limit=1)

    def author(self, omit_number=False):
        manifest = production.load(self.work / "build-manifest.json")
        for index, name in enumerate(manifest["scaffold"]["pages"], 1):
            title = "合成实验" if index == 1 else "证据边界"
            fact = "准确率 78.4%" if index == 1 else "样本量 1,233"
            if omit_number:
                fact = "结果仅适用于合成实验"
            notes = "这些结果仅用于合成实验演示，不代表真实设备测量。"
            (self.work / "pages" / name).write_text(f"""'use strict';
module.exports = function(ctx) {{
 const {{H,slide,tokens}}=ctx;
 H.addFittedText(slide,{json.dumps(title, ensure_ascii=False)},{{x:.6,y:.6,w:8.5,h:.8}},tokens,'chinese','title',{{fontSize:32}});
 H.addFittedText(slide,{json.dumps(fact, ensure_ascii=False)},{{x:.6,y:2,w:8.5,h:1.2}},tokens,'chinese','body',{{fontSize:24}});
}};
module.exports.presentation_copy={{headline:{json.dumps(title)},visual_labels:[{json.dumps(fact)}]}};
module.exports.notes={json.dumps(notes)};
""", encoding="utf-8")

    def test_plan_has_no_art_direction_or_agent_artifacts(self):
        result = production.plan(self.args)
        self.assertEqual(result["action"], "author_pages")
        self.assertEqual(len(result["pages"]), 2)
        for name in ("builder-packets", "calibration", "critic-execution.json", "visual-review.json"):
            self.assertFalse((self.work / name).exists())
        self.assertEqual(production.load(self.work / "build-manifest.json")["semantic_verification"], "main-session-self-check")

    def test_final_outline_uses_actual_title_and_visible_support_without_old_claim(self):
        spec = {'slides': [{'title': '旧标题', 'claim': '过时的结论', 'role': 'method'},
                           {'title': '导入页面', 'claim': '旧摘要'}]}
        before = json.dumps(spec, ensure_ascii=False)
        text = production.final_outline(spec, ['最终标题\n方法解释\n证据 78.4%', '导入正文'], {1: '最终标题'})
        self.assertIn('## 1. 最终标题', text)
        self.assertIn('方法解释\n证据 78.4%', text)
        self.assertIn('## 2. 导入页面', text)
        self.assertNotIn('过时的结论', text)
        self.assertNotIn('旧标题', text)
        self.assertEqual(json.dumps(spec, ensure_ascii=False), before)

    def test_author_review_is_stale_after_spec_or_artifact_changes(self):
        page = self.project / 'page.png'
        page.write_bytes(b'fixture')
        manifest = {'build': {'pptx': production.bind(self.spec)}, 'slide_spec': production.bind(self.spec),
                    'render': {'pages': [production.bind(page)]}}
        review = {'note': 'author account', 'pptx': manifest['build']['pptx'],
                  'slide_spec': manifest['slide_spec'], 'pages': manifest['render']['pages']}
        self.assertTrue(production.review_current(review, manifest))
        page.write_bytes(b'changed')
        self.assertFalse(production.review_current(review, manifest))

    def test_output_directory_is_frozen_and_cannot_escape_project_outputs(self):
        data = production.load(self.spec)
        data['meta']['output_dir'] = 'outputs/独立交付'
        production.write(self.spec, data)
        production.plan(self.args)
        self.assertEqual(production.load(self.work / 'build-manifest.json')['delivery_dir'],
                         str(self.project / 'outputs' / '独立交付'))
        for path in ('../escape', 'outputs/.pptx-work/unsafe'):
            with self.assertRaisesRegex(production.ProductionError, 'output_dir'):
                production.delivery_directory(self.work, {'output_dir': path})

    def test_windows_build_lock_retries_atomically_and_permanent_failure_preserves_original(self):
        target = self.work / 'deck.pptx'
        source = self.work / 'new.pptx'
        target.write_bytes(b'old')
        source.write_bytes(b'new')
        error = PermissionError('held file')
        error.winerror = 32
        real_replace = os.replace
        attempts = []

        def transient(first, second):
            attempts.append(first)
            if len(attempts) == 1:
                raise error
            real_replace(first, second)

        with patch.object(production.os, 'replace', side_effect=transient) as replace, \
             patch.object(production.time, 'sleep'):
            production.replace_build(source, target)
        self.assertEqual(replace.call_count, 2)
        self.assertEqual(target.read_bytes(), b'new')
        target.write_bytes(b'old')
        source.write_bytes(b'new')
        with patch.object(production.os, 'replace', side_effect=error), patch.object(production.time, 'sleep'):
            with self.assertRaisesRegex(production.ProductionError, 'build replacement failed'):
                production.replace_build(source, target)
        self.assertEqual(target.read_bytes(), b'old')
        real_replace(source, target)
        self.assertEqual(target.read_bytes(), b'new')

    def test_pending_intake_cannot_plan(self):
        state = production.load(self.work / "workflow-state.json")
        state["state"] = "intake_pending"
        production.write(self.work / "workflow-state.json", state)
        with self.assertRaisesRegex(production.ProductionError, "confirm"):
            production.plan(self.args)

    def test_imported_template_blank_placeholder_paragraphs_do_not_become_headline(self):
        import pptx_actual_content_check as content

        (self.work / 'ooxml').mkdir()
        pptx = self.work / 'deck.pptx'
        pptx.write_bytes(b'fixture')
        with patch.object(content, 'extract_pptx_text', return_value=['\n\n学院模板\n正式题目']), \
             patch.object(content, 'extract_pptx_notes', return_value={}):
            production.actual_copy(self.work, pptx, {'schema_version': '2.1'})
        copy = production.load(self.work / 'presentation-copy.json')
        self.assertEqual(copy['slides'][0]['headline'], '学院模板')
        self.assertEqual(copy['slides'][0]['text_runs'], ['\n\n学院模板\n正式题目'])

    def test_repository_cannot_receive_generated_artifacts(self):
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(ROOT.parents[1])}):
            with self.assertRaisesRegex(production.ProductionError, "repository"):
                production.work_directory(ROOT.parents[1] / "outputs" / ".pptx-work" / "forbidden")

    def test_old_manifest_is_not_silently_migrated(self):
        production.write(self.work / "build-manifest.json", {"manifest_version": "2.0", "state": "complete"})
        with self.assertRaisesRegex(production.ProductionError, "legacy manifests"):
            production.authorized(self.work)

    def test_status_reads_unknown_historical_publication_without_migration(self):
        old = {'manifest_version': '2.0', 'state': 'complete', 'published': ['legacy-artifact']}
        production.write(self.work / 'build-manifest.json', old)
        report = production.status(self.args)
        self.assertEqual(report['published'], old['published'])
        self.assertEqual(production.load(self.work / 'build-manifest.json'), old)

    def test_changed_spec_is_refused_before_build(self):
        production.plan(self.args)
        self.spec.write_text(self.spec.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(production.ProductionError, "slide_spec changed"):
            production.run(self.args)

    def test_unfinished_pages_still_fail_without_attempt_budget(self):
        self.args.repair_limit = 0
        production.plan(self.args)
        for _ in range(8):
            with self.assertRaisesRegex(production.ProductionError, "unfinished pages"):
                production.run(self.args)
        manifest=production.load(self.work / "build-manifest.json")
        self.assertEqual(manifest["state"], "producing")
        self.assertEqual(manifest["attempts"], 8)

    def test_typography_alias_is_used_for_sentences_and_unknown_keys_are_named(self):
        code = """
const H=require('./plugins/student-presentation-suite/scripts/pptx-helpers.js');
const R=require('./plugins/student-presentation-suite/scripts/pptx-page-runtime.js');
const tokens={model_led:true,typography:{key_statement_pt:34}};
const policy=H.rolePolicy(tokens,'chinese','statement');
let error='';
try {R.renderPage({tokens,designMode:'guided'},{typography:{wrong_pt:36}});} catch(e){error=e.message;}
const inherited={tokens:{model_led:true,typography:{title_pt:42,statement_pt:34}},designMode:'guided'};
try {R.renderPage(inherited,{typography:{body_pt:20}});} catch(e){ /* stop before drawing */ }
console.log(JSON.stringify({fontSize:policy.fontSize,error,inherited:inherited.tokens.typography}));
"""
        result = subprocess.run(["node", "-e", code], cwd=ROOT.parents[1], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["fontSize"], 34)
        self.assertIn("wrong_pt", data["error"])
        self.assertEqual(data["inherited"]["title_pt"], 42)
        self.assertEqual(data["inherited"]["statement_pt"], 34)

    def test_real_build_render_and_delivery_without_subagents(self):
        production.plan(self.args)
        self.author()
        manifest = production.load(self.work / 'build-manifest.json')
        manifest['last_error'] = 'previous failed build'
        production.write(self.work / 'build-manifest.json', manifest)
        result = production.run(self.args)
        self.assertNotIn('last_error', production.load(self.work / 'build-manifest.json'))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["previews"]["pages"]), 2)
        self.assertEqual(result["action"], "inspect_previews")
        self.assertEqual(result['changed_pages'], [1, 2])
        finished = production.complete(self.args)
        self.assertEqual(finished['author_review_status'], 'unrecorded')
        self.args.review_note = '测试作者自述：页1/2内容与备注已核对；本测试不宣称实际视觉检查。'
        finished = production.complete(self.args)
        self.assertEqual(finished['author_review_status'], 'recorded-current')
        review_report = production.load(self.work / 'production-check.json')
        self.assertFalse(review_report['check_scope']['visual_quality_verified'])
        self.assertFalse(review_report['author_review']['independent'])
        self.assertEqual(set(finished["outputs"]), {"pptx", "speaker-notes", "preview"})
        self.assertTrue(all(production.current(page) for page in finished['outputs']['preview']['pages']))
        self.assertEqual(len(finished['outputs']['preview']['pages']), 2)
        with patch.object(production, 'execute', side_effect=AssertionError('status must not build')):
            inspected = production.status(self.args)
        self.assertTrue(inspected['delivery_health']['ok'])
        self.assertFalse(inspected['production_performed'])
        self.assertEqual(production.complete(self.args)['outputs'], finished['outputs'])
        preview = Path(finished['outputs']['preview']['pages'][0]['path'])
        image = preview.read_bytes()
        preview.unlink()
        self.assertEqual(production.status(self.args)['state'], 'incomplete')
        # A lost exported copy breaks delivery, not the inspected internal render.
        self.assertEqual(production.status(self.args)['author_review_status'], 'recorded-current')
        preview.write_bytes(image)
        (self.work / 'pages' / '_shared.js').write_text('module.exports = {};', encoding='utf-8')
        rerun = production.run(self.args)
        self.assertTrue(rerun['shared_source_changed'])
        self.assertEqual(rerun['changed_pages'], [1, 2])
        production.complete(self.args)
        with zipfile.ZipFile(Path(finished["outputs"]["pptx"]["path"])) as package:
            xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
            self.assertIn("78.4%", xml)
            self.assertIn("<a:ea", xml)
        notes = Path(finished["outputs"]["speaker-notes"]["path"]).read_text(encoding="utf-8")
        self.assertIn("不代表真实设备测量", notes)
        source = Path(finished["outputs"]["pptx"]["path"])
        before = production.file_sha256(source)
        editing = self.work.parent / "notes-edit"
        editing.mkdir()
        state = production.load(self.work / "workflow-state.json")
        state.update(state="intake_confirmed", work_id=editing.name)
        production.write(editing / "workflow-state.json", state)
        spec = production.load(self.spec)
        spec.update(source_deck=str(source), edit_intent="review-fix", preserve=["页面主体"],
                    change_summary_required=True,
                    review_findings=[{"severity":"Minor","target":"第1页备注","problem":"表述调整","fix":"修改备注"}])
        production.write(editing / "slide-spec.json", spec)
        edit_args = argparse.Namespace(**vars(self.args))
        edit_args.work_dir, edit_args.slide_spec = editing, editing / "slide-spec.json"
        production.plan(edit_args)
        part = editing / "ooxml" / "ppt" / "notesSlides" / "notesSlide1.xml"
        part.write_text(part.read_text(encoding="utf-8").replace("不代表", "不等于"), encoding="utf-8")
        (editing / "change-summary.md").write_text("只调整第1页演讲备注措辞。", encoding="utf-8")
        self.assertTrue(production.run(edit_args)["ok"])
        revised = production.complete(edit_args)
        self.assertEqual(production.file_sha256(source), before)
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(Path(revised["outputs"]["pptx"]["path"])) as changed:
            self.assertEqual(set(original.namelist()), set(changed.namelist()))
            for name in original.namelist():
                if name != "ppt/notesSlides/notesSlide1.xml":
                    self.assertEqual(original.read(name), changed.read(name), name)
        page = Path(result["previews"]["pages"][0]["path"])
        page.write_bytes(b"changed preview")
        with self.assertRaisesRegex(production.ProductionError, "current build"):
            production.complete(self.args)

    def test_missing_numeric_fact_cannot_be_delivered(self):
        production.plan(self.args)
        self.author(omit_number=True)
        result = production.run(self.args)
        self.assertFalse(result["ok"])
        with self.assertRaisesRegex(production.ProductionError, "current build"):
            production.complete(self.args)

    def test_designed_placeholder_permission_and_actual_label_bind_delivery(self):
        from test_asset_contract import fixture

        production.plan(self.args)
        self.author()
        data = fixture()
        # Reuse a real visible carrier; an arbitrary unrendered label must fail.
        data['assets'][0]['placeholder']['label'] = '合成实验'
        production.write(self.work / 'asset-manifest.json', data)
        result = production.run(self.args)
        self.assertTrue(result['ok'])
        self.assertEqual(result['asset_placeholders'][0]['replacement'], '装置实拍照片')
        production.complete(self.args)
        data['placeholder_policy'] = 'forbid'
        production.write(self.work / 'asset-manifest.json', data)
        with self.assertRaisesRegex(production.ProductionError, 'asset manifest changed'):
            production.complete(self.args)
        result = production.run(self.args)
        self.assertFalse(result['ok'])
        with self.assertRaisesRegex(production.ProductionError, 'current build'):
            production.complete(self.args)


if __name__ == "__main__":
    unittest.main()
