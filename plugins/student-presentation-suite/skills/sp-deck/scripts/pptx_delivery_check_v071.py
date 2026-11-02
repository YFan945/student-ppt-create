#!/usr/bin/env python3
"""v0.7.1 delivery gate with immutable-plan and quality-report binding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import slide_spec_guard as spec_guard  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.hashing import file_sha256 as sha256_file  # noqa: E402


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
    parser.add_argument("--deliverables", help="Comma-separated confirmed deliverables (e.g. 'pptx')")
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


def main() -> int:
    from shared.validation_cli import main as validate_cli
    return validate_cli("delivery")


if __name__ == "__main__":
    main()
