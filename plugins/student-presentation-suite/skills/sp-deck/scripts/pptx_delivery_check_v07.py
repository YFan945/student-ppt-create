#!/usr/bin/env python3
"""v0.7 simplified delivery gate with actual-artifact binding.

This wrapper reuses the existing delivery checker and adds one new hard gate:
`pptx_actual_content_check.py` must pass and be bound to the current PPTX.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.hashing import file_sha256 as sha256_file  # noqa: E402


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
    parser.add_argument("--deliverables", help="Comma-separated confirmed deliverables (e.g. 'pptx')")
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


def main() -> int:
    from shared.validation_cli import main as validate_cli
    return validate_cli("delivery")


if __name__ == "__main__":
    main()
