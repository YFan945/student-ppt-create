"""Cross-artifact validation for Presentation Brief and Slide Spec handoffs."""

from __future__ import annotations

from typing import Any


def _error(path: str, message: str) -> dict[str, str]:
    return {"path": path, "message": message}


def handoff_errors(brief: Any, spec: Any) -> list[dict[str, str]]:
    """Return mismatches between a validated Brief and a validated Slide Spec."""
    if not isinstance(brief, dict) or not isinstance(spec, dict):
        return [_error(".", "Presentation Brief and Slide Spec must both be objects")]
    meta = spec.get("meta") or {}
    if not isinstance(meta, dict):
        return [_error(".meta", "Slide Spec meta must be an object")]

    errors: list[dict[str, str]] = []
    scalar_map = {
        "topic": "topic",
        "scenario": "scenario",
        "language": "language",
        "duration_min": "duration_min",
        "slide_count": "slide_count",
        "format": "format",
        "structure_mode": "structure_mode",
        "interaction_mode": "interaction_mode",
        "quality_level": "quality_level",
        "design_freedom": "design_freedom",
        "visual_style": "visual_style",
        "image_source": "image_source",
        "output_prefix": "output_prefix",
    }
    if spec.get("schema_version") == "2.1" or "design_freedom" in meta:
        scalar_map.update({"brand": "brand", "logo": "logo", "template": "template"})
    for brief_key, meta_key in scalar_map.items():
        brief_value = brief.get(brief_key)
        meta_value = meta.get(meta_key)
        if brief_value is not None and meta_value != brief_value:
            errors.append(
                _error(
                    f".meta.{meta_key}",
                    f"does not match Presentation Brief {brief_key}: {meta_value!r} != {brief_value!r}",
                )
            )

    brief_custom_style = brief.get("visual_style_custom")
    spec_custom_style = meta.get("visual_style_custom")
    if brief_custom_style is not None and spec_custom_style != brief_custom_style:
        errors.append(
            _error(
                ".meta.visual_style_custom",
                "does not match Presentation Brief visual_style_custom",
            )
        )

    audience = brief.get("audience") or {}
    if isinstance(audience, dict):
        for brief_key, meta_key in (("type", "audience_type"), ("depth", "audience_depth")):
            brief_value = audience.get(brief_key)
            meta_value = meta.get(meta_key)
            if brief_value is not None and meta_value != brief_value:
                errors.append(
                    _error(
                        f".meta.{meta_key}",
                        f"does not match Presentation Brief audience.{brief_key}: "
                        f"{meta_value!r} != {brief_value!r}",
                    )
                )

    controls = brief.get("controls") or {}
    if isinstance(controls, dict):
        control_map = {
            "max_words_per_slide": "max_words_per_slide",
            "max_chinese_chars_per_slide": "max_chinese_chars_per_slide",
            "visual_text_ratio": "visual_text_ratio",
            "speaker_notes": "include_speaker_notes",
            "key_lines": "include_key_lines",
            "citations": "citation_style",
            "versioning": "versioning",
        }
        for brief_key, meta_key in control_map.items():
            brief_value = controls.get(brief_key)
            meta_value = meta.get(meta_key)
            if brief_value is not None and meta_value != brief_value:
                errors.append(
                    _error(
                        f".meta.{meta_key}",
                        f"does not match Presentation Brief controls.{brief_key}: "
                        f"{meta_value!r} != {brief_value!r}",
                    )
                )

    brief_deliverables = set(brief.get("deliverables") or [])
    spec_deliverables = set(meta.get("deliverables") or [])
    if brief_deliverables and brief_deliverables != spec_deliverables:
        errors.append(
            _error(
                ".meta.deliverables",
                "does not match Presentation Brief deliverables: "
                f"{sorted(spec_deliverables)!r} != {sorted(brief_deliverables)!r}",
            )
        )
    return errors
