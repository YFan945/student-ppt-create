"""Session budget enforcement and deterministic resume handoffs (CD-8).

Cost targets in `references/cost-discipline.md` used to be prose nothing read at
runtime: one 12-page run finished at 287K peak context and 34.3M tokens against
targets of 150K / 25M. This module makes the budget a machine contract:

- stage boundaries report live usage + a rough remaining estimate;
- breaching a threshold writes a deterministic `session-handoff.md` and refuses
  further deterministic steps until the session rotates;
- the brake releases by itself when the live transcript source changes (a real
  new session), or explicitly via `advance --resume-after-handoff`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pipeline.core import (
    CONTRACT,
    ROOT,
    RefusedError,
    bind,
    load_manifest,
    now,
    record,
    save_manifest,
)

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import session_cost  # noqa: E402

DEFAULT_BUDGET = {
    "peak_context_tokens": 150_000,
    "session_minutes": 150,
    "task_total_tokens": 25_000_000,
    "default_minutes_per_agent_round": 8.0,
}

STAGE_PROGRESSION = {
    "intake_pending": ["intake", "plan", "build", "render", "qa", "complete"],
    "intake_confirmed": ["plan", "build", "render", "qa", "complete"],
    "planned": ["build", "render", "qa", "complete"],
    "producing": ["build", "render", "qa", "complete"],
    "qa": ["qa", "complete"],
    "complete": [],
}


def session_budget() -> dict[str, Any]:
    budget = dict(CONTRACT.get("session_budget") or {})
    merged = {**DEFAULT_BUDGET, **{k: v for k, v in budget.items() if v is not None}}
    return {
        "peak_context_tokens": int(merged["peak_context_tokens"]),
        "session_minutes": int(merged["session_minutes"]),
        "task_total_tokens": int(merged["task_total_tokens"]),
        "default_minutes_per_agent_round": float(merged["default_minutes_per_agent_round"]),
    }


_USAGE_CACHE: tuple[float, dict[str, Any] | None] | None = None
USAGE_CACHE_SECONDS = 5.0


def current_usage() -> dict[str, Any] | None:
    """Live usage snapshot; None when no transcript source is discoverable.

    Cached briefly inside one process: an advance loop consults the dispatch
    several times and the live model-io log can be hundreds of MB — scanning it
    once per step would make the brake itself a cost problem.
    """
    global _USAGE_CACHE  # noqa: PLW0603
    import time  # noqa: PLC0415

    now_mono = time.monotonic()
    if _USAGE_CACHE is not None and now_mono - _USAGE_CACHE[0] < USAGE_CACHE_SECONDS:
        return _USAGE_CACHE[1]
    try:
        snapshot = session_cost.current_session_usage()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        snapshot = None
    _USAGE_CACHE = (now_mono, snapshot)
    return snapshot


def budget_breaches(usage: dict[str, Any] | None, budget: dict[str, Any] | None = None) -> list[str]:
    budget = budget or session_budget()
    if not usage:
        return []
    breaches: list[str] = []
    peak = int(usage.get("peak_context") or 0)
    if peak and peak > budget["peak_context_tokens"]:
        breaches.append(
            f"peak context {peak:,} > {budget['peak_context_tokens']:,} tokens (CD-8)"
        )
    minutes = usage.get("elapsed_minutes")
    if minutes is not None and float(minutes) > budget["session_minutes"]:
        breaches.append(f"session ran {float(minutes):.0f} min > {budget['session_minutes']} min")
    total = int(usage.get("task_total_tokens") or 0)
    if total and total > budget["task_total_tokens"]:
        breaches.append(
            f"task total {total:,} > {budget['task_total_tokens']:,} tokens (CD-8)"
        )
    return breaches


def estimate_remaining(manifest: dict[str, Any] | None, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rough remaining wall clock: observed round mean x remaining stages."""
    budget = budget or session_budget()
    state = str((manifest or {}).get("state") or "intake_pending")
    remaining = STAGE_PROGRESSION.get(state, ["build", "render", "qa", "complete"])
    gaps: list[float] = []
    history = (manifest or {}).get("history") or []
    stamps = [entry.get("at") for entry in history if isinstance(entry, dict) and entry.get("at")]
    for previous, current in zip(stamps, stamps[1:], strict=False):
        try:
            from datetime import datetime  # noqa: PLC0415

            delta = (
                datetime.fromisoformat(str(current)) - datetime.fromisoformat(str(previous))
            ).total_seconds() / 60
        except ValueError:
            continue
        if 0 < delta <= 30:
            gaps.append(delta)
    mean_round = sum(gaps) / len(gaps) if gaps else budget["default_minutes_per_agent_round"]
    return {
        "remaining_stages": remaining,
        "observed_round_minutes": round(mean_round, 1),
        "estimate_minutes_remaining": round(mean_round * max(len(remaining), 1), 1),
    }


