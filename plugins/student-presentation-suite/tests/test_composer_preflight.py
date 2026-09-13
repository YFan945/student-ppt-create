"""Behavioral tests for composer preflight (review item 26: docs→behavior).

pptx-production.md promises a "safety preflight" that rejects compositions
whose zones fall outside the canvas and requires caller-supplied zones in
adaptive-freeform mode. These tests exercise the real composer instead of
asserting the doc mentions it.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]

NODE_SCRIPT = r"""
const path = require('path');
const composer = require(process.argv[2] + '/scripts/pptx-composer.js');
const cases = JSON.parse(process.argv[3]);
const ctx = {
  tokens: {},
  lang: 'chinese',
  safeArea: { x: 0.5, y: 1.2, w: 9, h: 4 },
  slideW: 10,
  slideH: 5.625,
};
const out = {};
if (cases.includes('no-composition')) {
  const r = composer.preflightSlide(
    { id: 1, title: '契约测试标题', kind: 'content', role: 'content', slide_copy: '正文内容' },
    ctx,
  );
  out.noComposition = { ok: r.ok, errors: r.errors };
}
if (cases.includes('valid-zones')) {
  const ctx2 = {
    ...ctx,
    composition: {
      silhouette: 'custom',
      zones: {
        title: { x: 0.5, y: 0.4, w: 9, h: 0.8 },
        body: { x: 0.5, y: 1.4, w: 9, h: 3.4 },
      },
    },
  };
  const r = composer.preflightSlide(
    { id: 1, title: '契约测试标题', kind: 'content', role: 'content', slide_copy: '正文内容' },
    ctx2,
  );
  out.validZones = {
    ok: r.ok,
    hasComposition: Boolean(r.composition && r.composition.zones && r.composition.zones.title),
    errors: r.errors,
  };
}
if (cases.includes('out-of-canvas')) {
  const ctx3 = {
    ...ctx,
    composition: {
      silhouette: 'custom',
      zones: {
        title: { x: 0.5, y: 0.4, w: 9, h: 99 },
        body: { x: 0.5, y: 1.4, w: 9, h: 3.4 },
      },
    },
  };
  const r = composer.preflightSlide(
    { id: 1, title: '契约测试标题', kind: 'content', role: 'content', slide_copy: '正文内容' },
    ctx3,
  );
  out.outOfCanvas = { ok: r.ok, errors: r.errors };
}
if (cases.includes('deck-preflight-message')) {
  const PptxGenJS = require(path.join(process.argv[2], 'node_modules', 'pptxgenjs'));
  try {
    composer.renderDeck(
      new PptxGenJS(),
      { meta: { topic: 'contract' }, slides: [
        { id: 1, title: '契约测试标题', kind: 'content', role: 'content', slide_copy: '正文内容' },
      ] },
      ctx,
    );
    out.deckMessage = null;
  } catch (error) {
    out.deckMessage = String(error.message);
  }
}
console.log(JSON.stringify(out));
"""


class ComposerPreflightBehaviorTests(unittest.TestCase):
    @classmethod
    def _run(cls, *cases: str) -> dict:
        import os

        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "preflight-cases.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            env = {**os.environ, "NODE_PATH": str(ROOT / "scripts")}
            result = subprocess.run(
                ["node", str(script), str(ROOT), json.dumps(list(cases))],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                env=env,
            )
        return json.loads(result.stdout)

    def test_missing_composition_zones_blocks_preflight(self) -> None:
        out = self._run("no-composition")
        self.assertFalse(out["noComposition"]["ok"])
        joined = " ".join(out["noComposition"]["errors"])
        self.assertIn("requires caller-supplied composition zones", joined)

    def test_supplied_zones_pass_and_carry_composition(self) -> None:
        out = self._run("valid-zones")
        self.assertTrue(out["validZones"]["ok"], out["validZones"]["errors"])
        self.assertTrue(out["validZones"]["hasComposition"])

    def test_zone_outside_canvas_is_rejected(self) -> None:
        out = self._run("out-of-canvas")
        self.assertFalse(out["outOfCanvas"]["ok"])
        joined = " ".join(out["outOfCanvas"]["errors"])
        self.assertIn("outside the slide canvas", joined)

    def test_deck_preflight_error_names_slide_and_details(self) -> None:
        """审查第 23 条：抛错要带每页明细，不能只给 slide_id。"""
        out = self._run("deck-preflight-message")
        message = out["deckMessage"]
        self.assertIsNotNone(message)
        self.assertIn("Deck preflight failed on slides", message)
        self.assertIn("1(", message)
        self.assertIn("composition zones", message)


if __name__ == "__main__":
    unittest.main()
