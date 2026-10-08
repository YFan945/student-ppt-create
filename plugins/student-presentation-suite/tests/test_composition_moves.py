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


def resolved_tokens() -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    from shared.design_tokens import resolve_design_tokens

    return resolve_design_tokens("Modern Minimal")


class CompositionMoveTests(unittest.TestCase):
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
            f"const C=require({json.dumps(str(SCRIPTS / 'pptx-composition.js'))});"
            f"const H=require({json.dumps(str(SCRIPTS / 'pptx-helpers.js'))});"
            f"const R=require({json.dumps(str(SCRIPTS / 'pptx-element-registry.js'))});"
            f"const TOKENS={json.dumps(self.tokens)};"
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


if __name__ == "__main__":
    unittest.main()
