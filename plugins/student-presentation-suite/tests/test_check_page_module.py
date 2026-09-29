"""check_page_module.js：builder 干跑自检正门（mock 幻灯片 + registry）。

2026-09-29 live：builder 盲写页面 → 主会话 build 后确定性门才暴露
text_overlap / near_miss / 溢出 → 一轮返工（10-20 分钟）。干跑把
这些发现合并进 builder 自己的回合。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_page_module.js"

GOOD_PAGE = """'use strict';
const L = require('pptx-layouts');
module.exports = function (ctx) {
  const { slide, registry, tokens, H } = ctx;
  const dark = false;
  H.renderBackground(slide, tokens, { kind: 'content', dark });
  const pt = H.paletteMode(tokens, 'light');
  L.renderArchetype({ ...ctx, tokens: pt }, {
    layout: { id: 'claim-focus' },
    slots: { title: '合规页标题', claim: '一句话主张，长度合理', body: ['要点一', '要点二'] },
  });
  slide.addNotes('notes');
};
"""

BAD_PAGE = """'use strict';
module.exports = function (ctx) {
  const { slide, registry } = ctx;
  registry.register(2, { type: 'text', text: '甲处文本', x: 1, y: 1, w: 3, h: 1, fontSize: 20 });
  registry.register(2, { type: 'text', text: '乙处文本', x: 1.2, y: 1.1, w: 3, h: 1, fontSize: 20 });
  slide.addText('甲处文本', { x: 1, y: 1, w: 3, h: 1, color: '000000' });
};
"""


class CheckPageModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "wd"
        (self.work / "pages").mkdir(parents=True)
        tokens = {
            "palette": {"canvas": "F8FAFC", "surface": "FFFFFF", "primary_text": "111827",
                        "secondary_text": "6B7280", "primary_accent": "2563EB", "secondary_accent": "93C5FD"},
            "dark_palette": {"canvas": "15171B"},
            "lines": {"hairline_pt": 0.75, "standard_pt": 1.25},
            "typography": {"title_min_pt": 32, "title_max_pt": 44, "subtitle_min_pt": 26,
                           "body_cjk_min_pt": 22, "body_max_pt": 22, "label_min_pt": 16},
        }
        (self.work / "deck.js").write_text(
            "const TOKENS = " + json.dumps(tokens) + ";" + chr(10) + "module.exports = {};" + chr(10),
            encoding="utf-8"
        )

    def run_check(self, pages: dict[str, str]) -> tuple[int, dict]:
        for name, body in pages.items():
            (self.work / name).write_text(body, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(SCRIPT), "--work-dir", str(self.work), "--pages", ",".join(pages)],
            capture_output=True, text=True, timeout=120,
        )
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = {}
        return proc.returncode, report

    def test_clean_page_passes(self) -> None:
        code, report = self.run_check({"pages/p01-good.js": GOOD_PAGE})
        self.assertEqual(0, code, report)

    def test_overlapping_and_offpalette_page_is_blocked_with_findings(self) -> None:
        code, report = self.run_check({"pages/p02-bad.js": BAD_PAGE})
        self.assertEqual(1, code)
        codes = {f.get("kind") or f.get("code") for f in report["findings"]}
        self.assertIn("registry", codes)
        self.assertIn("off-palette", codes)

    def test_declarative_page_runs_through_the_same_glue(self) -> None:
        page = """'use strict';
const COPY = { title: '声明式页标题', claim: '一句话主张，长度合理', keyLine: '收尾结论句', slideCopy: ['要点一'] };
module.exports = {
  dark: false,
  kind: 'content',
  context: { slideId: 3, slideKind: 'content', itemCount: 1, titleChars: 6 },
  slots: { title: COPY.title, claim: COPY.claim, key_line: COPY.keyLine, body: COPY.slideCopy },
  params: {},
  notes: '本页讲稿。',
};
"""
        code, report = self.run_check({"pages/p03-decl.js": page})
        self.assertEqual(0, code, report)

    def test_missing_notes_and_scaffold_marker_are_reported(self) -> None:
        notesless = """'use strict';
const COPY = { title: '无讲稿页标题', claim: '一句话主张，长度合理' };
module.exports = { dark: false, kind: 'content', context: { slideId: 4, itemCount: 0 },
  slots: { title: COPY.title, claim: COPY.claim }, params: {}, notes: '' };
"""
        stub = """'use strict';
/* student-presentation-suite-scaffold */
module.exports = function () {};
"""
        code, report = self.run_check(
            {"pages/p04-nonotes.js": notesless, "pages/p05-stub.js": stub}
        )
        self.assertEqual(1, code)
        kinds = {f["kind"] for f in report["findings"]}
        self.assertIn("notes", kinds)
        self.assertIn("scaffold", kinds)

    def test_throwing_page_module_is_reported(self) -> None:
        code, report = self.run_check(
            {"pages/p03-throw.js": "module.exports = function(){ throw new Error('boom'); };"}
        )
        self.assertEqual(1, code)
        self.assertEqual("throw", report["findings"][0]["kind"], report)


if __name__ == "__main__":
    unittest.main()
