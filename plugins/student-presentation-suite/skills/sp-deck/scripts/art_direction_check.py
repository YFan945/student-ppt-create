#!/usr/bin/env python3
"""Validate the v0.8 Art Direction artifact.

This checker validates positive design decisions before final slide coordinates are
authored. High-score mode also requires an explicit 3–5 slide high-leverage plan
that will be consumed by the v0.8 visual-generation evidence gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BLOCKING = {"critical", "major"}
REQUIRED_SECTIONS = (
    "concept",
    "color_system",
    "typography",
    "imagery",
    "icon_language",
    "chart_grammar",
    "component_language",
    "motif",
    "background_rhythm",
    "asset_plan",
    "high_leverage_slides",
)


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML Art Direction files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit("Art Direction root must be an object.")
    return value


def issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def high_leverage_numbers(data: dict[str, Any]) -> list[int]:
    raw = data.get("high_leverage_slides")
    if not isinstance(raw, list):
        return []
    numbers: list[int] = []
    for item in raw:
        slide = item.get("slide") if isinstance(item, dict) else item
        if isinstance(slide, int) and not isinstance(slide, bool) and slide > 0:
            numbers.append(slide)
    return numbers


def validate_art_direction(data: dict[str, Any], *, high_score: bool = True) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for field in REQUIRED_SECTIONS:
        value = data.get(field)
        if value in (None, "", [], {}):
            issues.append(issue("major", "missing_section", f"Art Direction is missing {field}."))

    concept = str(data.get("concept") or "").strip()
    if concept and len(concept) < 16:
        issues.append(issue("minor", "weak_visual_thesis", "Art Direction concept is too vague to guide composition."))

    color = data.get("color_system") if isinstance(data.get("color_system"), dict) else {}
    dominant = number(color.get("dominant_share_pct"))
    if dominant is None:
        issues.append(issue("major", "dominance_missing", "color_system.dominant_share_pct is required."))
    elif not 55 <= dominant <= 75:
        severity = "major" if high_score else "minor"
        issues.append(issue(severity, "dominance_out_of_range", "Dominant color/background share should normally be 55–75%."))

    typography = data.get("typography") if isinstance(data.get("typography"), dict) else {}
    title_pt = number(typography.get("slide_title_pt"))
    body_pt = number(typography.get("body_pt"))
    cover_pt = number(typography.get("cover_title_pt"))
    key_pt = number(typography.get("key_statement_pt"))
    caption_pt = number(typography.get("caption_pt"))
    if title_pt is None or body_pt is None:
        issues.append(issue("major", "type_scale_missing", "slide_title_pt and body_pt are required."))
    elif body_pt <= 0 or title_pt / body_pt < 1.45:
        issues.append(issue("major", "weak_type_hierarchy", "Slide title/body scale must create clear visual hierarchy (normally >= 1.45x)."))
    if cover_pt is not None and title_pt is not None and cover_pt < title_pt * 1.2:
        issues.append(issue("minor", "weak_cover_scale", "Cover title should normally be materially larger than ordinary slide titles."))
    if key_pt is not None and body_pt is not None and key_pt < body_pt * 1.25:
        issues.append(issue("minor", "weak_takeaway_scale", "Key statement scale is too close to body text."))
    if caption_pt is not None and not 11 <= caption_pt <= 13:
        issues.append(issue("minor", "caption_scale_unusual", "Caption/source text should stay within 11–13pt (design-tokens caption_min_pt is 11)."))

    imagery = data.get("imagery") if isinstance(data.get("imagery"), dict) else {}
    if not str(imagery.get("crop_language") or "").strip():
        issues.append(issue("major", "imagery_crop_missing", "Art Direction must decide an image crop language."))
    if not str(imagery.get("treatment") or "").strip():
        issues.append(issue("major", "imagery_treatment_missing", "Art Direction must decide an image treatment."))

    chart = data.get("chart_grammar") if isinstance(data.get("chart_grammar"), dict) else {}
    if not str(chart.get("default") or "").strip() or not str(chart.get("takeaway") or "").strip():
        issues.append(issue("major", "chart_grammar_incomplete", "Chart grammar needs a default treatment and takeaway rule."))

    components = data.get("component_language") if isinstance(data.get("component_language"), dict) else {}
    if not str(components.get("cards") or "").strip():
        issues.append(issue("major", "component_cards_undefined", "Component language must state how cards are used."))

    rhythm = data.get("background_rhythm")
    if not isinstance(rhythm, list) or len(rhythm) < 3:
        issues.append(issue("major", "background_rhythm_missing", "Background rhythm needs at least cover/content/closing decisions."))
    else:
        modes = {str(item.get("mode") or "").strip().lower() for item in rhythm if isinstance(item, dict)}
        if high_score and len(modes - {""}) < 2:
            issues.append(issue("major", "background_rhythm_flat", "High-score decks should normally use at least two background energy modes."))

    asset_plan = data.get("asset_plan") if isinstance(data.get("asset_plan"), dict) else {}
    mix_keys = ("hero_visuals", "evidence_visuals", "diagrams", "native_charts", "typography_led")
    visual_mix = sum(
        int(value)
        for key, value in asset_plan.items()
        if key in mix_keys
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    )
    if high_score:
        # 旧判定只数"有几个类别 >0"，不看总量：4 个类别各配 1 个元素的 8 页 deck
        # 也能放行。加总量下限（审查第 19 条的原始反例即 total=4）。
        total_visuals = sum(
            int(asset_plan.get(key))
            for key in mix_keys
            if isinstance(asset_plan.get(key), int) and not isinstance(asset_plan.get(key), bool)
        )
        if visual_mix < 4:
            issues.append(issue("major", "asset_mix_too_thin", "High-score Art Direction needs a deliberate mix of visual assets/strategies."))
        elif total_visuals < 5:
            issues.append(issue("major", "asset_mix_total_too_low", f"High-score Art Direction plans only {total_visuals} visual elements across the deck; raise the asset_plan totals."))

    raw_high = data.get("high_leverage_slides")
    high_numbers = high_leverage_numbers(data)
    if high_score:
        if not isinstance(raw_high, list) or not 3 <= len(raw_high) <= 5:
            issues.append(issue("major", "high_leverage_count_invalid", "High-score Art Direction must identify 3–5 high-leverage slides."))
        if len(set(high_numbers)) != len(high_numbers) or len(high_numbers) != len(raw_high or []):
            issues.append(issue("major", "high_leverage_slides_invalid", "Every high-leverage entry needs a unique positive integer slide number."))
        if isinstance(raw_high, list):
            for item in raw_high:
                if not isinstance(item, dict) or len(str(item.get("reason") or "").strip()) < 16:
                    issues.append(issue("major", "high_leverage_reason_missing", "Each high-leverage slide needs a concrete reason for multi-candidate exploration."))
                    break

    blockers = [item for item in issues if item["severity"] in BLOCKING]
    return {
        "ok": not blockers,
        "generation_core_version": "0.8",
        "high_leverage_slides": high_numbers,
        "blocker_count": len(blockers),
        "issue_count": len(issues),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("art_direction", type=Path)
    parser.add_argument("--quality", choices=["high-score", "standard"], default="high-score")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="deprecated no-op alias; gates are fail-closed by default")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="opt-in relaxation: exit 0 even when the report is not ok (default is fail-closed)",
    )
    args = parser.parse_args()

    report = validate_art_direction(load_structured(args.art_direction), high_score=args.quality == "high-score")
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
