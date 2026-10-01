#!/usr/bin/env python3
"""Rendered-artifact visual readback check.

The other gates validate *declared* values (art-direction YAML, slide spec).
This gate reads the generated OOXML, not raster pixels. It checks:

1. ``font-below-floor``  – every run size on every slide >= ``caption_min_pt``;
2. ``title-body-ratio``  – per-page title/body font ratio >= the tokens'
   ``title_min_pt / body_cjk_min_pt`` (the same 1.45x the art-direction gate
   demands on paper);
3. ``chart-axis-auto``   – every chart value axis carries an explicit
   ``c:max``/``c:min`` (auto-scaling hides real data differences);
4. ``dead-space``        – content-only bottom whitespace > 25% is advisory;
5. ``off-palette-color`` – every rendered sRGB color belongs to the approved
   light/dark role palettes when ``--art-direction`` is supplied.

Exit codes follow the v0.8 gate contract: fail-closed by default (2 when the
report is not ok), ``--lenient`` opts out, ``--strict`` is a deprecated no-op
alias kept for backward compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_static_core import (  # noqa: E402
    NS,
    inherited_font_context_for_layout,
    inherited_font_sizes,
    is_heading_shape,
    relationship_target,
    text_of,
)

DEFAULT_TOKENS = ROOT / "references" / "design-tokens.json"

# 与 JS 产物一致的兜底：pptx-helpers.js STUDENT_WIDE 版式 = 10×5.625in。
# tests/test_stack_contract.py 锁定两侧一致。
DEFAULT_SLIDE_W = 9144000  # EMU, 10in
DEFAULT_SLIDE_H = 5143500  # EMU, 5.625in
DEAD_SPACE_LIMIT = 0.25

_SLIDE_PART = re.compile(r"^ppt/slides/slide\d+\.xml$")
_CHART_PART = re.compile(r"^ppt/charts/[^/]+\.xml$")
_SLD_SZ = re.compile(r"<p:sldSz[^>]*\bcx=\"(\d+)\"[^>]*\bcy=\"(\d+)\"")
_FONT_SZ = re.compile(r"\bsz=\"(\d+)\"")
_VAL_AX = re.compile(r"<c:valAx>.*?</c:valAx>", re.DOTALL)


def _load_tokens(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_font_sizes(slide_xml: bytes) -> list[int]:
    """All run sizes on one slide, in hundredths of a point."""
    return [int(v) for v in _FONT_SZ.findall(slide_xml.decode("utf-8", "replace"))]


def parse_slide(xml: bytes) -> ET.Element:
    return ET.fromstring(xml)


def page_objects(root: ET.Element):
    """Resolve unrotated group child coordinates into slide coordinates."""
    def walk(parent, sx=1.0, sy=1.0, dx=0.0, dy=0.0):
        for node in parent:
            kind = node.tag.rsplit("}", 1)[-1]
            if kind not in {"sp", "pic", "graphicFrame", "cxnSp", "grpSp"}:
                continue
            transform = node.find("./p:grpSpPr/a:xfrm", NS) if kind == "grpSp" else node.find("./p:spPr/a:xfrm", NS)
            if transform is None:
                transform = node.find("./p:xfrm", NS)
            bounds = None
            if transform is not None:
                off, ext = transform.find("a:off", NS), transform.find("a:ext", NS)
                if off is not None and ext is not None:
                    x, y = float(off.get("x", 0)), float(off.get("y", 0))
                    w, h = float(ext.get("cx", 0)), float(ext.get("cy", 0))
                    bounds = (dx + sx*x, dy + sy*y, sx*w, sy*h)
                    if kind == "grpSp":
                        child_off, child_ext = transform.find("a:chOff", NS), transform.find("a:chExt", NS)
                        if child_off is not None and child_ext is not None:
                            cw, ch = float(child_ext.get("cx", 0)), float(child_ext.get("cy", 0))
                            if cw > 0 and ch > 0 and not int(transform.get("rot", 0)):
                                nsx, nsy = sx*w/cw, sy*h/ch
                                yield from walk(node, nsx, nsy, dx+sx*x-nsx*float(child_off.get("x", 0)), dy+sy*y-nsy*float(child_off.get("y", 0)))
                                continue
                        # Unknown group geometry: keep typography, not false bounds.
                        for child in page_objects(node):
                            yield child[0], None
                        continue
            if kind != "grpSp":
                yield node, bounds
    tree = root.find(".//p:spTree", NS)
    yield from walk(tree if tree is not None else root)


def effective_sizes(shape: ET.Element, context: dict) -> list[int]:
    inherited, _source = inherited_font_sizes(shape, context, is_heading_shape(shape))
    fallback = round(inherited[0]*100) if inherited else None
    sizes = []
    for paragraph in shape.findall(".//a:p", NS):
        default = paragraph.find("./a:pPr/a:defRPr", NS)
        level = int(paragraph.find("a:pPr", NS).get("lvl", 0)) if paragraph.find("a:pPr", NS) is not None else 0
        list_default = shape.find(f"./p:txBody/a:lstStyle/a:lvl{level+1}pPr/a:defRPr", NS)
        for run in list(paragraph.findall("a:r", NS)) + list(paragraph.findall("a:fld", NS)):
            if not text_of(run).strip():
                continue
            props = run.find("a:rPr", NS)
            value = next((node.get("sz") for node in (props, default, list_default) if node is not None and node.get("sz")), fallback)
            if value is not None:
                sizes.append(int(value))
    return sizes


def page_metrics(root: ET.Element, slide_h: int, slide_w: int, context: dict) -> tuple[list[int], float | None, float | None]:
    all_sizes, titles, bodies, texts = [], [], [], []
    lowest = 0.0
    for shape, bounds in page_objects(root):
        text = text_of(shape).strip()
        sizes = effective_sizes(shape, context) if text else []
        all_sizes.extend(sizes)
        name_node = shape.find(".//p:cNvPr", NS)
        name = name_node.get("name", "").lower() if name_node is not None else ""
        footer = any(word in name for word in ("footer", "page-number", "slide-number", "页脚", "页码"))
        if bounds and text and sizes and max(sizes) <= 1400 and bounds[1] >= slide_h*0.9:
            footer = True
        background = bool(bounds and not text and bounds[2] >= slide_w*0.95 and bounds[3] >= slide_h*0.95)
        decorative = any(word in name for word in ("background", "decoration", "背景", "装饰"))
        if bounds and not footer and not background and not decorative:
            lowest = max(lowest, bounds[1]+bounds[3])
        if not text or not sizes or footer:
            continue
        if is_heading_shape(shape):
            titles.extend(sizes)
        else:
            bodies.extend(sizes)
        texts.append(sizes)
    ratio = None
    if titles and bodies:
        ratio = max(titles)/Counter(bodies).most_common(1)[0][0]
    elif len(texts) >= 2:
        # Unnamed freeform shapes: infer within THIS page, never from a cover.
        # Count shapes, not rich-text runs: a ten-run title is still one title.
        shape_sizes = [max(entry) for entry in texts]
        title_index = shape_sizes.index(max(shape_sizes))
        body_sizes = [size for index, size in enumerate(shape_sizes) if index != title_index]
        ratio = shape_sizes[title_index]/Counter(body_sizes).most_common(1)[0][0]
    gap = max(0.0, (slide_h-lowest)/slide_h) if lowest > 0 else None
    return all_sizes, ratio, gap


def content_bottom_whitespace(slide_xml: bytes, slide_h: int) -> float | None:
    return page_metrics(parse_slide(slide_xml), slide_h, DEFAULT_SLIDE_W, {})[2]


def unbounded_value_axes(chart_xml: bytes) -> int:
    """Count value axes missing an explicit c:max or c:min."""
    unbounded = 0
    for block in _VAL_AX.findall(chart_xml.decode("utf-8", "replace")):
        if "<c:max" not in block or "<c:min" not in block:
            unbounded += 1
    return unbounded


def check_pptx(pptx: Path, tokens: dict[str, Any]) -> dict[str, Any]:
    typo = tokens.get("typography", {})
    floor_hundredths = int(typo.get("caption_min_pt", 11)) * 100
    body_pt = int(typo.get("body_cjk_min_pt", 22))
    title_pt = int(typo.get("title_min_pt", 32))
    min_ratio = title_pt / body_pt

    issues: list[dict[str, Any]] = []
    slide_sizes: list[int] = []
    whitespace: dict[str, float] = {}
    chart_total = 0
    chart_with_axis = 0
    axis_unbounded = 0
    slide_h = DEFAULT_SLIDE_H
    slide_w = DEFAULT_SLIDE_W
    page_ratios: dict[str, float] = {}
    slide_count = 0

    with zipfile.ZipFile(pptx, "r") as zf:
        presentation = zf.read("ppt/presentation.xml")
        match = _SLD_SZ.search(presentation.decode("utf-8", "replace"))
        if match:
            slide_h = int(match.group(2))
            slide_w = int(match.group(1))
        for name in sorted(n for n in zf.namelist() if _SLIDE_PART.match(n)):
            xml = zf.read(name)
            slide_count += 1
            number = re.search(r"slide(\d+)\.xml$", name)
            label = f"slide-{number.group(1)}" if number else name
            slide_no = int(number.group(1)) if number else None
            try:
                root = parse_slide(xml)
                layout = relationship_target(zf, name, "/slideLayout")
                context = inherited_font_context_for_layout(zf, layout)
                sizes, page_ratio, gap = page_metrics(root, slide_h, slide_w, context)
            except (ET.ParseError, ValueError) as exc:
                issues.append({"slide": slide_no, "severity": "critical", "code": "slide-xml-invalid", "detail": str(exc)})
                continue
            slide_sizes.extend(sizes)
            small = sorted({size for size in sizes if size < floor_hundredths})
            if small:
                issues.append({"slide": slide_no, "severity": "blocker", "code": "font-below-floor",
                               "detail": f"sizes {[size/100 for size in small]}pt below caption_min_pt {floor_hundredths/100:g}pt"})
            if page_ratio is not None:
                page_ratios[label] = round(page_ratio, 3)
                if page_ratio < min_ratio:
                    issues.append({"slide": slide_no, "severity": "blocker", "code": "title-body-ratio",
                                   "detail": f"page font ratio {page_ratio:.2f} below required {min_ratio:.2f}"})
            if gap is not None:
                whitespace[label] = round(gap, 4)
                if gap > DEAD_SPACE_LIMIT:
                    issues.append(
                        {
                            "slide": slide_no,
                            "severity": "advisory",
                            "code": "dead-space",
                            "detail": f"bottom whitespace {gap:.1%} exceeds {DEAD_SPACE_LIMIT:.0%}",
                        }
                    )
        for name in sorted(n for n in zf.namelist() if _CHART_PART.match(n)):
            xml = zf.read(name)
            axes = len(_VAL_AX.findall(xml.decode("utf-8", "replace")))
            chart_total += 1
            if axes:
                chart_with_axis += 1
                unbounded = unbounded_value_axes(xml)
                axis_unbounded += unbounded

    ratio: float | None = None
    if slide_sizes:
        mode = Counter(slide_sizes).most_common(1)[0][0]
        ratio = max(slide_sizes) / mode

    if axis_unbounded:
        issues.append(
            {
                "slide": None,
                "severity": "blocker",
                "code": "chart-axis-auto",
                "detail": (
                    f"{axis_unbounded} value axis(es) rely on auto scaling; "
                    "set explicit min/max so bar heights stay comparable"
                ),
            }
        )

    return {
        "ok": not any(item["severity"] in {"critical", "major", "blocker"} for item in issues),
        "pptx": str(pptx),
        "slide_count": slide_count,
        "metrics": {
            "font_min_pt": min(slide_sizes) / 100 if slide_sizes else None,
            "font_max_pt": max(slide_sizes) / 100 if slide_sizes else None,
            "font_mode_pt": Counter(slide_sizes).most_common(1)[0][0] / 100 if slide_sizes else None,
            "title_body_ratio": round(ratio, 3) if ratio is not None else None,
            "page_title_body_ratio": page_ratios,
            "required_ratio": round(min_ratio, 3),
            "charts": {"total": chart_total, "with_val_axis": chart_with_axis, "axis_unbounded": axis_unbounded},
            "bottom_whitespace": whitespace,
        },
        "issues": issues,
    }


def registry_sidecar_findings(pptx: Path) -> list[dict[str, Any]]:
    """deck.js 写的 `<pptx>.registry-report.json`：几何 warning 进 repair 视野。

    assertSafe 在 error 上抛错（build 阻断），warning（decorative_stripe /
    non_orthogonal_connector / content_dead_zone）以前被静默丢弃。这里把它们
    以 advisory 严重级带回——run_gates 的 advisory→minor 归一化让它们出现在
    repair packet，但不翻转门。sidecar 缺失（旧 deck）时返回空。
    """
    sidecar = Path(str(pptx) + ".registry-report.json")
    if not sidecar.is_file():
        return []
    try:
        report = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{"severity": "major", "code": "registry-report-invalid", "detail": str(exc)}]
    if not isinstance(report, dict) or report.get("pptx_sha256") != hashlib.sha256(pptx.read_bytes()).hexdigest():
        return [{"severity": "major", "code": "registry-report-stale",
                 "detail": "Registry report must bind the current PPTX SHA256; rebuild through the pipeline."}]
    findings: list[dict[str, Any]] = []
    for warning in report.get("warnings") or []:
        if not isinstance(warning, dict):
            continue
        findings.append(
            {
                "slide": warning.get("slide"),
                "severity": "advisory",
                "code": f"registry-{warning.get('code') or 'warning'}",
                "detail": str(warning.get("message") or "registry geometry warning"),
            }
        )
    return findings


def run(args: argparse.Namespace) -> int:
    """Run the rendered-artifact gate with pre-parsed arguments (shared by gate-all)."""
    report = check_pptx(args.pptx, _load_tokens(args.tokens))
    sidecar = registry_sidecar_findings(args.pptx)
    if sidecar:
        report["registry_geometry"] = {
            "source": str(args.pptx) + ".registry-report.json",
            "findings": sidecar,
        }
        report["issues"].extend(sidecar)
        report["ok"] = not any(item.get("severity") in {"critical", "major", "blocker"} for item in report["issues"])
    if getattr(args, "art_direction", None):
        import pptx_palette_check

        palette = pptx_palette_check.check_pptx(args.pptx, args.art_direction)
        report["palette"] = palette
        report["issues"].extend(palette["issues"])
        # Advisory issues (borderline contrast, sub-50%-alpha off-palette washes)
        # ride along for the repair packet but must not flip the gate: only
        # blocking severities decide ok, mirroring how collect() counts them.
        blocking = {"critical", "major", "blocker"}
        report["ok"] = not any(item.get("severity") in blocking for item in report["issues"])
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    if not report["ok"] and not args.lenient:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--art-direction", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="deprecated no-op alias; gates are fail-closed by default")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="opt-in relaxation: exit 0 even when the report is not ok (default is fail-closed)",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
