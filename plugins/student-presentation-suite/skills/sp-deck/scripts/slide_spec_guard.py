#!/usr/bin/env python3
"""Freeze a validated Slide Spec and prevent silent plan/evidence drift.

The Slide Spec is the approved production plan. Once frozen, generator/readback
failures must be fixed in the artifact, not by silently rewriting the plan. A
new research-backed plan is accepted only when Research Pack -> validation report
-> evidence map -> compiled Slide Spec form one hash-linked provenance chain.

Lock v1.0 remains readable for in-progress work created by older plugin versions;
new freezes use v1.1 and receive the stronger provenance checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCK_VERSION = "1.1"
COMPATIBLE_LOCK_VERSIONS = {"1.0", LOCK_VERSION}
RESEARCH_ARGS = (
    ("--research-pack", "research-pack.json to bind into the freeze"),
    ("--research-validation", "validate_research_pack.py report bound to that pack"),
    ("--evidence-map", "evidence-map.json bound to the pack, validation and compiled spec"),
)
RESEARCH_KEYS = {name.lstrip("-").replace("-", "_") for name, _ in RESEARCH_ARGS}


def _spec_report_regen_hint() -> str:
    """Exact regeneration command for the plan-compiled spec (2026-09-17).

    A live session burned three freeze attempts because the refusal named the
    problem but not the fix: the report must come from the plan-compiled spec
    (slide-spec-compiled.yaml), not the source slide-spec.yaml and not the
    research-pack validation report.
    """
    validator = Path(__file__).resolve().parents[3] / "scripts" / "validate_slide_spec.py"
    return (
        " Regenerate it with: "
        f'"{sys.executable}" "{validator}" "<work-dir>/slide-spec-compiled.yaml" '
        "--output <report.json> (the report must be produced from the plan-compiled "
        "spec, not the source slide-spec.yaml)."
    )


def _research_report_regen_hint() -> str:
    validator = Path(__file__).resolve().parents[3] / "scripts" / "validate_research_pack.py"
    return (
        " Regenerate it with: "
        f'"{sys.executable}" "{validator}" <research-pack.json> '
        "--output <report.json>."
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
        raise SystemExit(
            f"Slide Spec validation report does not exist: {report}.{_spec_report_regen_hint()}"
        )
    data = load_json(report)
    spec_hash = sha256_file(spec)
    if data.get("valid") is not True:
        raise SystemExit(f"Slide Spec validation report is not passing.{_spec_report_regen_hint()}")
    if data.get("slide_spec_sha256") != spec_hash:
        raise SystemExit(
            "Slide Spec validation report is stale or belongs to another spec."
            f"{_spec_report_regen_hint()}"
        )
    return spec_hash, sha256_file(report)


def validate_research_chain(paths: dict[str, Path], spec_hash: str) -> dict[str, Any]:
    """Verify all Research Gate artifacts belong to one exact evidence chain."""
    if not paths:
        return {}
    missing_keys = sorted(RESEARCH_KEYS - set(paths))
    extra_keys = sorted(set(paths) - RESEARCH_KEYS)
    if missing_keys or extra_keys:
        details = []
        if missing_keys:
            details.append(f"missing {missing_keys}")
        if extra_keys:
            details.append(f"unexpected {extra_keys}")
        raise SystemExit(
            "Research Gate is atomic: provide --research-pack, --research-validation and --evidence-map together ("
            + "; ".join(details)
            + ")."
        )

    for name, path in sorted(paths.items()):
        if not path.is_file():
            raise SystemExit(f"Research artifact does not exist: {name} -> {path}")

    pack_path = paths["research_pack"]
    validation_path = paths["research_validation"]
    evidence_map_path = paths["evidence_map"]
    pack_hash = sha256_file(pack_path)
    validation_hash = sha256_file(validation_path)

    validation = load_json(validation_path)
    if validation.get("ok") is not True:
        raise SystemExit(f"Research Pack validation report is not passing.{_research_report_regen_hint()}")
    if validation.get("research_pack_sha256") != pack_hash:
        raise SystemExit(
            "Research Pack validation report is stale or belongs to another pack."
            f"{_research_report_regen_hint()}"
        )

    evidence_map = load_json(evidence_map_path)
    if evidence_map.get("schema_version") != "1.0":
        raise SystemExit("Evidence map schema_version is unsupported; re-run research_pack_to_evidence.py.")
    if evidence_map.get("unresolved_refs"):
        raise SystemExit("Evidence map still has unresolved Slide Spec evidence_refs.")
    provenance = evidence_map.get("provenance") or {}
    if provenance.get("research_pack_sha256") != pack_hash:
        raise SystemExit("Evidence map does not belong to the supplied Research Pack.")
    if provenance.get("research_validation_sha256") != validation_hash:
        raise SystemExit("Evidence map does not belong to the supplied Research Pack validation report.")
    if provenance.get("compiled_slide_spec_sha256") != spec_hash:
        raise SystemExit("Evidence map was not compiled for the Slide Spec being frozen.")

    return {
        "research_pack": {"path": str(pack_path.resolve()), "sha256": pack_hash},
        "research_validation": {"path": str(validation_path.resolve()), "sha256": validation_hash},
        "evidence_map": {
            "path": str(evidence_map_path.resolve()),
            "sha256": sha256_file(evidence_map_path),
            "semantic_sha256": evidence_map.get("semantic_sha256"),
        },
    }


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
    lock: dict[str, Any] = {
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
    bound = validate_research_chain(research or {}, spec_hash)
    if bound:
        lock["research"] = bound
    return lock


def write_lock(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def research_paths_from_lock(lock: dict[str, Any]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, entry in (lock.get("research") or {}).items():
        if isinstance(entry, dict) and entry.get("path"):
            out[str(name)] = Path(str(entry["path"]))
    return out


def check_lock(lock_path: Path, spec_override: Path | None = None) -> dict[str, Any]:
    lock = load_lock(lock_path)
    errors: list[str] = []
    lock_version = str(lock.get("lock_version") or "")
    if lock_version not in COMPATIBLE_LOCK_VERSIONS or lock.get("status") != "frozen":
        errors.append("Slide Spec lock is invalid or is not frozen.")

    spec_value = spec_override or Path(str(lock.get("slide_spec") or ""))
    validation_value = Path(str(lock.get("validation_report") or ""))
    current_spec_hash: str | None = None
    if not spec_value.is_file():
        errors.append("Frozen Slide Spec is missing.")
    else:
        current_spec_hash = sha256_file(spec_value)
        if lock.get("slide_spec_sha256") != current_spec_hash:
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
        if current_spec_hash and report.get("slide_spec_sha256") != current_spec_hash:
            errors.append("Frozen validation report does not match the current Slide Spec.")

    research_paths = research_paths_from_lock(lock)
    for name, entry in (lock.get("research") or {}).items():
        if not isinstance(entry, dict):
            errors.append(f"Bound research artifact metadata is invalid: {name}.")
            continue
        path = Path(str(entry.get("path") or ""))
        if not path.is_file():
            errors.append(f"Bound research artifact is missing: {name}.")
        elif entry.get("sha256") != sha256_file(path):
            errors.append(
                f"Bound research artifact changed after freeze: {name}. "
                "Re-run the Research Gate and `revise` with a reason."
            )

    # New v1.1 locks must keep the full provenance chain valid. Legacy v1.0 locks
    # remain readable so upgrading the plugin does not invalidate in-progress work;
    # their existing file hashes are still checked above. Any revision upgrades the
    # lock to v1.1 and therefore must supply a fresh, fully linked research chain.
    if lock_version == LOCK_VERSION and research_paths and current_spec_hash:
        try:
            validate_research_chain(research_paths, current_spec_hash)
        except SystemExit as exc:
            errors.append(f"Research provenance chain is no longer valid: {exc}")

    return {
        "ok": not errors,
        "errors": errors,
        "lock": lock,
        "slide_spec_sha256": current_spec_hash,
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

    check = sub.add_parser("check", help="Verify the frozen Slide Spec and evidence chain have not changed")
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
    research = research_bindings(args)
    if previous.get("research") and not research:
        raise SystemExit(
            "This lock is research-backed. A revision must supply a freshly compiled Research Gate chain; "
            "omitting it would silently detach the plan from its evidence."
        )
    lock = make_lock(
        args.slide_spec,
        args.validation_report,
        revision=previous_revision + 1,
        reason=args.reason,
        parent_sha256=previous_hash,
        research=research,
    )
    lock["revised_at"] = lock.pop("frozen_at")
    write_lock(args.lock_file, lock)
    print(json.dumps({"ok": True, "action": "revise", **lock}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
