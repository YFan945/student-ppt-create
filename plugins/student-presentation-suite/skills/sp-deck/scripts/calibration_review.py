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

import hashlib
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
CALIBRATION_RECEIPT_NAME = "calibration-critic-execution.json"
PALETTE_REPORT_NAME = "palette-report.json"

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


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _binding(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def calibration_evidence_is_current(
    calibration: dict[str, Any],
) -> tuple[bool, str]:
    """Revalidate every byte used to produce the accepted calibration.

    v0.15.6 compared the review with the manifest's recorded PPTX hash but did
    not compare the manifest bindings with disk. A page, preview, palette
    report, spec or Art Direction could therefore change while the old green
    review remained accepted.
    """
    bindings: list[tuple[str, dict[str, Any]]] = []
    strict = str(calibration.get("version") or "1.0") != "1.0"

    def add(label: str, item: dict[str, Any]) -> None:
        # v1.0 test/legacy manifests sometimes carried only the review-facing
        # digest and no path. Real v0.15.6 manifests already contain paths for
        # pages/PPTX/renders/palette, so those are still revalidated. v1.1 makes
        # every binding mandatory, including spec and Art Direction.
        if strict or item.get("path"):
            bindings.append((label, item))

    for key, item in (calibration.get("inputs") or {}).items():
        if isinstance(item, dict):
            add(f"input {key}", item)
    for item in calibration.get("pages") or []:
        if isinstance(item, dict):
            add(f"page {item.get('slide')}", item)
    if isinstance(calibration.get("pptx"), dict):
        add("calibration PPTX", calibration["pptx"])
    if isinstance(calibration.get("palette"), dict):
        add("palette report", calibration["palette"])
    for item in calibration.get("render") or []:
        if isinstance(item, dict):
            add(f"render {item.get('slide')}", item)

    for label, item in bindings:
        path = Path(str(item.get("path") or ""))
        expected = str(item.get("sha256") or "")
        if not path.is_file() or not expected:
            return False, f"{label} binding is missing; rerun calibration_preview.py"
        try:
            current = _sha256(path)
        except OSError:
            return False, f"{label} cannot be read; rerun calibration_preview.py"
        if current != expected:
            return False, f"{label} changed after calibration preview; rerun calibration_preview.py"
    return True, ""


def _receipt_policy(work_dir: Path) -> str:
    manifest_path = work_dir / "build-manifest.json"
    try:
        manifest = _read_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "require"
    if manifest.get("receipt_policy") == "allow-missing":
        return "allow-missing"
    if (manifest.get("research") or {}).get("receipt_policy") == "allow-missing":
        return "allow-missing"
    return "require"


def calibration_receipt_valid(
    work_dir: Path,
    calibration: dict[str, Any],
    review_path: Path,
) -> tuple[bool, bool, str]:
    """Validate the hook-owned calibration critic receipt.

    Returns ``(ok, degraded, reason)``. Only a genuinely absent receipt may
    degrade under the work-id's ``allow-missing`` policy; a present but corrupt
    or stale receipt always fails closed, matching production QA semantics.
    """
    receipt_path = work_dir / CALIBRATION_DIR_NAME / CALIBRATION_RECEIPT_NAME
    if not receipt_path.is_file():
        if _receipt_policy(work_dir) == "allow-missing":
            return True, True, "calibration critic receipt is missing and explicitly allowed"
        return False, False, (
            "missing successful isolated calibration critic receipt; runtime_evidence.py "
            "must write calibration/calibration-critic-execution.json at SubagentStop"
        )
    try:
        receipt = _read_object(receipt_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, False, f"calibration critic receipt is unreadable: {exc}"
    if (
        receipt.get("agent") != "student-presentation-suite:visual-critic"
        or not receipt.get("agent_id")
        or receipt.get("spawn_verified") is not True
        or receipt.get("work_id") != work_dir.name
    ):
        return False, False, "calibration critic receipt identity is invalid"
    if receipt.get("artifact") != _binding(review_path):
        return False, False, "calibration review changed after isolated critic execution"
    reads = receipt.get("reads") or {}
    for item in calibration.get("render") or []:
        if not isinstance(item, dict):
            return False, False, "calibration manifest contains an invalid render binding"
        path = str(Path(str(item.get("path") or "")).resolve())
        if not item.get("sha256") or reads.get(path) != item.get("sha256"):
            return False, False, "independent calibration critic did not read every current render image"
    return True, False, ""


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
        "receipt": str(target / CALIBRATION_RECEIPT_NAME),
        "receipt_verified": False,
        "receipt_degraded": False,
        "action": "critic",
        "repair_slides": [],
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

    current, current_reason = calibration_evidence_is_current(calibration)
    if not current:
        status["action"] = "preview"
        status["repair_slides"] = slides
        status["blockers"] = 1
        status["reason"] = current_reason
        return status

    palette_path = target / PALETTE_REPORT_NAME
    palette = None
    if palette_path.is_file() or calibration.get("palette"):
        try:
            palette = _read_object(palette_path)
        except Exception as exc:
            status["action"] = "builder"
            status["repair_slides"] = slides
            status["blockers"] = 1
            status["reason"] = f"calibration palette report is unreadable: {exc}"
            return status
    if palette is not None and palette.get("ok") is not True:
        affected = sorted({
            int(item["slide"])
            for item in palette.get("issues") or []
            if isinstance(item, dict) and isinstance(item.get("slide"), int)
        })
        status["action"] = "builder"
        status["repair_slides"] = affected or slides
        status["blockers"] = len(palette.get("issues") or []) or 1
        status["reason"] = (
            "calibration PPTX uses colors outside the approved token palettes; "
            f"repair from {palette_path}"
        )
        return status

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

    receipt_ok, receipt_degraded, receipt_reason = calibration_receipt_valid(
        work_dir, calibration, review_path
    )
    if not receipt_ok:
        status["reason"] = receipt_reason
        return status
    status["receipt_verified"] = not receipt_degraded
    status["receipt_degraded"] = receipt_degraded

    blocking: list[str] = []
    repair_slides: set[int] = set()
    for item in review.get("slides") or []:
        if not isinstance(item, dict):
            continue
        slide_no = int(item.get("slide") or 0)
        if str(item.get("ai_template_feel") or "none").strip().lower() == "major":
            blocking.append(f"slide {slide_no}: ai_template_feel=major")
            repair_slides.add(slide_no)
        for finding in item.get("issues") or []:
            if not isinstance(finding, dict):
                continue
            if normalise_severity(review, finding) in QA_BLOCKING_SEVERITIES:
                blocking.append(f"slide {slide_no}: {finding.get('code') or 'visual_finding'}")
                repair_slides.add(slide_no)
    status["blockers"] = len(blocking)
    status["ok"] = not blocking
    if blocking:
        status["action"] = "builder"
        status["repair_slides"] = sorted(repair_slides)
        status["reason"] = "calibration review still reports systemic findings: " + "; ".join(blocking[:6])
        return status
    # Hard invariant (Batch 1-4 closure): green ALSO requires the calibration
    # builder's style summary, so the established visual system is guaranteed to
    # reach later builders via the style contract instead of only the Art Direction.
    ok, reason = style_summary_valid(work_dir)
    if not ok:
        status["action"] = "builder"
        status["repair_slides"] = slides
        status["blockers"] = len(blocking) + 1
        status["ok"] = False
        status["reason"] = reason
    else:
        status["action"] = None
    return status
