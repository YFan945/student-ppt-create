"""Mechanical repair application — the 0.26.0 autofix layer.

Run-14 economics: a repair round costs a full builder instance (hundreds of K
tokens) even when every finding is a mechanical layout swap. Since pages are
declarative data, those fixes are script-patchable: ``apply_page_fixes.js``
swaps ``layout`` in page modules when a finding carries
``repair_level: "implementation"`` and its ``fix`` names a known layout id.

Policy: only when EVERY pending major/critical finding is mechanical does the
pipeline apply them itself and route to a rebuild + fresh review. One creative
finding anywhere → the builder handles the whole round (the packet stays the
single task input; a half-fixed deck with a builder packet behind it would make
the packet's blocker projection lie).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def pending_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in review.get("slides") or []:
        for issue in entry.get("issues") or []:
            if issue.get("severity") in {"major", "critical"} and not issue.get("resolved"):
                findings.append(issue)
    return findings


def autofix_pending_repair(work_dir: Path) -> dict[str, Any] | None:
    """Apply mechanical review fixes and return the report, or None to fall back.

    None means "builder round as usual": no current review, nothing mechanical,
    or a mix of mechanical and creative findings.
    """
    review_path = work_dir / "visual-review.json"
    if not review_path.is_file():
        return None
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    findings = pending_findings(review)
    if not findings:
        return None
    if any(f.get("repair_level") != "implementation" for f in findings):
        return None
    report = _run_node(work_dir, review_path)
    if not report or not report.get("applied_count"):
        return None
    return report


def _run_node(work_dir: Path, review_path: Path) -> dict[str, Any] | None:
    node = os.environ.get("NODE") or "node"
    # pipeline/autofix.py → parents[3] is the plugin root
    script = HERE.parents[3] / "scripts" / "apply_page_fixes.js"
    try:
        proc = subprocess.run(
            [node, str(script), "--work-dir", str(work_dir), "--review", str(review_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
