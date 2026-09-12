#!/usr/bin/env python3
"""Freeze a validated Slide Spec and prevent silent plan drift during production.

The Slide Spec is the approved production plan. Once frozen, generator/readback
failures must be fixed in the artifact, not by silently rewriting the plan.
A genuine plan change must use the explicit `revise` command with a reason and
a fresh passing validation report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCK_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


def load_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"Slide Spec lock does not exist: {path}")
    return load_json(path)


def validated_spec(spec: Path, report: Path) -> tuple[str, str]:
    if not spec.is_file():
        raise SystemExit(f"Slide Spec does not exist: {spec}")
    if not report.is_file():
        raise SystemExit(f"Slide Spec validation report does not exist: {report}")
    data = load_json(report)
    spec_hash = sha256_file(spec)
    if data.get("valid") is not True:
        raise SystemExit("Slide Spec validation report is not passing.")
    if data.get("slide_spec_sha256") != spec_hash:
        raise SystemExit("Slide Spec validation report is stale or belongs to another spec.")
    return spec_hash, sha256_file(report)


def make_lock(
    spec: Path,
    validation_report: Path,
    *,
    revision: int,
    reason: str,
    parent_sha256: str | None = None,
) -> dict[str, Any]:
    spec_hash, report_hash = validated_spec(spec, validation_report)
    return {
        "lock_version": LOCK_VERSION,
        "status": "frozen",
        "revision": revision,
        "reason": reason,
        "parent_slide_spec_sha256": parent_sha256,
        "slide_spec": str(spec.resolve()),
        "slide_spec_sha256": spec_hash,
        "validation_report": str(validation_report.resolve()),
        "validation_report_sha256": report_hash,
        "frozen_at": datetime.now(UTC).isoformat(),
    }


def write_lock(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_lock(lock_path: Path, spec_override: Path | None = None) -> dict[str, Any]:
    lock = load_lock(lock_path)
    errors: list[str] = []
    if lock.get("lock_version") != LOCK_VERSION or lock.get("status") != "frozen":
        errors.append("Slide Spec lock is invalid or is not frozen.")

    spec_value = spec_override or Path(str(lock.get("slide_spec") or ""))
    validation_value = Path(str(lock.get("validation_report") or ""))
    if not spec_value.is_file():
        errors.append("Frozen Slide Spec is missing.")
    elif lock.get("slide_spec_sha256") != sha256_file(spec_value):
        errors.append(
            "Frozen Slide Spec changed after approval. Fix the artifact instead, or use "
            "`slide_spec_guard.py revise --reason ...` for an explicit plan revision."
        )
    if not validation_value.is_file():
        errors.append("Frozen Slide Spec validation report is missing.")
    elif lock.get("validation_report_sha256") != sha256_file(validation_value):
        errors.append("Frozen Slide Spec validation report changed after freeze.")
    else:
        report = load_json(validation_value)
        if report.get("valid") is not True:
            errors.append("Frozen Slide Spec validation report no longer passes.")
        if spec_value.is_file() and report.get("slide_spec_sha256") != sha256_file(spec_value):
            errors.append("Frozen validation report does not match the current Slide Spec.")

    return {
        "ok": not errors,
        "errors": errors,
        "lock": lock,
        "slide_spec_sha256": sha256_file(spec_value) if spec_value.is_file() else None,
        "lock_sha256": sha256_file(lock_path) if lock_path.is_file() else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze/check/revise a validated Slide Spec")
    sub = parser.add_subparsers(dest="action", required=True)

    freeze = sub.add_parser("freeze", help="Freeze the first validated Slide Spec")
    freeze.add_argument("--slide-spec", type=Path, required=True)
    freeze.add_argument("--validation-report", type=Path, required=True)
    freeze.add_argument("--lock-file", type=Path, required=True)
    freeze.add_argument("--reason", default="initial approved production plan")

    check = sub.add_parser("check", help="Verify the frozen Slide Spec has not changed")
    check.add_argument("--lock-file", type=Path, required=True)
    check.add_argument("--slide-spec", type=Path)
    check.add_argument("--json", action="store_true")

    revise = sub.add_parser("revise", help="Explicitly replace the frozen plan")
    revise.add_argument("--slide-spec", type=Path, required=True)
    revise.add_argument("--validation-report", type=Path, required=True)
    revise.add_argument("--lock-file", type=Path, required=True)
    revise.add_argument("--reason", required=True)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "freeze":
        if args.lock_file.exists():
            raise SystemExit(
                "Slide Spec lock already exists. Use `revise` with a concrete reason instead of overwriting it."
            )
        lock = make_lock(
            args.slide_spec,
            args.validation_report,
            revision=1,
            reason=args.reason,
        )
        write_lock(args.lock_file, lock)
        print(json.dumps({"ok": True, "action": "freeze", **lock}, ensure_ascii=False, indent=2))
        return 0

    if args.action == "check":
        result = check_lock(args.lock_file, args.slide_spec)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 2

    previous = load_lock(args.lock_file)
    previous_hash = str(previous.get("slide_spec_sha256") or "") or None
    previous_revision = int(previous.get("revision") or 1)
    lock = make_lock(
        args.slide_spec,
        args.validation_report,
        revision=previous_revision + 1,
        reason=args.reason,
        parent_sha256=previous_hash,
    )
    lock["revised_at"] = lock.pop("frozen_at")
    write_lock(args.lock_file, lock)
    print(json.dumps({"ok": True, "action": "revise", **lock}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
