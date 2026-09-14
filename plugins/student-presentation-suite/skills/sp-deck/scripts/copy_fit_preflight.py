#!/usr/bin/env python3
"""Check planned on-slide copy fits before any generator is authored.

Run 2 of the v0.8 pipeline lost roughly a third of its budget to one cascade:
the Slide Spec carried planning-sentence claims (60-90 chars) while the confirmed
density cap was <=80 chars per slide. `pptx_actual_content_check.py` demands
`title` / `claim` / `slide_copy` appear **verbatim**, so the readback failed with
30 blockers, the generator had to be rewritten in full, and every repair step
afterwards was re-run.

That failure is knowable *before* `deck.js` exists: given the type scale and the
content regions, it is arithmetic. This script does that arithmetic so the Spec
is revised while revising it is still cheap.

It checks, per slide:
  * `title` fits the title band at `slide_title_pt`;
  * `claim` (or `key_line`) fits the claim band at `body_pt`;
  * every `slide_copy` / `content` fragment fits the body region;
  * total on-slide characters stay within the confirmed density cap.

Width model: CJK and full-width punctuation cost one em, Latin letters and digits
0.58 em, half-width punctuation 0.35 em. Line height uses 1.45x, matching how
CJK actually renders (the same ratio `pptx_rendered_check.py` enforces).

Exit codes: 0 = fits, 2 = at least one violation.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# Standard 10 x 5.625in student-wide grid (see pptx-helpers.js SLIDE_W_IN/SLIDE_H_IN).
DEFAULT_SLIDE_W = 10.0
DEFAULT_MARGIN = 0.6
DEFAULT_REGIONS = {
    "title_w": None,   # None => content width
    "title_h": 0.72,
    "claim_w": None,
    "claim_h": 0.94,
    "body_w": None,
    "body_h": 3.04,
}
CJK_RE = re.compile(r"[　-〿一-鿿＀-￯]")
HALF_PUNCT_RE = re.compile(r"[.,:%+/()\-]")
LINE_HEIGHT_FACTOR = 1.45
CJK_EM = 1.0
LATIN_EM = 0.58
PUNCT_EM = 0.35


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit(f"Structured file root must be an object: {path}")
    return value


def text_width_in(text: str, font_size_pt: float) -> float:
    """Estimated rendered width in inches."""
    em = font_size_pt / 72.0
    total = 0.0
    for char in str(text or ""):
        if CJK_RE.match(char):
            total += em * CJK_EM
        elif char == " ":
            total += em * 0.30
        elif HALF_PUNCT_RE.match(char):
            total += em * PUNCT_EM
        else:
            total += em * LATIN_EM
    return total


def estimate_lines(text: str, box_w_in: float, font_size_pt: float) -> int:
    usable = max(0.05, box_w_in)
    return max(1, math.ceil(text_width_in(text, font_size_pt) / usable))


def required_height_in(text: str, box_w_in: float, font_size_pt: float) -> tuple[int, float]:
    lines = estimate_lines(text, box_w_in, font_size_pt)
    line_height = (font_size_pt * LINE_HEIGHT_FACTOR) / 72.0
    return lines, lines * line_height


def fragments(value: Any) -> list[str]:
    """Flatten slide_copy / content into individual on-slide strings."""
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(fragments(item))
        return out
    if isinstance(value, dict):
        out = []
        for key in ("text", "title", "claim", "label", "value"):
            if key in value:
                out.extend(fragments(value[key]))
        return out
    return []


def cjk_char_count(text: str) -> int:
    return len(CJK_RE.findall(str(text or "")))


def is_caption(text: str) -> bool:
    """Source lines and figure captions are excluded from the density cap."""
    return bool(re.match(r"^\s*(来源|注[:：]|数据来|图\d|表\d)", str(text or "")))


def check_slide(
    slide: dict[str, Any],
    *,
    regions: dict[str, Any],
    content_w: float,
    title_pt: float,
    body_pt: float,
    max_chars: int,
) -> dict[str, Any]:
    title = str(slide.get("title") or "").strip()
    claim = str(slide.get("claim") or slide.get("key_line") or "").strip()
    copy = fragments(slide.get("slide_copy") if slide.get("slide_copy") is not None else slide.get("content"))

    title_w = regions["title_w"] or content_w
    claim_w = regions["claim_w"] or content_w
    body_w = regions["body_w"] or content_w

    problems: list[dict[str, Any]] = []

    for label, text, box_w, box_h, pt in (
        ("title", title, title_w, regions["title_h"], title_pt),
        ("claim", claim, claim_w, regions["claim_h"], body_pt),
    ):
        if not text:
            continue
        lines, need_h = required_height_in(text, box_w, pt)
        if need_h > box_h + 1e-6:
            problems.append(
                {
                    "field": label,
                    "severity": "major",
                    "text": text,
                    "chars": len(text),
                    "estimated_lines": lines,
                    "required_h": round(need_h, 3),
                    "available_h": box_h,
                    "font_size_pt": pt,
                }
            )

    body_pieces = [piece for piece in copy if piece and not is_caption(piece)]
    if body_pieces:
        total_h = 0.0
        for piece in body_pieces:
            _, need_h = required_height_in(piece, body_w, body_pt)
            total_h += need_h
        if total_h > regions["body_h"] + 1e-6:
            problems.append(
                {
                    "field": "slide_copy",
                    "severity": "major",
                    "fragments": len(body_pieces),
                    "required_h": round(total_h, 3),
                    "available_h": regions["body_h"],
                    "font_size_pt": body_pt,
                }
            )

    on_slide = "".join([title, claim, *body_pieces])
    chars = cjk_char_count(on_slide) or len(on_slide)
    if chars > max_chars:
        problems.append(
            {
                "field": "density",
                "severity": "minor",
                "chars": chars,
                "max_chars": max_chars,
            }
        )

    return {
        "id": slide.get("id"),
        "title": title,
        "on_slide_chars": chars,
        "copy_fragments": len(body_pieces),
        "problems": problems,
    }


def preflight(
    spec: dict[str, Any],
    art_direction: dict[str, Any] | None,
    *,
    content_w: float,
    regions: dict[str, Any],
    max_chars: int,
) -> dict[str, Any]:
    typo = (art_direction or {}).get("typography") or {}
    title_pt = float(typo.get("slide_title_pt") or 32)
    body_pt = float(typo.get("body_pt") or 22)

    slides = [item for item in (spec.get("slides") or []) if isinstance(item, dict)]
    results = [
        check_slide(
            slide,
            regions=regions,
            content_w=content_w,
            title_pt=title_pt,
            body_pt=body_pt,
            max_chars=max_chars,
        )
        for slide in slides
    ]

    majors = [
        {"slide": index, **problem}
        for index, result in enumerate(results, start=1)
        for problem in result["problems"]
        if problem["severity"] == "major"
    ]
    minors = [
        {"slide": index, **problem}
        for index, result in enumerate(results, start=1)
        for problem in result["problems"]
        if problem["severity"] == "minor"
    ]
    return {
        "ok": not majors,
        "slide_count": len(results),
        "type_scale": {"title_pt": title_pt, "body_pt": body_pt},
        "regions": {**regions, "content_w": content_w},
        "max_chars": max_chars,
        "counts": {"major": len(majors), "minor": len(minors)},
        "problems": majors + minors,
        "slides": results,
    }


def render(report: dict[str, Any], report_path: Path, *, verbose: bool, max_items: int) -> str:
    state = "ok" if report["ok"] else "blocked"
    lines = [
        f"copy_fit_preflight: {state} — major {report['counts']['major']}, "
        f"minor {report['counts']['minor']} | slides {report['slide_count']} | "
        f"title {report['type_scale']['title_pt']}pt / body {report['type_scale']['body_pt']}pt | "
        f"report: {report_path}"
    ]
    visible = report["problems"] if verbose else [p for p in report["problems"] if p["severity"] == "major"]
    limit = len(visible) if max_items <= 0 else max_items
    for item in visible[:limit]:
        field = item.get("field")
        if field == "slide_copy":
            detail = f"{item['fragments']} 段需 {item['required_h']}in > 可用 {item['available_h']}in"
        elif field == "density":
            detail = f"{item['chars']} 字 > 上限 {item['max_chars']}"
        else:
            detail = f"{item['chars']} 字 / {item['estimated_lines']} 行 需 {item['required_h']}in > 可用 {item['available_h']}in"
        lines.append(f"  [{item['severity']}] slide {item['slide']} {field} — {detail}")
    hidden = len(visible) - min(len(visible), limit)
    if hidden > 0:
        lines.append(f"  … {hidden} more (full detail in {report_path})")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--art-direction", type=Path, help="art-direction.yaml|json for the type scale")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="also list minor density findings")
    parser.add_argument("--max-items", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=80, help="per-slide Chinese character cap")
    parser.add_argument("--slide-w", type=float, default=DEFAULT_SLIDE_W)
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    parser.add_argument("--title-h", type=float, default=DEFAULT_REGIONS["title_h"])
    parser.add_argument("--claim-h", type=float, default=DEFAULT_REGIONS["claim_h"])
    parser.add_argument("--body-h", type=float, default=DEFAULT_REGIONS["body_h"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    spec = load_structured(args.slide_spec)
    art = load_structured(args.art_direction) if args.art_direction else None
    content_w = args.slide_w - args.margin * 2
    regions = {
        "title_w": None,
        "title_h": args.title_h,
        "claim_w": None,
        "claim_h": args.claim_h,
        "body_w": None,
        "body_h": args.body_h,
    }

    report = preflight(spec, art, content_w=content_w, regions=regions, max_chars=args.max_chars)
    report_path = args.output or (args.slide_spec.parent / "copy-fit-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path, verbose=args.verbose, max_items=args.max_items), end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
