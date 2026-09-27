#!/usr/bin/env python3
"""Analyze a reference PPTX into functional types and archetype suggestions.

PPTAgent-style ingestion for `rebuild_from_source` (v0.19): instead of
reinventing a visual system, read a GOOD reference deck and extract, per slide,
its functional type (cover / section / data / comparison / process / quote /
references / closing / image-led / content-text) plus the layout signals that
justify it. `ppt_pipeline.py plan --reference-analysis <report>` feeds the
suggestions into the scaffold so pages start from the reference's structure
instead of a generic guess.

The analyzer is deterministic and read-only: it never modifies the source deck,
and its suggestions are advisory inputs the spec's own `layout` hints may
outweigh (scaffold records which slides were guided).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

LAYOUT_LIBRARY = Path(__file__).resolve().parents[1] / "references" / "layout-library.json"

_SLIDE_PART = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_XFRM = re.compile(
    r"<a:off\s+x=\"(-?\d+)\"\s+y=\"(-?\d+)\"\s*/>\s*"
    r"<a:ext\s+cx=\"(\d+)\"\s+cy=\"(\d+)\"\s*/>"
)
_RUN = re.compile(r"<a:rPr[^>]*\bsz=\"(\d+)\"[^>]*>.*?<a:t>(.*?)</a:t>", re.DOTALL)
_TEXT = re.compile(r"<a:t>(.*?)</a:t>", re.DOTALL)
_PIC = re.compile(r"<p:pic>.*?</p:pic>", re.DOTALL)
CHART_REFS = ("<c:chart", "graphicFrame")
REFERENCE_CUES = ("参考文献", "references", "bibliography", "works cited", "来源汇总")
CLOSING_CUES = ("谢谢", "感谢", "总结", "结论", "thanks", "conclusion", "q&a", "takeaway")
SECTION_CUES = ("第一部分", "第二部分", "第三部分", "第四部分", "part ", "section", "章节", "overview")
QUOTE_CUES = ("“", "”", "\"", "said", "曾指出", "认为")
PROCESS_CUES = ("步骤", "流程", "阶段", "step", "phase", "roadmap", "里程碑")
COMPARISON_CUES = ("对比", "比较", "vs", "versus", "优劣", "方案a", "方案b", "before", "after")

# Detected type → ordered archetype suggestions. Validated against the
# layout library at report time, so a renamed layout cannot slip through.
ARCHETYPE_SUGGESTIONS: dict[str, list[str]] = {
    "cover": ["cover-split", "cover-editorial", "cover-minimal"],
    "section": ["section-number", "section-statement"],
    "data": ["data-chart-takeaway", "data-chart-sidebar", "data-kpi-row"],
    "comparison": ["compare-balanced", "compare-criteria", "compare-before-after"],
    "process": ["process-horizontal", "process-vertical", "timeline-roadmap"],
    "quote": ["quote-focus", "quote-analysis"],
    "references": ["references-clean"],
    "closing": ["closing-takeaway", "closing-question"],
    "image-led": ["visual-right", "visual-left", "visual-full"],
    "content-text": ["text-two-column", "claim-evidence", "claim-focus"],
}


def _slide_size(archive: zipfile.ZipFile) -> tuple[int, int]:
    match = re.search(
        r"<p:sldSz[^>]*\bcx=\"(\d+)\"[^>]*\bcy=\"(\d+)\"",
        archive.read("ppt/presentation.xml").decode("utf-8", "replace"),
    )
    if not match:
        return 9144000, 5143500
    return int(match.group(1)), int(match.group(2))


def _inches(emu: int) -> float:
    return emu / 914400.0


def _shape_texts(slide_xml: str) -> list[dict[str, Any]]:
    """Per-shape text inventory: concatenated runs, max font size, bbox."""
    shapes: list[dict[str, Any]] = []
    for block in re.findall(r"<p:sp>.*?</p:sp>", slide_xml, re.DOTALL):
        texts = [re.sub(r"<[^>]+>", "", match) for match in _TEXT.findall(block)]
        text = "".join(texts).strip()
        sizes = [int(value) for value in re.findall(r"\bsz=\"(\d+)\"", block)]
        boxes = [
            {"x": _inches(int(x)), "y": _inches(int(y)), "w": _inches(int(cx)), "h": _inches(int(cy))}
            for x, y, cx, cy in _XFRM.findall(block)
        ]
        if not text and not boxes:
            continue
        shapes.append(
            {
                "text": text,
                "chars": len(text),
                "max_font_pt": (max(sizes) / 100) if sizes else None,
                "bbox": boxes[0] if boxes else None,
            }
        )
    return shapes


def _pic_area_ratio(slide_xml: str, slide_w: float, slide_h: float) -> float:
    largest = 0.0
    for pic in _PIC.findall(slide_xml):
        for _x, _y, cx, cy in _XFRM.findall(pic):
            w, h = _inches(int(cx)), _inches(int(cy))
            if w <= 0 or h <= 0:
                continue
            largest = max(largest, min(1.0, (w * h) / max(1.0, slide_w * slide_h)))
    return largest


def _column_count(shapes: list[dict[str, Any]]) -> int:
    """Side-by-side text blocks with high vertical overlap → column count."""
    boxes = [
        shape["bbox"]
        for shape in shapes
        if shape["text"] and shape["bbox"] and 1.2 <= shape["bbox"]["w"] <= 5.0
    ]
    columns = 0
    for box in boxes:
        overlaps_existing = any(
            min(box["y"] + box["h"], other["y"] + other["h"]) - max(box["y"], other["y"]) > 0.3
            for other in boxes
            if other is not box
        )
        if not overlaps_existing:
            columns += 1
        else:
            left_of = any(
                other["x"] + other["w"] <= box["x"] + 0.1
                and min(box["y"] + box["h"], other["y"] + other["h"]) - max(box["y"], other["y"]) > 0.3
                for other in boxes
                if other is not box
            )
            if not left_of:
                columns += 1
    return max(1, min(3, columns))


def classify_slide(
    slide_xml: str,
    *,
    slide_no: int,
    slide_count: int,
    slide_w: float,
    slide_h: float,
) -> dict[str, Any]:
    shapes = _shape_texts(slide_xml)
    texts = [shape["text"] for shape in shapes if shape["text"]]
    joined = " ".join(texts).casefold()
    total_chars = sum(shape["chars"] for shape in shapes)
    title = max(
        (shape for shape in shapes if shape["text"]),
        key=lambda shape: shape["max_font_pt"] or 0,
        default=None,
    )
    has_chart = "<c:chart" in slide_xml or "graphicFrame" in slide_xml
    has_table = "<a:tbl>" in slide_xml
    image_ratio = _pic_area_ratio(slide_xml, float(slide_w), float(slide_h))
    columns = _column_count(shapes)

    signals: list[str] = []
    confidence = 0.4
    detected = "content-text"

    if slide_no == 1:
        detected, confidence = "cover", 0.85
        signals.append("first-slide")
    elif any(cue in joined for cue in REFERENCE_CUES) or (
        total_chars > 400 and slide_no == slide_count
    ):
        detected, confidence = "references", 0.7
        signals.append("reference-cues")
    elif has_chart or has_table:
        # 图表/表格证据先于 closing 线索：图表结论面板的默认英文文本
        # （"State the conclusion…"）会命中 closing 关键词，但那不是收尾页。
        detected, confidence = "data", 0.8
        signals.append("chart-or-table")
    elif slide_no == slide_count or any(cue in joined for cue in CLOSING_CUES):
        detected, confidence = "closing", 0.6
        signals.append("closing-cues")
    elif total_chars <= 25 and title and (title["max_font_pt"] or 0) >= 28:
        detected, confidence = "section", 0.65
        signals.append("sparse-large-title")
    elif image_ratio >= 0.55:
        detected, confidence = "image-led", 0.7
        signals.append(f"image-covers-{image_ratio:.0%}")
    elif any(cue in joined for cue in COMPARISON_CUES) or (columns >= 2 and total_chars > 200):
        detected, confidence = "comparison", 0.55
        signals.append(f"{columns}-column-text")
    elif any(cue in joined for cue in PROCESS_CUES):
        detected, confidence = "process", 0.5
        signals.append("process-cues")
    elif any(cue in joined for cue in QUOTE_CUES) and total_chars <= 220:
        detected, confidence = "quote", 0.5
        signals.append("quote-cues")
    elif total_chars <= 120:
        detected, confidence = "content-text", 0.45
        signals.append("sparse-text")
    else:
        signals.append(f"dense-text-{columns}col")

    return {
        "slide": slide_no,
        "detected_type": detected,
        "confidence": confidence,
        "signals": signals,
        "title_text": (title or {}).get("text", "")[:60],
        "text_chars": total_chars,
        "has_chart": has_chart or has_table,
        "image_area_ratio": round(image_ratio, 3),
        "columns": columns,
        "suggested_archetypes": ARCHETYPE_SUGGESTIONS.get(detected, []),
    }


def analyze_pptx(pptx: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source": str(pptx.resolve()),
        "source_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
        "slides": [],
        "warnings": [],
    }
    with zipfile.ZipFile(pptx, "r") as archive:
        slide_w_emu, slide_h_emu = _slide_size(archive)
        names = sorted(
            name for name in archive.namelist() if _SLIDE_PART.match(name)
        )
        if not names:
            report["warnings"].append("no slide parts found")
            return report
        for name in names:
            slide_no = int(_SLIDE_PART.match(name).group(1))
            xml = archive.read(name).decode("utf-8", "replace")
            report["slides"].append(
                classify_slide(
                    xml,
                    slide_no=slide_no,
                    slide_count=len(names),
                    slide_w=_inches(slide_w_emu),
                    slide_h=_inches(slide_h_emu),
                )
            )
    return report


def load_layout_ids() -> set[str]:
    data = json.loads(LAYOUT_LIBRARY.read_text(encoding="utf-8"))
    return {layout["id"] for layout in data.get("layouts", [])}


def validate_report(report: dict[str, Any]) -> list[str]:
    """Shape + vocabulary validation for `plan --reference-analysis`."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["reference analysis must be a JSON object"]
    if not isinstance(report.get("slides"), list) or not report["slides"]:
        errors.append("reference analysis must contain a non-empty slides array")
        return errors
    known = load_layout_ids()
    seen: set[int] = set()
    for entry in report["slides"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("slide"), int):
            errors.append("each analysis slide entry needs an integer slide number")
            continue
        slide_no = int(entry["slide"])
        if slide_no in seen:
            errors.append(f"slide {slide_no} appears more than once")
        seen.add(slide_no)
        if not str(entry.get("detected_type") or "").strip():
            errors.append(f"slide {slide_no} is missing detected_type")
        suggestions = entry.get("suggested_archetypes") or []
        if not isinstance(suggestions, list):
            errors.append(f"slide {slide_no} suggested_archetypes must be an array")
        else:
            unknown = [item for item in suggestions if item not in known]
            if unknown:
                errors.append(f"slide {slide_no} suggests unknown layouts: {', '.join(unknown)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.pptx.is_file():
        raise SystemExit(f"reference deck does not exist: {args.pptx}")
    report = analyze_pptx(args.pptx)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    summary = ", ".join(
        f"s{entry['slide']}:{entry['detected_type']}" for entry in report["slides"][:8]
    )
    print(f"reference_deck_analysis: {len(report['slides'])} slides — {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
