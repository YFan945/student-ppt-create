#!/usr/bin/env python3
"""v0.8 delivery gate with visual-generation evidence binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pptx_delivery_check as legacy
import pptx_delivery_check_v07 as v07
import pptx_delivery_check_v071 as v071

PLUGIN_ROOT = Path(__file__).resolve().parents[3]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        for item in evidence:
            if not isinstance(item, dict):
                errors.append("Visual-generation evidence entry is invalid.")
                continue
            for key in (
                "reference_selection_sha256",
                "composition_candidates_sha256",
                "wireframe_sha256",
            ):
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


def main() -> None:
    args = parse_args()
    deliverables = confirmed_deliverables(args.slide_spec, args.deliverables)
    owed = legacy.required_deliverables(
        deliverables,
        allow_missing_notes=args.allow_missing_notes,
        allow_missing_preview=args.allow_missing_preview,
    )
    require_notes, require_preview = legacy.resolve_requirements(
        deliverables,
        allow_missing_notes=args.allow_missing_notes,
        allow_missing_preview=args.allow_missing_preview,
    )
    result = legacy.inspect_delivery(
        args.pptx,
        args.notes,
        args.preview,
        require_notes=require_notes,
        require_preview=require_preview,
        owed_deliverables=owed,
        extra_files={
            "pdf": args.pdf,
            "full-script": args.full_script,
            "teleprompter": args.teleprompter,
        },
        package_report=args.package_report,
        require_package_report=True,
        slide_spec_report=args.slide_spec_report,
        simple=True,
        visual_reviewed=args.visual_reviewed,
        visual_review_report=args.visual_review_report,
    )
    actual = v07.validate_actual_report(args.actual_content_report, args.pptx, result.get("slide_count"))
    quality = v071.validate_quality_report(
        args.quality_report,
        args.pptx,
        args.slide_spec,
        args.spec_lock,
        result.get("slide_count"),
    )
    visual_generation = validate_visual_generation_report(
        args.visual_generation_report,
        args.slide_spec,
        args.art_direction,
    )
    result["actual_content_report"] = actual
    result["quality_report"] = quality
    result["visual_generation_report"] = visual_generation

    delivery = result["delivery_report"]
    delivery["actual_content_check_passed"] = actual["valid"]
    delivery["actual_content_report_sha256"] = actual.get("sha256")
    delivery["quality_check_passed"] = quality["valid"]
    delivery["quality_report_sha256"] = quality.get("sha256")
    delivery["visual_generation_check_passed"] = visual_generation["valid"]
    delivery["visual_generation_report_sha256"] = visual_generation.get("sha256")
    delivery["slide_spec_sha256"] = sha256_file(args.slide_spec) if args.slide_spec.is_file() else None
    delivery["spec_lock_sha256"] = sha256_file(args.spec_lock) if args.spec_lock.is_file() else None
    delivery["art_direction_sha256"] = sha256_file(args.art_direction) if args.art_direction.is_file() else None
    delivery["gate_profile"] = "simplified-v08"
    delivery["generation_core_version"] = "0.8"
    delivery["deliverables"] = deliverables
    delivery["owed_deliverables"] = owed
    delivery["notes_required"] = require_notes
    delivery["preview_required"] = require_preview
    delivery["missing_deliverables"] = [
        name for name, evidence in result.get("deliverable_evidence", {}).items() if not evidence["satisfied"]
    ]

    review_check = (result.get("delivery_report") or {}).get("visual_review_check") or {}
    delivery["visual_review_check_passed"] = review_check.get("valid") is True
    if not review_check.get("valid"):
        result["ok"] = False

    if not actual["valid"] or not quality["valid"] or not visual_generation["valid"]:
        result["ok"] = False
        delivery["ok"] = False
        delivery["status"] = "incomplete"
    # Per-name deliverable verification is the last word: confirming a deliverable
    # and then not producing its file must block completion, not just appear as a
    # warning line in the report. `required_deliverables` already limits `owed` to
    # names backed by a concrete artifact (and honours --allow-missing-*), so an
    # empty `owed` — e.g. "PPTX only" — cannot fail here.
    if delivery["missing_deliverables"]:
        result["ok"] = False
        delivery["ok"] = False
        delivery["status"] = "incomplete"
        delivery["deliverable_blockers"] = delivery["missing_deliverables"]

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        legacy.print_text(result)
        print(f"Actual content check: valid={actual['valid']} errors={actual['errors']}")
        print(f"Quality check: valid={quality['valid']} errors={quality['errors']}")
        print(
            "Visual generation check: "
            f"valid={visual_generation['valid']} errors={visual_generation['errors']}"
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.strict and not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
