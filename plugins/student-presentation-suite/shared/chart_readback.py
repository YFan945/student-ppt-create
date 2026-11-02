"""Read visible native-chart labels through slide relationships, never hidden caches."""
from __future__ import annotations

import posixpath
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree import ElementTree as ET
from zipfile import ZipFile

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


class ChartRegion(str):
    """A visible label and its chart-local title/unit context."""
    def __new__(cls, text: str, contexts: tuple[str, ...] = ()):
        item = super().__new__(cls, text)
        item.contexts = contexts
        return item


def relationships(package: ZipFile, part: str) -> dict[str, str]:
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in package.namelist():
        return {}
    return {node.get("Id", ""): posixpath.normpath(posixpath.join(posixpath.dirname(part), node.get("Target", ""))).lstrip("/")
            for node in ET.fromstring(package.read(path)).findall(f"{{{PKG}}}Relationship")
            if node.get("TargetMode") != "External"}


def slide_parts(package: ZipFile) -> list[str]:
    if "ppt/presentation.xml" in package.namelist():
        rels = relationships(package, "ppt/presentation.xml")
        root = ET.fromstring(package.read("ppt/presentation.xml"))
        parts = [rels[node.get(f"{{{R}}}id")] for node in root.iter()
                 if node.tag.endswith("}sldId") and node.get(f"{{{R}}}id") in rels]
        if parts:
            return parts
    return sorted((name for name in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                  key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))


def flag(node: ET.Element | None, name: str, default: bool = False) -> bool:
    child = node.find(f"{{{C}}}{name}") if node is not None else None
    return child.get("val", "1") not in {"0", "false"} if child is not None else default


def points(node: ET.Element | None) -> dict[int, str]:
    return {int(point.get("idx", "0")): point.findtext(f"{{{C}}}v", "")
            for point in node.iter(f"{{{C}}}pt")} if node is not None else {}


def displayed_number(raw: str, code: str = "General") -> str | None:
    """Common Excel label formats. Unsupported formats stay for visual review."""
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    if code in {"", "General"}:
        return format(value.normalize(), "f")
    section = code.split(";")[1 if value < 0 and ";" in code else 0]
    # Retain literal positions. Unsupported Excel expressions are not guessed.
    pattern = re.sub(r'"([^"]*)"', r"\1", section)
    number = re.search(r"[#0][#0,]*(?:\.[#0]+)?", pattern)
    if not number or re.search(r"[\[\]_*?\\]", section):
        return None
    prefix, suffix = pattern[:number.start()], pattern[number.end():]
    if re.search(r"[0#]", prefix + suffix):
        return None
    if not re.fullmatch(r"[ %()+\-$€¥\w\u4e00-\u9fff]*", prefix + suffix):
        return None
    digits = number.group()
    scale = len(digits) - len(digits.rstrip(","))
    digits = digits.rstrip(",")
    value /= 1000 ** scale
    if "%" in pattern:
        value *= 100
    decimal = digits.split(".", 1)[1] if "." in digits else ""
    precision = len(decimal)
    explicit_negative = value < 0 and ";" in code
    if explicit_negative:
        value = abs(value)
    value = value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
    text = format(value, f",.{precision}f" if "," in digits.split(".")[0] else f".{precision}f")
    optional = len(decimal) - len(decimal.rstrip("#"))
    while optional and text.endswith("0"):
        text = text[:-1]
        optional -= 1
    return prefix + text.rstrip(".") + suffix


