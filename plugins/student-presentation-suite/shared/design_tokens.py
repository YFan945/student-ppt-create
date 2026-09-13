"""Resolve lightweight visual references for PPTX production and QA."""

from __future__ import annotations

import colorsys
import copy
import json
import re
from pathlib import Path
from typing import Any

from shared.pptx_static_core import contrast_ratio

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "references" / "design-tokens.json"

STYLE_ALIASES = {
    "berry-cream": "warm-terracotta",
    "sage-calm": "forest-moss",
}

PALETTE_ROLES = (
    "canvas",
    "surface",
    "primary_text",
    "secondary_text",
    "primary_accent",
    "secondary_accent",
)
BACKGROUND_ROLES = ("cover", "content", "section", "closing")
HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")

# Contrast floors shared by the light palette and its dark companion.
TEXT_CONTRAST_MIN = 4.5
ACCENT_CONTRAST_MIN = 3.0


def style_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


# ── Dark companion palette ────────────────────────────────────────────────
# Every style needs a cover/section/closing scheme that belongs to the same
# colour family as its content scheme; otherwise the cover and the body pages
# read as two different decks. Built-in styles ship an explicit dark palette,
# and `derive_dark_palette` produces a contrast-safe companion for anything else.


def _to_hls(value: str) -> tuple[float, float, float]:
    hex_value = value.lstrip("#")
    rgb = tuple(int(hex_value[index : index + 2], 16) / 255 for index in (0, 2, 4))
    return colorsys.rgb_to_hls(*rgb)


def _from_hls(hue: float, lightness: float, saturation: float) -> str:
    r, g, b = colorsys.hls_to_rgb(
        hue, max(0.0, min(1.0, lightness)), max(0.0, min(1.0, saturation))
    )
    return "".join(f"{max(0, min(255, round(channel * 255))):02X}" for channel in (r, g, b))


def _lightness_for_contrast(hue: float, saturation: float, background: str, target: float) -> str:
    """Smallest lightness whose contrast against `background` reaches `target`."""
    low, high = 0.0, 1.0
    for _ in range(32):
        mid = (low + high) / 2
        if contrast_ratio(_from_hls(hue, mid, saturation), background) >= target:
            high = mid
        else:
            low = mid
    return _from_hls(hue, min(1.0, high + 0.02), saturation)


def derive_dark_palette(palette: dict[str, Any]) -> dict[str, str]:
    """Deterministic, contrast-safe dark companion for a light palette."""
    hue_text, _, sat_text = _to_hls(str(palette["primary_text"]))
    hue_canvas, _, sat_canvas = _to_hls(str(palette["canvas"]))
    hue_accent, _, sat_accent = _to_hls(str(palette["primary_accent"]))
    canvas = _from_hls(hue_text, 0.115, min(0.55, sat_text * 1.15))
    surface = _from_hls(hue_text, 0.175, min(0.45, sat_text))
    return {
        "canvas": canvas,
        "surface": surface,
        "primary_text": _lightness_for_contrast(hue_canvas, min(0.30, sat_canvas), surface, 9.0),
        "secondary_text": _lightness_for_contrast(hue_canvas, min(0.22, sat_canvas), surface, 5.2),
        "primary_accent": _lightness_for_contrast(hue_accent, min(0.85, sat_accent * 1.05), surface, 3.6),
        "secondary_accent": _from_hls(hue_accent, 0.34, min(0.45, sat_accent * 0.9)),
    }


