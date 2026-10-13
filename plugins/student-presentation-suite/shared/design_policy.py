"""Design freedom is independent of assurance tier and frozen per work-id."""

from __future__ import annotations

from typing import Any

MODES = ("auto", "guided", "deterministic")
def design_mode(spec: dict[str, Any]) -> str:
    value = (spec.get("meta") or {}).get("design_freedom")
    if value is not None:
        if value not in MODES:
            raise ValueError(f"Unknown design_freedom: {value}")
        return str(value)
    return "auto" if spec.get("schema_version") == "2.1" else "guided"


def model_led(spec: dict[str, Any]) -> bool:
    return spec.get("schema_version") == "2.1" or "design_freedom" in (spec.get("meta") or {})