def chart_regions(package: ZipFile, slide: ET.Element, part: str) -> list[str]:
    rels = relationships(package, part)
    result: list[str] = []
    targets = dict.fromkeys(rels.get(node.get(f"{{{R}}}id", "")) for node in slide.iter(f"{{{C}}}chart"))
    for target in targets:
        if not target or target not in package.namelist():
            continue
        root = ET.fromstring(package.read(target))
        chart = root.find(f"{{{C}}}chart")
        if chart is None:
            continue
        title = "".join(node.text or "" for node in chart.findall(f"{{{C}}}title//{{{A}}}t"))
        contexts = (title,) if title else ()
        result.extend(contexts)
        legend = chart.find(f"{{{C}}}legend") is not None
        axes = chart.findall(f"{{{C}}}plotArea/{{{C}}}catAx")
        plot_area = chart.find(f"{{{C}}}plotArea")
        if plot_area is not None:
            result.extend("".join(node.text or "" for node in axis.findall(f"{{{C}}}title//{{{A}}}t"))
                          for axis in plot_area if axis.tag.endswith("Ax"))
        for plot in plot_area if plot_area is not None else []:
            pie = plot.tag in {f"{{{C}}}pieChart", f"{{{C}}}doughnutChart"}
            axis_ids = {node.get("val") for node in plot.findall(f"{{{C}}}axId")}
            categories_visible = any(not flag(axis, "delete") and axis.find(f"{{{C}}}tickLblPos[@val='none']") is None
                and axis.find(f"{{{C}}}axId") is not None and axis.find(f"{{{C}}}axId").get("val") in axis_ids for axis in axes)
            scoped = contexts + tuple("".join(node.text or "" for node in axis.findall(f"{{{C}}}title//{{{A}}}t"))
                for axis in plot_area if axis.find(f"{{{C}}}axId") is not None
                and axis.find(f"{{{C}}}axId").get("val") in axis_ids)
            for series in plot.findall(f"{{{C}}}ser"):
                name = "".join(node.text or "" for node in series.findall(f"{{{C}}}tx//{{{C}}}v"))
                if legend and name and not pie:
                    result.append(name)
                cats = points(series.find(f"{{{C}}}cat"))
                if categories_visible or pie and legend:
                    result.extend(cats.values())
                values_node = series.find(f"{{{C}}}val")
                values = points(values_node)
                default_format = values_node.findtext(f".//{{{C}}}formatCode", "General") if values_node is not None else "General"
                plot_labels = plot.find(f"{{{C}}}dLbls")
                series_labels = series.find(f"{{{C}}}dLbls")
                labels = series_labels if series_labels is not None else plot_labels
                for index, raw in values.items():
                    point = next((node for node in labels.findall(f"{{{C}}}dLbl")
                                  if node.find(f"{{{C}}}idx[@val='{index}']") is not None), None) if labels is not None else None
                    if flag(point, "delete", flag(labels, "delete")):
                        continue
                    custom = "".join(node.text or "" for node in point.findall(f"{{{C}}}tx//{{{A}}}t")) if point is not None else ""
                    category_label = flag(point, "showCatName", flag(labels, "showCatName", flag(plot_labels, "showCatName")))
                    series_label = flag(point, "showSerName", flag(labels, "showSerName", flag(plot_labels, "showSerName")))
                    if category_label and index in cats:
                        result.append(cats[index])
                    if series_label and name:
                        result.append(name)
                    text = custom
                    if not text and flag(point, "showVal", flag(labels, "showVal", flag(plot_labels, "showVal"))):
                        formatting = point.find(f"{{{C}}}numFmt") if point is not None else None
                        if formatting is None and labels is not None:
                            formatting = labels.find(f"{{{C}}}numFmt")
                        text = displayed_number(raw, formatting.get("formatCode", default_format) if formatting is not None else default_format)
                    if text:
                        result.append(ChartRegion(text, scoped))
                        if index in cats and (categories_visible or category_label or pie and legend):
                            result.append(ChartRegion(cats[index] + ":" + text, scoped))
                        if (legend and not pie or series_label) and name:
                            result.append(ChartRegion(name + ":" + text, scoped))
                    if not custom and flag(point, "showPercent", flag(labels, "showPercent", flag(plot_labels, "showPercent"))) and pie:
                        try:
                            if any(Decimal(value) < 0 for value in values.values()):
                                continue  # Negative pie semantics require visual inspection.
                            total = sum(Decimal(value) for value in values.values())
                            proportion = Decimal(raw) / total
                            formatting = point.find(f"{{{C}}}numFmt") if point is not None else None
                            if formatting is None and labels is not None:
                                formatting = labels.find(f"{{{C}}}numFmt")
                            code = formatting.get("formatCode", "0%") if formatting is not None else "0%"
                            percent = displayed_number(str(proportion), code if "%" in code else "0%")
                        except (InvalidOperation, ZeroDivisionError):
                            percent = None
                        if percent:
                            result.append(ChartRegion(percent, scoped))
                            if index in cats and (category_label or categories_visible or pie and legend):
                                result.append(ChartRegion(cats[index] + ":" + percent, scoped))
    return result
