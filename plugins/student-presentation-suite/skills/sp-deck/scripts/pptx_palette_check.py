#!/usr/bin/env python3
"""Check that rendered slide colors stay inside the approved token palettes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.design_tokens import PALETTE_ROLES, resolve_design_tokens  # noqa: E402

SLIDE_PART = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
VISIBLE_PART = re.compile(
    r"^ppt/(?:slides/slide\d+|charts/chart\d+|diagrams/(?:data|drawing)\d+)\.xml$"
)
SRGB = re.compile(r"<a:srgbClr\b[^>]*\bval=['\"]([0-9A-Fa-f]{6})['\"]")
SCHEME = re.compile(r"<a:schemeClr\b[^>]*\bval=['\"]([A-Za-z0-9]+)['\"]")
THEME_COLOR = re.compile(
    r"<a:(?P<role>dk1|lt1|dk2|lt2|accent[1-6]|hlink|folHlink)>.*?"
    r"<a:(?:srgbClr\b[^>]*\bval|sysClr\b[^>]*\blastClr)=['\"](?P<value>[0-9A-Fa-f]{6})['\"]",
    re.DOTALL,
)
SCHEME_ALIASES = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}
CHART_REL_RE = re.compile(r'Target="\.\./charts/(chart\d+\.xml)"')
CHART_ELEMENT_RE = re.compile(
    r"<c:(?P<tag>catAx|valAx|dateAx|serAx|legend|title|dLbls|ser)>.*?</c:(?P=tag)>",
    re.DOTALL,
)
CHART_ELEMENT_ROLES = {
    "catAx": "axis",
    "valAx": "axis",
    "dateAx": "axis",
    "serAx": "axis",
    "legend": "legend",
    "title": "title",
    "dLbls": "data-labels",
    "ser": "series",
}
GENERATOR_DEFAULT_COLOR = "000000"
GENERATOR_DEFAULT_ROLES = {"axis", "legend", "title"}


def chart_slide_map(archive: zipfile.ZipFile) -> dict[str, int]:
    """chart part -> slide number, via each slide's relationship file."""
    out: dict[str, int] = {}
    for name in archive.namelist():
        match = re.fullmatch(r"ppt/slides/_rels/slide(\d+)\.xml\.rels", name)
        if not match:
            continue
        slide = int(match.group(1))
        for chart in CHART_REL_RE.findall(archive.read(name).decode("utf-8", "replace")):
            out[f"ppt/charts/{chart}"] = slide
    return out


def chart_element_colors(text: str) -> dict[str, dict[str, int]]:
    """Which chart chrome carries which colors: axis / legend / title / series / labels."""
    out: dict[str, Counter[str]] = {}
    for match in CHART_ELEMENT_RE.finditer(text):
        role = CHART_ELEMENT_ROLES[match.group("tag")]
        colors = Counter(value.upper() for value in SRGB.findall(match.group(0)))
        out.setdefault(role, Counter()).update(colors)
    return {role: dict(sorted(colors.items())) for role, colors in out.items()}


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def approved_colors(art_direction: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    art = load_structured(art_direction)
    style = str(
        art.get("style_seed")
        or art.get("style_id")
        or art.get("visual_style")
        or "Modern Minimal"
    )
    tokens = resolve_design_tokens(style, art.get("visual_style_custom"))
    light = {role: str(tokens["palette"][role]).upper() for role in PALETTE_ROLES}
    dark = {role: str(tokens["dark_palette"][role]).upper() for role in PALETTE_ROLES}
    return str(tokens.get("style_name") or style), light, dark


def theme_colors(archive: zipfile.ZipFile) -> dict[str, str]:
    """Resolve the theme roles referenced by ``a:schemeClr`` values."""
    names = sorted(name for name in archive.namelist() if name.startswith("ppt/theme/theme") and name.endswith(".xml"))
    if not names:
        return {}
    text = archive.read(names[0]).decode("utf-8", "replace")
    return {
        match.group("role"): match.group("value").upper()
        for match in THEME_COLOR.finditer(text)
    }


def check_pptx(pptx: Path, art_direction: Path) -> dict[str, Any]:
    style, light, dark = approved_colors(art_direction)
    allowed = set(light.values()) | set(dark.values())
    counts: Counter[str] = Counter()
    per_part: dict[str, Counter[str]] = {}
    scheme_counts: Counter[str] = Counter()
    with zipfile.ZipFile(pptx, "r") as archive:
        theme = theme_colors(archive)
        chart_slides = chart_slide_map(archive)
        chart_texts: dict[str, str] = {}
        for name in archive.namelist():
            if not VISIBLE_PART.match(name):
                continue
            text = archive.read(name).decode("utf-8", "replace")
            if name.startswith("ppt/charts/"):
                chart_texts[name] = text
            colors = Counter(value.upper() for value in SRGB.findall(text))
            for role in SCHEME.findall(text):
                canonical = SCHEME_ALIASES.get(role, role)
                resolved = theme.get(canonical)
                scheme_counts[role] += 1
                if resolved:
                    colors[resolved] += 1
            per_part[name] = colors
            counts.update(colors)

    issues: list[dict[str, Any]] = []
    for part, colors in sorted(per_part.items()):
        outside = {color: count for color, count in sorted(colors.items()) if color not in allowed}
        if outside:
            slide_match = SLIDE_PART.match(part)
            slide = int(slide_match.group(1)) if slide_match else chart_slides.get(part)
            is_chart = part in chart_texts
            elements = chart_element_colors(chart_texts[part]) if is_chart else {}
            message = (
                f"{part} contains colors outside the approved light/dark role palettes: "
                + ", ".join(f"{color} x{count}" for color, count in outside.items())
            )
            if (
                is_chart
                and GENERATOR_DEFAULT_COLOR in outside
                and set(elements) & GENERATOR_DEFAULT_ROLES
            ):
                message += (
                    " — 000000 sits in chart chrome (axis/legend/title): the generator left"
                    " pptxgenjs defaults. Set those colors once in pptx-visuals.js chart"
                    " options instead of patching each chart"
                )
            issues.append({
                "slide": slide,
                "part": part,
                "severity": "major",
                "code": "off-palette-color",
                "message": message,
                "colors": outside,
                **({"elements": elements} if elements else {}),
            })
    return {
        "ok": not issues,
        "pptx": str(pptx.resolve()),
        "art_direction": str(art_direction.resolve()),
        "style": style,
        "allowed": {"light": light, "dark": dark},
        "used": dict(sorted(counts.items())),
        "scheme_references": dict(sorted(scheme_counts.items())),
        "coverage": {
            "parts": sorted(per_part),
            "images": "exempt; provenance and visual review govern raster imagery",
        },
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--art-direction", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = check_pptx(args.pptx, args.art_direction)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
