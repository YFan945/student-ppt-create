#!/usr/bin/env python3
"""Deterministic static-risk gate: box-level overflow / out-of-bounds / overlap.

The precise element-level findings (shape, bounds, fill ratio) already live in
shared/pptx_static_core.inspect_pptx, but until this gate only the visual critic
caught them — pricing every text overflow as one critic round plus one repair
round. Running the same detector inside build's deterministic pre-QA surfaces
them before any render or critic cost, with the element coordinates the repair
builder needs instead of prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_static_core import inspect_pptx, summarize_static_risks  # noqa: E402

# The classification summary decides what is blocker-like; the gate maps that to
# QA severities so `collect()` can hand it to the repair packet unchanged.
BLOCKER_SEVERITY = "major"
ADVISORY_SEVERITY = "minor"


def check(pptx: Path) -> dict[str, Any]:
    result = inspect_pptx(pptx)
    summary = summarize_static_risks(result)
    blocker_like = {id(item) for item in summary.get("blocker_like") or []}
    issues = []
    for item in result.get("findings") or []:
        if not isinstance(item, dict):
            continue
        risks = [str(value) for value in item.get("risk") or []]
        if not risks:
            continue
        severity = BLOCKER_SEVERITY if id(item) in blocker_like else ADVISORY_SEVERITY
        issues.append({
            "slide": item.get("slide"),
            "severity": severity,
            "code": risks[0],
            "message": (
                f"{', '.join(risks)} on slide {item.get('slide')} "
                f"({str(item.get('shape') or '')[:60]}): "
                f"{str(item.get('text_preview') or '')[:80]}"
            ),
            "detail": {
                "risks": risks,
                "shape": item.get("shape"),
                "text_preview": item.get("text_preview"),
                "bounds": item.get("bounds"),
                "overflow_estimate": item.get("overflow_estimate"),
                "min_font_pt": item.get("min_font_pt"),
                "char_count": item.get("char_count"),
            },
        })
    return {
        "ok": not any(item["severity"] == BLOCKER_SEVERITY for item in issues),
        "pptx": str(pptx.resolve()),
        "issue_count": len(issues),
        "risk_counts": summary.get("risk_counter") or {},
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.pptx.is_file():
        raise SystemExit(f"PPTX does not exist: {args.pptx}")
    report = check(args.pptx)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
