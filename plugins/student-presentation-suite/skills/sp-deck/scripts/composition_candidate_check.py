#!/usr/bin/env python3
"""Validate v0.8 composition candidates before final slide authoring.

High-leverage slides must explore genuinely different silhouettes rather than
jump directly from Slide Spec to final coordinates. This checker validates the
candidate contract, selected reference ids, hierarchy and normalized wireframe
geometry. It does not choose the design for the model; it prevents fake
'multi-candidate' output where all candidates are effectively the same layout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_LIBRARY = HERE.parent / "references" / "visual-reference-library.json"
BLOCKING = {"critical", "major"}
WEAK_STRUCTURES = {"equal-cards", "card-grid", "three-column", "numbered-list", "plain-list"}


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML composition candidate files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit("Composition candidate root must be an object.")
    return value


def issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def load_reference_ids(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    refs = raw.get("references") if isinstance(raw, dict) else []
    return {
        normalize(item.get("id"))
        for item in refs or []
        if isinstance(item, dict) and item.get("id")
    }


def valid_zone(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        return False
    x, y, w, h = [float(item) for item in value]
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1.000001 and y + h <= 1.000001


def validate_candidates(
    data: dict[str, Any],
    *,
    known_reference_ids: set[str] | None = None,
    high_score: bool = True,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    candidates = data.get("candidates")
    high_leverage = data.get("high_leverage") is True
    if not isinstance(candidates, list):
        candidates = []
        issues.append(issue("critical", "candidates_missing", "candidates must be an array."))

    minimum = 2 if high_leverage else 1
    if len(candidates) < minimum:
        issues.append(
            issue(
                "major",
                "candidate_count_low",
                f"This slide requires at least {minimum} composition candidate(s).",
                high_leverage=high_leverage,
            )
        )
    if high_leverage and len(candidates) > 3:
        issues.append(issue("minor", "candidate_count_high", "High-leverage exploration should normally stay at 2–3 focused candidates."))

    by_id: dict[str, dict[str, Any]] = {}
    silhouettes: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            issues.append(issue("major", "candidate_invalid", f"Candidate {index} must be an object."))
            continue
        candidate_id = str(candidate.get("id") or "").strip()
        if not candidate_id:
            issues.append(issue("major", "candidate_id_missing", f"Candidate {index} is missing id."))
            continue
        if candidate_id in by_id:
            issues.append(issue("major", "candidate_id_duplicate", f"Candidate id {candidate_id} is duplicated."))
            continue
        by_id[candidate_id] = candidate

        silhouette = normalize(candidate.get("silhouette"))
        if not silhouette:
            issues.append(issue("major", "silhouette_missing", f"Candidate {candidate_id} is missing silhouette.", candidate=candidate_id))
        else:
            silhouettes.append(silhouette)

        rationale = str(candidate.get("rationale") or "").strip()
        if len(rationale) < 20:
            issues.append(issue("minor", "rationale_weak", f"Candidate {candidate_id} needs a concrete design rationale.", candidate=candidate_id))

        focal_share = candidate.get("focal_share")
        if isinstance(focal_share, bool) or not isinstance(focal_share, (int, float)):
            issues.append(issue("major", "focal_share_missing", f"Candidate {candidate_id} needs focal_share.", candidate=candidate_id))
        elif not 0.35 <= float(focal_share) <= 0.78:
            issues.append(issue("major", "focal_share_weak", f"Candidate {candidate_id} focal_share should normally be 0.35–0.78.", candidate=candidate_id))

        title_pt = candidate.get("title_pt")
        body_pt = candidate.get("body_pt")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (title_pt, body_pt)):
            if float(body_pt) <= 0 or float(title_pt) / float(body_pt) < (1.45 if high_score else 1.3):
                issues.append(issue("major", "candidate_type_hierarchy_weak", f"Candidate {candidate_id} title/body hierarchy is too weak.", candidate=candidate_id))
        elif high_score:
            issues.append(issue("major", "candidate_type_scale_missing", f"Candidate {candidate_id} needs title_pt and body_pt.", candidate=candidate_id))

        refs = candidate.get("reference_ids") or []
        if not isinstance(refs, list):
            issues.append(issue("major", "reference_ids_invalid", f"Candidate {candidate_id} reference_ids must be an array.", candidate=candidate_id))
            refs = []
        if high_score and not refs:
            issues.append(issue("major", "reference_ids_missing", f"Candidate {candidate_id} must cite at least one visual reference recipe.", candidate=candidate_id))
        if known_reference_ids is not None:
            unknown = [str(ref) for ref in refs if normalize(ref) not in known_reference_ids]
            if unknown:
                issues.append(issue("major", "unknown_visual_reference", f"Candidate {candidate_id} uses unknown visual references: {unknown}.", candidate=candidate_id))

        zones = candidate.get("zones")
        if not isinstance(zones, dict) or not zones:
            issues.append(issue("major", "zones_missing", f"Candidate {candidate_id} must define normalized zones.", candidate=candidate_id))
        else:
            for name, zone in zones.items():
                if not valid_zone(zone):
                    issues.append(issue("major", "zone_out_of_bounds", f"Candidate {candidate_id} zone {name} must be a normalized [x,y,w,h] inside 0..1.", candidate=candidate_id, zone=name))

    distinct_silhouettes = {item for item in silhouettes if item}
    if high_leverage and len(distinct_silhouettes) < 2:
        issues.append(issue("major", "candidate_silhouettes_not_distinct", "High-leverage candidates must explore at least two genuinely different silhouettes."))

    selected_id = str(data.get("selected_id") or "").strip()
    if not selected_id:
        issues.append(issue("major", "selected_id_missing", "A selected_id is required before final slide authoring."))
        selected = None
    elif selected_id not in by_id:
        issues.append(issue("critical", "selected_id_unknown", f"selected_id {selected_id} does not match a candidate."))
        selected = None
    else:
        selected = by_id[selected_id]

    selection_reason = str(data.get("selection_reason") or "").strip()
    if selected_id and len(selection_reason) < 20:
        issues.append(issue("major", "selection_reason_weak", "Selection reason must explain why this composition best serves the slide claim/art direction."))

    if selected is not None:
        selected_silhouette = normalize(selected.get("silhouette"))
        if high_leverage and selected_silhouette in WEAK_STRUCTURES:
            justification = str(selected.get("exception_justification") or "").strip()
            if len(justification) < 40:
                issues.append(
                    issue(
                        "major",
                        "weak_high_leverage_structure",
                        f"High-leverage slide selected weak structure {selected_silhouette} without a strong exception justification.",
                        candidate=selected_id,
                    )
                )

    blockers = [item for item in issues if item["severity"] in BLOCKING]
    return {
        "ok": not blockers,
        "generation_core_version": "0.8",
        "high_leverage": high_leverage,
        "candidate_count": len(candidates),
        "distinct_silhouettes": sorted(distinct_silhouettes),
        "selected_id": selected_id or None,
        "blocker_count": len(blockers),
        "issue_count": len(issues),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_file", type=Path)
    parser.add_argument("--reference-library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--quality", choices=["high-score", "standard"], default="high-score")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report = validate_candidates(
        load_structured(args.candidate_file),
        known_reference_ids=load_reference_ids(args.reference_library),
        high_score=args.quality == "high-score",
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
