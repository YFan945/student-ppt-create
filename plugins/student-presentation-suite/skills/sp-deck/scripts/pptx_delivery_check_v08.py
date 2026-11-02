#!/usr/bin/env python3
"""v0.8 delivery gate with visual-generation evidence binding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pptx_delivery_check as legacy

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from page_brief import load_structured  # noqa: E402

from shared.design_policy import model_led  # noqa: E402
from shared.hashing import file_sha256 as sha256_file  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]




def validate_visual_generation_report(path: Path, slide_spec: Path, art_direction: Path) -> dict:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"Cannot read v0.8 visual-generation report: {exc}"]}
    if not isinstance(data, dict):
        errors.append("v0.8 visual-generation report must be a JSON object.")
        return {"valid": False, "errors": errors}
    if data.get("ok") is not True:
        errors.append("v0.8 visual-generation gate did not pass.")
    if data.get("generation_core_version") != "0.8":
        errors.append("Visual-generation report is not a v0.8 report.")
    if slide_spec.is_file() and data.get("slide_spec_sha256") != sha256_file(slide_spec):
        errors.append("Visual-generation report does not match the current frozen Slide Spec.")
    if art_direction.is_file() and data.get("art_direction_sha256") != sha256_file(art_direction):
        errors.append("Visual-generation report does not match the current Art Direction.")
    high = data.get("high_leverage_slides")
    evidence = data.get("evidence")
    if not isinstance(high, list) or not high:
        errors.append("Visual-generation report has no high-leverage slide plan.")
    if not isinstance(evidence, list) or len(evidence) != len(high or []):
        errors.append("Visual-generation report does not cover every high-leverage slide.")
    else:
        # D2 consistency: fast tiers treat wireframes as advisory exploration, so
        # the report legitimately carries no wireframe_sha256 for its slides;
        # demanding it here would make every wireframe-less fast deck undeliverable.
        discretionary = model_led(load_structured(slide_spec)) if slide_spec.is_file() else False
        require_wireframe = data.get("quality") != "fast" and not discretionary
        for item in evidence:
            if not isinstance(item, dict):
                errors.append("Visual-generation evidence entry is invalid.")
                continue
            keys = [] if discretionary else ["reference_selection_sha256", "composition_candidates_sha256"]
            if require_wireframe:
                keys.append("wireframe_sha256")
            for key in keys:
                value = item.get(key)
                if not isinstance(value, str) or len(value) != 64:
                    errors.append(f"High-leverage slide {item.get('slide')} lacks valid {key}.")
    if data.get("blocker_count") not in (0, None):
        errors.append("Visual-generation report still contains blockers.")
    return {
        "valid": not errors,
        "errors": errors,
        "sha256": sha256_file(path) if path.is_file() else None,
        "report": data,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student PPT v0.8 delivery check")
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--spec-lock", type=Path, required=True)
    parser.add_argument("--art-direction", type=Path, required=True)
    parser.add_argument("--visual-generation-report", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--preview", type=Path, action="append", default=[])
    parser.add_argument("--pdf", type=Path, help="Requested PDF export (also counts as preview evidence)")
    parser.add_argument(
        "--full-script",
        type=Path,
        help="Requested full-script Markdown; discovered by name when omitted",
    )
    parser.add_argument(
        "--teleprompter",
        type=Path,
        help="Requested HTML teleprompter; discovered by name when omitted",
    )
    parser.add_argument("--package-report", type=Path, required=True)
    parser.add_argument("--slide-spec-report", type=Path, required=True)
    parser.add_argument("--actual-content-report", type=Path, required=True)
    parser.add_argument("--visual-reviewed", action="store_true")
    parser.add_argument(
        "--visual-review-report",
        type=Path,
        help="Visual-review JSON bound to the PPTX via pptx_sha256; required for completion",
    )
    parser.add_argument("--allow-missing-notes", action="store_true")
    parser.add_argument("--allow-missing-preview", action="store_true")
    parser.add_argument(
        "--deliverables",
        help=(
            "Comma-separated confirmed deliverables (e.g. 'pptx'). When omitted "
            "they are read from --slide-spec meta.deliverables."
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def deliverables_from_spec(spec_path: Path) -> list[str] | None:
    """Read confirmed deliverables from a Slide Spec.

    Keeps the gate honest about what the user actually approved: the pipeline
    always renders pages and a contact sheet for QA, but a deck approved as
    "PPTX only" must not fail delivery for a speaker-notes file nobody asked
    for. ``None`` means the spec is silent or unreadable, and
    ``resolve_requirements`` then keeps the historical default (notes and
    preview required) so projects predating `meta.deliverables` keep the
    behaviour they were validated under.
    """
    try:
        if spec_path.suffix.lower() == ".json":
            data = json.loads(spec_path.read_text(encoding="utf-8"))
        else:
            import yaml  # noqa: PLC0415 - optional dependency, spec YAML is not always parsed here

            data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, ImportError):
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        return None
    for key in ("deliverables", "export_formats"):
        value = meta.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    return None


def confirmed_deliverables(spec_path: Path, raw: str | None) -> list[str]:
    """The confirmed set, resolved through ONE rule shared with the brief.

    `slide_spec_to_pptx_brief.required_deliverables()` decides what the
    Production Summary and the generation brief call owed; this gate must read
    the same source with the same fallback, or a spec with no
    `meta.deliverables` produces "Brief: PPTX only" from the brief and
    "Delivery QA: Notes required" from the gate. The brief owns the default
    (`["pptx"]`); this module only decides between "spec said something" and
    "nobody said anything", because the latter is what selects the legacy
    default in `resolve_requirements`.
    """
    explicit = legacy.parse_deliverables(raw)
    if explicit is not None:
        return explicit
    return deliverables_from_spec(spec_path) or list(brief_required_deliverables({}))


def brief_required_deliverables(meta: dict) -> list[str]:
    """The brief's own resolver, imported without a second copy of the rule."""
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))
    try:
        from slide_spec_to_pptx_brief import required_deliverables  # noqa: PLC0415

        return required_deliverables(meta)
    except ImportError:  # pragma: no cover - brief module always ships with the plugin
        return ["pptx"]


def main() -> int:
    from shared.validation_cli import main as validate_cli
    return validate_cli("delivery")


if __name__ == "__main__":
    main()
