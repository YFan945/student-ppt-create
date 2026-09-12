#!/usr/bin/env python3
"""v0.8 delivery gate with visual-generation evidence binding."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pptx_delivery_check as legacy
import pptx_delivery_check_v07 as v07
import pptx_delivery_check_v071 as v071


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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = legacy.inspect_delivery(
        args.pptx,
        args.notes,
        args.preview,
        require_notes=not args.allow_missing_notes,
        require_preview=not args.allow_missing_preview,
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

    review_check = (result.get("delivery_report") or {}).get("visual_review_check") or {}
    delivery["visual_review_check_passed"] = review_check.get("valid") is True
    if not review_check.get("valid"):
        result["ok"] = False

    if not actual["valid"] or not quality["valid"] or not visual_generation["valid"]:
        result["ok"] = False
        delivery["ok"] = False
        delivery["status"] = "incomplete"

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
