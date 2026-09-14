#!/usr/bin/env python3
"""Benchmark report: read build-manifest.json files and print the cost table.

The fixed six-deck benchmark (benchmarks/decks.json) turns "the pipeline feels
faster" into "0.10 -> 1.0 cut builds from N to M": each release run leaves a
build-manifest.json per work dir, and this script aggregates the mechanical
metrics — builds, repair rounds, final blockers, wall time between plan and
complete. Session-level token/context cost lives in session_cost.py; this file
covers the deck-level half so the two together close the loop.

Usage:
    python scripts/benchmark_report.py                    # scan the default work root
    python scripts/benchmark_report.py --work-root DIR --json
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
    qa = manifest.get("qa") or {}
    history = manifest.get("history") or []
    planned = next((h for h in history if h.get("command") == "plan"), None)
    completed = next((h for h in history if h.get("command") == "complete"), None)
    start = parse_time(planned.get("at")) if planned else None
    end = parse_time(completed.get("at")) if completed else None
    minutes = (end - start).total_seconds() / 60 if start and end else None
    return {
        "work_id": manifest.get("work_id"),
        "state": manifest.get("state"),
        "builds": int(build.get("build_count") or 0),
        "repairs": int(build.get("repair_count") or 0),
        "blockers": int(qa.get("blockers") or 0),
        "qa_ok": bool(qa.get("ok")),
        "minutes": round(minutes, 1) if minutes is not None else None,
    }


def render(rows: list[dict[str, Any]]) -> str:
    header = f"{'work_id':<28} {'state':<10} {'builds':>6} {'repairs':>7} {'blockers':>8} {'min':>6}"
    lines = [header, "-" * len(header)]
    for row in rows:
        minutes = "-" if row["minutes"] is None else row["minutes"]
        lines.append(
            f"{row['work_id']:<28} {row['state']:<10} {row['builds']:>6} "
            f"{row['repairs']:>7} {row['blockers']:>8} {minutes:>6}"
        )
    if rows:
        totals = {
            "builds": sum(r["builds"] for r in rows),
            "repairs": sum(r["repairs"] for r in rows),
            "blockers": sum(r["blockers"] for r in rows),
        }
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL (' + str(len(rows)) + ' decks)':<28} {'':<10} "
            f"{totals['builds']:>6} {totals['repairs']:>7} {totals['blockers']:>8}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-root", type=Path, help="directory holding <work-id>/build-manifest.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.work_root or default_work_root()
    manifests = sorted(root.glob(f"*/{MANIFEST_NAME}"))
    if not manifests:
        print(f"benchmark_report: no {MANIFEST_NAME} under {root}", file=sys.stderr)
        return 2

    rows = []
    for path in manifests:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(manifest, dict):
            rows.append(collect(manifest))

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render(rows), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
