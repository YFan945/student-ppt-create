#!/usr/bin/env python3
"""Run the fixed 6-deck benchmark and record 0.11.x cost against the 0.10 baseline.

Why this exists: `benchmarks/decks.json` has defined the six scenarios since
0.10.5, but the only live numbers on record are `live_baseline_0_10`
(82.5M tokens / 307 requests / 456k peak). Nothing has ever proved what the
0.11.x mechanical gates actually saved. This runner produces that data.

It is deliberately not part of CI: it spends real money and needs LibreOffice.
Each deck runs one real `claude -p` session against the plugin, then the
deterministic cost is read back from that deck's `build-manifest.json`.

    # pilot first: calibrate cost with one deck before spending on all six
    python scripts/benchmark_run.py --deck course-report-zh --topic "..." --budget-usd 8

    python scripts/benchmark_run.py --all --budget-usd 8
    python scripts/benchmark_run.py --report          # aggregate what already ran
    python scripts/benchmark_run.py --deck data-heavy --topic "..." --dry-run

Artifacts (gitignored, under the project root):

    outputs/.benchmark/<run-id>/<deck-id>/result.json     raw CLI result
    outputs/.benchmark/<run-id>/<deck-id>/metrics.json    merged deterministic + model cost
    benchmarks/baseline-<version>-<date>.json             all decks, for decks.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
DECKS_PATH = PLUGIN_ROOT / "benchmarks" / "decks.json"
MANIFEST_NAME = "build-manifest.json"
PLACEHOLDER = re.compile(r"^<.+>$")


class RefusedError(Exception):
    """The runner refused to spend money on an unusable configuration."""


def find_claude() -> str | None:
    """Resolve a real CLI binary, never the npm `.cmd` shim.

    The npm wrapper on Windows silently drops `--output-format json`, so a run
    through it yields prose instead of a machine-readable result and the cost
    metrics come back empty. Skip `.cmd`/`.bat` candidates outright.
    """
    candidates = [
        os.environ.get("CLAUDE_BIN"),
        shutil.which("claude"),
        str(Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
            continue
        if path.is_file():
            return str(path)
    return None


def load_decks() -> dict[str, Any]:
    try:
        value = json.loads(DECKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusedError(f"cannot read {DECKS_PATH}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("decks"), list):
        raise RefusedError(f"{DECKS_PATH} must hold a 'decks' list")
    return value


def plugin_version() -> str:
    try:
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(manifest.get("version") or "unknown")


def deck_by_id(document: dict[str, Any], deck_id: str) -> dict[str, Any]:
    for deck in document["decks"]:
        if isinstance(deck, dict) and deck.get("id") == deck_id:
            return deck
    known = ", ".join(str(d.get("id")) for d in document["decks"] if isinstance(d, dict))
    raise RefusedError(f"unknown deck '{deck_id}' (known: {known})")


def resolve_topic(deck: dict[str, Any], override: str | None) -> str:
    brief = deck.get("brief") or {}
    topic = str(override or brief.get("topic") or "").strip()
    if not topic or PLACEHOLDER.match(topic):
        raise RefusedError(
            f"deck '{deck.get('id')}' still carries the placeholder topic in decks.json; "
            "pass --topic with a real subject (a benchmark on a placeholder measures nothing)"
        )
    return topic


def resolve_materials(deck: dict[str, Any], override: str | None) -> str | None:
    raw = str(override or deck.get("materials") or "").strip()
    if not raw or PLACEHOLDER.match(raw):
        return None
    path = Path(raw)
    if not path.is_file():
        raise RefusedError(f"materials for '{deck.get('id')}' not found: {path}")
    return str(path.resolve())


def state_file_path(project_dir: Path) -> Path:
    """Must match `ppt_pipeline.default_workflow_state` for CLAUDE_PROJECT_DIR."""
    return project_dir / "outputs" / ".student-presentation-state.json"


def production_summary(deck: dict[str, Any], topic: str, work_id: str, materials: str | None) -> str:
    brief = deck.get("brief") or {}
    lines = [
        "# Production Summary",
        "",
        f"- work-id: {work_id}",
        f"- topic: {topic}",
        f"- scenario: {brief.get('scenario')}",
        "- audience: 授课教师与同学（课程汇报场景）",
        f"- language: {brief.get('language')}",
        f"- duration: {brief.get('duration_min')} minutes",
        f"- slide count: {brief.get('slide_count')}",
        f"- evidence scope: {deck.get('scope')}",
        "- mode: create",
        "",
        "## Confirmation",
        "",
        "Confirmed by the automated benchmark harness. Nobody is available for",
        "interactive clarification and every field above is final. Proceed straight to",
        "`ppt_pipeline.py plan`.",
        "",
    ]
    notes = str(brief.get("notes") or "").strip()
    if notes:
        lines.append(f"Extra requirement: {notes}")
    if materials:
        lines.append(f"User-supplied materials: {materials}")
    return "\n".join(lines) + "\n"


def prepare_intake(
    project_dir: Path, deck: dict[str, Any], topic: str, work_id: str, materials: str | None
) -> dict[str, Any]:
    """Pre-confirm the intake gate so an unattended run cannot stall at intake.

    `sp-deck` must not start production before a Production Summary is confirmed.
    With no human to answer, the model stops at intake and asks for the topic — that
    is exactly what the first pilot did. The harness therefore performs the
    confirmation itself, deterministically, and the invocation states that it is done.
    """
    work = project_dir / "outputs" / ".pptx-work" / work_id
    work.mkdir(parents=True, exist_ok=True)
    summary = work / "production-summary.md"
    summary.write_text(production_summary(deck, topic, work_id, materials), encoding="utf-8")
    state = state_file_path(project_dir)
    guard = PLUGIN_ROOT / "scripts" / "workflow_guard.py"
    python = os.environ.get("PYTHON") or sys.executable
    steps = [
        [python, str(guard), "init", "--state-file", str(state), "--topic", topic],
        [python, str(guard), "confirm", "--state-file", str(state), "--topic", topic,
         "--summary-file", str(summary), "--force"],
    ]
    log: list[dict[str, Any]] = []
    for argv in steps:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        log.append({
            "step": argv[2], "exit_code": proc.returncode,
            "stderr": (proc.stderr or "").strip()[:300],
        })
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise RefusedError(f"intake preparation failed at '{argv[2]}': {detail}")
    return {
        "summary_file": str(summary),
        "state_file": str(state),
        "summary_sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
        "steps": log,
    }


def build_invocation(
    deck: dict[str, Any],
    topic: str,
    work_id: str,
    materials: str | None,
    intake: dict[str, Any] | None = None,
) -> str:
    brief = deck.get("brief") or {}
    scope = str(deck.get("scope") or "A")
    lines = ["/student-presentation-suite:sp-deck", ""]
    if intake:
        lines += [
            "Build one deck end to end for a real student presentation.",
            "",
            "INTAKE IS ALREADY COMPLETE. The Production Summary has been written and confirmed",
            "through `workflow_guard.py confirm`, so the workflow state is `intake_confirmed`.",
            f"State file: {intake['state_file']}",
            f"Confirmed summary: {intake['summary_file']}",
            "",
            "Do NOT ask any clarifying question, do NOT run the intake gate again, and do NOT",
            "wait for a user — nobody is available. Every field below is final. Start at",
            "`ppt_pipeline.py plan` and drive through to `complete`.",
            "",
        ]
    else:
        lines += [
            "Build one deck end to end for a real student presentation. The user has ALREADY",
            "approved the Production Summary: do not ask for confirmation and do not ask any",
            "clarifying question — treat the requirements below as final and produce the deck.",
            "",
        ]
    lines += [
        f"- work-id: {work_id}",
        f"- topic: {topic}",
        f"- scenario: {brief.get('scenario')}",
        f"- language: {brief.get('language')}",
        f"- duration: {brief.get('duration_min')} minutes",
        f"- slide count: {brief.get('slide_count')}",
        f"- evidence scope: {scope}",
    ]
    notes = str(brief.get("notes") or "").strip()
    if notes:
        lines.append(f"- extra requirement: {notes}")
    if materials:
        lines.append(f"- user-supplied materials: {materials}")
    lines += [
        "",
        "Requirements:",
        f"- keep every work artifact under outputs/.pptx-work/{work_id}/",
        "- drive production through skills/sp-deck/scripts/ppt_pipeline.py",
        "  (plan -> build -> render -> qa -> complete); do not hand-orchestrate the gates",
        "- only run `sp-research` when the topic genuinely needs external evidence",
        "- the deck must reach state 'complete' with zero QA blockers",
        "- finish by printing the absolute path of the delivered .pptx on its own line",
    ]
    return "\n".join(lines)


def build_command(
    claude: str,
    invocation: str,
    budget: float,
    model: str | None,
    session_id: str,
    *,
    resume: bool = False,
) -> list[str]:
    command = [
        claude,
        "-p",
        invocation,
        "--plugin-dir",
        str(PLUGIN_ROOT),
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--max-budget-usd",
        str(budget),
    ]
    # A new run pins a session id; a resumed run re-attaches to an existing one.
    command += ["--resume", session_id] if resume else ["--session-id", session_id]
    if model:
        command += ["--model", model]
    return command


def resume_invocation(work_id: str) -> str:
    """Prompt for continuing an interrupted session without redoing finished stages."""
    return "\n".join([
        "/student-presentation-suite:sp-deck",
        "",
        "CONTINUE the deck build from where it stopped. Nobody is available to answer",
        "questions, so do not ask any and do not restart finished work.",
        "",
        f"- work-id: {work_id}",
        "",
        "Research pack, evidence map, compiled Slide Spec, Art Direction and the page scaffold",
        "already exist in this session. Read the current pipeline state with",
        "`ppt_pipeline.py next --work-dir <wd>` and pick up from there:",
        "implement the remaining pages, then build -> render -> visual critique -> qa -> complete.",
        "",
        "The deck must reach state 'complete' with zero QA blockers.",
        "Finish by printing the absolute path of the delivered .pptx on its own line.",
    ])


def manifest_metrics(project_dir: Path, work_id: str) -> dict[str, Any]:
    path = project_dir / "outputs" / ".pptx-work" / work_id / MANIFEST_NAME
    if not path.is_file():
        return {"manifest_found": False, "manifest_path": str(path)}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"manifest_found": False, "manifest_path": str(path), "manifest_error": str(exc)}

    sys.path.insert(0, str(HERE))
    import benchmark_report as report

    metrics = report.collect(manifest)
    metrics.update({
        "manifest_found": True,
        "manifest_path": str(path),
        "final_blockers": int((manifest.get("qa") or {}).get("blockers") or 0),
        "pptx": ((manifest.get("build") or {}).get("pptx") or {}).get("path"),
    })
    return metrics


def model_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Model-side cost. Field names vary, so record what is present, never guess.

    The CLI reports per-model totals under `modelUsage` (inputTokens /
    outputTokens / cacheReadInputTokens) and leaves the top-level `usage`
    counters at zero — so the token estimate must be built from `modelUsage`.
    """
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    model_usage = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    for entry in model_usage.values():
        if not isinstance(entry, dict):
            continue
        totals["input"] += int(entry.get("inputTokens") or 0)
        totals["output"] += int(entry.get("outputTokens") or 0)
        totals["cache_read"] += int(entry.get("cacheReadInputTokens") or 0)
        totals["cache_creation"] += int(entry.get("cacheCreationInputTokens") or 0)
    context_estimate = totals["input"] + totals["cache_read"] + totals["cache_creation"]
    if not context_estimate:
        context_estimate = sum(
            int(usage.get(key) or 0)
            for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
    return {
        "total_cost_usd": result.get("total_cost_usd"),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "stop_reason": result.get("stop_reason"),
        "terminal_reason": result.get("terminal_reason"),
        "is_error": bool(result.get("is_error")),
        "session_id": result.get("session_id"),
        "models": sorted(model_usage),
        "usage": usage,
        "token_context_estimate": context_estimate,
        "token_breakdown": totals,
    }


def run_one(
    deck: dict[str, Any],
    *,
    project_dir: Path,
    run_dir: Path,
    topic: str,
    materials: str | None,
    budget: float,
    model: str | None,
    dry_run: bool,
    resume_session: str | None = None,
) -> dict[str, Any]:
    deck_id = str(deck["id"])
    work_id = deck_id
    session_id = resume_session or str(uuid.uuid4())

    deck_dir = run_dir / deck_id
    deck_dir.mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "deck_id": deck_id,
        "deck_type": deck.get("type"),
        "scope": deck.get("scope"),
        "topic": topic,
        "materials": materials,
        "work_id": work_id,
        "session_id": session_id,
        "resumed": bool(resume_session),
        "plugin_version": plugin_version(),
        "budget_usd": budget,
        "started_at": datetime.now(UTC).isoformat(),
        "command": [],
    }
    if dry_run:
        invocation = (
            resume_invocation(work_id) if resume_session
            else build_invocation(deck, topic, work_id, materials)
        )
        (deck_dir / "invocation.md").write_text(invocation + "\n", encoding="utf-8")
        record.update({"dry_run": True, "metrics": {}, "state": "dry-run"})
        return record

    if resume_session:
        # intake was confirmed when the interrupted run started; redoing it would
        # reset the workflow state the pipeline is already sitting in.
        invocation = resume_invocation(work_id)
    else:
        intake = prepare_intake(project_dir, deck, topic, work_id, materials)
        record["intake"] = intake
        invocation = build_invocation(deck, topic, work_id, materials, intake)
    (deck_dir / "invocation.md").write_text(invocation + "\n", encoding="utf-8")

    claude = find_claude()
    if not claude:
        raise RefusedError("cannot find a real claude CLI binary; set CLAUDE_BIN")
    command = build_command(
        claude, invocation, budget, model, session_id, resume=bool(resume_session)
    )
    record["command"] = command

    started = datetime.now(UTC)
    proc = subprocess.run(
        command, cwd=str(project_dir), check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    finished = datetime.now(UTC)
    (deck_dir / "result.json").write_text(proc.stdout or "", encoding="utf-8")
    (deck_dir / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")

    result: dict[str, Any] = {}
    try:
        parsed = json.loads(proc.stdout)
        if isinstance(parsed, dict):
            result = parsed
    except json.JSONDecodeError:
        pass

    metrics = manifest_metrics(project_dir, work_id)
    metrics.update(model_metrics(result))
    metrics["wall_minutes"] = round((finished - started).total_seconds() / 60, 1)
    metrics["cli_exit_code"] = proc.returncode
    reached_complete = (
        str(metrics.get("state") or "") == "complete" and not int(metrics.get("final_blockers") or 0)
    )
    record.update({
        "finished_at": finished.isoformat(),
        "dry_run": False,
        "metrics": metrics,
        "state": "ok" if reached_complete else "attention",
        "notes": "" if reached_complete else "deck did not reach 'complete' with zero blockers",
    })
    return record


def aggregate(records: list[dict[str, Any]], document: dict[str, Any], version: str) -> dict[str, Any]:
    live = [r for r in records if not r.get("dry_run")]
    truncated = [r for r in live if r.get("state") != "ok"]
    total_cost = sum(float((r.get("metrics") or {}).get("total_cost_usd") or 0) for r in live)
    total_tokens = sum(int((r.get("metrics") or {}).get("token_context_estimate") or 0) for r in live)
    baseline = document.get("live_baseline_0_10") or {}
    return {
        "benchmark_version": document.get("benchmark_version"),
        "plugin_version": version,
        "recorded_at": datetime.now(UTC).isoformat(),
        "decks_run": len(live),
        "decks_expected": len(document.get("decks") or []),
        "comparable": not truncated and len(live) == len(document.get("decks") or []),
        "totals": {
            "builds": sum(int((r.get("metrics") or {}).get("builds") or 0) for r in live),
            "repairs": sum(int((r.get("metrics") or {}).get("repairs") or 0) for r in live),
            "render_events": sum(int((r.get("metrics") or {}).get("render_events") or 0) for r in live),
            "render_reused": sum(int((r.get("metrics") or {}).get("render_reused") or 0) for r in live),
            "qa_events": sum(int((r.get("metrics") or {}).get("qa_events") or 0) for r in live),
            "qa_reused": sum(int((r.get("metrics") or {}).get("qa_reused") or 0) for r in live),
            "stale_evidence_moved": sum(int((r.get("metrics") or {}).get("stale_evidence_moved") or 0) for r in live),
            "blockers": sum(int((r.get("metrics") or {}).get("final_blockers") or 0) for r in live),
            "num_turns": sum(int((r.get("metrics") or {}).get("num_turns") or 0) for r in live),
            "token_context_estimate": total_tokens,
            "cost_usd": round(total_cost, 4),
            "complete_decks": len(live) - len(truncated),
            "truncated_decks": len(truncated),
        },
        "truncated": [
            {
                "deck_id": r.get("deck_id"),
                "terminal_reason": (r.get("metrics") or {}).get("terminal_reason"),
                "manifest_state": (r.get("metrics") or {}).get("state"),
                "note": "did not reach 'complete'; its cost/tokens are a lower bound, not a full-deck figure",
            }
            for r in truncated
        ],
        "targets": {
            "target_tokens_per_deck": baseline.get("target_tokens"),
            "target_peak_context": baseline.get("target_peak_context"),
            "note": baseline.get("notes"),
        },
        "records": records,
    }


def print_summary(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print(f"benchmark_run: {report['decks_run']}/{report['decks_expected']} decks, plugin {report['plugin_version']}")
    print(
        f"  builds {totals['builds']} repairs {totals['repairs']} "
        f"render {totals['render_events']} (+{totals['render_reused']} reused) "
        f"qa {totals['qa_events']} (+{totals['qa_reused']} reused)"
    )
    print(
        f"  blockers {totals['blockers']} turns {totals['num_turns']} "
        f"token-context {totals['token_context_estimate']:,} cost ${totals['cost_usd']}"
    )
    if totals.get("truncated_decks"):
        print(
            f"  NOTE: {totals['truncated_decks']} deck(s) never reached 'complete' — "
            "their cost and token figures are lower bounds"
        )
    for record in report["records"]:
        metrics = record.get("metrics") or {}
        if record.get("dry_run"):
            print(f"  [dry-run] {record['deck_id']}")
            continue
        print(
            f"  {record['deck_id']:<18} {record.get('state', '-'):<9} "
            f"builds {metrics.get('builds', '-')} repairs {metrics.get('repairs', '-')} "
            f"blockers {metrics.get('final_blockers', '-')} "
            f"${metrics.get('total_cost_usd', '-')} {metrics.get('wall_minutes', '-')}min"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", help="run a single deck by id")
    parser.add_argument("--all", action="store_true", help="run every deck in benchmarks/decks.json")
    parser.add_argument(
        "--resume", metavar="SESSION_ID",
        help="continue an interrupted deck session (needs --deck); skips intake and finished stages",
    )
    parser.add_argument("--report", action="store_true", help="only aggregate the current run, spend nothing")
    parser.add_argument("--project-dir", type=Path, help="CLAUDE_PROJECT_DIR for the runs (default: repo root)")
    parser.add_argument("--run-id", help="run directory name (default: version-timestamp)")
    parser.add_argument("--topic", help="override the deck topic (decks.json ships placeholders)")
    parser.add_argument("--materials", help="override the materials path for scope C/D decks")
    parser.add_argument(
        "--budget-usd", type=float, default=14.0,
        help="per-deck --max-budget-usd (default 14; the pilot spent $8.04 before QA even ran)",
    )
    parser.add_argument("--model", help="pass through to --model")
    parser.add_argument("--dry-run", action="store_true", help="write the invocation, call nothing")
    parser.add_argument("--topic-deck", action="append", default=[], metavar="ID=TOPIC",
                        help="per-deck topic, repeatable (use with --all)")
    args = parser.parse_args(argv)

    document = load_decks()
    version = plugin_version()
    project_dir = (args.project_dir or PLUGIN_ROOT.parents[1]).resolve()
    run_id = args.run_id or f"{version}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = project_dir / "outputs" / ".benchmark" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.resume and not args.deck:
        raise RefusedError("--resume continues one interrupted session; pass --deck <id> too")
    if not args.report and not args.deck and not args.all:
        parser.error("choose --deck <id>, --all, or --report")
    if args.all and not args.dry_run and not args.topic and not args.topic_deck:
        raise RefusedError(
            "--all needs real topics: decks.json ships placeholders. "
            "Pass --topic-deck <id>=<topic> for each deck (repeatable), or run --deck one at a time."
        )

    overrides = {}
    for item in args.topic_deck:
        if "=" not in item:
            raise RefusedError(f"--topic-deck expects ID=TOPIC, got {item!r}")
        key, value = item.split("=", 1)
        overrides[key.strip()] = value.strip()

    records: list[dict[str, Any]] = []
    if args.deck or args.all:
        targets = [deck_by_id(document, args.deck)] if args.deck else list(document["decks"])
        for deck in targets:
            deck_id = str(deck["id"])
            if args.resume:
                # the original run already resolved a real topic; do not re-validate it
                topic = str(overrides.get(deck_id) or (deck.get("brief") or {}).get("topic") or deck_id)
                materials = args.materials
            else:
                topic = resolve_topic(deck, args.topic or overrides.get(deck_id))
                materials = resolve_materials(deck, args.materials)
            print(f"benchmark_run: {deck_id} ({deck.get('type')}, scope {deck.get('scope')})")
            record = run_one(
                deck, project_dir=project_dir, run_dir=run_dir, topic=topic, materials=materials,
                budget=args.budget_usd, model=args.model, dry_run=args.dry_run,
                resume_session=args.resume,
            )
            (run_dir / deck_id / "record.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            records.append(record)
    else:
        for path in sorted(run_dir.glob("*/record.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)

    report = aggregate(records, document, version)
    report_path = run_dir / "benchmark-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(report)
    print(f"benchmark_run: report -> {report_path}")
    if records and not args.dry_run and not args.report:
        baseline_path = PLUGIN_ROOT / "benchmarks" / f"baseline-{version}-{datetime.now().strftime('%Y%m%d')}.json"
        baseline_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"benchmark_run: baseline -> {baseline_path}")
        print("benchmark_run: fold the totals into decks.json's live_baseline once all six decks are in")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RefusedError as exc:
        print(f"benchmark_run: REFUSED — {exc}", file=sys.stderr)
        sys.exit(2)
