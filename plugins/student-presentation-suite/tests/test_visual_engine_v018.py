"""v0.18 视觉质量专项：版式引擎、背景指令、registry 美学检查、主导度检查。

覆盖 2026-09-28 视觉质量方案的四个执行端：
* renderArchetype（zones → pptxgenjs，fallback 链，双栏，visual 派发）
* renderBackground（background_directives 执行）
* element registry 的 D1/D2/对齐/死区检查
* palette check 的 60-30-10 主导度近似
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HERE = ROOT / "skills" / "sp-deck" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolved_tokens() -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    from shared.design_tokens import resolve_design_tokens

    return resolve_design_tokens("Modern Minimal")


class RenderArchetypeTests(unittest.TestCase):
    """renderArchetype 通过 node 子进程驱动（与 test_pptx_layouts 同模式）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is unavailable")
        cls.tokens = resolved_tokens()

    def run_node(self, body: str) -> dict:
        script = (
            "const path=require('node:path');"
            f"const SCRIPTS={json.dumps(str(SCRIPTS))};"
            f"const L=require({json.dumps(str(SCRIPTS / 'pptx-layouts.js'))});"
            f"const TOKENS={json.dumps(self.tokens)};"
            "function mock(){const calls=[];const rec=(k)=>(...a)=>{calls.push(k);return {};};"
            "return {calls,addText:rec('text'),addShape:rec('shape'),addImage:rec('image'),"
            "addChart:rec('chart'),addTable:rec('table'),addNotes:rec('notes')};}"
            + body
        )
        result = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)

    def test_places_slots_inside_zones_and_reports_the_archetype(self) -> None:
        out = self.run_node(
            """
            const slide = mock(); const report = [];
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 3, layoutReport: report },
              { layout: { id: 'text-sidebar' },
                slots: { title: '研究方法概述', claim: '三步完成证据检索', body: ['第一步', '第二步'] } });
            console.log(JSON.stringify({ layout: res.layout, calls: slide.calls.length,
              report: report, hasTitle: slide.calls.includes('text'),
              zones: Object.keys(res.zones) }));
            """
        )
        self.assertEqual("text-sidebar", out["layout"])
        self.assertGreaterEqual(out["calls"], 3)
        self.assertEqual("text-sidebar", out["report"][0]["layout"])
        self.assertIn("title", out["zones"])

    def test_long_cover_claim_still_renders_without_throwing(self) -> None:
        # 显示页 claim 走 body 角色（22-26pt），窄列也放得下；即使装不下也会
        # 沿 fallback 链换版式——总之不能抛错炸 build。
        out = self.run_node(
            """
            const slide = mock();
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 1 },
              { layout: { id: 'cover-split' },
                slots: { title: '深度的实证研究', claim: '让检索为你所用，而不是替你发言' } });
            console.log(JSON.stringify({ layout: res.layout, family: res.family, calls: slide.calls.length }));
            """
        )
        self.assertEqual("cover", out["family"])
        self.assertGreaterEqual(out["calls"], 2)

    def test_data_payload_dispatches_chart_via_details_merge(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 4 },
              { layout: { id: 'data-chart-takeaway' },
                slots: { title: '实验结果', claim: '方法 A 领先',
                  visual: { type: 'chart', details: { series: [
                    { name: 'A', labels: ['x', 'y'], values: [3, 5] },
                    { name: 'B', labels: ['x', 'y'], values: [2, 4] }] } } } });
            console.log(JSON.stringify({ layout: res.layout, chart: slide.calls.includes('chart') }));
            """
        )
        self.assertEqual("data-chart-takeaway", out["layout"])
        self.assertTrue(out["chart"])

    def test_empty_visual_payload_draws_no_placeholder(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 2 },
              { layout: { id: 'cover-editorial' },
                slots: { title: '封面标题', claim: '一句话' } });
            console.log(JSON.stringify({ layout: res.layout,
              images: slide.calls.filter((c) => c === 'image').length,
              shapes: slide.calls.filter((c) => c === 'shape').length }));
            """
        )
        self.assertEqual(0, out["images"])
        self.assertEqual(0, out["shapes"])

    def test_two_column_text_splits_items_across_zones(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 5 },
              { layout: { id: 'text-two-column' },
                slots: { title: '利与弊分析', claim: '两侧各有取舍', body: ['优点：成本低', '缺点：速度慢'] } });
            console.log(JSON.stringify({ layout: res.layout, texts: slide.calls.filter((c) => c === 'text').length }));
            """
        )
        self.assertEqual("text-two-column", out["layout"])
        self.assertGreaterEqual(out["texts"], 3)  # title + claim + 2 columns

    def test_registry_records_role_title_for_d1_gate(self) -> None:
        out = self.run_node(
            """
            const R=require(path.join(SCRIPTS, 'pptx-element-registry.js'));
            const slide = mock(); const reg = new R.SlideElementRegistry();
            L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 1, registry: reg },
              { layout: { id: 'cover-editorial' }, slots: { title: '标题', claim: 'claim' } });
            const report = reg.analyzeDeck();
            console.log(JSON.stringify({ ok: report.ok, elementCount: report.slides[0].elementCount }));
            """
        )
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(out["elementCount"], 2)


class RegistryDesignGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is unavailable")

    def run_node(self, body: str) -> dict:
        script = (
            "const path=require('node:path');"
            f"const R=require({json.dumps(str(SCRIPTS / 'pptx-element-registry.js'))});"
            + body
        )
        result = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)

    def test_accent_line_under_title_blocks(self) -> None:
        out = self.run_node(
            """
            const reg = new R.SlideElementRegistry();
            reg.register(1, { id: 't', type: 'text', role: 'title', text: '标题', x: 0.6, y: 0.4, w: 8.8, h: 1.0, fontSize: 32 });
            reg.register(1, { id: 'bar', type: 'shape', x: 0.6, y: 1.5, w: 1.2, h: 0.05 });
            const r = reg.analyzeDeck();
            console.log(JSON.stringify({ ok: r.ok, codes: r.errors.map((e) => e.code) }));
            """
        )
        self.assertFalse(out["ok"])
        self.assertIn("accent_line_under_title", out["codes"])

    def test_near_miss_alignment_blocks_but_containment_exempts(self) -> None:
        out = self.run_node(
            """
            const reg = new R.SlideElementRegistry();
            reg.register(1, { id: 'a', type: 'text', text: 'x', x: 0.6, y: 1.0, w: 8.8, h: 1.0, fontSize: 22 });
            reg.register(1, { id: 'b', type: 'text', text: 'y', x: 0.68, y: 2.1, w: 8.6, h: 1.0, fontSize: 22 });
            reg.register(2, { id: 'panel', type: 'shape', decorative: true, x: 1.0, y: 1.0, w: 4.0, h: 2.0 });
            reg.register(2, { id: 'lbl', type: 'text', text: 'l', x: 1.08, y: 1.1, w: 3.8, h: 0.5, fontSize: 18 });
            const r = reg.analyzeDeck();
            console.log(JSON.stringify({
              slide1: r.slides[0].errors.map((e) => e.code),
              slide2: r.slides[1].errors.map((e) => e.code) }));
            """
        )
        self.assertIn("near_miss_alignment", out["slide1"])
        self.assertEqual([], out["slide2"])

    def test_diagonal_connector_and_dead_zone_are_warnings(self) -> None:
        out = self.run_node(
            """
            const reg = new R.SlideElementRegistry();
            reg.register(1, { id: 'diag', type: 'line', x1: 1, y1: 1, x2: 3, y2: 2 });
            reg.register(1, { id: 'narrow', type: 'text', text: '窄内容', x: 1.0, y: 1.0, w: 3.0, h: 1.0, fontSize: 22 });
            const r = reg.analyzeDeck();
            console.log(JSON.stringify({ warnings: r.warnings.map((w) => w.code) }));
            """
        )
        self.assertIn("non_orthogonal_connector", out["warnings"])

    def test_unsafe_font_width_slack_tightens_fit(self) -> None:
        # 12 个 CJK 字在 2.0in 盒里：安全字体 1.83 盒宽 → 2 行；
        # +10% 余量后 2.02 盒宽 → 3 行。requiredH 必须变大。
        out = self.run_node(
            """
            const safe = R.estimateTextFit({ text: '一二三四五六七八九十百千', x: 0.6, y: 1, w: 2.0, h: 1.2, fontSize: 22, fontFace: 'Calibri' });
            const unsafe = R.estimateTextFit({ text: '一二三四五六七八九十百千', x: 0.6, y: 1, w: 2.0, h: 1.2, fontSize: 22, fontFace: 'Aptos' });
            console.log(JSON.stringify({ unsafeNeedsMore: unsafe.requiredH > safe.requiredH,
              safeLines: safe.estimatedLines, unsafeLines: unsafe.estimatedLines }));
            """
        )
        self.assertTrue(out["unsafeNeedsMore"], out)
        self.assertEqual(2, out["safeLines"])
        self.assertEqual(3, out["unsafeLines"])


class BackgroundDirectiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is unavailable")
        cls.tokens = resolved_tokens()

    def test_render_background_executes_directives(self) -> None:
        script = (
            "const path=require('node:path');"
            f"const H=require({json.dumps(str(SCRIPTS / 'pptx-helpers.js'))});"
            f"const TOKENS={json.dumps(self.tokens)};"
            "function mock(){const calls=[];const rec=(k)=>(...a)=>{calls.push(k);return {};};"
            "return {calls,addText:rec('text'),addShape:rec('shape'),addImage:rec('image'),"
            "addChart:rec('chart'),addTable:rec('table'),addNotes:rec('notes')};}"
            "const dark = mock(); H.renderBackground(dark, TOKENS, { kind: 'cover', dark: true });"
            "const light = mock(); H.renderBackground(light, TOKENS, { kind: 'content' });"
            "const legacy = mock(); H.renderBackground(legacy, { palette: { canvas: 'FFFFFF' } }, { kind: 'content' });"
            "console.log(JSON.stringify({ darkImages: dark.calls.filter((c) => c === 'image').length,"
            " darkBackground: dark.background, lightImages: light.calls.filter((c) => c === 'image').length,"
            " legacyImages: legacy.calls.filter((c) => c === 'image').length }));"
        )
        result = subprocess.run([self.node, "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(result.stdout)
        # dark cover: 渐变（+可能的纹理/母题）至少一张整页图；content 现代极简 restrained 无纹理
        self.assertGreaterEqual(out["darkImages"], 1)
        self.assertEqual(out["darkBackground"]["color"], self.tokens["dark_palette"]["canvas"])
        self.assertEqual(0, out["legacyImages"])  # 旧 tokens 退化为纯色，不炸


class AccentDominanceTests(unittest.TestCase):
    def test_dominance_and_absence_findings(self) -> None:
        module = _load("pptx_palette_check_dom", HERE / "pptx_palette_check.py")
        from collections import Counter

        accent = "2563EB"
        per_part = {
            "ppt/slides/slide1.xml": Counter({accent: 20, "111827": 5}),
            "ppt/slides/slide2.xml": Counter({accent: 1, "111827": 40}),
        }
        light = {
            "primary_accent": accent,
            "secondary_accent": "16A34A",
            "canvas": "F8FAFC",
            "surface": "FFFFFF",
            "primary_text": "111827",
            "secondary_text": "4B5563",
        }
        findings = module.accent_dominance_findings(per_part, light, light)
        codes = {item["code"] for item in findings}
        self.assertIn("accent-element-dominance", codes)
        self.assertIn("accent-absent", codes)
        for item in findings:
            self.assertEqual("minor", item["severity"])

    def test_balanced_deck_is_silent(self) -> None:
        module = _load("pptx_palette_check_dom2", HERE / "pptx_palette_check.py")
        from collections import Counter

        light = {
            "primary_accent": "2563EB",
            "secondary_accent": "16A34A",
            "canvas": "F8FAFC",
            "surface": "FFFFFF",
            "primary_text": "111827",
            "secondary_text": "4B5563",
        }
        per_part = {
            f"ppt/slides/slide{n}.xml": Counter({"2563EB": 3, "111827": 40})
            for n in range(1, 5)
        }
        self.assertEqual([], module.accent_dominance_findings(per_part, light, light))


class ScaffoldEngineContractTests(unittest.TestCase):
    """scaffold 与引擎的接线契约（stub 内的 engine 调用形态）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scaffold = _load("generator_scaffold_v018", ROOT / "skills/sp-deck/scripts/generator_scaffold.py")

    def test_dark_sandwich_defaults(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps({
                    "slides": [
                        {"id": 1, "kind": "cover", "title": "封面"},
                        {"id": 2, "kind": "content", "title": "内容页标题", "role": "analysis", "slide_copy": ["要点一", "要点二"]},
                        {"id": 3, "kind": "closing", "title": "结论"},
                    ]
                }),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            cover = (work / "pages" / "p01-cover.js").read_text(encoding="utf-8")
            content = (work / "pages" / "p02-s02.js").read_text(encoding="utf-8")
            closing = (work / "pages" / "p03-closing.js").read_text(encoding="utf-8")
            self.assertIn("const dark = true;", cover)
            self.assertIn("const dark = false;", content)
            self.assertIn("const dark = true;", closing)
            # 列表 slide_copy 嵌成真 JS 数组
            self.assertIn('["要点一", "要点二"]', content)
            # visual 载荷直通
            self.assertIn('"layoutFamily"', content)


if __name__ == "__main__":
    unittest.main()
