#!/usr/bin/env python3
"""v0.7.1 delivery gate with immutable-plan and quality-report binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pptx_delivery_check as legacy  # noqa: E402
import pptx_delivery_check_v07 as v07  # noqa: E402
import slide_spec_guard as spec_guard  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student PPT v0.7.1 delivery check")
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--spec-lock", type=Path, required=True)
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
        default=None,
        help="visual-review JSON bound to the PPTX via pptx_sha256; "
        "required for the simplified gate to reach complete",
    )
    parser.add_argument("--allow-missing-notes", action="store_true")
    parser.add_argument("--allow-missing-preview", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def validate_quality_report(
    path: Path,
    pptx: Path,
    slide_spec: Path,
    spec_lock_path: Path,
    slide_count: int | None,
) -> dict:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"Cannot read v0.7.1 quality report: {exc}"]}

    if not isinstance(data, dict) or data.get("ok") is not True:
        errors.append("v0.7.1 quality gate did not pass.")
    if data.get("generation_core_version") != "0.7.1":
        errors.append("Quality report is not a v0.7.1 quality report.")
    if pptx.is_file() and data.get("pptx_sha256") != sha256_file(pptx):
        errors.append("Quality report does not match the current PPTX.")
    if slide_spec.is_file() and data.get("slide_spec_sha256") != sha256_file(slide_spec):
        errors.append("Quality report does not match the frozen Slide Spec.")
    if spec_lock_path.is_file() and data.get("spec_lock_sha256") != sha256_file(spec_lock_path):
        errors.append("Quality report does not match the current Slide Spec lock.")
    if slide_count is not None and data.get("slide_count") != slide_count:
        errors.append("Quality report slide count does not match the current PPTX.")
    if data.get("blocker_count") not in (0, None):
        errors.append("Quality report still contains blockers.")

    lock_result = spec_guard.check_lock(spec_lock_path, slide_spec)
    if not lock_result["ok"]:
        errors.extend(lock_result["errors"])

    return {
        "valid": not errors,
        "errors": errors,
        "sha256": sha256_file(path) if path.is_file() else None,
        "report": data,
    }


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
    quality = validate_quality_report(
        args.quality_report,
        args.pptx,
        args.slide_spec,
        args.spec_lock,
        result.get("slide_count"),
    )
    result["actual_content_report"] = actual
    result["quality_report"] = quality

    delivery = result["delivery_report"]
    delivery["actual_content_check_passed"] = actual["valid"]
    delivery["actual_content_report_sha256"] = actual.get("sha256")
    delivery["quality_check_passed"] = quality["valid"]
    delivery["quality_report_sha256"] = quality.get("sha256")
    delivery["slide_spec_sha256"] = sha256_file(args.slide_spec) if args.slide_spec.is_file() else None
    delivery["spec_lock_sha256"] = sha256_file(args.spec_lock) if args.spec_lock.is_file() else None
    delivery["gate_profile"] = "simplified-v1"
    delivery["generation_core_version"] = "0.7.1"

    if not actual["valid"] or not quality["valid"]:
        result["ok"] = False
        delivery["ok"] = False
        delivery["status"] = "incomplete"

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        legacy.print_text(result)
        print(f"Actual content check: valid={actual['valid']} errors={actual['errors']}")
        print(f"Quality check: valid={quality['valid']} errors={quality['errors']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(delivery, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.strict and not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
