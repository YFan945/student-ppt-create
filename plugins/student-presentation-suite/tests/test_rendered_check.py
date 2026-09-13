"""Tests for the rendered-artifact visual readback gate (pptx_rendered_check)."""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "skills" / "sp-deck" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pptx_rendered_check as rendered_check  # noqa: E402

PRESENTATION = '<p:sldSz cx="9144000" cy="5143500"/>'
# Body 22pt everywhere, title 33pt -> ratio 1.5 >= 32/22; footer anchors the bottom.
SLIDE_OK = (
    '<p:sp><p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="6000000" cy="600000"/></p:spPr>'
    '<p:txBody><a:p><a:r><a:rPr lang="zh-CN" sz="2200"/><a:t>正文</a:t></a:r></a:p></p:txBody></p:sp>'
    '<p:sp><p:spPr><a:xfrm><a:off x="914400" y="3200000"/><a:ext cx="6000000" cy="600000"/></p:spPr>'
    '<p:txBody><a:p><a:r><a:rPr lang="zh-CN" sz="3300"/><a:t>标题</a:t></a:r></a:p></p:txBody></p:sp>'
    '<p:sp><p:spPr><a:xfrm><a:off x="914400" y="6458000"/><a:ext cx="6000000" cy="300000"/></p:spPr>'
    '<p:txBody><a:p><a:r><a:rPr lang="zh-CN" sz="1300"/><a:t>页脚</a:t></a:r></a:p></p:txBody></p:sp>'
)
CHART_OK = (
    '<c:chartSpace><c:chart><c:plotArea>'
    '<c:valAx><c:scaling><c:orientation val="minMax"/><c:max val="80.0"/><c:min val="0.0"/></c:scaling></c:valAx>'
    '</c:plotArea></c:chart></c:chartSpace>'
)
CHART_AUTO = CHART_OK.replace('<c:max val="80.0"/><c:min val="0.0"/>', "")
# 9pt run + nothing below mid-slide.
SLIDE_BAD = (
    '<p:sp><p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="6000000" cy="600000"/></p:spPr>'
    '<p:txBody><a:p><a:r><a:rPr lang="zh-CN" sz="900"/><a:t>过小</a:t></a:r></a:p></p:txBody></p:sp>'
)


def _make_pptx(directory: Path, slide_xml: str, chart_xml: str | None = None) -> Path:
    path = directory / "deck.pptx"
    entries = {"ppt/presentation.xml": PRESENTATION, "ppt/slides/slide1.xml": slide_xml}
    if chart_xml:
        entries["ppt/charts/chart1.xml"] = chart_xml
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class RenderedCheckTests(unittest.TestCase):
    def test_clean_deck_passes_all_metrics(self) -> None:
        with TemporaryDirectory() as tmp:
            report = rendered_check.check_pptx(_make_pptx(Path(tmp), SLIDE_OK, CHART_OK), {})
            self.assertTrue(report["ok"], report["issues"])
            self.assertEqual([], report["issues"])
            metrics = report["metrics"]
            self.assertEqual(22.0, metrics["font_mode_pt"])
            self.assertEqual(1.5, metrics["title_body_ratio"])
            self.assertEqual({"total": 1, "with_val_axis": 1, "axis_unbounded": 0}, metrics["charts"])

    def test_small_font_triggers_font_below_floor(self) -> None:
        with TemporaryDirectory() as tmp:
            report = rendered_check.check_pptx(_make_pptx(Path(tmp), SLIDE_BAD), {})
            codes = {i["code"] for i in report["issues"]}
            self.assertIn("font-below-floor", codes)

    def test_flat_font_hierarchy_triggers_ratio_finding(self) -> None:
        flat = SLIDE_OK.replace('sz="3300"', 'sz="2600"')
        with TemporaryDirectory() as tmp:
            report = rendered_check.check_pptx(_make_pptx(Path(tmp), flat), {})
            codes = {i["code"] for i in report["issues"]}
            self.assertIn("title-body-ratio", codes)

    def test_auto_scaled_axis_triggers_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            report = rendered_check.check_pptx(_make_pptx(Path(tmp), SLIDE_OK, CHART_AUTO), {})
            codes = {i["code"] for i in report["issues"]}
            self.assertIn("chart-axis-auto", codes)

    def test_bottom_dead_space_triggers_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            report = rendered_check.check_pptx(_make_pptx(Path(tmp), SLIDE_BAD), {})
            codes = {i["code"] for i in report["issues"]}
            self.assertIn("dead-space", codes)

    def test_exit_codes_fail_closed_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            bad = _make_pptx(Path(tmp), SLIDE_BAD)
            argv_base = ["--pptx", str(bad)]
            with mock.patch.object(sys, "argv", ["gate", *argv_base]):
                self.assertEqual(2, rendered_check.main())
            with mock.patch.object(sys, "argv", ["gate", *argv_base, "--lenient"]):
                self.assertEqual(0, rendered_check.main())


if __name__ == "__main__":
    unittest.main()
