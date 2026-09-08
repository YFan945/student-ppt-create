#!/usr/bin/env python3
"""Artifact-aware simplified delivery gate for sp-deck.

Runs the existing simplified delivery checker, then binds the actual-PPTX static
analysis and plan-vs-actual reports to the same PPTX hash. The resulting report
uses gate_profile=simplified-v2 and is intended for workflow_guard completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bound_report(path: Path, *, expected_profile: str, pptx_sha256: str, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Cannot read {label}: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{label} root must be an object."]
    if data.get("profile") != expected_profile:
        errors.append(f"{label} profile is unsupported: {data.get('profile')!r}")
    if data.get("ok") is not True:
        errors.append(f"{label} did not pass.")
    if data.get("pptx_sha256") != pptx_sha256:
        errors.append(f"{label} is not bound to the current PPTX.")
    return data, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Artifact-aware simplified PPTX delivery gate")
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--slide-spec-report", type=Path, required=True)
    parser.add_argument("--package-report", type=Path, required=True)
    parser.add_argument("--static-report", type=Path, required=True)
    parser.add_argument("--plan-actual-report", type=Path, required=True)
    parser.add_argument("--preview", type=Path, action="append", default=[])
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--teleprompter", type=Path)
    parser.add_argument("--quality-report", type=Path)
    parser.add_argument("--revision-manifest", type=Path)
    parser.add_argument("--allow-missing-notes", action="store_true")
    parser.add_argument("--allow-missing-preview", action="store_true")
    parser.add_argument("--visual-reviewed", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.pptx.is_file():
        raise SystemExit(f"PPTX not found: {args.pptx}")
    pptx_hash = sha256_file(args.pptx)

    static_data, static_errors = read_bound_report(
        args.static_report,
        expected_profile="actual-pptx-static-v1",
        pptx_sha256=pptx_hash,
        label="static artifact report",
    )
    plan_data, plan_errors = read_bound_report(
        args.plan_actual_report,
        expected_profile="plan-vs-actual-v1",
        pptx_sha256=pptx_hash,
        label="plan-vs-actual report",
    )
    errors = static_errors + plan_errors
    if errors:
        payload = {"ok": False, "status": "incomplete", "errors": errors}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if args.strict else 1

    checker = Path(__file__).with_name("pptx_delivery_check.py")
    with tempfile.TemporaryDirectory(prefix="pptx-delivery-v2-") as td:
        base_report = Path(td) / "base-delivery.json"
        command = [
            sys.executable,
            str(checker),
            "--simple",
            "--strict",
            "--visual-reviewed",
            "--pptx",
            str(args.pptx),
            "--slide-spec-report",
            str(args.slide_spec_report),
            "--package-report",
            str(args.package_report),
            "--output",
            str(base_report),
            "--json",
        ]
        for preview in args.preview:
            command.extend(["--preview", str(preview)])
        for flag, value in (
            ("--notes", args.notes),
            ("--pdf", args.pdf),
            ("--teleprompter", args.teleprompter),
            ("--quality-report", args.quality_report),
            ("--revision-manifest", args.revision_manifest),
        ):
            if value is not None:
                command.extend([flag, str(value)])
        if args.allow_missing_notes:
            command.append("--allow-missing-notes")
        if args.allow_missing_preview:
            command.append("--allow-missing-preview")

        completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
        if completed.returncode != 0 or not base_report.is_file():
            if args.json and completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, file=sys.stderr, end="")
            return completed.returncode or 2

        report = json.loads(base_report.read_text(encoding="utf-8"))

    report.update(
        {
            "gate_profile": "simplified-v2",
            "static_artifact_passed": True,
            "static_report": str(args.static_report.resolve()),
            "static_report_sha256": sha256_file(args.static_report),
            "static_warnings": (static_data or {}).get("warnings", 0),
            "plan_actual_passed": True,
            "plan_actual_report": str(args.plan_actual_report.resolve()),
            "plan_actual_report_sha256": sha256_file(args.plan_actual_report),
            "plan_actual_warnings": (plan_data or {}).get("warnings", 0),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
