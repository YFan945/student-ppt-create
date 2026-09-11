#!/usr/bin/env python3
"""v0.7.1 quality gate for rendered presentation artifacts.

This gate complements deterministic package/content checks with four quality
contracts that were previously too easy to treat as subjective prose:

1. a structured per-slide visual critic report bound to the current PPTX;
2. deck-level visual rhythm / repetition checks;
3. evidence-ledger closure into the final reference area;
4. speaker-note timing estimation against the confirmed duration.

The visual observations are authored after looking at real rendered pages; this
script makes those observations auditable and prevents unresolved Major/Critical
findings from being silently marked as complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pptx_actual_content_check as actual_check  # noqa: E402
import slide_spec_guard as spec_guard  # noqa: E402

SCORE_FIELDS = ("hierarchy", "focal_point", "composition", "visual_interest", "whitespace")
REPETITIVE_STRUCTURES = {
    "equal-cards",
    "card-grid",
    "three-column",
    "numbered-list",
    "plain-list",
}
BLOCKING_SEVERITIES = {"critical", "major"}


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


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML Slide Spec files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit("Slide Spec root must be an object.")
    return value


def issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def normalized_severity(value: Any) -> str:
    return str(value or "").strip().lower()


def has_resolution_evidence(finding: dict[str, Any], pptx_digest: str) -> bool:
    """A claimed fix only counts when bound to the current artifact.

    ``resolved: true`` on its own is self-attestation by the generating model:
    the same actor that created the finding also declares it gone, so the
    "human review" layer degenerates into a no-op. Require
    ``resolved_evidence`` with the pre-fix digest (audit trail) and an
    ``after_sha256`` equal to the PPTX being gated — the claim is then either
    backed by real artifacts or trivially falsifiable.
    """
    if finding.get("resolved") is not True:
        return False
    evidence = finding.get("resolved_evidence")
    if not isinstance(evidence, dict):
        return False
    before = str(evidence.get("before_sha256") or "")
    after = str(evidence.get("after_sha256") or "")
    return bool(before) and after == pptx_digest


def validate_visual_report(
    report_path: Path,
    pptx: Path,
    slide_count: int,
    *,
    high_score: bool,
) -> dict[str, Any]:
    report = load_json(report_path)
    issues: list[dict[str, Any]] = []
    pptx_digest = sha256_file(pptx)
    if report.get("pptx_sha256") != pptx_digest:
        issues.append(issue("critical", "visual_report_stale", "Visual review is not bound to the current PPTX."))

    raw_slides = report.get("slides")
    if not isinstance(raw_slides, list):
        raw_slides = []
        issues.append(issue("critical", "visual_slides_missing", "Visual review must contain a slides array."))

    by_slide: dict[int, dict[str, Any]] = {}
    score_values: list[float] = []
    for item in raw_slides:
        if not isinstance(item, dict) or not isinstance(item.get("slide"), int):
            issues.append(issue("major", "visual_slide_invalid", "Each visual review entry needs an integer slide number."))
            continue
        slide_no = int(item["slide"])
        if slide_no in by_slide:
            issues.append(issue("major", "visual_slide_duplicate", f"Slide {slide_no} appears more than once in visual review."))
            continue
        by_slide[slide_no] = item
        structure = str(item.get("visual_structure") or "").strip().lower()
        if not structure:
            issues.append(issue("major", "visual_structure_missing", f"Slide {slide_no} is missing visual_structure.", slide=slide_no))

        scores = item.get("scores")
        if not isinstance(scores, dict):
            scores = {}
        for field in SCORE_FIELDS:
            raw = scores.get(field)
            if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not 1 <= float(raw) <= 10:
                issues.append(issue("major", "visual_score_invalid", f"Slide {slide_no} needs a 1-10 score for {field}.", slide=slide_no, field=field))
                continue
            score = float(raw)
            score_values.append(score)
            minimum = 6.0 if high_score else 5.0
            if score < minimum:
                issues.append(issue("major", "visual_score_low", f"Slide {slide_no} {field} score {score:g} is below the quality floor {minimum:g}.", slide=slide_no, field=field, score=score))

        ai_feel = str(item.get("ai_template_feel") or "none").strip().lower()
        if ai_feel == "major":
            issues.append(issue("major", "ai_template_feel", f"Slide {slide_no} still has obvious AI-template/card-grid feel.", slide=slide_no))

        for finding in item.get("issues") or []:
            if not isinstance(finding, dict):
                continue
            sev = normalized_severity(finding.get("severity"))
            if sev not in BLOCKING_SEVERITIES:
                continue
            if has_resolution_evidence(finding, pptx_digest):
                continue
            if finding.get("resolved") is True:
                issues.append(
                    issue(
                        "major",
                        "resolved_without_evidence",
                        f"Slide {slide_no} finding '{finding.get('code')}' claims resolved without sha256-bound evidence.",
                        slide=slide_no,
                    )
                )
            issues.append(issue(sev, str(finding.get("code") or "visual_finding"), str(finding.get("message") or "Unresolved visual finding."), slide=slide_no))

    expected = set(range(1, slide_count + 1))
    missing = sorted(expected - set(by_slide))
    extras = sorted(set(by_slide) - expected)
    if missing:
        issues.append(issue("critical", "visual_pages_missing", f"Visual review does not cover slides: {missing}."))
    if extras:
        issues.append(issue("major", "visual_pages_extra", f"Visual review contains unknown slides: {extras}."))

    # Deck-level visual rhythm. Two consecutive equal-card/list pages are already
    # a Major because this was the dominant failure mode in the first real v0.7 run.
    ordered_structures = [
        str(by_slide[i].get("visual_structure") or "").strip().lower()
        for i in range(1, slide_count + 1)
        if i in by_slide
    ]
    for idx in range(1, len(ordered_structures)):
        current = ordered_structures[idx]
        previous = ordered_structures[idx - 1]
        if current and current == previous and current in REPETITIVE_STRUCTURES:
            issues.append(issue("major", "repetitive_structure_pair", f"Slides {idx} and {idx + 1} repeat the same weak structure: {current}.", slides=[idx, idx + 1], visual_structure=current))

    run_start = 0
    while run_start < len(ordered_structures):
        run_end = run_start + 1
        while run_end < len(ordered_structures) and ordered_structures[run_end] == ordered_structures[run_start]:
            run_end += 1
        if ordered_structures[run_start] and run_end - run_start >= 3:
            issues.append(issue("major", "repetitive_structure_run", f"Slides {run_start + 1}-{run_end} repeat visual structure {ordered_structures[run_start]} three or more times.", slides=list(range(run_start + 1, run_end + 1))))
        run_start = run_end

    distinct = {value for value in ordered_structures if value}
    min_distinct = 3 if slide_count >= 6 else 2 if slide_count >= 3 else 1
    if len(distinct) < min_distinct:
        issues.append(issue("major", "low_visual_variety", f"Deck uses only {len(distinct)} distinct visual structures; expected at least {min_distinct} for this length."))

    deck = report.get("deck")
    if isinstance(deck, dict):
        for finding in deck.get("issues") or []:
            if not isinstance(finding, dict):
                continue
            sev = normalized_severity(finding.get("severity"))
            if sev not in BLOCKING_SEVERITIES:
                continue
            if has_resolution_evidence(finding, pptx_digest):
                continue
            if finding.get("resolved") is True:
                issues.append(
                    issue(
                        "major",
                        "resolved_without_evidence",
                        f"Deck finding '{finding.get('code')}' claims resolved without sha256-bound evidence.",
                    )
                )
            issues.append(issue(sev, str(finding.get("code") or "deck_visual_finding"), str(finding.get("message") or "Unresolved deck-level visual finding.")))

    average_score = sum(score_values) / len(score_values) if score_values else 0.0
    target_average = 7.0 if high_score else 6.0
    if score_values and average_score < target_average:
        issues.append(issue("major", "visual_average_low", f"Average visual score {average_score:.2f} is below {target_average:.1f}."))

    blockers = [item for item in issues if item["severity"] in BLOCKING_SEVERITIES]
    return {
        "ok": not blockers,
        "report_sha256": sha256_file(report_path),
        "average_score": round(average_score, 3),
        "distinct_visual_structures": sorted(distinct),
        "issues": issues,
        "blocker_count": len(blockers),
    }


def _clean(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def evidence_markers(entry: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    locator = str(entry.get("locator") or "")
    candidates.extend(re.findall(r"(?:arxiv:)?\d{4}\.\d{4,5}|10\.\d{4,9}/[^\s,;]+", locator, flags=re.I))
    author = str(entry.get("author") or "").strip()
    if author:
        pieces = [p for p in re.split(r"[\s,;]+", author) if len(p) >= 3]
        if pieces:
            candidates.append(pieces[0])
    date = str(entry.get("date") or "")
    year = re.search(r"(?:19|20)\d{2}", date)
    if year:
        candidates.append(year.group(0))
    title = str(entry.get("title") or "").strip()
    title_words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,}", title) if w.lower() not in {"with", "from", "using", "large", "language", "model", "models", "survey"}]
    candidates.extend(title_words[:3])
    cjk = re.findall(r"[\u3400-\u9fff]{4,}", title)
    candidates.extend(chunk[:8] for chunk in cjk[:2])
    return list(dict.fromkeys(_clean(item) for item in candidates if item))


def evidence_match(text: str, entry: dict[str, Any]) -> bool:
    normalized = _clean(text)
    markers = evidence_markers(entry)
    if not markers:
        return False
    strong = [m for m in markers if re.fullmatch(r"(?:arxiv:)?\d{4}\.\d{4,5}|10\..+", m)]
    if any(marker in normalized for marker in strong):
        return True
    matched = sum(marker in normalized for marker in markers)
    return matched >= min(2, len(markers))


def check_evidence(spec: dict[str, Any], actual_text: list[str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    slides = [item for item in spec.get("slides") or [] if isinstance(item, dict)]
    ledger_raw = [item for item in spec.get("evidence_ledger") or [] if isinstance(item, dict)]
    ledger = {str(item.get("id")): item for item in ledger_raw if item.get("id")}
    usage: dict[str, set[int]] = {}
    for slide in slides:
        slide_no = int(slide.get("id") or 0)
        for ref in slide.get("evidence_refs") or []:
            usage.setdefault(str(ref), set()).add(slide_no)

    for ref, slide_numbers in usage.items():
        if ref not in ledger:
            issues.append(issue("critical", "unknown_evidence_ref", f"Evidence ref {ref} is used but missing from evidence_ledger.", evidence_ref=ref))
            continue
        declared = {int(value) for value in ledger[ref].get("used_on_slides") or []}
        if declared != slide_numbers:
            issues.append(issue("major", "evidence_usage_mismatch", f"Evidence {ref} used_on_slides {sorted(declared)} does not match actual Slide Spec refs {sorted(slide_numbers)}.", evidence_ref=ref))

    citation_style = str((spec.get("meta") or {}).get("citation_style") or "classroom")
    reference_indices = {
        int(slide.get("id") or 0)
        for slide in slides
        if str(slide.get("kind") or "").lower() == "references"
        or re.search(r"参考|references|bibliography|works cited", str(slide.get("title") or ""), flags=re.I)
    }
    # Classroom decks often combine conclusion + references on the final page.
    # Do not include the penultimate slide automatically: a short source line on
    # a content slide is not a substitute for the final bibliography.
    if actual_text:
        reference_indices.add(len(actual_text))
    reference_text = "\n".join(actual_text[index - 1] for index in sorted(reference_indices) if 1 <= index <= len(actual_text))

    if citation_style != "none":
        for ref in sorted(usage):
            entry = ledger.get(ref)
            if entry and not evidence_match(reference_text, entry):
                issues.append(issue("major", "missing_final_reference", f"Evidence {ref} is used in the deck but cannot be matched in the final reference area.", evidence_ref=ref, title=entry.get("title")))

    unused = sorted(set(ledger) - set(usage))
    for ref in unused:
        issues.append(issue("minor", "unused_evidence", f"Evidence {ref} is listed but not referenced by any slide.", evidence_ref=ref))

    blockers = [item for item in issues if item["severity"] in BLOCKING_SEVERITIES]
    return {
        "ok": not blockers,
        "citation_style": citation_style,
        "used_evidence_count": len(usage),
        "issues": issues,
        "blocker_count": len(blockers),
    }


def estimate_note_seconds(text: str) -> float:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text or ""))
    latin_text = re.sub(r"[\u3400-\u9fff]", " ", text or "")
    words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9+._/-]*", latin_text))
    # Conservative classroom pace with room for slide changes and emphasis.
    return (cjk / 240.0) * 60.0 + (words / 130.0) * 60.0


def check_timing(spec: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    slides = [item for item in spec.get("slides") or [] if isinstance(item, dict)]
    meta = spec.get("meta") or {}
    include_notes = meta.get("include_speaker_notes") is True
    estimated_total = 0.0
    planned_total = 0.0
    slide_reports: list[dict[str, Any]] = []

    for slide in slides:
        slide_no = int(slide.get("id") or 0)
        planned = float(slide.get("timing_sec") or 0)
        planned_total += planned
        notes = str(slide.get("speaker_notes") or "").strip()
        estimated = estimate_note_seconds(notes) if notes else 0.0
        estimated_total += estimated
        ratio = estimated / planned if planned > 0 else math.inf if estimated > 0 else 0.0
        if include_notes and not notes:
            issues.append(issue("major", "speaker_notes_missing", f"Slide {slide_no} requires speaker notes but none are present.", slide=slide_no))
        elif planned > 0 and ratio > 1.35:
            issues.append(issue("major", "slide_timing_overrun", f"Slide {slide_no} notes are estimated at {estimated:.0f}s versus {planned:.0f}s planned.", slide=slide_no, estimated_sec=round(estimated, 1), planned_sec=planned))
        elif planned > 0 and ratio > 1.15:
            issues.append(issue("minor", "slide_timing_tight", f"Slide {slide_no} notes are estimated at {estimated:.0f}s versus {planned:.0f}s planned.", slide=slide_no, estimated_sec=round(estimated, 1), planned_sec=planned))
        slide_reports.append({"slide": slide_no, "planned_sec": planned, "estimated_sec": round(estimated, 1), "ratio": round(ratio, 3) if math.isfinite(ratio) else None})

    duration_min = meta.get("duration_min")
    confirmed_total = float(duration_min) * 60.0 if isinstance(duration_min, (int, float)) and not isinstance(duration_min, bool) else planned_total
    if confirmed_total > 0:
        overall_ratio = estimated_total / confirmed_total
        if overall_ratio > 1.15:
            issues.append(issue("major", "deck_timing_overrun", f"Speaker notes are estimated at {estimated_total / 60.0:.2f} min for a {confirmed_total / 60.0:.2f} min presentation."))
        elif overall_ratio > 1.05:
            issues.append(issue("minor", "deck_timing_tight", f"Speaker notes are estimated at {estimated_total / 60.0:.2f} min for a {confirmed_total / 60.0:.2f} min presentation."))
        elif include_notes and overall_ratio < 0.55:
            issues.append(issue("minor", "deck_timing_sparse", f"Speaker notes cover only about {estimated_total / 60.0:.2f} min of a {confirmed_total / 60.0:.2f} min presentation."))

    blockers = [item for item in issues if item["severity"] in BLOCKING_SEVERITIES]
    return {
        "ok": not blockers,
        "planned_total_sec": round(planned_total, 1),
        "confirmed_total_sec": round(confirmed_total, 1),
        "estimated_total_sec": round(estimated_total, 1),
        "estimated_total_min": round(estimated_total / 60.0, 3),
        "slides": slide_reports,
        "issues": issues,
        "blocker_count": len(blockers),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student PPT v0.7.1 quality gate")
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--spec-lock", type=Path, required=True)
    parser.add_argument("--visual-report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.pptx.is_file():
        raise SystemExit(f"PPTX does not exist: {args.pptx}")
    if not args.slide_spec.is_file():
        raise SystemExit(f"Slide Spec does not exist: {args.slide_spec}")

    spec_lock = spec_guard.check_lock(args.spec_lock, args.slide_spec)
    spec = load_structured(args.slide_spec)
    actual_text = actual_check.extract_pptx_text(args.pptx)
    meta = spec.get("meta") or {}
    high_score = str(meta.get("quality_level") or "").lower() == "high-score"

    visual = validate_visual_report(args.visual_report, args.pptx, len(actual_text), high_score=high_score)
    evidence = check_evidence(spec, actual_text)
    timing = check_timing(spec)
    lock_issues = [] if spec_lock["ok"] else [issue("critical", "slide_spec_lock_invalid", message) for message in spec_lock["errors"]]
    all_issues = lock_issues + visual["issues"] + evidence["issues"] + timing["issues"]
    blockers = [item for item in all_issues if item["severity"] in BLOCKING_SEVERITIES]

    result = {
        "ok": not blockers,
        "generation_core_version": "0.7.1",
        "pptx_sha256": sha256_file(args.pptx),
        "slide_spec_sha256": sha256_file(args.slide_spec),
        "spec_lock_sha256": sha256_file(args.spec_lock),
        "visual_report_sha256": sha256_file(args.visual_report),
        "slide_count": len(actual_text),
        "blocker_count": len(blockers),
        "issue_count": len(all_issues),
        "visual": visual,
        "evidence": evidence,
        "timing": timing,
        "issues": all_issues,
    }

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(payload)
    if args.strict and not result["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
