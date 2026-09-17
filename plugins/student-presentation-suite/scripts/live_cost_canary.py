#!/usr/bin/env python3
"""Manual, real-Claude E2E cost canary for the complete sp-deck pipeline.

This runner is intentionally NOT part of normal validation. It launches Claude
Code headlessly in a dedicated project/config directory, performs the real
Production Summary confirmation as a second user turn, then combines:

- Claude's persisted main/subagent transcripts via session_cost.py
- deterministic build/repair/render/QA metrics via pipeline_report.py
- the final build-manifest state

The primary model-cost metric is *estimated token-context work*:
`request_count * average resident context`. It is a regression proxy, not an
API billing token count. Monetary spend is separately bounded by Claude CLI's
`--max-budget-usd` on each turn.

Examples:
    python scripts/live_cost_canary.py --plugin-dir . --scenario deck-local
    python scripts/live_cost_canary.py --plugin-dir . --scenario deck-research
    python scripts/live_cost_canary.py --plugin-dir . --scenario both --result-dir canary-results

Exit codes:
    0 = requested canary scenario(s) completed and stayed inside guardrails
    2 = harness/auth/runtime infrastructure failure
    3 = real pipeline ran but did not complete or exceeded a cost guardrail
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pipeline_report
import session_cost

HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "live_prompts"
DEFAULT_PERMISSION_MODE = "acceptEdits"
CORE_TOOLS = ("Read", "Write", "Edit", "Grep", "Glob", "Bash", "PowerShell", "Agent", "Skill")
WEB_TOOLS = ("WebSearch", "WebFetch")

SCENARIOS: dict[str, dict[str, Any]] = {
    "deck-local": {
        "prompt": PROMPT_DIR / "canary-deck-local.md",
        "work_id": "canary-deck-local",
        "scope": "C",
        "intake_budget_usd": 1.0,
        "production_budget_usd": 6.0,
        "guardrails": {
            "main_peak_context": 200_000,
            "main_requests": 180,
            "total_estimated_token_context": 40_000_000,
            "builds": 3,
            "repairs": 2,
        },
    },
    "deck-research": {
        "prompt": PROMPT_DIR / "canary-deck-research.md",
        "work_id": "canary-deck-research",
        "scope": "A",
        "intake_budget_usd": 1.5,
        "production_budget_usd": 9.0,
        "guardrails": {
            "main_peak_context": 200_000,
            "main_requests": 240,
            "total_estimated_token_context": 60_000_000,
            "builds": 3,
            "repairs": 2,
        },
    },
}

CONFIRMATION = """我确认刚才的 Production Summary。请继续使用同一个 work-id，按插件的生产管线完成整套 PPTX，直到 build-manifest.json 的 state=complete。必须经过隔离 presentation-builder、calibration preview、正式 build/render、隔离 visual-critic、QA 和 complete；不要绕过门禁，不要再次询问可自行决定的默认项。若某一步被机械门禁拒绝，按照 ppt_pipeline.py next 给出的合法动作修正后继续。"""


def find_claude() -> str | None:
    for candidate in (
        os.environ.get("CLAUDE_BIN"),
        shutil.which("claude"),
        Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
    ):
        if candidate and Path(str(candidate)).is_file():
            return str(candidate)
    return None


def parse_result(stdout: str) -> dict[str, Any]:
    """Return the last JSON result object Claude emitted."""
    payload: dict[str, Any] = {}
    raw = stdout.strip()
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            payload = value
    except json.JSONDecodeError:
        pass
    if payload:
        return payload
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and (
            value.get("type") == "result" or "session_id" in value or "total_cost_usd" in value
        ):
            payload = value
    return payload


def build_command(
    claude: str,
    plugin_dir: Path,
    prompt: str,
    budget: float,
    *,
    scope: str,
    model: str | None = None,
    resume: str | None = None,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
) -> list[str]:
    tools = list(CORE_TOOLS)
    if scope.upper() != "C":
        tools.extend(WEB_TOOLS)
    command = [
        claude,
        "-p",
        prompt,
        "--plugin-dir",
        str(plugin_dir.resolve()),
        "--add-dir",
        str(plugin_dir.resolve()),
        "--output-format",
        "json",
        "--permission-mode",
        permission_mode,
        "--allowedTools",
        ",".join(tools),
        "--max-budget-usd",
        str(budget),
    ]
    if scope.upper() == "C":
        command += ["--disallowedTools", ",".join(WEB_TOOLS)]
    if resume:
        command += ["--resume", resume]
    if model:
        command += ["--model", model]
    return command


def run_turn(
    command: list[str],
    *,
    project_dir: Path,
    config_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    env = dict(os.environ)
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(config_dir.resolve()),
            "CLAUDE_PROJECT_DIR": str(project_dir.resolve()),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=str(project_dir),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    payload = parse_result(proc.stdout)
    payload.setdefault("harness_wall_sec", round(time.time() - started, 2))
    payload.setdefault("process_returncode", proc.returncode)
    return proc, payload


def transcript_profiles(config_dir: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    root = config_dir / "projects"
    mains = session_cost.discover(root, include_subagents=False)
    if not mains:
        raise RuntimeError(f"Claude persisted no main-session transcript under {root}")
    main_path = mains[0]
    main_profile = session_cost.profile(session_cost.read_records(main_path))

    all_paths = session_cost.discover(root, include_subagents=True)
    profiles: list[dict[str, Any]] = []
    for path in all_paths:
        profile = session_cost.profile(session_cost.read_records(path))
        profile["transcript"] = str(path)
        profile["is_main"] = path == main_path
        profile["estimated_token_context"] = int(profile["requests"] * profile["context"]["average"])
        profiles.append(profile)
    return main_path, main_profile, profiles


def aggregate_model_cost(main_profile: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    main_estimated = int(main_profile["requests"] * main_profile["context"]["average"])
    total_estimated = sum(int(item.get("estimated_token_context") or 0) for item in profiles)
    total_requests = sum(int(item.get("requests") or 0) for item in profiles)
    return {
        "main_requests": int(main_profile["requests"]),
        "main_average_context": int(main_profile["context"]["average"]),
        "main_peak_context": int(main_profile["context"]["peak"]),
        "main_estimated_token_context": main_estimated,
        "all_agent_requests": total_requests,
        "total_estimated_token_context": total_estimated,
        "main_token_context_share_pct": round(main_estimated / total_estimated * 100, 1)
        if total_estimated
        else 0.0,
        "transcript_count": len(profiles),
    }


def collect_pipeline(project_dir: Path, expected_work_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    root = project_dir / "outputs" / ".pptx-work"
    rows: list[dict[str, Any]] = []
    target: dict[str, Any] | None = None
    for path in sorted(root.glob("*/build-manifest.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        row = pipeline_report.collect(value)
        row["manifest"] = str(path)
        rows.append(row)
        if row.get("work_id") == expected_work_id:
            target = row
    return rows, target


def evaluate_guardrails(
    model_cost: dict[str, Any], pipeline: dict[str, Any] | None, guardrails: dict[str, int]
) -> list[str]:
    problems: list[str] = []
    if pipeline is None:
        return ["expected build-manifest.json was not produced"]
    if pipeline.get("state") != "complete":
        problems.append(f"pipeline state is {pipeline.get('state')!r}, expected 'complete'")
    mapping = {
        "main_peak_context": model_cost.get("main_peak_context"),
        "main_requests": model_cost.get("main_requests"),
        "total_estimated_token_context": model_cost.get("total_estimated_token_context"),
        "builds": pipeline.get("builds"),
        "repairs": pipeline.get("repairs"),
    }
    for key, ceiling in guardrails.items():
        value = mapping.get(key)
        if value is not None and int(value) > int(ceiling):
            problems.append(f"{key}={value} exceeds guardrail {ceiling}")
    return problems


def discover_session_id(payload: dict[str, Any], config_dir: Path) -> str | None:
    session = payload.get("session_id")
    if session:
        return str(session)
    mains = session_cost.discover(config_dir / "projects", include_subagents=False)
    return mains[0].stem if mains else None


def run_scenario(
    name: str,
    *,
    claude: str,
    plugin_dir: Path,
    result_root: Path,
    model: str | None,
    production_budget_override: float | None,
    permission_mode: str,
) -> tuple[dict[str, Any], bool, bool]:
    scenario = SCENARIOS[name]
    prompt_path = Path(scenario["prompt"])
    if not prompt_path.is_file():
        raise RuntimeError(f"canary prompt missing: {prompt_path}")

    scenario_root = result_root / name
    project_dir = scenario_root / "project"
    config_dir = scenario_root / "claude-config"
    project_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    prompt = prompt_path.read_text(encoding="utf-8")

    intake_budget = float(scenario["intake_budget_usd"])
    production_budget = (
        production_budget_override
        if production_budget_override is not None
        else float(scenario["production_budget_usd"])
    )
    first_cmd = build_command(
        claude,
        plugin_dir,
        prompt,
        intake_budget,
        scope=str(scenario["scope"]),
        model=model,
        permission_mode=permission_mode,
    )
    first_proc, first_payload = run_turn(
        first_cmd,
        project_dir=project_dir,
        config_dir=config_dir,
        stdout_path=scenario_root / "turn-1.stdout.json",
        stderr_path=scenario_root / "turn-1.stderr.txt",
    )
    session_id = discover_session_id(first_payload, config_dir)
    infrastructure_ok = first_proc.returncode == 0 and bool(session_id)
    if not session_id:
        summary = {
            "scenario": name,
            "infrastructure_ok": False,
            "canary_ok": False,
            "reason": "first headless turn produced no resumable Claude session",
            "turns": [first_payload],
        }
        return summary, False, False

    second_cmd = build_command(
        claude,
        plugin_dir,
        CONFIRMATION,
        production_budget,
        scope=str(scenario["scope"]),
        model=model,
        resume=session_id,
        permission_mode=permission_mode,
    )
    second_proc, second_payload = run_turn(
        second_cmd,
        project_dir=project_dir,
        config_dir=config_dir,
        stdout_path=scenario_root / "turn-2.stdout.json",
        stderr_path=scenario_root / "turn-2.stderr.txt",
    )
    infrastructure_ok = infrastructure_ok and second_proc.returncode == 0

    try:
        main_path, main_profile, profiles = transcript_profiles(config_dir)
        model_cost = aggregate_model_cost(main_profile, profiles)
    except RuntimeError as exc:
        summary = {
            "scenario": name,
            "infrastructure_ok": False,
            "canary_ok": False,
            "reason": str(exc),
            "turns": [first_payload, second_payload],
        }
        return summary, False, False

    rows, pipeline = collect_pipeline(project_dir, str(scenario["work_id"]))
    guardrail_problems = evaluate_guardrails(model_cost, pipeline, scenario["guardrails"])
    permission_denials = []
    for payload in (first_payload, second_payload):
        permission_denials.extend(payload.get("permission_denials") or [])
    if permission_denials:
        guardrail_problems.append(f"permission denials occurred: {permission_denials}")

    reported_cost = sum(
        float(payload.get("total_cost_usd") or 0.0) for payload in (first_payload, second_payload)
    )
    summary = {
        "scenario": name,
        "work_id": scenario["work_id"],
        "prompt": str(prompt_path),
        "prompt_sha256": __import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest(),
        "session_id": session_id,
        "main_transcript": str(main_path),
        "infrastructure_ok": infrastructure_ok,
        "canary_ok": infrastructure_ok and not guardrail_problems,
        "reported_turn_cost_usd_sum": round(reported_cost, 4),
        "budgets_usd": {"intake": intake_budget, "production": production_budget},
        "model_cost": model_cost,
        "agent_profiles": profiles,
        "pipeline": pipeline,
        "all_pipeline_rows": rows,
        "guardrails": scenario["guardrails"],
        "problems": guardrail_problems,
        "turns": [first_payload, second_payload],
    }
    (scenario_root / "canary-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary, infrastructure_ok, bool(summary["canary_ok"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "both"], default="deck-local")
    parser.add_argument("--result-dir", type=Path, help="persistent result root; defaults to a temp directory")
    parser.add_argument("--model", help="optional Claude model passed to both turns")
    parser.add_argument("--production-budget-usd", type=float, help="override production-turn budget")
    parser.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    claude = find_claude()
    if not claude:
        print("live_cost_canary: cannot find claude CLI (set CLAUDE_BIN)", file=sys.stderr)
        return 2
    plugin_dir = args.plugin_dir.resolve()
    if not plugin_dir.is_dir():
        print(f"live_cost_canary: plugin dir not found: {plugin_dir}", file=sys.stderr)
        return 2

    result_root = (
        args.result_dir.resolve()
        if args.result_dir
        else Path(tempfile.mkdtemp(prefix="ppt-live-cost-canary-"))
    )
    result_root.mkdir(parents=True, exist_ok=True)
    selected = list(SCENARIOS) if args.scenario == "both" else [args.scenario]
    summaries: list[dict[str, Any]] = []
    infrastructure_ok = True
    canary_ok = True
    for name in selected:
        try:
            summary, infra, ok = run_scenario(
                name,
                claude=claude,
                plugin_dir=plugin_dir,
                result_root=result_root,
                model=args.model,
                production_budget_override=args.production_budget_usd,
                permission_mode=args.permission_mode,
            )
        except (OSError, RuntimeError) as exc:
            summary, infra, ok = ({"scenario": name, "infrastructure_ok": False, "canary_ok": False, "reason": str(exc)}, False, False)
        summaries.append(summary)
        infrastructure_ok = infrastructure_ok and infra
        canary_ok = canary_ok and ok

    combined = {
        "result_dir": str(result_root),
        "infrastructure_ok": infrastructure_ok,
        "canary_ok": canary_ok,
        "scenarios": summaries,
    }
    (result_root / "canary-summary.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(combined, ensure_ascii=False, indent=2))
    else:
        for item in summaries:
            cost = item.get("model_cost") or {}
            pipe = item.get("pipeline") or {}
            print(
                f"{item['scenario']}: {'PASS' if item.get('canary_ok') else 'FAIL'} | "
                f"main req={cost.get('main_requests', '?')} peak={cost.get('main_peak_context', '?')} "
                f"token-context={cost.get('total_estimated_token_context', '?')} | "
                f"build={pipe.get('builds', '?')} repair={pipe.get('repairs', '?')} state={pipe.get('state', '?')}"
            )
            for problem in item.get("problems") or []:
                print(f"  - {problem}")
        print(f"results: {result_root}")

    if not infrastructure_ok:
        return 2
    return 0 if canary_ok else 3


if __name__ == "__main__":
    sys.exit(main())
