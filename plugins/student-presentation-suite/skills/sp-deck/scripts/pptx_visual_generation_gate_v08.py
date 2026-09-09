#!/usr/bin/env python3
"""Hard gate for v0.8 visual-generation evidence.

The skill text requires Art Direction, reference retrieval and multi-candidate
wireframe exploration for high-leverage slides. This script turns those steps
into auditable production evidence so the final delivery cannot silently fall
back to the old `Slide Spec -> deck.js` path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import art_direction_check as art_check  # noqa: E402
import composition_candidate_check as candidate_check  # noqa: E402

REFERENCE_LIBRARY = HERE.parent / "references" / "visual-reference-library.json"
BLOCKING = {"critical", "major"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit(f"Structured file root must be an object: {path}")
    return value


def issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def slide_ids(spec: dict[str, Any]) -> set[int]:
    result: set[int] = set()
    for item in spec.get("slides") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("id")
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return result


def wireframe_slide_count(path: Path) -> int | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(
                bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
                for name in archive.namelist()
            )
    except (OSError, zipfile.BadZipFile):
        return None


def validate_reference_selection(
    path: Path,
    *,
    known_reference_ids: set[str],
    minimum: int = 2,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"Cannot read reference selection: {exc}"]}
    selected = data.get("selected") if isinstance(data, dict) else None
    if not isinstance(selected, list) or len(selected) < minimum:
        errors.append(f"Reference selection must contain at least {minimum} references.")
        selected = selected if isinstance(selected, list) else []
    ids: list[str] = []
    silhouettes: list[str] = []
    for item in selected:
        if not isinstance(item, dict):
            errors.append("Each reference selection entry must be an object.")
            continue
        ref_id = str(item.get("id") or "").strip()
        silhouette = str(item.get("silhouette") or "").strip()
        if not ref_id or ref_id not in known_reference_ids:
            errors.append(f"Unknown visual reference id: {ref_id or '<missing>'}.")
        else:
            ids.append(ref_id)
        if silhouette:
            silhouettes.append(silhouette)
    if len(set(silhouettes)) < min(minimum, len(selected)):
        errors.append("Reference selection must expose distinct silhouettes, not duplicate recipes.")
    return {
        "valid": not errors,
        "errors": errors,
        "sha256": sha256_file(path) if path.is_file() else None,
        "reference_ids": ids,
        "silhouettes": silhouettes,
    }


def validate_visual_generation(
    *,
    slide_spec: Path,
    art_direction: Path,
    evidence_dir: Path,
    quality: str = "high-score",
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    high_score = quality == "high-score"
    try:
        spec = load_structured(slide_spec)
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "generation_core_version": "0.8",
            "blocker_count": 1,
            "issues": [issue("critical", "slide_spec_unreadable", str(exc))],
        }
    try:
        art_data = load_structured(art_direction)
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "generation_core_version": "0.8",
            "blocker_count": 1,
            "issues": [issue("critical", "art_direction_unreadable", str(exc))],
        }

    art_report = art_check.validate_art_direction(art_data, high_score=high_score)
    if not art_report["ok"]:
        for item in art_report["issues"]:
            if item.get("severity") in BLOCKING:
                issues.append({**item, "source": "art-direction"})

    spec_ids = slide_ids(spec)
    high_leverage = art_report.get("high_leverage_slides") or []
    unknown_high = [value for value in high_leverage if value not in spec_ids]
    if unknown_high:
        issues.append(
            issue(
                "critical",
                "high_leverage_unknown_slide",
                f"Art Direction references unknown Slide Spec ids: {unknown_high}.",
            )
        )

    known_refs = candidate_check.load_reference_ids(REFERENCE_LIBRARY)
    evidence: list[dict[str, Any]] = []
    for slide_no in high_leverage:
        ref_path = evidence_dir / f"references-slide-{slide_no}.json"
        candidate_path = evidence_dir / f"composition-candidates-{slide_no}.json"
        wireframe_path = evidence_dir / f"wireframes-{slide_no}.pptx"

        item: dict[str, Any] = {"slide": slide_no}
        if not ref_path.is_file():
            issues.append(issue("critical", "reference_selection_missing", f"Missing visual reference selection for high-leverage slide {slide_no}.", slide=slide_no))
            ref_result = {"valid": False, "errors": ["missing"]}
        else:
            ref_result = validate_reference_selection(ref_path, known_reference_ids=known_refs, minimum=2)
            if not ref_result["valid"]:
                issues.append(issue("major", "reference_selection_invalid", f"Invalid reference selection for slide {slide_no}: {ref_result['errors']}", slide=slide_no))
            item["reference_selection_sha256"] = ref_result.get("sha256")
            item["reference_ids"] = ref_result.get("reference_ids", [])

        if not candidate_path.is_file():
            issues.append(issue("critical", "composition_candidates_missing", f"Missing composition candidates for high-leverage slide {slide_no}.", slide=slide_no))
            candidate_result = {"ok": False, "candidate_count": 0}
        else:
            candidate_data = load_structured(candidate_path)
            if int(candidate_data.get("slide_id") or 0) != slide_no:
                issues.append(issue("critical", "candidate_slide_mismatch", f"Candidate file for slide {slide_no} declares another slide id.", slide=slide_no))
            if candidate_data.get("high_leverage") is not True:
                issues.append(issue("major", "candidate_not_high_leverage", f"Candidate file for slide {slide_no} must declare high_leverage=true.", slide=slide_no))
            candidate_result = candidate_check.validate_candidates(
                candidate_data,
                known_reference_ids=known_refs,
                high_score=high_score,
            )
            if not candidate_result["ok"]:
                issues.append(issue("major", "composition_candidates_invalid", f"Composition candidates for slide {slide_no} failed validation.", slide=slide_no, candidate_issues=candidate_result["issues"]))
            candidate_refs = {
                str(ref)
                for candidate in candidate_data.get("candidates") or []
                if isinstance(candidate, dict)
                for ref in candidate.get("reference_ids") or []
            }
            selected_refs = set(ref_result.get("reference_ids") or [])
            if selected_refs and candidate_refs and not candidate_refs.intersection(selected_refs):
                issues.append(issue("major", "candidate_reference_disconnected", f"Slide {slide_no} candidates do not use any retrieved visual reference.", slide=slide_no))
            item["composition_candidates_sha256"] = sha256_file(candidate_path)
            item["candidate_count"] = candidate_result.get("candidate_count")
            item["selected_id"] = candidate_result.get("selected_id")

        if not wireframe_path.is_file():
            issues.append(issue("critical", "wireframe_missing", f"Missing wireframe PPTX for high-leverage slide {slide_no}.", slide=slide_no))
        else:
            count = wireframe_slide_count(wireframe_path)
            if count is None:
                issues.append(issue("critical", "wireframe_invalid", f"Wireframe file for slide {slide_no} is not a readable PPTX.", slide=slide_no))
            elif candidate_result.get("candidate_count") and count != candidate_result.get("candidate_count"):
                issues.append(issue("major", "wireframe_candidate_count_mismatch", f"Wireframe slide count {count} does not match candidate count for slide {slide_no}.", slide=slide_no))
            item["wireframe_sha256"] = sha256_file(wireframe_path)
            item["wireframe_slide_count"] = count
        evidence.append(item)

    blockers = [item for item in issues if item["severity"] in BLOCKING]
    return {
        "ok": not blockers,
        "generation_core_version": "0.8",
        "slide_spec_sha256": sha256_file(slide_spec) if slide_spec.is_file() else None,
        "art_direction_sha256": sha256_file(art_direction) if art_direction.is_file() else None,
        "reference_library_sha256": sha256_file(REFERENCE_LIBRARY),
        "quality": quality,
        "high_leverage_slides": high_leverage,
        "evidence": evidence,
        "blocker_count": len(blockers),
        "issue_count": len(issues),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--art-direction", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--quality", choices=["high-score", "standard"], default="high-score")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report = validate_visual_generation(
        slide_spec=args.slide_spec,
        art_direction=args.art_direction,
        evidence_dir=args.evidence_dir,
        quality=args.quality,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    if args.strict and not report["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
