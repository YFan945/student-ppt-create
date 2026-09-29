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
import os
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
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            check=True,
            # pptx-visuals 内部按裸名 require('pptx-helpers')，靠 NODE_PATH 解析。
            env={**os.environ, "NODE_PATH": str(SCRIPTS)},
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

    def test_exhausted_fallback_chain_names_the_pinned_layout_and_the_chain(self) -> None:
        """链耗尽报错点名请求版式 + 整条链，而不是只剩链尾 archetype 名。

        2026-09-28 live：cover-split 沿链退到 cover-minimal，报错只说 cover-minimal，
        被误读成 request.layout.id 没生效，白烧一轮 builder 去修不存在的落版问题。
        """
        out = self.run_node(
            """
            const slide = mock();
            let message = null;
            try {
              L.renderArchetype(
                { slide, tokens: TOKENS, slideNumber: 1 },
                { layout: { id: 'cover-split' },
                  slots: { title: '超'.repeat(400), claim: '装不下任何版式' } });
            } catch (error) {
              message = error.message;
            }
            console.log(JSON.stringify({ message }));
            """
        )
        message = out["message"] or ""
        library = json.loads(
            (ROOT / "skills/sp-deck/references/layout-library.json").read_text(encoding="utf-8")
        )
        by_id = {item["id"]: item for item in library["layouts"]}
        chain = []
        cursor = by_id["cover-split"]
        while cursor is not None and cursor["id"] not in chain:
            chain.append(cursor["id"])
            cursor = by_id.get(cursor.get("fallback"))
        self.assertIn('pinned layout "cover-split"', message)
        self.assertIn(f"[{' -> '.join(chain)}]", message)
        self.assertIn("all failed", message)
        self.assertIn("title does not fit", message)
        # 每条候选各自的失败原因都要在场：一轮交底，一轮修完，不再一次露一条。
        self.assertIn(f"{chain[0]}: slide", message)
        self.assertIn(f"{chain[-1]}: slide", message)

    def test_fit_failure_reports_text_and_box_evidence(self) -> None:
        """同一条 fit 错误连烧三轮的教训：报错必须带文本预览/字数/盒子尺寸。"""
        out = self.run_node(
            """
            const H = require(path.join(SCRIPTS, 'pptx-helpers.js'));
            const slide = mock();
            let message = null;
            try {
              H.addFittedText(slide, '这一段文本无论如何都放不进这么小的盒子',
                { x: 1, y: 1, w: 0.3, h: 0.2 }, TOKENS, 'chinese', 'label', { label: '解释焦点' });
            } catch (error) {
              message = error.message;
            }
            console.log(JSON.stringify({ message }));
            """
        )
        message = out["message"] or ""
        self.assertIn("cannot fit at", message)
        self.assertIn("0.30x0.20in", message)
        self.assertIn("chars)", message)

    def test_failed_fallback_attempts_leave_nothing_on_the_slide(self) -> None:
        """失败尝试不得在真 slide 上留半成品（2026-09-28 live：页 2 沿链试 3 个
        候选落 text-two-column，slide 上留下 4 份标题，assertSafe 以 text_overlap
        拒绝整副 deck）。探针模式：成功才落真迹。"""
        out = self.run_node(
            """
            const R = require(path.join(SCRIPTS, 'pptx-element-registry.js'));
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            let titles = 0, total = 0;
            const slide = { addText: (t) => { total++; if (String(t).includes('双碳目标')) titles++; return {}; },
              addShape: () => ({}), addImage: () => ({}), addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}) };
            const report = [];
            L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 2, registry, layoutReport: report },
              { layout: { id: 'data-kpi-row' },
                context: { slideId: 2, slideKind: 'content', layoutFamily: 'dashboard', itemCount: 3, titleChars: 13 },
                slots: { title: '双碳目标把风光推成主力增量',
                  claim: '2030年非化石能源消费比重25%左右，风光总装机12亿千瓦以上',
                  body: ['2060年非化石能源消费比重80%以上', '两个目标均引自2021年中央文件口径'] } });
            const analysis = registry.analyzeDeck();
            console.log(JSON.stringify({ titles, total, reportLen: report.length, ok: analysis.ok }));
            """
        )
        self.assertEqual(1, out["titles"], out)
        self.assertEqual(1, out["reportLen"], out)
        self.assertTrue(out["ok"], out)

    def test_borrowed_visual_column_must_be_a_disjoint_side_column(self) -> None:
        """claim-focus 的 visual 区在 body 投影内：借作双栏第二列会与第一列重叠
        （2026-09-28 live 页 2 残留 1 处 text_overlap）。非侧栏形态走单栏，装不下
        交 fallback 链——addBody 的容量失败必须以 layoutFit 参与链，而不是裸
        RangeError 炸掉 deck。"""
        out = self.run_node(
            """
            const R = require(path.join(SCRIPTS, 'pptx-element-registry.js'));
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const slide = { addText: () => ({}), addShape: () => ({}), addImage: () => ({}),
              addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}) };
            let threw = null;
            try {
              L.renderArchetype(
                { slide, tokens: TOKENS, slideNumber: 2, registry },
                { layout: { id: 'claim-focus' },
                  slots: { title: '标题',
                    claim: '2030年非化石能源消费比重25%左右，风光总装机12亿千瓦以上',
                    body: ['2060年非化石能源消费比重80%以上', '两个目标均引自2021年中央文件口径'] } });
            } catch (error) { threw = error.message; }
            const analysis = registry.analyzeDeck();
            const overlaps = analysis.errors.filter((e) => e.code === 'text_overlap').length;
            console.log(JSON.stringify({ threw, overlaps }));
            """
        )
        self.assertEqual(0, out["overlaps"], out)
        if out["threw"] is not None:
            self.assertIn("all failed", out["threw"], out)

    def test_timeline_nodes_follow_real_time_intervals(self) -> None:
        """D12：带年份的时间轴按真实间隔比例布点——等距渲染 2021→2060 会把 30 年画成
        4 年（critic 记 major）；序数阶段等距是诚实的，维持原布局。"""
        out = self.run_node(
            """
            const V = require(path.join(SCRIPTS, 'pptx-visuals.js'));
            function markers(stages) {
              const shapes = [];
              const slide = { addText: () => ({}), addShape: (kind, o) => { shapes.push(o); return {}; },
                addImage: () => ({}), addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}) };
              V.addTimeline(slide, { stages }, { x: 0.6, y: 1.0, w: 8.8, h: 2.0 }, TOKENS, 'chinese');
              return shapes.filter((s) => Math.abs(s.h - 0.4) < 0.001).map((s) => +(s.x + 0.2).toFixed(3));
            }
            console.log(JSON.stringify({
              years: markers([{ label: '2021' }, { label: '2025' }, { label: '2030' }, { label: '2060' }]),
              ordinal: markers([{ label: '阶段一' }, { label: '阶段二' }, { label: '阶段三' }, { label: '阶段四' }]),
            }));
            """
        )
        years = out["years"]
        gaps = [round(b - a, 3) for a, b in zip(years, years[1:], strict=False)]
        self.assertGreater(gaps[2], gaps[0] * 3, gaps)
        ordinal = out["ordinal"]
        equal = [round(b - a, 3) for a, b in zip(ordinal, ordinal[1:], strict=False)]
        self.assertTrue(all(abs(g - equal[0]) < 0.01 for g in equal), equal)

    def test_key_line_renders_the_uniform_closing_band(self) -> None:
        """D11 收尾带由引擎统一渲染：slots.key_line 一到，细规线 + 结论句落在
        安全区底部，builder 不再手画（2026-09-28 live：收尾带缺失/不一致被
        critic 记 major）。"""
        out = self.run_node(
            """
            const R = require(path.join(SCRIPTS, 'pptx-element-registry.js'));
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const texts = [], shapes = [];
            const slide = {
              addText: (t, o) => { texts.push({ text: String(t).slice(0, 12), y: +Number(o.y).toFixed(2) }); return {}; },
              addShape: (kind, o) => { shapes.push(o); return {}; },
              addImage: () => ({}), addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}) };
            L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 3, registry },
              { layout: { id: 'claim-focus' },
                slots: { title: '标题', claim: '主张一句话', body: ['要点一', '要点二'],
                  key_line: '约束先定死，风光才有主力增量的位置' } });
            const key = texts.find((t) => t.text.startsWith('约束先定死'));
            const analysis = registry.analyzeDeck();
            console.log(JSON.stringify({
              hasKey: Boolean(key), keyY: key && key.y,
              rules: shapes.filter((s) => Math.abs(s.h) < 0.001).map((s) => +Number(s.y).toFixed(2)),
              errors: analysis.errors.map((e) => e.code),
            }));
            """
        )
        self.assertTrue(out["hasKey"], out)
        self.assertTrue(out["keyY"] > 4.5, out)
        self.assertTrue(any(abs(y - (out["keyY"] - 0.08)) < 0.06 for y in out["rules"]), out)
        self.assertEqual([], out["errors"], out)

    def test_timeline_labels_fit_with_tight_margin(self) -> None:
        """2026-09-29 live："2021 双碳目标写入中…" 15 字在默认 6pt 内边距下差 2%
        放不下，校准构建连败。margin 2 后 16pt 两行可容纳。"""
        out = self.run_node(
            """
            const V = require(path.join(SCRIPTS, 'pptx-visuals.js'));
            const slide = { addText: () => ({}), addShape: () => ({}), addImage: () => ({}),
              addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}) };
            let threw = null;
            try {
              V.addTimeline(slide, { stages: [
                { label: '2021 双碳目标写入中' },
                { label: '2025 非化石装机过半' },
                { label: '2030 碳达峰' },
                { label: '2060 碳中和' }] },
                { x: 0.6, y: 1.0, w: 8.8, h: 2.0 }, TOKENS, 'chinese');
            } catch (error) { threw = error.message; }
            console.log(JSON.stringify({ threw }));
            """
        )
        self.assertIsNone(out["threw"], out)

    def test_no_feasible_context_falls_back_instead_of_dying(self) -> None:
        """容量/禁忌全卡死时不再"no feasible layout"一句话炸死：保底 claim-focus
        起渲染（2026-09-29 live：校准构建连败于该死路）。"""
        out = self.run_node(
            """
            const slide = mock();
            let threw = null, layout = null;
            try {
              const res = L.renderArchetype(
                { slide, tokens: TOKENS, slideNumber: 9 },
                { context: { slideId: 9, slideKind: 'definition-example', itemCount: 50,
                  titleChars: 500, contraindications: ['text-only', 'equal-width-cards'] },
                  slots: { title: '标题', claim: '主张', body: ['要点'] } });
              layout = res.layout;
            } catch (error) { threw = error.message; }
            console.log(JSON.stringify({ threw, layout }));
            """
        )
        if out["threw"] is not None:
            self.assertIn("all failed", out["threw"], out)
        else:
            self.assertTrue(out["layout"], out)

    def test_visual_purpose_is_design_intent_and_never_on_screen(self) -> None:
        """visual.purpose 是设计意图（slide-spec.md handoff rules），绝不上屏。

        2026-09-28 live：44 字的 purpose 被 visual-dominant 当焦点标签渲染，
        在小视觉区连 16pt 下限都装不下，整条 fallback 链炸掉；而装不下的焦点
        标签本身是装饰，必须静默跳过而不是抛错。
        """
        out = self.run_node(
            """
            const V = require(path.join(SCRIPTS, 'pptx-visuals.js'));
            const texts = [];
            const slide = {
              addText: (t) => { texts.push(String(t)); return {}; },
              addShape: () => ({}), addImage: () => ({}),
              addChart: () => ({}), addTable: () => ({}), addNotes: () => ({}),
            };
            const purpose = '用左右双轨一次性建立蓝等于光伏绿等于风电的全局配色语义说明'.repeat(2);
            let threw = null;
            try {
              V.renderVisual(slide, 'visual-dominant', { purpose },
                { x: 0.5, y: 1, w: 3, h: 2 }, TOKENS, 'chinese');
              V.renderVisual(slide, 'visual-dominant', { purpose },
                { x: 0.5, y: 1, w: 1, h: 0.4 }, TOKENS, 'chinese');
            } catch (error) {
              threw = error.message;
            }
            console.log(JSON.stringify({ threw, texts }));
            """
        )
        self.assertIsNone(out["threw"], out)
        self.assertFalse([text for text in out["texts"] if "双轨" in text], out["texts"])

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


