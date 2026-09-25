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
PACKET_FALLBACKS_NAME = "builder-packets/fallbacks.json"


def packet_fallback_count(work_dir: Path) -> int:
    """How many packet generations failed for this deck.

    Each entry is a builder that fell back to the legacy full-read context path —
    the Batch 2 projection's savings quietly gave back. Visible per next --json
    payload too; aggregated here so a report shows it without hunting work dirs.
    """
    try:
        value = json.loads((work_dir / PACKET_FALLBACKS_NAME).read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 0
    except (OSError, json.JSONDecodeError):
        return 0


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


def collect(manifest: dict[str, Any], work_dir: Path | None = None) -> dict[str, Any]:
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
    render_calls = [h for h in history if h.get("command") == "render"]
    qa_calls = [h for h in history if h.get("command") == "qa"]
    render_reused = sum(1 for h in render_calls if h.get("reused"))
    qa_reused = sum(1 for h in qa_calls if h.get("reused"))
    # Advance ledger (Batch 3.1): one history entry per `advance` call with the
    # deterministic actions it executed. Each action used to be its own model
    # round-trip ("run command → read result → issue next command"), so the
    # collapsed count is actions minus the calls that carried them.
    advance = [h for h in history if h.get("command") == "advance"]
    advance_actions = sum(len(h.get("actions") or []) for h in advance)
    return {
        "work_id": manifest.get("work_id"),
        "manifest_version": manifest.get("manifest_version"),
        "state": manifest.get("state"),
        "builds": int(build.get("build_count") or 0),
        "repairs": int(build.get("repair_count") or 0),
        "render_events": len(render_calls) - render_reused,
        "render_reused": render_reused,
        "rendered_pages": int(render.get("page_count") or 0),
        "qa_events": len(qa_calls) - qa_reused,
        "qa_reused": qa_reused,
        "stale_evidence_moved": sum(
            int(h.get("stale_render_moved") or 0)
            for h in history
            if h.get("command") == "build"
        ),
        "qa_stage_ms": int(sum(int(v or 0) for v in stage_cost.values())),
        "blockers": int(qa.get("blockers") or 0),
        "qa_ok": bool(qa.get("ok")),
        "packet_fallbacks": packet_fallback_count(work_dir) if work_dir else 0,
        "advance_calls": len(advance),
        "advance_actions": advance_actions,
        "advance_collapsed": max(0, advance_actions - len(advance)),
        "advance_agent_boundaries": sum(1 for h in advance if h.get("status") == "needs_agent"),
        "advance_user_boundaries": sum(
            1 for h in advance if h.get("status") == "needs_user" and not h.get("step_cap")
        ),
        "advance_refusals": sum(1 for h in advance if h.get("status") == "refused"),
        "advance_session_rotations": sum(1 for h in advance if h.get("status") == "session_rotate"),
        "advance_step_cap_hits": sum(1 for h in advance if h.get("step_cap")),
        # Batch 1-4 closure: rhythm planning failures must be visible in the report,
        # not silently absorbed at plan time.
        "deck_rhythm_failed": (manifest.get("deck_rhythm") or {}).get("status") == "failed",
        "minutes": round(minutes, 1) if minutes is not None else None,
    }


def render_table(rows: list[dict[str, Any]]) -> str:
    """`render` / `qa` count real executions; `r_reuse` / `q_reuse` are cache hits.

    Without the reuse columns the report can only show what was spent, not what
    the mechanical gates actually avoided. `adv` / `col` are the Batch 3 ledger:
    advance calls and the deterministic round-trips they collapsed (actions minus
    calls); the full boundary/refusal/step-cap breakdown is in the --json rows.
    """
    header = (
        f"{'work_id':<24} {'state':<9} {'build':>5} {'repair':>6} {'render':>6} "
        f"{'r_reuse':>7} {'qa':>3} {'q_reuse':>7} {'qa_s':>7} {'block':>5} {'pk_fb':>5} {'adv':>4} {'col':>4} {'min':>6}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        minutes = "-" if row["minutes"] is None else row["minutes"]
        lines.append(
            f"{str(row['work_id']):<24} {str(row['state']):<9} {row['builds']:>5} "
            f"{row['repairs']:>6} {row['render_events']:>6} {row['render_reused']:>7} "
            f"{row['qa_events']:>3} {row['qa_reused']:>7} "
            f"{row['qa_stage_ms'] / 1000:>7.2f} {row['blockers']:>5} {row['packet_fallbacks']:>5} "
            f"{row['advance_calls']:>4} {row['advance_collapsed']:>4} {minutes:>6}"
        )
    if rows:
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL (' + str(len(rows)) + ' decks)':<24} {'':<9} "
            f"{sum(r['builds'] for r in rows):>5} {sum(r['repairs'] for r in rows):>6} "
            f"{sum(r['render_events'] for r in rows):>6} {sum(r['render_reused'] for r in rows):>7} "
            f"{sum(r['qa_events'] for r in rows):>3} {sum(r['qa_reused'] for r in rows):>7} "
            f"{sum(r['qa_stage_ms'] for r in rows) / 1000:>7.2f} "
            f"{sum(r['blockers'] for r in rows):>5} {sum(r['packet_fallbacks'] for r in rows):>5} "
            f"{sum(r['advance_calls'] for r in rows):>4} {sum(r['advance_collapsed'] for r in rows):>4}"
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
        print(f"pipeline_report: no {MANIFEST_NAME} under {root}", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    for path in manifests:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(collect(value, path.parent))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render_table(rows), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
