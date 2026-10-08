"""Deterministic visual components must support asymmetric (non-equal) layouts.

The "equal card" output of addComparison / addProcessFlow / addMetricDashboard
was identified as the biggest source of AI-template feel. Two columns may stay
equal. Three or more columns without a real weight spread are drawn with the
first column wider. Short string lists are a weighted list, not equal KPI cards.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
const V = require('pptx-visuals');
function stub() {
  return {
    shapes: [],
    texts: [],
    addShape(name, o) { this.shapes.push({ name, o }); },
    addText(_text, options) { this.texts.push(options || {}); },
  };
}
const tokens = {
  palette: {
    canvas: 'FFFFFF', surface: 'F1F5F9', primary_text: '0F172A',
    secondary_text: '475569', primary_accent: '2563EB', secondary_accent: '93C5FD',
  },
};
const area = { x: 0.6, y: 1, w: 8.8, h: 3 };
function widths(component, data) {
  const s = stub();
  component(s, data, area, tokens, 'chinese');
  return s.shapes.filter((x) => x.name === 'roundRect').map((x) => x.o.w);
}
function textColumnWidths(component, data) {
  const s = stub();
  component(s, data, area, tokens, 'chinese');
  return s.texts.map((t) => t.w).filter((w) => w > 0.8);
}
const out = {};
out.equal = widths(V.addComparison, { items: ['A', 'B'] });
out.asym = widths(V.addComparison, { items: ['A', 'B'], highlight: 1 });
out.weights = widths(V.addComparison, { items: ['A', 'B'], weights: [3, 1] });
out.dashboard = widths(V.addMetricDashboard, {
  metrics: [{ value: '1', label: 'a' }, { value: '2', label: 'b' }, { value: '3', label: 'c' }],
  emphasis: 1,
});
out.flow = textColumnWidths(V.addProcessFlow, { steps: ['a', 'b', 'c'], weights: [2, 1, 1] });
out.flatThree = textColumnWidths(V.addProcessFlow, { steps: ['a', 'b', 'c'] });
const listSlide = stub();
V.renderVisual(listSlide, 'dashboard', { items: ['甲', '乙', '丙'] }, area, tokens, 'chinese');
out.listHeights = listSlide.shapes.filter((x) => x.name === 'roundRect').map((x) => x.o.h);
out.listWidths = listSlide.shapes.filter((x) => x.name === 'roundRect').map((x) => x.o.w);
console.log(JSON.stringify(out));
"""


class VisualComponentAsymmetryTests(unittest.TestCase):
    def _run_node(self) -> dict:
        result = subprocess.run(
            ["node", "-e", SCRIPT],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "NODE_PATH": str(ROOT / "scripts")},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_comparison_defaults_to_equal_columns(self) -> None:
        widths = self._run_node()["equal"]
        self.assertAlmostEqual(widths[0], widths[1], places=6)

    def test_highlight_applies_default_asymmetric_tilt(self) -> None:
        widths = self._run_node()["asym"]
        self.assertGreater(widths[1], widths[0])
        self.assertAlmostEqual(widths[1] / widths[0], 1.55, places=2)

    def test_explicit_weights_are_honored(self) -> None:
        widths = self._run_node()["weights"]
        self.assertAlmostEqual(widths[0] / widths[1], 3.0, places=2)

    def test_dashboard_emphasis_widens_one_metric(self) -> None:
        widths = self._run_node()["dashboard"]
        self.assertGreater(widths[1], widths[0])
        self.assertGreater(widths[1], widths[2])
        self.assertAlmostEqual(widths[0], widths[2], places=6)

    def test_process_flow_supports_weights(self) -> None:
        widths = self._run_node()["flow"]
        self.assertAlmostEqual(widths[0] / widths[1], 2.0, places=2)
        self.assertAlmostEqual(widths[1], widths[2], places=6)

    def test_three_columns_without_weights_are_not_equal(self) -> None:
        widths = self._run_node()["flatThree"]
        self.assertGreater(widths[0], widths[1])
        self.assertGreater(widths[0], widths[2])

    def test_short_string_list_is_not_an_equal_kpi_row(self) -> None:
        result = self._run_node()
        heights = result["listHeights"]
        widths = result["listWidths"]
        self.assertGreaterEqual(len(heights), 3)
        self.assertGreater(heights[0], heights[1])
        self.assertTrue(all(w < 0.3 for w in widths))


if __name__ == "__main__":
    unittest.main()
