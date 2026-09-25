"""addTextBox/assertTextFits regressions from the 2026-09-16 live run.

Three failure modes were silently swallowed by the helper and only surfaced in the
independent visual critique (verdict fail, 2.8/10):

1. a requested fontSize below the body floor was clamped to the floor with no
   signal at all — captions/data labels rendered at 22pt and overflowed;
2. a palette role name passed as `color` was accepted and produced unreadable
   text on dark pages (1.19:1 contrast);
3. `assertTextFits` printed "填充率 Infinity" whenever the box had no usable
   height left after margins, which tells the generator nothing.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "scripts" / "pptx-helpers.js"

TOKENS = """
{
  palette: {
    canvas: 'FFFFFF', surface: 'FFFFFF', primary_text: '182033',
    secondary_text: '5B6475', primary_accent: '990011', secondary_accent: '2F3C7E'
  },
  dark_palette: {
    canvas: '111829', surface: '1D263D', primary_text: 'E0C9C5',
    secondary_text: 'B89590', primary_accent: 'F04A5C', secondary_accent: '7E3038'
  },
  typography: { body_cjk_min_pt: 22 }
}
"""


def run_node(body: str) -> subprocess.CompletedProcess:
    script = f"""
const H = require({json.dumps(str(HELPERS))});
const tokens = {TOKENS};
const warnings = [];
const original = console.warn;
console.warn = (...args) => {{ warnings.push(args.join(' ')); }};
const slide = {{ calls: [], addText(text, options) {{ this.calls.push({{ text, options }}); return options; }} }};
try {{
{body}
}} catch (error) {{
  console.warn = original;
  if (error instanceof RangeError) process.exit(2);
  process.stderr.write(String(error && error.stack));
  process.exit(3);
}}
console.warn = original;
process.stdout.write(JSON.stringify({{ warnings, calls: slide.calls }}));
"""
    return subprocess.run(["node", "-e", script], cwd=ROOT, check=False, capture_output=True, text=True)


class AddTextBoxFloorTests(unittest.TestCase):
    def test_sub_body_font_size_warns_and_clamps(self) -> None:
        result = run_node(
            """
  H.addTextBox(slide, '数据标签 0.034', { x: 0.5, y: 0.5, w: 4, h: 1.2 }, tokens, 'chinese', { fontSize: 12, label: '数据标签' });
  if (slide.calls[0].options.fontSize !== 22) process.exit(4);
  if (!warnings.some((w) => w.includes('数据标签') && w.includes('12pt') && w.includes('22pt'))) process.exit(5);
  if (!warnings.some((w) => w.includes('role'))) process.exit(6);
"""
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_body_size_does_not_warn(self) -> None:
        result = run_node(
            """
  H.addTextBox(slide, '正文内容', { x: 0.5, y: 0.5, w: 3, h: 1.2 }, tokens, 'chinese', { fontSize: 24, label: '正文' });
  if (slide.calls[0].options.fontSize !== 24) process.exit(4);
  if (warnings.length) process.exit(5);
"""
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_role_route_provides_the_small_text_escape_hatch(self) -> None:
        result = run_node(
            """
  H.addTextBox(slide, '来源：IRENA 2024', { x: 0.5, y: 4.6, w: 6, h: 0.6 }, tokens, 'chinese', { role: 'source', margin: 4, label: '来源' });
  const size = slide.calls[0].options.fontSize;
  if (!(size > 0 && size <= 12)) process.exit(4);
"""
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


class ColorInputTests(unittest.TestCase):
    def test_palette_role_name_is_rejected(self) -> None:
        result = run_node(
            """
  H.addTextBox(slide, '深色页文本', { x: 0.5, y: 0.5, w: 3, h: 1 }, tokens, 'chinese', { color: 'primary_text', label: '深色文本' });
  process.exit(0);
"""
        )
        self.assertEqual(2, result.returncode, result.stdout)

    def test_resolved_hex_is_accepted(self) -> None:
        result = run_node(
            """
  H.addTextBox(slide, '深色页文本', { x: 0.5, y: 0.5, w: 3, h: 1 }, tokens, 'chinese', { color: H.color(tokens, 'primary_text'), label: '深色文本' });
  if (slide.calls[0].options.color !== '182033') process.exit(4);
  H.addFittedText(slide, '正文', { x: 0.5, y: 0.5, w: 3, h: 1 }, tokens, 'chinese', 'caption', { color: '#5B6475' });
  if (slide.calls[1].options.color !== '5B6475') process.exit(5);
"""
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


class OverflowMessageTests(unittest.TestCase):
    def test_zero_usable_height_explains_instead_of_infinity(self) -> None:
        result = run_node(
            """
  H.assertTextFits('很长的说明文字需要换行', 3, -0.2, 22, true, '注解');
  if (!warnings.length) process.exit(4);
  if (warnings[0].includes('Infinity') || warnings[0].includes('NaN')) process.exit(5);
  if (!warnings[0].includes('≤ 0')) process.exit(6);
"""
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
