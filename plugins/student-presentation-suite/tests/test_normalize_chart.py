"""pptxgenjs per-point chart colours (c:dPt) must survive OpenXML validation.

pptxgenjs writes <c:dPt> AFTER <c:dLbls> when a single-series bar chart uses
per-point colours (accentRamp). CT_*Ser requires dPt* BEFORE dLbls, so the
OpenXML SDK rejects the file with "unexpected child element dPt".
normalize_unpacked re-orders the series children; these tests pin that repair.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from shared.pptx_runtime.normalize import normalize_unpacked

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"

# 顺序模拟 pptxgenjs 原始输出：dLbls 在 dPt 之前（非法）。
SER_BROKEN = (
    "<c:ser>"
    '<c:idx val="0"/><c:order val="0"/>'
    "<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f></c:strRef></c:tx>"
    '<c:spPr/><c:invertIfNegative val="0"/>'
    "<c:dLbls/>"
    '<c:dPt><c:idx val="0"/><c:invertIfNegative val="0"/><c:spPr/></c:dPt>'
    '<c:dPt><c:idx val="1"/><c:invertIfNegative val="0"/><c:spPr/></c:dPt>'
    "<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$4</c:f></c:strRef></c:cat>"
    '<c:val><c:numRef><c:f>Sheet1!$B$2:$B$4</c:f></c:numRef></c:val>'
    "</c:ser>"
)
# 已符合序列的 ser：normalize 不得改动。
SER_OK = SER_BROKEN.replace("<c:dLbls/>", "").replace(
    "</c:dLbls>",
    "",
)


def _ser_children_order(chart_xml: str) -> list[str]:
    root = ET.fromstring(chart_xml)
    ser = next(element for element in root.iter() if element.tag.endswith("}ser"))
    return [element.tag.split("}")[1] for element in list(ser)]


def _chart_xml(ser_inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{C_NS}"><c:chart><c:plotArea>'
        f"<c:barChart>{ser_inner}</c:barChart>"
        '<c:valAx><c:axId val="1"/></c:valAx>'
        "</c:plotArea></c:chart></c:chartSpace>"
    )


class ChartSeriesNormalizeTests(unittest.TestCase):
    def test_dpt_points_move_before_dlbls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            charts = root / "ppt" / "charts"
            charts.mkdir(parents=True)
            (charts / "chart1.xml").write_text(_chart_xml(SER_BROKEN), encoding="utf-8")

            changed = normalize_unpacked(root)

            self.assertTrue(changed)
            fixed = (charts / "chart1.xml").read_text(encoding="utf-8")
            order = _ser_children_order(fixed)
            # dPt* 必须全部位于 dLbls 之前，且相对顺序保持。
            self.assertEqual(
                ["idx", "order", "tx", "spPr", "invertIfNegative", "dPt", "dPt", "dLbls", "cat", "val"],
                order,
            )

    def test_already_ordered_chart_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            charts = root / "ppt" / "charts"
            charts.mkdir(parents=True)
            # 构造"dPt 已在 dLbls 之前"的合法 ser：normalize 不得改动。
            ordered = (
                "<c:ser>"
                '<c:idx val="0"/><c:order val="0"/>'
                "<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f></c:strRef></c:tx>"
                '<c:spPr/><c:invertIfNegative val="0"/>'
                '<c:dPt><c:idx val="0"/><c:invertIfNegative val="0"/><c:spPr/></c:dPt>'
                '<c:dPt><c:idx val="1"/><c:invertIfNegative val="0"/><c:spPr/></c:dPt>'
                "<c:dLbls/>"
                "<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$4</c:f></c:strRef></c:cat>"
                '<c:val><c:numRef><c:f>Sheet1!$B$2:$B$4</c:f></c:numRef></c:val>'
                "</c:ser>"
            )
            (charts / "chart1.xml").write_text(_chart_xml(ordered), encoding="utf-8")

            changed = normalize_unpacked(root)

            self.assertEqual([], changed)
            fixed = (charts / "chart1.xml").read_text(encoding="utf-8")
            order = _ser_children_order(fixed)
            self.assertEqual(
                ["idx", "order", "tx", "spPr", "invertIfNegative", "dPt", "dPt", "dLbls", "cat", "val"],
                order,
            )


if __name__ == "__main__":
    unittest.main()
