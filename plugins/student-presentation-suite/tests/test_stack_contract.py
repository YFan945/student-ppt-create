"""Python ↔ Node stack contract tests (review architecture item D).

The two stacks had conflicting assumptions about the same artifacts:

* canvas size — ``pptx-helpers.js`` builds decks at 10×5.625in (STUDENT_WIDE),
  while Python fallbacks assumed 13.333×7.5in;
* slide count — ``workflow_guard``/``pptx_delivery_check`` count zip entries
  under ``ppt/slides/``, while ``pptx_runtime.package`` counts direct
  ``<p:sldId>`` children of the main ``sldIdLst``;
* font hierarchy — ``art_direction_check.py`` hardcodes a 1.45 title/body
  ratio gate, ``design-tokens.json`` supplies title_min_pt/body_cjk_min_pt,
  and ``pptx_rendered_check.py`` re-measures rendered runs.

These tests pin the stacks to the same numbers, using one artifact generated
by the real Node pipeline.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.pptx_runtime.package import count_registered_slides  # noqa: E402
from shared.pptx_static_core import (  # noqa: E402
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    slide_size,
)

NODE_SCRIPT = r"""
const path = require('path');
const pluginRoot = process.argv[2];
const outPath = process.argv[3];
const PptxGenJS = require(path.join(pluginRoot, 'node_modules', 'pptxgenjs'));
const H = require(path.join(pluginRoot, 'scripts', 'pptx-helpers.js'));
const pptx = new PptxGenJS();
H.applyTokens(pptx, {}, 'chinese');
for (let i = 0; i < 3; i++) {
  const slide = pptx.addSlide();
  slide.addText('契约测试 ' + (i + 1), { x: 1, y: 1, w: 4, h: 0.5, fontSize: 22 });
}
pptx.writeFile({ fileName: outPath }).then(() => console.log('written'));
"""


def _read_js_constants() -> tuple[float, float]:
    code = (
        "const H = require(process.argv[1] + '/scripts/pptx-helpers.js');"
        "console.log(H.SLIDE_W_IN, H.SLIDE_H_IN);"
    )
    result = subprocess.run(
        ["node", "-e", code, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    width, height = result.stdout.split()
    return float(width), float(height)


class StackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.deck = Path(cls.tmp.name) / "contract-deck.pptx"
        script = Path(cls.tmp.name) / "make-deck.js"
        script.write_text(NODE_SCRIPT, encoding="utf-8")
        subprocess.run(
            ["node", str(script), str(ROOT), str(cls.deck)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_canvas_constants_agree_across_stacks(self) -> None:
        js_width_in, js_height_in = _read_js_constants()
        self.assertEqual(round(js_width_in * 914400), DEFAULT_SLIDE_WIDTH_EMU)
        self.assertEqual(round(js_height_in * 914400), DEFAULT_SLIDE_HEIGHT_EMU)

    def test_generated_deck_uses_the_shared_canvas(self) -> None:
        """真实产物写入的 sldSz 与两侧常量一致，Python 兜底永不偏航。"""
        import zipfile

        with zipfile.ZipFile(self.deck) as zf:
            width, height = slide_size(zf)
        self.assertEqual((width, height), (DEFAULT_SLIDE_WIDTH_EMU, DEFAULT_SLIDE_HEIGHT_EMU))
        self.assertEqual((width, height), (9_144_000, 5_143_500))

    def test_slide_count_methods_agree_on_real_artifact(self) -> None:
        from scripts.workflow_guard import count_slides as count_slide_files

        # zip 条目口径（workflow_guard / pptx_delivery_check）与
        # sldIdLst 直系子元素口径（pptx_runtime.package）必须一致。
        self.assertEqual(3, count_slide_files(self.deck))
        self.assertEqual(3, count_registered_slides(self.deck))

    def test_font_ratio_sources_agree(self) -> None:
        sys.path.insert(0, str(ROOT / "skills" / "sp-deck" / "scripts"))
        import pptx_rendered_check  # noqa: PLC0415

        tokens = json.loads(
            (ROOT / "references" / "design-tokens.json").read_text(encoding="utf-8")
        )
        typo = tokens.get("defaults", tokens)["typography"]
        ratio = typo["title_min_pt"] / typo["body_cjk_min_pt"]
        # art_direction_check.py:97 hardcodes 1.45 — the tokens must always be
        # able to satisfy the gate they feed, or "declared compliant" is a lie.
        self.assertGreaterEqual(ratio, 1.45)
        # rendered check must read the same tokens file, so its rendered-side
        # requirement is identical to the declared-side gate.
        self.assertEqual(
            pptx_rendered_check.DEFAULT_TOKENS, ROOT / "references" / "design-tokens.json"
        )
        self.assertEqual(round(ratio, 3), 1.455)


if __name__ == "__main__":
    unittest.main()
