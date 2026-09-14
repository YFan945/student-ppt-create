#!/usr/bin/env python3
"""Aggregate deterministic deck-pipeline cost metrics from build manifests.

This report is intentionally manifest-first: it measures work the pipeline can
control (builds, repairs, renders, QA stage time, blockers, wall time). Pair it
with session_cost.py for model request/context cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = "build-manifest.json"


def default_work_root() -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    root = Path(configured) if configured else Path.cwd()
    return root / "outputs" / ".pptx-work"


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def collect(manifest: dict[str, Any]) -> dict[str, Any]:
    build = manifest.get("build") or {}
    render = manifest.get("render") or {}
    qa = manifest.get("qa") or {}
    history = manifest.get("history") or []
    planned = next((h for h in history if h.get("command") == "plan"), None)
    completed = next((h for h in reversed(history) if h.get("command") == "complete"), None)
    start = parse_time(planned.get("at")) if planned else None
    end = parse_time(completed.get("at")) if completed else None
    minutes = (end - start).total_seconds() / 60 if start and end else None
    stage_cost = qa.get("stage_cost_ms") or {}
    render_events = sum(1 for h in history if h.get("command") == "render")
    qa_events = sum(1 for h in history if h.get("command") == "qa")
    return {
        "work_id": manifest.get("work_id"),
        "manifest_version": manifest.get("manifest_version"),
        "state": manifest.get("state"),
        "builds": int(build.get("build_count") or 0),
        "repairs": int(build.get("repair_count") or 0),
        "render_events": render_events,
        "rendered_pages": int(render.get("page_count") or 0),
        "qa_events": qa_events,
        "qa_stage_ms": int(sum(int(v or 0) for v in stage_cost.values())),
        "blockers": int(qa.get("blockers") or 0),
        "qa_ok": bool(qa.get("ok")),
        "minutes": round(minutes, 1) if minutes is not None else None,
    }


def render_table(rows: list[dict[str, Any]]) -> str:
    header = (
        f"{'work_id':<26} {'state':<9} {'build':>5} {'repair':>6} "
        f"{'render':>6} {'qa':>3} {'qa_s':>7} {'block':>5} {'min':>6}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        minutes = "-" if row["minutes"] is None else row["minutes"]
        lines.append(
            f"{str(row['work_id']):<26} {str(row['state']):<9} {row['builds']:>5} "
            f"{row['repairs']:>6} {row['render_events']:>6} {row['qa_events']:>3} "
            f"{row['qa_stage_ms'] / 1000:>7.2f} {row['blockers']:>5} {minutes:>6}"
        )
    if rows:
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL (' + str(len(rows)) + ' decks)':<26} {'':<9} "
            f"{sum(r['builds'] for r in rows):>5} {sum(r['repairs'] for r in rows):>6} "
            f"{sum(r['render_events'] for r in rows):>6} {sum(r['qa_events'] for r in rows):>3} "
            f"{sum(r['qa_stage_ms'] for r in rows) / 1000:>7.2f} "
            f"{sum(r['blockers'] for r in rows):>5}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, help="directory holding <work-id>/build-manifest.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.work_root or default_work_root()
    manifests = sorted(root.glob(f"*/{MANIFEST_NAME}"))
    if not manifests:
        print(f"benchmark_report: no {MANIFEST_NAME} under {root}", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    for path in manifests:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(collect(value))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render_table(rows), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
