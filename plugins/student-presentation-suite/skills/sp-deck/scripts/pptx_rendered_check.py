#!/usr/bin/env python3
"""Rendered-artifact visual readback check.

The other gates validate *declared* values (art-direction YAML, slide spec).
This gate re-opens the generated PPTX itself and measures what actually got
rendered, so "declared compliant but rendered violating" cannot ship:

1. ``font-below-floor``  – every run size on every slide >= ``caption_min_pt``;
2. ``title-body-ratio``  – deck-level max/mode font ratio >= the tokens'
   ``title_min_pt / body_cjk_min_pt`` (the same 1.45x the art-direction gate
   demands on paper);
3. ``chart-axis-auto``   – every chart value axis carries an explicit
   ``c:max``/``c:min`` (auto-scaling hides real data differences);
4. ``dead-space``        – bottom whitespace per slide <= 25% of slide height.

Exit codes follow the v0.8 gate contract: fail-closed by default (2 when the
report is not ok), ``--lenient`` opts out, ``--strict`` is a deprecated no-op
alias kept for backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
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
# pptxgenjs always writes <a:off x= y=/> immediately followed by <a:ext cx= cy=/>;
# grouped shapes would need child-space resolution and are out of scope here.
_XFRM = re.compile(
    r"<a:off\s+x=\"(-?\d+)\"\s+y=\"(-?\d+)\"\s*/>\s*"
    r"<a:ext\s+cx=\"(\d+)\"\s+cy=\"(\d+)\"\s*/>"
)
_VAL_AX = re.compile(r"<c:valAx>.*?</c:valAx>", re.DOTALL)


def _load_tokens(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_font_sizes(slide_xml: bytes) -> list[int]:
    """All run sizes on one slide, in hundredths of a point."""
    return [int(v) for v in _FONT_SZ.findall(slide_xml.decode("utf-8", "replace"))]


def content_bottom_whitespace(slide_xml: bytes, slide_h: int) -> float | None:
    """Fraction of slide height below the lowest shape, or None if no shapes."""
    lowest = 0
    for _x, y, _cx, cy in _XFRM.findall(slide_xml.decode("utf-8", "replace")):
        lowest = max(lowest, int(y) + int(cy))
    if lowest <= 0:
        return None
    return max(0.0, (slide_h - lowest) / slide_h)


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
    slide_count = 0

    with zipfile.ZipFile(pptx, "r") as zf:
        presentation = zf.read("ppt/presentation.xml")
        match = _SLD_SZ.search(presentation.decode("utf-8", "replace"))
        if match:
            slide_h = int(match.group(2))
        for name in sorted(n for n in zf.namelist() if _SLIDE_PART.match(n)):
            xml = zf.read(name)
            slide_count += 1
            slide_sizes.extend(collect_font_sizes(xml))
            number = re.search(r"slide(\d+)\.xml$", name)
            label = f"slide-{number.group(1)}" if number else name
            gap = content_bottom_whitespace(xml, slide_h)
            if gap is not None:
                whitespace[label] = round(gap, 4)
                if gap > DEAD_SPACE_LIMIT:
                    issues.append(
                        {
                            "slide": label,
                            "severity": "blocker",
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

    too_small = sorted({s for s in slide_sizes if s < floor_hundredths})
    if too_small:
        issues.append(
            {
                "slide": None,
                "severity": "blocker",
                "code": "font-below-floor",
                "detail": (
                    f"sizes {', '.join(f'{s / 100:g}pt' for s in too_small)} "
                    f"below caption_min_pt {floor_hundredths / 100:g}pt"
                ),
            }
        )

    ratio: float | None = None
    if slide_sizes:
        mode = Counter(slide_sizes).most_common(1)[0][0]
        ratio = max(slide_sizes) / mode
        if ratio < min_ratio:
            issues.append(
                {
                    "slide": None,
                    "severity": "blocker",
                    "code": "title-body-ratio",
                    "detail": (
                        f"deck max/mode font ratio {ratio:.2f} below required {min_ratio:.2f} "
                        f"({title_pt}pt / {body_pt}pt tokens)"
                    ),
                }
            )

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
        "ok": not issues,
        "pptx": str(pptx),
        "slide_count": slide_count,
        "metrics": {
            "font_min_pt": min(slide_sizes) / 100 if slide_sizes else None,
            "font_max_pt": max(slide_sizes) / 100 if slide_sizes else None,
            "font_mode_pt": Counter(slide_sizes).most_common(1)[0][0] / 100 if slide_sizes else None,
            "title_body_ratio": round(ratio, 3) if ratio is not None else None,
            "required_ratio": round(min_ratio, 3),
            "charts": {"total": chart_total, "with_val_axis": chart_with_axis, "axis_unbounded": axis_unbounded},
            "bottom_whitespace": whitespace,
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="deprecated no-op alias; gates are fail-closed by default")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="opt-in relaxation: exit 0 even when the report is not ok (default is fail-closed)",
    )
    args = parser.parse_args()

    report = check_pptx(args.pptx, _load_tokens(args.tokens))
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    if not report["ok"] and not args.lenient:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
