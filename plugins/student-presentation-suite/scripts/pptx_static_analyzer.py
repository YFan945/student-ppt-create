#!/usr/bin/env python3
"""Inspect the actual PPTX artifact for geometry and text-fit risks.

This analyzer intentionally runs *after* PptxGenJS/OOXML production so the objects
being inspected are the same objects that will be rendered. It is conservative:
only objective geometry failures are blockers; suspicious overlaps/text-fit are
reported as warnings for the render-review loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

EMU_PER_INCH = 914400
PT_PER_INCH = 72

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


@dataclass
class Element:
    kind: str
    name: str
    box: Box
    text: str
    font_pt: float | None


@dataclass
class Finding:
    severity: str
    code: str
    slide: int
    target: str
    message: str
    details: dict[str, Any]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inch(value: str | None) -> float:
    try:
        return int(value or 0) / EMU_PER_INCH
    except (TypeError, ValueError):
        return 0.0


def _font_pt(value: str | None) -> float | None:
    try:
        return int(value or 0) / 100
    except (TypeError, ValueError):
        return None


def _shape_name(node: ET.Element, fallback: str) -> str:
    nv = node.find(".//p:cNvPr", NS)
    return (nv.get("name") if nv is not None else None) or fallback


def _box_from_node(node: ET.Element) -> Box | None:
    # Most slide objects ultimately carry DrawingML xfrm/off/ext. Search locally
    # rather than assuming one concrete OOXML object type.
    xfrm = node.find(".//a:xfrm", NS)
    if xfrm is None:
        xfrm = node.find(".//p:xfrm", NS)
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    if off is None:
        off = xfrm.find("p:off", NS)
    ext = xfrm.find("a:ext", NS)
    if ext is None:
        ext = xfrm.find("p:ext", NS)
    if off is None or ext is None:
        return None
    return Box(
        x=_inch(off.get("x")),
        y=_inch(off.get("y")),
        w=_inch(ext.get("cx")),
        h=_inch(ext.get("cy")),
    )


def _text(node: ET.Element) -> str:
    values = [t.text or "" for t in node.findall(".//a:t", NS)]
    return "".join(values).strip()


def _dominant_font_pt(node: ET.Element) -> float | None:
    sizes: list[float] = []
    for rpr in node.findall(".//a:rPr", NS) + node.findall(".//a:defRPr", NS):
        size = _font_pt(rpr.get("sz"))
        if size:
            sizes.append(size)
    return max(sizes) if sizes else None


def _kind(node: ET.Element) -> str:
    tag = node.tag.rsplit("}", 1)[-1]
    return {
        "sp": "shape",
        "pic": "image",
        "graphicFrame": "graphic",
        "cxnSp": "connector",
    }.get(tag, tag)


def _elements(root: ET.Element) -> list[Element]:
    result: list[Element] = []
    candidates = root.findall(".//p:sp", NS) + root.findall(".//p:pic", NS) + root.findall(".//p:graphicFrame", NS)
    for index, node in enumerate(candidates, start=1):
        box = _box_from_node(node)
        if box is None:
            continue
        kind = _kind(node)
        result.append(
            Element(
                kind=kind,
                name=_shape_name(node, f"{kind}-{index}"),
                box=box,
                text=_text(node),
                font_pt=_dominant_font_pt(node),
            )
        )
    return result


def _intersection(a: Box, b: Box) -> float:
    w = max(0.0, min(a.right, b.right) - max(a.x, b.x))
    h = max(0.0, min(a.bottom, b.bottom) - max(a.y, b.y))
    return w * h


def _overlap_ratio(a: Box, b: Box) -> float:
    inter = _intersection(a, b)
    smaller = min(a.area, b.area)
    return inter / smaller if smaller > 0 else 0.0


def _estimated_text_height(text: str, box: Box, font_pt: float) -> tuple[int, float]:
    if not text or box.w <= 0 or box.h <= 0:
        return (0, 0.0)
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff")
    ratio = cjk / max(1, len(text))
    # Conservative mixed-script width approximation. We intentionally prefer
    # false-positive warnings over silently clipping text, but never make this
    # heuristic a blocker by itself.
    avg_char_in = (font_pt / PT_PER_INCH) * (0.92 if ratio >= 0.35 else 0.55)
    chars_per_line = max(1, int(box.w / max(avg_char_in, 0.01)))
    lines = 0
    for paragraph in text.splitlines() or [text]:
        lines += max(1, math.ceil(max(1, len(paragraph)) / chars_per_line))
    line_height = (font_pt / PT_PER_INCH) * 1.28
    return lines, lines * line_height


def analyze_slide(slide_no: int, root: ET.Element, slide_w: float, slide_h: float) -> tuple[list[Element], list[Finding]]:
    elems = _elements(root)
    findings: list[Finding] = []
    eps = 0.015

    for elem in elems:
        b = elem.box
        if b.w <= 0 or b.h <= 0:
            findings.append(Finding("blocker", "degenerate_box", slide_no, elem.name, "元素宽高必须大于 0。", asdict(b)))
            continue
        if b.x < -eps or b.y < -eps or b.right > slide_w + eps or b.bottom > slide_h + eps:
            findings.append(
                Finding(
                    "blocker",
                    "out_of_canvas",
                    slide_no,
                    elem.name,
                    "实际 PPTX 元素越出幻灯片画布。",
                    {"box": asdict(b), "slide": {"w": slide_w, "h": slide_h}},
                )
            )
        if elem.text:
            font_pt = elem.font_pt or 20.0
            lines, estimated_h = _estimated_text_height(elem.text, b, font_pt)
            if estimated_h > b.h * 0.96:
                findings.append(
                    Finding(
                        "warning",
                        "text_fit_risk",
                        slide_no,
                        elem.name,
                        "实际 PPTX 文本框存在溢出/拥挤风险，必须在渲染图中复核。",
                        {
                            "font_pt": font_pt,
                            "estimated_lines": lines,
                            "estimated_text_h": round(estimated_h, 3),
                            "box_h": round(b.h, 3),
                            "text_preview": elem.text[:100],
                        },
                    )
                )

    # Pairwise checks intentionally emit warnings: background panels, image masks,
    # and intentional overlays are common in good slides. Render review decides.
    for i, a in enumerate(elems):
        for b in elems[i + 1 :]:
            ratio = _overlap_ratio(a.box, b.box)
            if ratio < 0.20:
                continue
            if a.text and b.text:
                findings.append(
                    Finding(
                        "warning",
                        "text_text_overlap",
                        slide_no,
                        f"{a.name} ↔ {b.name}",
                        "两个含文字元素存在显著几何重叠，需确认是否为有意叠放。",
                        {"overlap_ratio_of_smaller": round(ratio, 3)},
                    )
                )
            elif (a.text and b.kind in {"image", "graphic"}) or (b.text and a.kind in {"image", "graphic"}):
                findings.append(
                    Finding(
                        "warning",
                        "visual_text_overlap",
                        slide_no,
                        f"{a.name} ↔ {b.name}",
                        "图片/图形与文字区域显著重叠，需在真实渲染中检查遮挡与对比度。",
                        {"overlap_ratio_of_smaller": round(ratio, 3)},
                    )
                )
    return elems, findings


def presentation_size(archive: zipfile.ZipFile) -> tuple[float, float]:
    root = ET.fromstring(archive.read("ppt/presentation.xml"))
    sld_sz = root.find("p:sldSz", NS)
    if sld_sz is None:
        return 13.333, 7.5
    return _inch(sld_sz.get("cx")), _inch(sld_sz.get("cy"))


def analyze(path: Path) -> dict[str, Any]:
    findings: list[Finding] = []
    slides: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            slide_w, slide_h = presentation_size(archive)
            names = sorted(
                (n for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
                key=lambda n: int(Path(n).stem.replace("slide", "")),
            )
            for no, name in enumerate(names, start=1):
                root = ET.fromstring(archive.read(name))
                elements, slide_findings = analyze_slide(no, root, slide_w, slide_h)
                findings.extend(slide_findings)
                slides.append(
                    {
                        "slide": no,
                        "element_count": len(elements),
                        "text_element_count": sum(1 for e in elements if e.text),
                        "finding_count": len(slide_findings),
                    }
                )
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        return {"ok": False, "error": str(exc), "pptx": str(path)}

    blockers = sum(1 for f in findings if f.severity == "blocker")
    warnings = sum(1 for f in findings if f.severity == "warning")
    return {
        "ok": blockers == 0,
        "profile": "actual-pptx-static-v1",
        "pptx": str(path.resolve()),
        "pptx_sha256": sha256_file(path),
        "slide_size_in": {"w": round(slide_w, 3), "h": round(slide_h, 3)},
        "slide_count": len(slides),
        "blockers": blockers,
        "warnings": warnings,
        "slides": slides,
        "findings": [asdict(f) for f in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze actual PPTX geometry and text-fit risks.")
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when objective blockers exist")
    args = parser.parse_args()

    if not args.pptx.is_file():
        parser.error(f"PPTX not found: {args.pptx}")
    report = analyze(args.pptx)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.json or not args.output:
        print(text, end="")
    if args.strict and report.get("ok") is not True:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
