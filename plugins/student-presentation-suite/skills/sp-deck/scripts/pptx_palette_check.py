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
# A color element plus its OOXML transform children (tint/shade/alpha/…): the
# rendered color is the RESOLVED result, not the base val. Flat scanning saw
# only the base, so `tint`/`shade` could smuggle off-palette renders past this
# gate (B3).
COLOR_ELEMENT = re.compile(
    r"<a:(?P<kind>srgbClr|schemeClr)\b(?P<attrs>[^>]*?)(?:/>|>(?P<children>.*?)</a:(?P=kind)>)",
    re.DOTALL,
)
COLOR_TRANSFORM = re.compile(
    r"<a:(?P<op>tint|shade|alpha|alphaMod|lumMod|lumOff)\b[^>]*\bval=['\"](?P<val>-?\d+)['\"]"
)
RUN_RE = re.compile(r"<a:r>(?P<body>.*?)</a:r>", re.DOTALL)
RPR_RE = re.compile(r"<a:rPr\b(?P<attrs>[^>]*?)(?:/>|>(?P<children>.*?)</a:rPr>)", re.DOTALL)
RUN_TEXT_RE = re.compile(r"<a:t>([^<]*)</a:t>")
SHAPE_RE = re.compile(r"<p:sp>(?P<body>.*?)</p:sp>", re.DOTALL)
SPPR_RE = re.compile(r"<p:spPr>(?P<body>.*?)</p:spPr>", re.DOTALL)
SLIDE_BG_RE = re.compile(r"<p:bg>(?P<body>.*?)</p:bg>", re.DOTALL)
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
# WCAG-ish contrast floors (B3): large text (>=18pt, or >=14pt bold) 3.0, body 4.5.
# Severity is graded: below 3.0 the text is near-invisible — major on every tier.
# Between 3.0 and the size floor it is borderline (five token pairings — accent
# text on canvas — sit at 3.88–4.42 by design), so it degrades to an advisory the
# rendered-page critic can judge; the gate must not block token-conformant decks.
LARGE_TEXT_FLOOR = 3.0
BODY_TEXT_FLOOR = 4.5
HARD_CONTRAST_FLOOR = 3.0
LARGE_TEXT_MIN_SZ = 1800
LARGE_BOLD_MIN_SZ = 1400
# A heavily transparent fill reads as a wash over whatever sits behind it; the
# base color can no longer be attributed to the visible surface, so an
# off-palette base under 50% alpha degrades to advisory instead of major.
OPAQUE_ALPHA_FLOOR = 50_000


def _channel(value: float) -> int:
    return max(0, min(255, round(value)))


def _hls_lum_shift(rgb: tuple[int, int, int], mod: float, off: float) -> tuple[int, int, int]:
    import colorsys

    r, g, b = (value / 255 for value in rgb)
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = max(0.0, min(1.0, light * mod + off))
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return (_channel(r * 255), _channel(g * 255), _channel(b * 255))


def resolve_color(base: tuple[int, int, int], transforms: list[tuple[str, int]]) -> tuple[int, int, int]:
    """Apply OOXML color transforms in document order (B3)."""
    rgb = base
    for op, val in transforms:
        factor = val / 100_000
        if op == "shade":
            rgb = tuple(_channel(value * factor) for value in rgb)
        elif op == "tint":
            rgb = tuple(_channel(value * factor + 255 * (1 - factor)) for value in rgb)
        elif op == "lumMod":
            rgb = _hls_lum_shift(rgb, factor, 0.0)
        elif op == "lumOff":
            rgb = _hls_lum_shift(rgb, 1.0, factor)
        # alpha / alphaMod change opacity, not RGB: handled by the caller
    return rgb


