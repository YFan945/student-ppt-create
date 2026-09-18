#!/usr/bin/env python3
"""Independent calibration review status — the single owner of the green check.

Moved out of ppt_pipeline.py (v0.15 Batch 4.2) so that both the pipeline dispatch
and the style-contract generator can ask "is the calibration independently
reviewed and green?" without a circular import. The blocking-severity vocabulary
shared by the QA DAG and this review lives here too.

Calibration exists to catch a systemic visual choice before it is copied onto
every page. It cannot do that while the reviewer is the session that made the
choice: 2026-09-18 live, the main session reviewed its own calibration PNGs,
accepted them, and the independent critic then rejected the pattern applied to
all 13 built pages — 76.4M tokens (58.8% of that session) for a rework that a
3-page review would have caught for 1.4M.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CALIBRATION_DIR_NAME = "calibration"
CALIBRATION_MANIFEST_NAME = "calibration-manifest.json"
CALIBRATION_REVIEW_NAME = "calibration-visual-review.json"
STYLE_SUMMARY_NAME = "style-summary.json"

# The treatment keys the calibration builder records about what it established.
STYLE_SUMMARY_KEYS = (
    "title_treatment",
    "body_treatment",
    "surface_language",
    "image_language",
    "chart_language",
    "rhythm",
)

QA_BLOCKING_SEVERITIES = ("critical", "major")


def normalise_severity(report: dict[str, Any], issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity") or "").lower()
    if severity == "advisory":
        # Batch 4.4: aesthetic score findings ride in the quality gate's issues list
        # as non-blocking; they aggregate under minor in pipeline-qa.json.
        return "minor"
    if severity in {"critical", "major", "blocker"}:
        return "critical" if severity == "critical" else "major"
    if severity == "minor":
        return "minor"
    return "major" if not report.get("ok", True) else "minor"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def style_summary_valid(work_dir: Path) -> tuple[bool, str]:
    """Whether calibration/style-summary.json exists with a usable shape.

    The calibration builder records what it actually established (one line per
    treatment key, plus do_not_repeat). Without those bytes, later builders can
    only inherit the Art Direction — the calibration's own treatment would not be
    mechanically passed on — so a green review REQUIRES a valid summary.
    """
    path = work_dir / CALIBRATION_DIR_NAME / STYLE_SUMMARY_NAME
    if not path.is_file():
        return False, (
            f"calibration/{STYLE_SUMMARY_NAME} is missing: the calibration builder must record "
            "what it established (established with one line per "
            f"{', '.join(STYLE_SUMMARY_KEYS)}, plus do_not_repeat) so the visual system is "
            "mechanically passed to later builders"
        )
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"calibration/{STYLE_SUMMARY_NAME} is unreadable: {exc}"
    if not isinstance(summary, dict):
        return False, f"calibration/{STYLE_SUMMARY_NAME} must be an object"
    established = summary.get("established")
    has_treatment = (
        isinstance(established, dict)
        and any(str(established.get(key) or "").strip() for key in STYLE_SUMMARY_KEYS)
    )
    do_not_repeat = summary.get("do_not_repeat")
    has_avoid = isinstance(do_not_repeat, list) and any(str(item).strip() for item in do_not_repeat)
    if not (has_treatment or has_avoid):
        return False, (
            f"calibration/{STYLE_SUMMARY_NAME} carries no usable content: expected "
            "established.<key> lines or a do_not_repeat list"
        )
    return True, ""


def calibration_review(work_dir: Path) -> dict[str, Any]:
    """Status of the INDEPENDENT calibration review (SKILL.md step 8).

    Only applies once calibration evidence exists, so a work-dir that never ran
    calibration is not retroactively blocked by this contract.
    """
    target = work_dir / CALIBRATION_DIR_NAME
    manifest_path = target / CALIBRATION_MANIFEST_NAME
    review_path = target / CALIBRATION_REVIEW_NAME
    status: dict[str, Any] = {
        "required": False,
        "present": False,
        "ok": False,
        "blockers": None,
        "slides": [],
        "path": str(review_path),
        "reason": "",
    }
    if not manifest_path.is_file():
        return status
    try:
        calibration = _read_object(manifest_path)
    except Exception as exc:  # pragma: no cover - corrupt evidence
        status["required"] = True
        status["reason"] = f"calibration manifest is unreadable: {exc}"
        return status

    status["required"] = True
    slides = [int(value) for value in calibration.get("slides") or [] if isinstance(value, int)]
    status["slides"] = slides
    expected_pptx = str((calibration.get("pptx") or {}).get("sha256") or "")

    if not review_path.is_file():
        status["reason"] = (
            "no independent calibration review on disk; the main session's own read of the "
            "calibration PNGs is not a substitute (it is the session that chose the treatment)"
        )
        return status
    status["present"] = True
    try:
        review = _read_object(review_path)
    except Exception as exc:
        status["reason"] = f"calibration review is unreadable: {exc}"
        return status

    if not expected_pptx or review.get("pptx_sha256") != expected_pptx:
        status["reason"] = "calibration review is not bound to the current calibration render"
        return status

    reviewed = {
        int(item["slide"])
        for item in review.get("slides") or []
        if isinstance(item, dict) and isinstance(item.get("slide"), int)
    }
    if reviewed != set(slides):
        status["reason"] = (
            f"calibration review covers slides {sorted(reviewed)} but the calibrated pages are {sorted(slides)}"
        )
        return status

    blocking: list[str] = []
    for item in review.get("slides") or []:
        if not isinstance(item, dict):
            continue
        slide_no = int(item.get("slide") or 0)
        if str(item.get("ai_template_feel") or "none").strip().lower() == "major":
            blocking.append(f"slide {slide_no}: ai_template_feel=major")
        for finding in item.get("issues") or []:
            if not isinstance(finding, dict):
                continue
            if normalise_severity(review, finding) in QA_BLOCKING_SEVERITIES:
                blocking.append(f"slide {slide_no}: {finding.get('code') or 'visual_finding'}")
    status["blockers"] = len(blocking)
    status["ok"] = not blocking
    if blocking:
        status["reason"] = "calibration review still reports systemic findings: " + "; ".join(blocking[:6])
        return status
    # Hard invariant (Batch 1-4 closure): green ALSO requires the calibration
    # builder's style summary, so the established visual system is guaranteed to
    # reach later builders via the style contract instead of only the Art Direction.
    ok, reason = style_summary_valid(work_dir)
    if not ok:
        status["blockers"] = len(blocking) + 1
        status["ok"] = False
        status["reason"] = reason
    return status