class SolveStackTests(unittest.TestCase):
    """v0.19 P2-9：mini stack/flex 求解器。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is unavailable")

    def run_node(self, body: str) -> dict:
        script = (
            "const path=require('node:path');"
            f"const SCRIPTS={json.dumps(str(SCRIPTS))};"
            f"const H=require({json.dumps(str(SCRIPTS / 'pptx-helpers.js'))});"
            + body
        )
        result = subprocess.run(
            [self.node, "-e", script], capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)

    def test_between_distributes_leftover(self) -> None:
        out = self.run_node(
            """
            const r = H.solveStack({ x: 1, y: 1, w: 4, h: 3 },
              [{ key: 'a', height: 0.5 }, { key: 'b', height: 1.0 }],
              { gap: 0.2, justify: 'between' });
            console.log(JSON.stringify({ a: r.boxes.a.y, b: r.boxes.b.y, bBottom: r.boxes.b.y + r.boxes.b.h, overflow: r.overflow }));
            """
        )
        self.assertAlmostEqual(1.0, out["a"])
        self.assertAlmostEqual(3.0, out["b"])  # 首尾贴边
        self.assertAlmostEqual(4.0, out["bBottom"])
        self.assertFalse(out["overflow"])

    def test_center_centers_a_sparse_stack(self) -> None:
        out = self.run_node(
            """
            const r = H.solveStack({ x: 0, y: 1, w: 4, h: 3 }, [{ key: 'x', height: 0.5 }], { justify: 'center' });
            console.log(JSON.stringify({ y: r.boxes.x.y }));
            """
        )
        self.assertAlmostEqual(2.25, out["y"])

    def test_measure_uses_natural_size_and_flags_overflow(self) -> None:
        # measure 收到主轴全长（h=1）→ 自然高 0.3；加 b 0.6 + gap 0.2 = 1.1 > 1 溢出。
        out = self.run_node(
            """
            const r = H.solveStack({ x: 0, y: 0, w: 4, h: 1 },
              [{ key: 'a', measure: (flowLen) => flowLen * 0.3 }, { key: 'b', height: 0.6 }],
              { gap: 0.2, justify: 'start' });
            console.log(JSON.stringify({ aH: r.boxes.a.h, overflow: r.overflow, used: r.used }));
            """
        )
        self.assertAlmostEqual(0.3, out["aH"])
        self.assertTrue(out["overflow"])
        self.assertAlmostEqual(1.1, out["used"])

    def test_row_direction_solves_horizontally(self) -> None:
        out = self.run_node(
            """
            const r = H.solveStack({ x: 0, y: 0, w: 4, h: 1 },
              [{ key: 'l', height: 1.0 }, { key: 'r', height: 2.0 }],
              { direction: 'row', gap: 0.25, justify: 'between' });
            console.log(JSON.stringify({ l: r.boxes.l, r: r.boxes.r }));
            """
        )
        self.assertAlmostEqual(0.0, out["l"]["x"])
        self.assertAlmostEqual(4.0, out["r"]["x"] + out["r"]["w"])
        self.assertAlmostEqual(1.0, out["l"]["h"])
        self.assertAlmostEqual(2.0, out["r"]["w"])

    def test_engine_centers_display_claim_without_body(self) -> None:
        # cover-editorial claim-only：claim 应垂直居中于 body zone，而不是贴顶。
        out = self.run_node(
            """
            const L=require(path.join(SCRIPTS, 'pptx-layouts.js'));
            const TOKENS=__TOKENS__;
            function mock(){const calls=[];const rec=(k)=>(...a)=>{calls.push(k);return {};};
              return {calls,addText:rec('text'),addShape:rec('shape'),addImage:rec('image'),addChart:rec('chart'),addTable:rec('table'),addNotes:rec('notes')};}
            const slide = mock(); const reg = { registered: [], register(n, el) { this.registered.push(el); } };
            const res = L.renderArchetype(
              { slide, tokens: TOKENS, slideNumber: 1, registry: reg },
              { layout: { id: 'cover-editorial' }, slots: { title: '标题', claim: '一句话主张' } });
            const claim = reg.registered.find((el) => el.role === 'subtitle');
            console.log(JSON.stringify({ layout: res.layout, claimY: claim ? claim.y : null,
              bodyY: res.zones.body ? res.zones.body.y : null,
              centered: claim ? claim.y > res.zones.body.y + 0.01 : false }));
            """.replace("__TOKENS__", json.dumps(resolved_tokens()))
        )
        self.assertTrue(out["centered"], out)


class ReferenceDeckIngestionTests(unittest.TestCase):
    """v0.19 P2-10：参考 deck 分析器 + plan 接线。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load(
            "reference_deck_analysis_test", HERE / "reference_deck_analysis.py"
        )

    def test_classifies_synthetic_slide_xml(self) -> None:
        chart_slide = (
            "<p:sp><a:rPr sz=\"3200\"/><a:t>实验结果对比</a:t></p:sp>"
            "<c:chart><c:title>Key result</c:title></c:chart>"
        )
        entry = self.module.classify_slide(
            chart_slide, slide_no=3, slide_count=6, slide_w=10.0, slide_h=5.625
        )
        self.assertEqual("data", entry["detected_type"])
        self.assertIn("chart-or-table", entry["signals"])
        self.assertIn("data-chart-takeaway", entry["suggested_archetypes"])

    def test_chart_evidence_outranks_english_conclusion_word(self) -> None:
        xml = "<c:chart/>" + "<a:t>State the conclusion supported by this chart.</a:t>"
        entry = self.module.classify_slide(
            xml, slide_no=2, slide_count=6, slide_w=10.0, slide_h=5.625
        )
        self.assertEqual("data", entry["detected_type"])

    def test_validate_report_rejects_unknown_layout_ids(self) -> None:
        report = {
            "slides": [
                {"slide": 1, "detected_type": "cover", "suggested_archetypes": ["cover-split"]},
                {"slide": 2, "detected_type": "data", "suggested_archetypes": ["not-a-layout"]},
            ]
        }
        errors = self.module.validate_report(report)
        self.assertTrue(any("not-a-layout" in error for error in errors))

    def test_scaffold_uses_reference_suggestions(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps({
                    "slides": [
                        {"id": 1, "kind": "cover", "title": "封面"},
                        {"id": 2, "kind": "content", "title": "内容页标题测试", "role": "analysis"},
                    ]
                }),
                encoding="utf-8",
            )
            analysis = {
                "slides": [
                    {"slide": 1, "detected_type": "cover", "suggested_archetypes": ["cover-split"]},
                    {"slide": 2, "detected_type": "data", "suggested_archetypes": ["data-chart-sidebar"]},
                ]
            }
            result = self.scaffold_for(work, spec, analysis)
            self.assertEqual(2, result["reference_guided"])
            cover = (work / "pages" / "p01-cover.js").read_text(encoding="utf-8")
            content = (work / "pages" / "p02-s02.js").read_text(encoding="utf-8")
            self.assertIn('"layout": "cover-split"', cover)
            self.assertIn('"layout": "data-chart-sidebar"', content)

    @staticmethod
    def scaffold_for(work: Path, spec: Path, analysis: dict):
        scaffold = _load(
            "generator_scaffold_ref_test", ROOT / "skills/sp-deck/scripts/generator_scaffold.py"
        )
        return scaffold.scaffold_generator(work, spec, reference_analysis=analysis)


class StylePreviewTests(unittest.TestCase):
    """v0.19 P2-11：风格小样驱动（渲染链路 env-gated）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load("style_previews_test", HERE / "style_previews.py")
        if not shutil.which("soffice") and not Path(
            r"C:\Program Files\LibreOffice\program\soffice.exe"
        ).is_file():
            raise unittest.SkipTest("LibreOffice unavailable")
        if not shutil.which("pdftoppm"):
            raise unittest.SkipTest("poppler unavailable")
        if not shutil.which("node"):
            raise unittest.SkipTest("node unavailable")

    def test_single_style_preview_renders_two_pages(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            argv = ["--topic", "测试主题", "--styles", "modern-minimal", "--out", str(out)]
            rc = self.module.main(argv)
            self.assertEqual(0, rc)
            manifest = json.loads((out / "style-previews.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(manifest["previews"]))
            self.assertEqual(2, len(manifest["previews"][0]["pngs"]))
            self.assertTrue(all(Path(p).is_file() for p in manifest["previews"][0]["pngs"]))

    def test_default_trio_covers_three_categories(self) -> None:
        self.assertEqual(3, len(self.module.DEFAULT_STYLES))


if __name__ == "__main__":
    unittest.main()
