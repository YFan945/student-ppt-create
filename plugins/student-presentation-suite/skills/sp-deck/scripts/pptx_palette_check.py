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
SRGB = re.compile(r'<a:srgbClr\s+val="([0-9A-Fa-f]{6})"')


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


def check_pptx(pptx: Path, art_direction: Path) -> dict[str, Any]:
    style, light, dark = approved_colors(art_direction)
    allowed = set(light.values()) | set(dark.values())
    counts: Counter[str] = Counter()
    per_slide: dict[int, Counter[str]] = {}
    with zipfile.ZipFile(pptx, "r") as archive:
        for name in archive.namelist():
            match = SLIDE_PART.match(name)
            if not match:
                continue
            slide = int(match.group(1))
            colors = Counter(value.upper() for value in SRGB.findall(
                archive.read(name).decode("utf-8", "replace")
            ))
            per_slide[slide] = colors
            counts.update(colors)

    issues: list[dict[str, Any]] = []
    for slide, colors in sorted(per_slide.items()):
        outside = {color: count for color, count in sorted(colors.items()) if color not in allowed}
        if outside:
            issues.append({
                "slide": slide,
                "severity": "major",
                "code": "off-palette-color",
                "message": (
                    "PPTX contains colors outside the approved light/dark role palettes: "
                    + ", ".join(f"{color} x{count}" for color, count in outside.items())
                ),
                "colors": outside,
            })
    return {
        "ok": not issues,
        "pptx": str(pptx.resolve()),
        "art_direction": str(art_direction.resolve()),
        "style": style,
        "allowed": {"light": light, "dark": dark},
        "used": dict(sorted(counts.items())),
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
