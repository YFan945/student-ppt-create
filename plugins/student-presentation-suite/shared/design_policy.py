"""Design freedom is independent of assurance tier and frozen per work-id."""

from __future__ import annotations

from typing import Any

MODES = ("auto", "guided", "deterministic")
DESIGN_FAILURES = {
    "text_overflow", "text_may_overflow", "text_overlap", "out_of_canvas",
    "layout_fit", "layoutFit", "near_miss_alignment", "unreadable",
    "composition_failure", "asset_crop_invalid",
    "invalid_bbox", "non_positive_size",
}

FACT_OR_CONSTRAINT_FAILURES = {
    "unsupported_claim", "factual_error", "source_mismatch", "semantic_contradiction",
    "bar-height-implies-unstated-ratio", "unsupported_visual_ratio",
    "brand_constraint_changed", "template_constraint_changed", "logo_missing", "preserve_violation",
}


def failure_class(code: str) -> str:
    return "fit" if code in {"text_overflow", "text_may_overflow", "layout_fit", "layoutFit", "invalid_bbox", "non_positive_size"} else "composition"


def design_mode(spec: dict[str, Any]) -> str:
    value = (spec.get("meta") or {}).get("design_freedom")
    if value is not None:
        if value not in MODES:
            raise ValueError(f"Unknown design_freedom: {value}")
        return str(value)
    return "auto" if spec.get("schema_version") == "2.1" else "guided"


def model_led(spec: dict[str, Any]) -> bool:
    return spec.get("schema_version") == "2.1" or "design_freedom" in (spec.get("meta") or {})


def advance_design(manifest: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """After an unsuccessful repair, lower only pages with recurring design defects.

    Content, source, receipt and package failures never cause a downgrade.
    This records page choices without adding execution limits.
    """
    if "design_freedom" not in manifest or manifest.get("model_led") is False:
        return  # historical work-id, not a migration
    state = manifest.setdefault("design_state", {})
    previous = set()
    for signature in state.get("signatures", []):
        page, _, code = str(signature).partition(":")
        previous.add(f"{page}:{failure_class(code) if code in DESIGN_FAILURES else code}")
    current: set[str] = set()
    modes = state.setdefault("page_modes", {})
    downgraded: set[str] = set()
    for finding in findings:
        code = str(finding.get("code") or "")
        code = code.removeprefix("registry-")
        slide = finding.get("slide")
        if code in FACT_OR_CONSTRAINT_FAILURES or finding.get("category") in {"fact", "user_constraint"}:
            continue
        if not isinstance(slide, int) or slide < 1:
            continue
        if code in DESIGN_FAILURES:
            category = failure_class(code)
        elif finding.get("category") == "readability":
            category = "fit"
        elif finding.get("category") == "structure" and finding.get("repair_level") == "composition":
            category = "composition"
        else:
            continue
        signature = f"{slide}:{category}"
        current.add(signature)
        key = str(slide)
        if signature not in previous or key in downgraded:
            continue
        before = modes.get(key, manifest["design_freedom"])
        after = {"auto": "guided", "guided": "deterministic"}.get(before, before)
        if before != after:
            modes[key] = after
            downgraded.add(key)
            state.setdefault("history", []).append({
                "slide": slide, "from": before, "to": after, "code": code, "class": category,
                "repair": (manifest.get("build") or {}).get("repair_count", 0) + 1,
            })
    state["signatures"] = sorted(current)