def parse_color_element(match: re.Match[str], theme: dict[str, str]) -> dict[str, Any] | None:
    """Base + transforms -> resolved rgb, final alpha, transform list.

    None when the base cannot be resolved (unknown scheme role / missing theme).
    """
    kind = match.group("kind")
    attrs = match.group("attrs") or ""
    children = match.group("children") or ""
    if kind == "srgbClr":
        base_match = re.search(r"\bval=['\"]([0-9A-Fa-f]{6})['\"]", attrs)
        if not base_match:
            return None
        base = tuple(int(base_match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
        scheme_role = None
    else:
        role_match = re.search(r"\bval=['\"]([A-Za-z0-9]+)['\"]", attrs)
        if not role_match:
            return None
        scheme_role = SCHEME_ALIASES.get(role_match.group(1), role_match.group(1))
        resolved = theme.get(scheme_role or "")
        if not resolved:
            return None
        base = tuple(int(resolved[i:i + 2], 16) for i in (0, 2, 4))
    transforms = [(op, int(val)) for op, val in COLOR_TRANSFORM.findall(children)]
    rgb = resolve_color(base, transforms) if transforms else base
    alpha = 100_000
    for op, val in transforms:
        if op == "alpha":
            alpha = val
        elif op == "alphaMod":
            alpha = round(alpha * val / 100_000)
    return {
        "base": "{:02X}{:02X}{:02X}".format(*base),
        "rgb": "{:02X}{:02X}{:02X}".format(*rgb),
        "alpha": alpha,
        "scheme_role": scheme_role,
        "transforms": transforms,
    }


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def lin(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(first: str, second: str) -> float:
    a = tuple(int(first[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(second[i:i + 2], 16) for i in (0, 2, 4))
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def text_contrast_issues(
    text: str,
    slide_no: int,
    theme: dict[str, str],
) -> list[dict[str, Any]]:
    """Runs whose resolved text color fails the WCAG-ish floor on their resolvable background.

    Background resolution: the innermost shape with a solid fill, else the slide
    background, else theme lt1. Runs over pictures/gradients and runs with
    inherited (unresolvable) color are skipped — this gate stays deterministic.
    """
    default_bg = theme.get("lt1")
    slide_bg = None
    bg_match = SLIDE_BG_RE.search(text)
    if bg_match:
        bg_block = bg_match.group("body")
        if "<a:blipFill" in bg_block or "<a:gradFill" in bg_block:
            default_bg = None  # slide-level picture/gradient: unresolvable
        else:
            for match in COLOR_ELEMENT.finditer(bg_block):
                parsed = parse_color_element(match, theme)
                if parsed:
                    slide_bg = parsed["rgb"]
                    break
    shapes = [
        (match.start(), match.end(), match.group("body"))
        for match in SHAPE_RE.finditer(text)
    ]

    def shape_fill(span_body: str) -> str | None:
        sp_pr = SPPR_RE.search(span_body)
        if not sp_pr:
            return None
        fill = sp_pr.group("body")
        if "<a:blipFill" in fill or "<a:gradFill" in fill:
            return None
        for match in COLOR_ELEMENT.finditer(fill):
            parsed = parse_color_element(match, theme)
            if parsed and parsed["alpha"] >= OPAQUE_ALPHA_FLOOR:
                return parsed["rgb"]
        return None

    issues: list[dict[str, Any]] = []
    for run in RUN_RE.finditer(text):
        body = run.group("body")
        run_text = (RUN_TEXT_RE.search(body).group(1) if RUN_TEXT_RE.search(body) else "").strip()
        if not run_text:
            continue
        rpr = RPR_RE.search(body)
        if not rpr:
            continue
        attrs = rpr.group("attrs") or ""
        sz_match = re.search(r"\bsz=['\"](\d+)['\"]", attrs)
        if not sz_match:
            continue  # inherited size: cannot classify large vs body
        sz = int(sz_match.group(1))
        color = None
        for match in COLOR_ELEMENT.finditer(rpr.group("children") or ""):
            parsed = parse_color_element(match, theme)
            if parsed:
                color = parsed["rgb"]
                break
        if not color:
            continue  # inherited/theme-list color: unresolvable deterministically
        background = None
        for start, end, span_body in shapes:
            if start <= run.start() < end:
                background = shape_fill(span_body)
                break
        if background is None:
            background = slide_bg if slide_bg else default_bg
        if not background:
            continue
        floor = (
            LARGE_TEXT_FLOOR
            if sz >= LARGE_TEXT_MIN_SZ or ("b=\"1\"" in attrs and sz >= LARGE_BOLD_MIN_SZ)
            else BODY_TEXT_FLOOR
        )
        ratio = contrast_ratio(color, background)
        if ratio < floor:
            major = ratio < HARD_CONTRAST_FLOOR or floor == LARGE_TEXT_FLOOR
            issues.append({
                "slide": slide_no,
                "severity": "major" if major else "minor",
                "code": "low-contrast-text",
                "message": (
                    f"Slide {slide_no} text {run_text[:40]!r} ({sz / 100:.0f}pt, {color}) on "
                    f"{background} has contrast {ratio:.2f} < {floor:.1f}."
                ),
                "detail": {"text": run_text[:80], "color": color, "background": background,
                           "ratio": round(ratio, 2), "floor": floor, "sz": sz},
            })
    return issues


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
    low_alpha_parts: set[str] = set()
    scheme_counts: Counter[str] = Counter()
    transform_count = 0
    issues: list[dict[str, Any]] = []
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
            colors: Counter[str] = Counter()
            for match in COLOR_ELEMENT.finditer(text):
                parsed = parse_color_element(match, theme)
                if match.group("kind") == "schemeClr":
                    role = re.search(r"\bval=['\"]([A-Za-z0-9]+)['\"]", match.group("attrs") or "")
                    if role:
                        scheme_counts[role.group(1)] += 1
                if not parsed:
                    continue
                if parsed["transforms"]:
                    transform_count += 1
                if parsed["alpha"] < OPAQUE_ALPHA_FLOOR:
                    low_alpha_parts.add(name)
                colors[parsed["rgb"]] += 1
            slide_match = SLIDE_PART.match(name)
            if slide_match:
                issues.extend(text_contrast_issues(text, int(slide_match.group(1)), theme))
            per_part[name] = colors
            counts.update(colors)

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
            # A <50% alpha fill is a wash over an unknown background: the base
            # color no longer determines the visible surface, so downgrade.
            issues.append({
                "slide": slide,
                "part": part,
                "severity": "minor" if part in low_alpha_parts else "major",
                "code": "off-palette-color",
                "message": message,
                "colors": outside,
                **({"elements": elements} if elements else {}),
            })
    return {
        "ok": not any(item["severity"] in {"critical", "major"} for item in issues),
        "pptx": str(pptx.resolve()),
        "art_direction": str(art_direction.resolve()),
        "style": style,
        "allowed": {"light": light, "dark": dark},
        "used": dict(sorted(counts.items())),
        "scheme_references": dict(sorted(scheme_counts.items())),
        "transforms_resolved": transform_count,
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