def usage_block(usage: dict[str, Any] | None, manifest: dict[str, Any] | None) -> dict[str, Any]:
    budget = session_budget()
    block: dict[str, Any] = {
        "budget": {
            "peak_context_tokens": budget["peak_context_tokens"],
            "session_minutes": budget["session_minutes"],
            "task_total_tokens": budget["task_total_tokens"],
        },
        "breaches": budget_breaches(usage, budget),
        **estimate_remaining(manifest, budget),
    }
    if usage is None:
        block["available"] = False
        return block
    block.update({
        "available": True,
        "source": usage.get("source"),
        "requests": usage.get("requests"),
        "fresh_input": usage.get("fresh_input"),
        "cache_read": usage.get("cache_read"),
        "output": usage.get("output"),
        "peak_context": usage.get("peak_context"),
        "elapsed_minutes": usage.get("elapsed_minutes"),
        "task_total_tokens": usage.get("task_total_tokens"),
        "subagent_tokens": usage.get("subagent_tokens"),
        "subagent_files": usage.get("subagent_files"),
    })
    return block


def brake_state(
    manifest: dict[str, Any], usage: dict[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    """("ok" | "rotate", detail). A new transcript source releases the brake."""
    budget = session_budget()
    breaches = budget_breaches(usage, budget)
    recorded = manifest.get("session_brake") or {}
    status = str(recorded.get("status") or "")
    source = str((usage or {}).get("source") or "")
    recorded_source = str(recorded.get("source") or "")
    if status == "breached":
        if usage is None or source != recorded_source:
            return "ok", {"released": "new-session", "previous": dict(recorded)}
        if recorded.get("ack"):
            return "ok", {"released": "resume-after-handoff", "previous": dict(recorded)}
        merged = list(dict.fromkeys([*(recorded.get("breaches") or []), *breaches]))
        return "rotate", {"breaches": merged, "recorded": dict(recorded)}
    if status == "acked" and source and source == recorded_source:
        # An explicit override sticks to the transcript it was granted for
        # (the metric was wrong, not the budget); `released` gets no such pass —
        # a real new session is metered fresh like any other.
        return "ok", {"breaches": breaches}
    if breaches:
        return "rotate", {"breaches": breaches}
    return "ok", {"breaches": []}


def mark_breached(
    work_dir: Path,
    manifest: dict[str, Any],
    usage: dict[str, Any] | None,
    breaches: list[str],
    handoff: dict[str, Any],
) -> None:
    previous = dict(manifest.get("session_brake") or {})
    already = str(previous.get("status") or "") == "breached" and previous.get("source") == (
        (usage or {}).get("source")
    )
    manifest["session_brake"] = {
        "status": "breached",
        "breaches": breaches,
        "source": (usage or {}).get("source"),
        "at": now(),
        "handoff": handoff,
    }
    if not already:
        record(
            manifest,
            "session-brake",
            str(manifest.get("state")),
            str(manifest.get("state")),
            status="breached",
            breaches=breaches,
        )
    save_manifest(work_dir, manifest)


def release_brake(
    work_dir: Path, manifest: dict[str, Any], reason: str, usage: dict[str, Any] | None
) -> None:
    recorded = dict(manifest.get("session_brake") or {})
    manifest["session_brake"] = {
        **recorded,
        "status": "acked" if reason == "resume-after-handoff" else "released",
        "released_at": now(),
        "release_reason": reason,
        "source": (usage or {}).get("source"),
        "ack": reason == "resume-after-handoff",
    }
    record(
        manifest,
        "session-brake",
        str(manifest.get("state")),
        str(manifest.get("state")),
        status=manifest["session_brake"]["status"],
        release_reason=reason,
    )
    save_manifest(work_dir, manifest)


def write_session_handoff(
    work_dir: Path,
    manifest: dict[str, Any],
    usage: dict[str, Any] | None,
    dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic resume brief: enough to continue in a fresh session."""
    dispatch = dispatch or {}
    budget = session_budget()
    breaches = budget_breaches(usage, budget)
    estimate = estimate_remaining(manifest, budget)
    summaries = sorted(path.name for path in work_dir.glob("stage-*-summary.md"))
    history_tail = [
        {
            "at": entry.get("at"),
            "command": entry.get("command"),
            "from": entry.get("from"),
            "to": entry.get("to"),
        }
        for entry in (manifest.get("history") or [])[-8:]
        if isinstance(entry, dict)
    ]
    next_command = str(dispatch.get("next_command") or "")
    if not next_command and dispatch.get("agent"):
        mode = str(dispatch.get("builder_mode") or dispatch.get("mode") or "")
        next_command = f"spawn {dispatch['agent']}" + (f" ({mode})" if mode else "")
    if not next_command and not dispatch:
        # Only when called stand-alone (cmd_handoff / the advance brake, which
        # passes no dispatch). build_next_payload itself always passes one —
        # resolving it back here would recurse into the brake.
        try:
            from pipeline.dispatch import build_next_payload  # noqa: PLC0415

            next_command = str(build_next_payload(work_dir).get("next_command") or "")
        except RefusedError:
            next_command = ""
    payload = {
        "work_id": work_dir.name,
        "work_dir": str(work_dir),
        "state": manifest.get("state"),
        "mode": manifest.get("mode"),
        "quality_level": manifest.get("quality_level"),
        "next_command": next_command,
        "repair_budget": dispatch.get("repair_budget"),
        "repair_convergence": dispatch.get("repair_convergence"),
        "builder_packets": [str(item) for item in (dispatch.get("builder_packets") or [])],
        "stage_summaries": summaries,
        "usage": usage_block(usage, manifest),
        "breaches": breaches,
        "estimate": estimate,
        "history_tail": history_tail,
        "resume_command": (
            f'"{sys.executable}" "{ROOT / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"}" '
            f'advance --resume-after-handoff --work-dir "{work_dir}"'
        ),
    }
    json_path = work_dir / "session-handoff.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Session handoff — {work_dir.name}",
        "",
        f"- state: `{payload['state']}` | mode: `{payload['mode']}` | quality: `{payload['quality_level']}`",
        f"- work-dir: `{work_dir}`",
        f"- next: `{next_command}`",
    ]
    lines += [f"- budget breach: {item}" for item in breaches]
    lines += [
        f"- usage: {usage_block(usage, manifest).get('peak_context', '?')} peak ctx | "
        f"{usage_block(usage, manifest).get('task_total_tokens', '?')} task tokens | "
        f"{usage_block(usage, manifest).get('elapsed_minutes', '?')} min",
        f"- estimate: {estimate['estimate_minutes_remaining']} min over {estimate['remaining_stages']}",
        f"- repair budget: {payload['repair_budget']}",
        f"- stage summaries: {', '.join(summaries) or '(none)'}",
        "- history tail:",
        *[f"  - {item['at']} {item['command']} {item['from']}→{item['to']}" for item in history_tail],
        f"- resume: `{payload['resume_command']}`",
    ]
    md_path = work_dir / "session-handoff.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(md_path), "json": str(json_path), "sha256": bind(md_path)["sha256"]}


def cmd_handoff(args: Any) -> int:
    """`ppt_pipeline.py handoff`: write the resume brief on demand (CD-8)."""
    work_dir = Path(args.work_dir).resolve()
    manifest = load_manifest(work_dir)
    if manifest is None:
        raise RefusedError("handoff requires a manifest; run plan first")
    paths = write_session_handoff(work_dir, manifest, current_usage())
    if getattr(args, "json", False):
        print(json.dumps(paths, ensure_ascii=False, indent=2))
    else:
        print(f"ppt_pipeline: handoff written — {paths['path']}")
    return 0
