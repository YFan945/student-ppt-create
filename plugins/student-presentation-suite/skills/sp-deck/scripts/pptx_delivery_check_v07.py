#!/usr/bin/env python3
"""v0.7 simplified delivery gate with actual-artifact binding.

This wrapper reuses the existing delivery checker and adds one new hard gate:
`pptx_actual_content_check.py` must pass and be bound to the current PPTX.
"""

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student PPT v0.7 delivery check")
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--preview", type=Path, action="append", default=[])
    parser.add_argument("--package-report", type=Path, required=True)
    parser.add_argument("--slide-spec-report", type=Path, required=True)
    parser.add_argument("--actual-content-report", type=Path, required=True)
    parser.add_argument("--visual-reviewed", action="store_true")
    parser.add_argument("--allow-missing-notes", action="store_true")
    parser.add_argument("--allow-missing-preview", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def validate_actual_report(path: Path, pptx: Path, slide_count: int | None) -> dict:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"Cannot read actual content report: {exc}"]}

    if not isinstance(data, dict) or data.get("ok") is not True:
        errors.append("Actual content check did not pass.")
    if pptx.is_file() and data.get("pptx_sha256") != sha256_file(pptx):
        errors.append("Actual content report does not match the current PPTX.")
    if slide_count is not None and data.get("slide_count") != slide_count:
        errors.append("Actual content report slide count does not match the current PPTX.")
    if data.get("blocker_count") not in (0, None):
        errors.append("Actual content report still contains blockers.")

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
    )

    actual = validate_actual_report(args.actual_content_report, args.pptx, result.get("slide_count"))
    result["actual_content_report"] = actual
    result["delivery_report"]["actual_content_check_passed"] = actual["valid"]
    result["delivery_report"]["actual_content_report_sha256"] = actual.get("sha256")
    result["delivery_report"]["gate_profile"] = "simplified-v2"

    if not actual["valid"]:
        result["ok"] = False
        result["delivery_report"]["ok"] = False
        result["delivery_report"]["status"] = "incomplete"

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        legacy.print_text(result)
        print(f"Actual content check: valid={actual['valid']} errors={actual['errors']}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result["delivery_report"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.strict and not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
