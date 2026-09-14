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

# Research Gate artifacts a freeze can bind. All optional: decks with no external
# facts are still legitimate, they simply carry no research block.
RESEARCH_ARGS = (
    ("--research-pack", "research-pack.json to bind into the freeze"),
    ("--research-validation", "validate_research_pack.py report to bind"),
    ("--evidence-map", "evidence-map.json from research_pack_to_evidence.py"),
)


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


def bind_research(paths: dict[str, Path]) -> dict[str, Any]:
    """Record the research artifacts a freeze depends on.

    The Research Gate is only real if the plan it froze is bound to the evidence it
    was built from. Without these hashes a pack can be edited after freeze and
    nothing notices that the deck now cites evidence nobody validated.
    """
    bound: dict[str, Any] = {}
    for name, path in sorted(paths.items()):
        if path is None:
            continue
        if not path.is_file():
            raise SystemExit(f"Research artifact does not exist: {name} -> {path}")
        bound[name] = {"path": str(path.resolve()), "sha256": sha256_file(path)}
    return bound


def make_lock(
    spec: Path,
    validation_report: Path,
    *,
    revision: int,
    reason: str,
    parent_sha256: str | None = None,
    research: dict[str, Path] | None = None,
) -> dict[str, Any]:
    spec_hash, report_hash = validated_spec(spec, validation_report)
    lock = {
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
    bound = bind_research(research or {})
    if bound:
        lock["research"] = bound
    return lock


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
    for name, entry in (lock.get("research") or {}).items():
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path") or ""))
        if not path.is_file():
            errors.append(f"Bound research artifact is missing: {name}.")
        elif entry.get("sha256") != sha256_file(path):
            errors.append(
                f"Bound research artifact changed after freeze: {name}. "
                "Re-run the Research Gate and `revise` with a reason."
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
    for name, help_text in RESEARCH_ARGS:
        freeze.add_argument(name, type=Path, help=help_text)

    check = sub.add_parser("check", help="Verify the frozen Slide Spec has not changed")
    check.add_argument("--lock-file", type=Path, required=True)
    check.add_argument("--slide-spec", type=Path)
    check.add_argument("--json", action="store_true")

    revise = sub.add_parser("revise", help="Explicitly replace the frozen plan")
    revise.add_argument("--slide-spec", type=Path, required=True)
    revise.add_argument("--validation-report", type=Path, required=True)
    revise.add_argument("--lock-file", type=Path, required=True)
    revise.add_argument("--reason", required=True)
    for name, help_text in RESEARCH_ARGS:
        revise.add_argument(name, type=Path, help=help_text)

    return parser.parse_args()


def research_bindings(args: argparse.Namespace) -> dict[str, Path]:
    """Collect whichever Research Gate artifacts the caller supplied."""
    out: dict[str, Path] = {}
    for name, _ in RESEARCH_ARGS:
        key = name.lstrip("-").replace("-", "_")
        value = getattr(args, key, None)
        if value is not None:
            out[key] = value
    return out


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
            research=research_bindings(args),
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
        research=research_bindings(args),
    )
    lock["revised_at"] = lock.pop("frozen_at")
    write_lock(args.lock_file, lock)
    print(json.dumps({"ok": True, "action": "revise", **lock}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