def _palette_errors(palette: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    for role in PALETTE_ROLES:
        if not HEX_COLOR.fullmatch(str(palette.get(role, ""))):
            errors.append(f"{prefix}.{role} must be a 6-digit hex color")
    if errors:
        return errors
    for text_role in ("primary_text", "secondary_text"):
        for background_role in ("canvas", "surface"):
            ratio = contrast_ratio(palette[text_role], palette[background_role])
            if ratio < TEXT_CONTRAST_MIN:
                errors.append(
                    f"{prefix}.{text_role} must reach {TEXT_CONTRAST_MIN}:1 "
                    f"against {background_role}; got {ratio:.2f}:1"
                )
    for background_role in ("canvas", "surface"):
        ratio = contrast_ratio(palette["primary_accent"], palette[background_role])
        if ratio < ACCENT_CONTRAST_MIN:
            errors.append(
                f"{prefix}.primary_accent must reach {ACCENT_CONTRAST_MIN}:1 "
                f"against {background_role}; got {ratio:.2f}:1"
            )
    return errors


def validate_custom_style(custom: dict[str, Any] | None) -> list[str]:
    """Return actionable validation errors for the four-field Other contract."""
    if not isinstance(custom, dict):
        return ["visual_style_custom is required when visual_style is Other"]
    errors: list[str] = []
    expected = {"style_character", "palette", "dark_palette", "backgrounds", "svg_reference"}
    extra = sorted(set(custom) - expected)
    if extra:
        errors.append(f"visual_style_custom contains unsupported fields: {', '.join(extra)}")
    if not isinstance(custom.get("style_character"), str) or not custom["style_character"].strip():
        errors.append("visual_style_custom.style_character is required")
    palette = custom.get("palette")
    if not isinstance(palette, dict):
        errors.append("visual_style_custom.palette is required")
    else:
        extra_palette = sorted(set(palette) - set(PALETTE_ROLES))
        if extra_palette:
            errors.append(
                "visual_style_custom.palette contains unsupported roles: "
                + ", ".join(extra_palette)
            )
        errors.extend(_palette_errors(palette, "visual_style_custom.palette"))
    # The dark companion is optional: it is derived from `palette` when omitted,
    # but when supplied it must clear the same contrast floors.
    dark_palette = custom.get("dark_palette")
    if dark_palette is not None:
        if not isinstance(dark_palette, dict):
            errors.append("visual_style_custom.dark_palette must be an object")
        else:
            extra_dark = sorted(set(dark_palette) - set(PALETTE_ROLES))
            if extra_dark:
                errors.append(
                    "visual_style_custom.dark_palette contains unsupported roles: "
                    + ", ".join(extra_dark)
                )
            errors.extend(_palette_errors(dark_palette, "visual_style_custom.dark_palette"))
    backgrounds = custom.get("backgrounds")
    if not isinstance(backgrounds, dict):
        errors.append("visual_style_custom.backgrounds is required")
    else:
        extra_backgrounds = sorted(set(backgrounds) - set(BACKGROUND_ROLES))
        if extra_backgrounds:
            errors.append(
                "visual_style_custom.backgrounds contains unsupported roles: "
                + ", ".join(extra_backgrounds)
            )
        for role in BACKGROUND_ROLES:
            if not isinstance(backgrounds.get(role), str) or not backgrounds[role].strip():
                errors.append(f"visual_style_custom.backgrounds.{role} is required")
    svg_reference = custom.get("svg_reference")
    if not isinstance(svg_reference, dict):
        errors.append("visual_style_custom.svg_reference is required")
    else:
        extra_svg = sorted(set(svg_reference) - {"name", "usage"})
        if extra_svg:
            errors.append(
                "visual_style_custom.svg_reference contains unsupported fields: "
                + ", ".join(extra_svg)
            )
        for role in ("name", "usage"):
            if not isinstance(svg_reference.get(role), str) or not svg_reference[role].strip():
                errors.append(f"visual_style_custom.svg_reference.{role} is required")
    return errors


def resolve_design_tokens(
    visual_style: str | None,
    visual_style_custom: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve global safety tokens plus a lightweight visual reference."""
    catalog = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    styles = catalog["styles"]
    requested_name = visual_style or "Modern Minimal"
    requested_key = style_key(requested_name)
    warnings: list[str] = []

    if requested_key in STYLE_ALIASES:
        target = STYLE_ALIASES[requested_key]
        warnings.append(
            f"Legacy visual style {requested_name!r} maps to {styles[target]['name']!r}."
        )
        requested_key = target

    tokens = copy.deepcopy(catalog["defaults"])
    if requested_key == "other":
        errors = validate_custom_style(visual_style_custom)
        if errors:
            raise ValueError("; ".join(errors))
        assert visual_style_custom is not None
        _merge(tokens, visual_style_custom)
        tokens["style_key"] = "other"
        tokens["style_name"] = "Other"
        tokens["custom_style"] = True
    elif requested_key in styles:
        _merge(tokens, styles[requested_key])
        tokens["style_key"] = requested_key
        tokens["style_name"] = styles[requested_key]["name"]
    else:
        fallback = styles["modern-minimal"]
        _merge(tokens, fallback)
        tokens["style_character"] = requested_name
        tokens["style_key"] = requested_key or "custom"
        tokens["style_name"] = requested_name or "Custom"
        tokens["custom_style"] = True
        warnings.append(
            "Legacy custom style has no visual_style_custom record; Modern Minimal safety "
            "colors, backgrounds, and SVG reference were used."
        )

    # Guarantee a dark companion so cover/section/closing pages stay in the same
    # colour family as the content pages, even for custom or legacy styles.
    dark = tokens.get("dark_palette")
    if not isinstance(dark, dict) or set(dark) != set(PALETTE_ROLES):
        tokens["dark_palette"] = derive_dark_palette(tokens["palette"])

    if warnings:
        tokens["compatibility_warnings"] = warnings
    return tokens
