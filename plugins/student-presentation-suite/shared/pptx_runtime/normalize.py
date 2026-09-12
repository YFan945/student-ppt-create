"""Normalize generated PPTX structures before schema validation.

Only fixes structures that cannot pass validation without mutation. The
<p:presentation> child order that pptxgenjs writes (notesMasterIdLst directly
after sldIdLst) is left untouched on disk: PowerPoint reads that order, and the
official pptx skill says never to reorder it. Schema validation reorders a
temporary copy instead (see validate._schema_preprocessed_package).
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as StdET
from pathlib import Path

from defusedxml import ElementTree as ET

from ._util import local as _local
from .package import pack_directory, safe_extract_package

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
StdET.register_namespace("c", C_NS)
StdET.register_namespace("a", A_NS)

_SLIDE_PART_DIRS = ("slides", "notesSlides")


def _fix_rich_text_paragraphs(root) -> int:
    """pptxgenjs 富文本缺陷：每个 run 之后都重复写一个 <a:pPr>。

    schema 规定 <a:p> 的 pPr 至多一个且必须是第一个子元素。删除所有
    非首位的 pPr，使行内强调（多 run 混排变色）合法可用。返回删除数。
    """
    removed = 0
    for paragraph in root.iter(f"{{{A_NS}}}p"):
        children = list(paragraph)
        pprs = [c for c in children if c.tag == f"{{{A_NS}}}pPr"]
        if len(pprs) < 2:
            continue
        # 合法写法：pPr 位于首位。首位之外的全部删除。
        for extra in pprs:
            if list(paragraph).index(extra) != 0:
                paragraph.remove(extra)
                removed += 1
    return removed


def normalize_unpacked(root: Path) -> list[str]:
    changed: list[str] = []
    for part_dir in _SLIDE_PART_DIRS:
        parts_root = root / "ppt" / part_dir
        if not parts_root.is_dir():
            continue
        for part_path in sorted(parts_root.glob("*.xml")):
            part = ET.parse(part_path).getroot()
            removed = _fix_rich_text_paragraphs(part)
            if removed:
                StdET.ElementTree(part).write(
                    part_path,
                    encoding="utf-8",
                    xml_declaration=True,
                )
                changed.append(f"{part_path.relative_to(root).as_posix()} (removed {removed} stray pPr)")
    charts_root = root / "ppt" / "charts"
    for chart_path in sorted(charts_root.glob("chart*.xml")) if charts_root.is_dir() else []:
        chart = ET.parse(chart_path).getroot()
        plot_area = chart.find(f".//{{{C_NS}}}plotArea")
        if plot_area is None:
            continue
        declared_axes = {
            axis_id.get("val")
            for axis_name in ("catAx", "dateAx", "valAx", "serAx")
            for axis in plot_area.findall(f"{{{C_NS}}}{axis_name}")
            for axis_id in axis.findall(f"{{{C_NS}}}axId")
            if axis_id.get("val")
        }
        chart_changed = False
        for chart_node in list(plot_area):
            if not _local(chart_node.tag).endswith("Chart"):
                continue
            for axis_id in list(chart_node.findall(f"{{{C_NS}}}axId")):
                if axis_id.get("val") not in declared_axes:
                    chart_node.remove(axis_id)
                    chart_changed = True
            # pptxgenjs line-chart 缺陷：漏写 <c:grouping>，且 ser 内带非法的
            # invertIfNegative（该元素只属于 barChart 的 ser）。两处都必须修，
            # 否则 OpenXML schema 校验失败。
            if _local(chart_node.tag) == "lineChart":
                if chart_node.find(f"{{{C_NS}}}grouping") is None:
                    grouping = StdET.Element(f"{{{C_NS}}}grouping", {"val": "standard"})
                    chart_node.insert(0, grouping)
                    chart_changed = True
                for ser in chart_node.findall(f"{{{C_NS}}}ser"):
                    broken = ser.find(f"{{{C_NS}}}invertIfNegative")
                    if broken is not None:
                        ser.remove(broken)
                        chart_changed = True
                    # ser 内 marker 必须紧跟 spPr（在 dLbls 之前），pptxgenjs 写在 dLbls 之后。
                    ser_marker = ser.find(f"{{{C_NS}}}marker")
                    if ser_marker is not None:
                        d_lbls = ser.find(f"{{{C_NS}}}dLbls")
                        if d_lbls is not None and list(ser).index(ser_marker) > list(ser).index(d_lbls):
                            ser.remove(ser_marker)
                            ser.insert(list(ser).index(d_lbls), ser_marker)
                            chart_changed = True
                # marker 必须位于 axId 之前；pptxgenjs 把它写到末尾。
                marker = chart_node.find(f"{{{C_NS}}}marker")
                if marker is not None:
                    ax_ids = chart_node.findall(f"{{{C_NS}}}axId")
                    if ax_ids and list(chart_node).index(marker) > list(chart_node).index(ax_ids[0]):
                        chart_node.remove(marker)
                        chart_node.insert(list(chart_node).index(ax_ids[0]), marker)
                        chart_changed = True
        # pptxgenjs 单系列多色柱状图把 <c:dPt> 写在 <c:dLbls> 之后，违反
        # CT_*Ser 的元素序列（dPt* 必须在 dLbls 之前），OpenXML SDK 校验直接
        # 报 unexpected child。把 dPt 统一移到 dLbls 之前（保持相对顺序）。
        for ser in plot_area.iter(f"{{{C_NS}}}ser"):
            d_lbls = ser.find(f"{{{C_NS}}}dLbls")
            if d_lbls is None:
                continue
            d_lbls_index = list(ser).index(d_lbls)
            for element in [
                element
                for element in ser.findall(f"{{{C_NS}}}dPt")
                if list(ser).index(element) > d_lbls_index
            ]:
                ser.remove(element)
                ser.insert(list(ser).index(d_lbls), element)
                chart_changed = True
        if chart_changed:
            StdET.ElementTree(chart).write(
                chart_path,
                encoding="utf-8",
                xml_declaration=True,
            )
            changed.append(chart_path.relative_to(root).as_posix())
    return changed


def normalize_generated_package(source: Path, output: Path) -> list[str]:
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("normalization output must differ from the generated source")
    if output.exists():
        raise FileExistsError(f"normalization output already exists: {output}")
    with tempfile.TemporaryDirectory(prefix="pptx-normalize-") as tmp:
        unpacked = Path(tmp) / "package"
        safe_extract_package(source, unpacked)
        changed = normalize_unpacked(unpacked)
        pack_directory(unpacked, output)
    return changed
