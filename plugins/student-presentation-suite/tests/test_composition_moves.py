"""Generation-time composition moves draw hierarchy instead of filling a plain zone."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def resolved_tokens(style: str = "Modern Minimal") -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    from shared.design_tokens import resolve_design_tokens

    return resolve_design_tokens(style)


def shipped_styles() -> list[str]:
    """Every style the catalog ships, by display name (no hand-kept list to drift)."""
    catalog = json.loads((ROOT / "references" / "design-tokens.json").read_text(encoding="utf-8"))
    return [record["name"] for record in catalog["styles"].values()]


class CompositionMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node is unavailable")
        cls.tokens = resolved_tokens()

    def run_node(self, body: str, tokens: dict | None = None) -> dict:
        script = (
            "const path=require('node:path');"
            f"const SCRIPTS={json.dumps(str(SCRIPTS))};"
            f"const L=require({json.dumps(str(SCRIPTS / 'pptx-layouts.js'))});"
            f"const C=require({json.dumps(str(SCRIPTS / 'pptx-composition.js'))});"
            f"const H=require({json.dumps(str(SCRIPTS / 'pptx-helpers.js'))});"
            f"const R=require({json.dumps(str(SCRIPTS / 'pptx-element-registry.js'))});"
            f"const TOKENS={json.dumps(tokens or self.tokens)};"
            "function mock(){const calls=[];const rec=(k)=>(...a)=>{calls.push({k,a});return {};};"
            "return {calls,addText:rec('text'),addShape:rec('shape'),addImage:rec('image'),"
            "addChart:rec('chart'),addTable:rec('table'),addNotes:rec('notes')};}"
            + body
        )
        result = subprocess.run(
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "NODE_PATH": str(SCRIPTS)},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_thesis_draws_a_primary_mass(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const res = L.renderDeclaredPage(
              { slide, tokens: TOKENS, slideNumber: 2, registry, lang: 'chinese' },
              { kind: 'content', move: 'thesis',
                slots: { title: '课堂问题', claim: '模型优化的是像', body: ['而不是真'] } });
            const texts = registry.analyzeDeck().slides[0]
              ? null : null;
            const elements = registry._slide ? registry._slide(2) : [];
            const primary = elements.find((el) => el.role === 'stat');
            const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS, { reserveTitle: false });
            console.log(JSON.stringify({
              move: res.move,
              fontSize: primary && primary.fontSize,
              share: primary ? (primary.w * primary.h) / (area.w * area.h) : 0,
            }));
            """
        )
        self.assertEqual("thesis", out["move"])
        self.assertGreaterEqual(out["fontSize"], 44)
        self.assertGreaterEqual(out["share"], 0.4)

    def test_layout_only_page_still_renders(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const res = L.renderDeclaredPage(
              { slide, tokens: TOKENS, slideNumber: 1, lang: 'chinese' },
              { kind: 'content', layout: 'claim-focus',
                slots: { title: '标题', claim: '一句话主张', body: ['要点'] } });
            console.log(JSON.stringify({ layout: res.layout, move: res.move || null }));
            """
        )
        self.assertTrue(out["layout"])
        self.assertIsNone(out["move"])

    def test_oversized_thesis_falls_back_to_an_archetype(self) -> None:
        out = self.run_node(
            """
            const slide = mock();
            const claim = '模型在缺少事实约束时会把流畅当成正确'.repeat(4);
            const res = L.renderDeclaredPage(
              { slide, tokens: TOKENS, slideNumber: 4, lang: 'chinese' },
              { kind: 'content', move: 'thesis', layout: 'claim-evidence',
                slots: { title: '标题', claim, body: ['补充一句'] } });
            console.log(JSON.stringify({ layout: res.layout, move: res.move || null, fallback: res.fallbackFrom || null }));
            """
        )
        self.assertEqual("thesis", out["fallback"])
        self.assertNotEqual("thesis", out["layout"])
        self.assertTrue(out["layout"])

    def test_six_moves_record_hierarchy_and_leave_a_sample(self) -> None:
        sample = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "student-ppt-composition-sample.pptx"
        script = """
        const fs = require('node:fs');
        const path = require('node:path');
        const pptxgen = require('pptxgenjs');
        const H = require('pptx-helpers');
        const L = require('pptx-layouts');
        const R = require('pptx-element-registry');
        const TOKENS = JSON.parse(process.env.SAMPLE_TOKENS);
        const pptx = new pptxgen();
        H.applyTokens(pptx, TOKENS, 'chinese');
        const registry = new R.SlideElementRegistry({ slideW: H.SLIDE_W_IN, slideH: H.SLIDE_H_IN });
        const pages = [
          { move: 'thesis', slots: { title: '问题', claim: '流畅不是证据', body: ['其余解释退到后面'] } },
          { move: 'weighted', slots: { title: '判断', claim: '主判断占六成', body: ['第一支撑', '第二支撑更短'] } },
          { move: 'metric', slots: { title: '结果', claim: '91', body: ['领先基线'] } },
          { move: 'proof', slots: { title: '证据', claim: '方法领先', visual: { type: 'chart', series: [{ name: 'A', labels: ['甲','乙'], values: [3, 5] }] } } },
          { move: 'sequence', slots: { title: '步骤', claim: '先做这一步', body: ['收集', '核验', '写下'] } },
          { move: 'figure', slots: { title: '图', claim: '图占主区域', visual: { type: 'chart', series: [{ name: 'A', labels: ['甲','乙'], values: [2, 4] }] } } },
        ];
        const report = [];
        pages.forEach((page, index) => {
          const slide = pptx.addSlide();
          L.renderDeclaredPage(
            { slide, tokens: TOKENS, registry, slideNumber: index + 1, lang: 'chinese', layoutReport: report },
            { kind: index === 0 ? 'cover' : 'content', dark: index === 0, ...page },
          );
        });
        registry.assertSafe();
        const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS, { reserveTitle: false });
        const slides = [];
        for (let n = 1; n <= 6; n += 1) {
          const elements = registry._slide(n);
          const candidates = elements.filter((el) => el.role === 'stat' || el.role === 'visual');
          const primary = candidates.sort((a, b) => b.w * b.h - a.w * a.h)[0];
          const secondary = elements.find((el) => el.role === 'body' || el.role === 'label');
          slides.push({
            move: report.find((row) => row.slide === n).move,
            share: primary ? (primary.w * primary.h) / (area.w * area.h) : 0,
            primaryPt: primary && primary.fontSize || null,
            secondaryPt: secondary && secondary.fontSize || null,
          });
        }
        const out = process.env.SAMPLE_PPTX;
        pptx.writeFile({ fileName: out }).then(() => {
          console.log(JSON.stringify({ slides, out }));
        });
        """
        result = subprocess.run(
            [self.node, "-e", script],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "NODE_PATH": os.pathsep.join(
                    [str(SCRIPTS), str(ROOT / "node_modules"), os.environ.get("NODE_PATH", "")]
                ),
                "SAMPLE_PPTX": str(sample),
                "SAMPLE_TOKENS": json.dumps(self.tokens),
            },
        )
        if "Cannot find module 'pptxgenjs'" in result.stderr:
            self.skipTest("pptxgenjs is not installed")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            ["thesis", "weighted", "metric", "proof", "sequence", "figure"],
            [item["move"] for item in payload["slides"]],
        )
        for item in payload["slides"]:
            self.assertGreaterEqual(item["share"], 0.28, item)
        thesis = payload["slides"][0]
        self.assertGreaterEqual(thesis["primaryPt"], 44)
        self.assertGreater(thesis["primaryPt"], thesis["secondaryPt"])
        self.assertTrue(sample.is_file(), sample)
        self.assertTrue(sample.read_bytes().startswith(b"PK"), sample)

    def test_style_rule_and_chart_follow_visual_language(self) -> None:
        out = self.run_node(
            """
            const V = require(path.join(SCRIPTS, 'pptx-visuals.js'));
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const slide = mock();
            L.renderDeclaredPage(
              { slide, tokens: TOKENS, registry, slideNumber: 2, lang: 'chinese' },
              { kind: 'content', move: 'thesis',
                slots: { title: '课堂问题', claim: '模型优化的是像', body: ['而不是真'] } });
            const chartSlide = mock();
            V.addChartWithTakeaway(
              chartSlide,
              { series: [{ name: 'A', labels: ['甲'], values: [3] }], takeaway: '结论' },
              { x: 0.8, y: 1.2, w: 8, h: 3.2 },
              TOKENS,
              'chinese',
            );
            const chart = chartSlide.calls.find((call) => call.k === 'chart');
            console.log(JSON.stringify({
              rule: TOKENS.visual_language.rule,
              chart: TOKENS.visual_language.chart,
              width: registry._slide(2).find((el) => el.role === 'stat').w,
              area: H.contentArea(TOKENS, 'content').w,
              chartType: chart && chart.a[0],
            }));
            """
        )
        self.assertEqual("underline-left", out["rule"])
        self.assertEqual("line", out["chart"])
        self.assertAlmostEqual(out["width"], out["area"], places=2)
        self.assertEqual("line", out["chartType"])

    def test_sequence_emphasis_marker_replaces_the_lead_number(self) -> None:
        out = self.run_node(
            """
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const slide = mock();
            L.renderDeclaredPage(
              { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
              { kind: 'content', move: 'sequence', params: { emphasis: 2 },
                slots: { title: '步骤', claim: '先写下', body: ['收集', '核验', '写下'] } });
            const elements = registry._slide(1);
            console.log(JSON.stringify({
              marker: TOKENS.visual_language.emphasis_marker,
              stats: elements.filter((el) => el.role === 'stat').length,
              shapes: slide.calls.filter((call) => call.k === 'shape').length,
            }));
            """
        )
        self.assertEqual("dash", out["marker"])
        self.assertEqual(0, out["stats"])
        self.assertGreaterEqual(out["shapes"], 1)

    def test_short_thesis_owns_most_of_the_page(self) -> None:
        out = self.run_node(
            """
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const slide = mock();
            L.renderDeclaredPage(
              { slide, tokens: TOKENS, registry, slideNumber: 2, lang: 'chinese' },
              { kind: 'content', move: 'thesis',
                slots: { title: '问题', claim: '像', body: ['不是真'] } });
            const primary = registry._slide(2).find((el) => el.role === 'stat');
            const area = H.contentArea(TOKENS, 'content');
            console.log(JSON.stringify({
              share: primary ? (primary.w * primary.h) / (area.w * area.h) : 0,
            }));
            """
        )
        self.assertGreaterEqual(out["share"], 0.7)

    def test_primary_share_widens_the_judgment(self) -> None:
        out = self.run_node(
            """
            function claimWidth(share) {
              const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
              const slide = mock();
              L.renderDeclaredPage(
                { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
                { kind: 'content', move: 'weighted', params: { primaryShare: share },
                  slots: { title: '判断', claim: '主判断', body: ['支撑'] } });
              const claim = registry._slide(1).find((el) => el.role === 'stat');
              return claim.w;
            }
            console.log(JSON.stringify({ narrow: claimWidth(0.52), wide: claimWidth(0.74) }));
            """
        )
        self.assertGreater(out["wide"], out["narrow"])

    # --- 0.28.4: the style tokens that had no renderer ---------------------

    def test_style_rule_is_drawn_for_every_shipped_style(self) -> None:
        """`visual_language.rule` had no renderer at all: 12 styles, one skeleton.

        The field was declared by every style and read by nobody, so changing it
        had no effect on any page.
        """
        rows = {}
        for style in shipped_styles():
            rows[style] = self.run_node(
                """
                const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
                const slide = mock();
                let safe = 'ok';
                try {
                  L.renderDeclaredPage(
                    { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
                    { kind: 'content', move: 'thesis',
                      slots: { title: '课堂问题', claim: '干扰来自波动', body: ['而不是平均值'] } });
                  registry.assertSafe();
                } catch (error) { safe = String(error.message).slice(0, 90); }
                const rules = registry._slide(1).filter((el) => el.role === 'style_rule');
                console.log(JSON.stringify({
                  rule: TOKENS.visual_language.rule,
                  count: rules.length,
                  vertical: rules.filter((el) => el.type === 'line' && el.x1 === el.x2).length,
                  safe,
                }));
                """,
                tokens=resolved_tokens(style),
            )
        for style, out in rows.items():
            with self.subTest(style=style):
                self.assertEqual("ok", out["safe"])
                self.assertGreaterEqual(
                    out["count"], 1, f"{style} declares rule {out['rule']!r} and drew nothing"
                )
        # The five kinds must stay five distinguishable marks, not one shape.
        self.assertEqual(5, len({out["rule"] for out in rows.values()}))
        rails = [out for out in rows.values() if out["rule"] == "left-rail"]
        self.assertTrue(rails)
        self.assertTrue(all(out["vertical"] >= 1 for out in rails), "left-rail must be vertical")

    def test_motif_anchor_survives_token_resolution(self) -> None:
        """Three styles declare `edge-right`; outside the enum the motif was dropped."""
        import sys

        sys.path.insert(0, str(ROOT))
        from shared.design_tokens import resolve_design_tokens

        for style in ("Data Driven", "Ocean Tech", "Coral Energy"):
            with self.subTest(style=style):
                tokens = resolve_design_tokens(style)
                self.assertEqual(
                    "edge-right", tokens["background_directives"]["content"]["motif"], style
                )

    def test_outlined_panel_hugs_its_copy(self) -> None:
        """The focal panel was as tall as the band, so short copy left half of it blank."""
        out = self.run_node(
            """
            const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
            const slide = mock();
            L.renderDeclaredPage(
              { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
              { kind: 'content', move: 'thesis',
                slots: { title: '问题', claim: '扰动', body: ['支撑'] } });
            const surface = registry._slide(1).find((el) => el.role === 'surface');
            console.log(JSON.stringify({
              panel: TOKENS.visual_language.panel,
              band: H.contentArea(TOKENS, 'content').h,
              height: surface ? surface.h : null,
            }));
            """,
            tokens=resolved_tokens("Academic Rigorous"),
        )
        self.assertEqual("outlined", out["panel"])
        self.assertIsNotNone(out["height"])
        # Was 84% of the band (~4.2in); a one-line claim must not carry that much box.
        self.assertLess(out["height"], 2.0)
        self.assertGreater(out["height"], 0.6)

    def test_a_text_move_refuses_a_payload_it_cannot_draw(self) -> None:
        """metric/weighted/thesis/sequence used to drop a declared KPI payload silently."""
        out = self.run_node(
            """
            const payload = { type: 'dashboard', details: { items: ['31% 效率下降', '14 个采样夜'] } };
            const withPayload = (() => {
              const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
              const slide = mock();
              const res = L.renderDeclaredPage(
                { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
                { kind: 'content', move: 'metric',
                  slots: { title: '实测', claim: '波动组效率最低', body: ['平均 50 分贝'],
                           visual: payload } });
              return { move: res.move, fallback: res.fallbackFrom || null,
                       visual: registry._slide(1).filter((el) => el.role === 'visual').length };
            })();
            const plainNumber = (() => {
              const registry = new R.SlideElementRegistry({ slideW: 10, slideH: 5.625 });
              const slide = mock();
              const res = L.renderDeclaredPage(
                { slide, tokens: TOKENS, registry, slideNumber: 1, lang: 'chinese' },
                { kind: 'content', move: 'metric',
                  slots: { title: '结果', visual: { type: 'stat', value: '31%' } } });
              return { move: res.move, fallback: res.fallbackFrom || null };
            })();
            console.log(JSON.stringify({ withPayload, plainNumber }));
            """
        )
        self.assertEqual("metric", out["withPayload"]["fallback"])
        self.assertNotEqual("metric", out["withPayload"]["move"])
        self.assertGreaterEqual(out["withPayload"]["visual"], 1)
        # A one-figure metric page is still a metric page.
        self.assertEqual("metric", out["plainNumber"]["move"])
        self.assertIsNone(out["plainNumber"]["fallback"])


if __name__ == "__main__":
    unittest.main()
