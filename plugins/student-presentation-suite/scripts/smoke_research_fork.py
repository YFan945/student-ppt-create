#!/usr/bin/env python3
"""Live smoke test: does `sp-research` actually spawn a real, isolated subagent,
and does that subagent write a schema-shaped Research Pack to the contract path?

Item 14 of the review is really two questions, conflated into one "Live E2E":

  MECHANISM  Does the skill launch `presentation-researcher` in its own context,
             foreground, without the raw retrieval reaching the main session?
  ARTIFACT   Does that subagent produce a Research Pack at
             `${CLAUDE_PROJECT_DIR}/outputs/.pptx-work/<work-id>/research-pack.json`
             that is valid JSON with findings + sources?

The mechanism half is cheap and model-independent, so it is asserted mechanically.
The artifact half depends on the model and on whether the network lets the
researcher fetch anything, so it is reported separately, not folded into the
verdict. With `--validate`, the pack is also checked by validate_research_pack.py.

The instrument is `claude -p --output-format json`: its result carries
`subagent_stats.spawned` and `started_in_background` — the difference between
"the docs say retrieval is isolated" and "the runtime spawned a foreground
subagent".

The accepted evidence changed in 0.12.0. Earlier revisions relied on `context: fork`
in the skill frontmatter, and this scaffold also accepted a fork event in the
stream as proof. Two live runs showed that under `claude -p` no subagent was
spawned *and* no fork event was emitted, while the skill ran inline in the main
session — so `context: fork` is no longer the isolation mechanism (see
`live_prompts/FINDINGS.md`). The skill now spawns explicitly, and **only**
`subagent_stats.spawned >= 1` counts as the mechanism being real.

Usage:
    # default minimal smoke (scope A, inline brief)
    python scripts/smoke_research_fork.py --plugin-dir plugins/student-presentation-suite

    # the two Live E2E scenarios shipped under scripts/live_prompts
    python scripts/smoke_research_fork.py --plugin-dir plugins/student-presentation-suite --scenario ai-agent-trends
    python scripts/smoke_research_fork.py --plugin-dir plugins/student-presentation-suite --scenario d-mode --materials scripts/live_prompts/sample-paper.md

    # or wire your own brief / scope directly
    python scripts/smoke_research_fork.py --plugin-dir . --brief-file my.brief.md --scope A

Exit codes: 0 = mechanism ok and an artifact landed; 2 = mechanism failed;
3 = mechanism ok but no Research Pack was written.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_INVOCATION = "/student-presentation-suite:sp-research {work_id} {brief} {scope} {materials}"
BRIEF = """# Presentation Brief

topic: smoke test - a single claim that must be sourced
scenario: coursework
language: Chinese
duration_min: 5
slide_count: 7
"""

# Scenario presets. `brief_file` is resolved relative to the plugin root so the
# harness can be launched from anywhere.
SCENARIOS = {
    "smoke": {"scope": "A", "budget": 1.0, "brief": BRIEF, "materials": "-"},
    "ai-agent-trends": {
        "scope": "A",
        "budget": 3.0,
        "brief_file": "scripts/live_prompts/ai-agent-trends-2026.brief.md",
        "materials": "-",
    },
    "d-mode": {
        "scope": "D",
        "budget": 1.0,
        "brief_file": "scripts/live_prompts/own-paper-d-mode.brief.md",
        # materials must be supplied via --materials on the command line
    },
}


def find_claude() -> str | None:
    import os

    for candidate in (
        os.environ.get("CLAUDE_BIN"),
        shutil.which("claude"),
        Path.home()
        / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
    ):
        if candidate and Path(str(candidate)).is_file():
            return str(candidate)
    return None


def build_command(
    claude: str,
    plugin_dir: Path,
    invocation: str,
    budget: float,
    model: str | None,
    stream: bool = False,
) -> list[str]:
    command = [
        claude,
        "-p",
        invocation,
        "--plugin-dir",
        str(plugin_dir.resolve()),
        "--output-format",
        "stream-json" if stream else "json",
        "--permission-mode",
        "acceptEdits",
        "--max-budget-usd",
        str(budget),
        "--no-session-persistence",
    ]
    if stream:
        command += ["--verbose"]
    if model:
        command += ["--model", model]
    return command


def pack_path(project_dir: Path, work_id: str) -> Path:
    return project_dir / "outputs" / ".pptx-work" / work_id / "research-pack.json"


def mechanism_verdict(
    payload: dict[str, Any], fork_event_types: set[str] | None = None
) -> tuple[bool, list[str], list[str]]:
    """Did a real, foreground subagent run? Independent of what it produced.

    Since the isolation contract moved from `context: fork` to an explicit Agent-tool
    spawn, `subagent_stats.spawned >= 1` is the *only* accepted evidence. A
    `context: fork` skill might have forked a context that this counter does not
    track, which is exactly why that mechanism was abandoned: two live runs showed
    `spawned = 0` with no subagent event while the skill ran inline in the main
    session. An explicit spawn is always counted, so spawn count alone now decides.
    """
    fork_event_types = fork_event_types or set()
    problems: list[str] = []
    notes: list[str] = []
    stats = payload.get("subagent_stats")
    if not isinstance(stats, dict):
        problems.append("result carries no subagent_stats - cannot tell whether the spawn happened")
        return False, problems, notes

    spawned = stats.get("spawned") or 0
    background = stats.get("started_in_background") or 0
    if spawned < 1:
        detail = f" (fork/subagent events seen: {sorted(fork_event_types)})" if fork_event_types else ""
        problems.append(
            f"no subagent was spawned (subagent_stats.spawned={spawned}){detail}; "
            "sp-research must spawn student-presentation-suite:presentation-researcher through "
            "the Agent tool - an explicit spawn is always counted here"
        )
    if background:
        problems.append(
            f"{background} subagent(s) ran in the background; sp-research requires a foreground "
            "spawn so the pipeline cannot proceed on an unfinished Research Pack"
        )
    denials = payload.get("permission_denials") or []
    if denials:
        problems.append(f"permission denials: {denials}")
    if payload.get("terminal_reason") == "budget_exhausted":
        problems.append("budget exhausted before the run finished - raise --max-budget-usd for a real verdict")
    return not problems, problems, notes


def artifact_verdict(pack: Path) -> tuple[bool, str]:
    if not pack.is_file():
        return False, f"no research-pack.json at {pack}"
    try:
        data = json.loads(pack.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"research-pack.json is not readable JSON: {exc}"
    findings = data.get("findings") or []
    sources = data.get("sources") or []
    if not isinstance(findings, list) or not isinstance(sources, list):
        return False, f"research-pack.json is missing findings/sources lists at {pack}"
    return True, f"{pack} ({len(findings)} findings, {len(sources)} sources)"


def main_flow_leaked_retrieval(payload: dict[str, Any]) -> list[str]:
    """CD-5: the parent result must not carry raw retrieval tools."""
    blob = json.dumps(payload.get("result") or payload.get("result_text") or "", ensure_ascii=False)
    problems: list[str] = []
    for marker in ("WebSearch", "WebFetch"):
        if marker in blob:
            problems.append(f"main transcript contains {marker}")
    return problems


def run_validator(pack: Path) -> str:
    validator = Path(__file__).resolve().parent / "validate_research_pack.py"
    if not validator.is_file():
        return "validator skipped (validate_research_pack.py not found)"
    proc = subprocess.run(
        [sys.executable, str(validator), str(pack), "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode == 0:
        try:
            rep = json.loads(proc.stdout)
            return f"validator ok: {rep.get('counts', {}).get('blockers', '?')} blockers"
        except json.JSONDecodeError:
            return "validator ok"
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
    return "validator found issues: " + " | ".join(tail)


def render(
    mechanism_ok: bool,
    mechanism_problems: list[str],
    mechanism_notes: list[str],
    artifact_ok: bool,
    artifact_note: str,
    payload: dict[str, Any],
    validate_note: str = "",
) -> str:
    state = "ok" if mechanism_ok and artifact_ok else ("mechanism-ok" if mechanism_ok else "blocked")
    lines = [
        f"smoke_research_fork: {state} — mechanism {'ok' if mechanism_ok else 'FAILED'} | "
        f"artifact {'ok' if artifact_ok else 'missing'} | cost ${payload.get('total_cost_usd', '?')} | "
        f"stop={payload.get('terminal_reason', '?')}"
    ]
    for line in mechanism_problems:
        lines.append(f"  [major] mechanism — {line}")
    for line in mechanism_notes:
        lines.append(f"  [note] mechanism — {line}")
    lines.append(f"  artifact — {artifact_note}")
    if validate_note:
        lines.append(f"  validate — {validate_note}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="smoke")
    parser.add_argument("--brief-file", type=Path, help="override the scenario brief")
    parser.add_argument("--scope", choices=["A", "B", "C", "D"])
    parser.add_argument("--materials", default=None, help="D-mode materials path (or - for none)")
    parser.add_argument("--work-dir", type=Path, help="project dir / CLAUDE_PROJECT_DIR (defaults to a temp dir)")
    parser.add_argument("--max-budget-usd", type=float, help="override the scenario budget")
    parser.add_argument("--model", help="pass through to --model; use to bypass a per-model rate limit")
    parser.add_argument("--output", type=Path, help="where to write the raw result JSON")
    parser.add_argument("--validate", action="store_true", help="run validate_research_pack.py on the pack")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="use --output-format stream-json and watch for explicit subagent/fork events "
        "(definitively distinguishes a real skill-fork from an inline run)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    claude = find_claude()
    if not claude:
        print("smoke_research_fork: cannot find the claude CLI (set CLAUDE_BIN)", file=sys.stderr)
        return 2

    scen = dict(SCENARIOS[args.scenario])
    scope = args.scope or scen.get("scope", "A")
    budget = args.max_budget_usd if args.max_budget_usd is not None else scen.get("budget", 1.0)
    materials = args.materials if args.materials is not None else scen.get("materials", "-")

    plugin_dir = args.plugin_dir.resolve()
    project_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="research-fork-"))
    project_dir.mkdir(parents=True, exist_ok=True)
    work_id = project_dir.name

    # brief: explicit file wins, else the scenario's inline brief, else BRIEF
    if args.brief_file:
        brief_src = Path(args.brief_file)
    elif scen.get("brief_file"):
        brief_src = plugin_dir / scen["brief_file"]
    else:
        brief_src = None
    brief = project_dir / "brief.md"
    if brief_src is not None:
        if not brief_src.is_file():
            print(f"smoke_research_fork: brief file not found: {brief_src}", file=sys.stderr)
            return 2
        brief.write_text(brief_src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        brief.write_text(scen.get("brief", BRIEF), encoding="utf-8")

    # materials (D mode): copy into project_dir so the subagent can read it by path
    mat_arg = materials
    if materials not in ("-", None):
        mat_src = Path(materials)
        if not mat_src.is_file():
            print(f"smoke_research_fork: materials file not found: {materials}", file=sys.stderr)
            return 2
        mat_dst = project_dir / mat_src.name
        mat_dst.write_text(mat_src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        mat_arg = str(mat_dst.resolve())

    invocation = DEFAULT_INVOCATION.format(
        work_id=work_id, brief=str(brief.resolve()), scope=scope, materials=mat_arg
    )
    command = build_command(claude, plugin_dir, invocation, budget, args.model, stream=args.stream)

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(project_dir),
    )

    raw = result.stdout.strip()
    payload: dict[str, Any] = {}
    fork_event_types: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type", ""))
        if etype:
            low = etype.lower()
            if "subagent" in low or "fork" in low or "agent" in low:
                fork_event_types.add(etype)
        # subagent_stats lives on the final result event
        if "subagent_stats" in event:
            payload = event
    if not payload:
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict) and "subagent_stats" in candidate:
                payload = candidate
        except json.JSONDecodeError:
            pass

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload or {"raw_stdout": raw, "raw_stderr": result.stderr}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    if not payload:
        print(
            "smoke_research_fork: no JSON result with subagent_stats was returned - the session did not "
            "complete. Raw tail:\n" + (raw or result.stderr)[-800:],
            file=sys.stderr,
        )
        return 2

    mechanism_ok, mechanism_problems, mechanism_notes = mechanism_verdict(payload, fork_event_types)
    mechanism_problems.extend(main_flow_leaked_retrieval(payload))
    if mechanism_problems:
        mechanism_ok = False
    pack = pack_path(project_dir, work_id)
    artifact_ok, artifact_note = artifact_verdict(pack)

    validate_note = ""
    if args.validate and artifact_ok:
        validate_note = run_validator(pack)

    if args.json:
        print(
            json.dumps(
                {
                    **payload,
                    "fork_event_types": sorted(fork_event_types),
                    "mechanism_ok": mechanism_ok,
                    "artifact_ok": artifact_ok,
                    "artifact_note": artifact_note,
                    "validate_note": validate_note,
                    "pack_path": str(pack),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            render(
                mechanism_ok,
                mechanism_problems,
                mechanism_notes,
                artifact_ok,
                artifact_note,
                payload,
                validate_note,
            ),
            end="",
        )

    if not mechanism_ok:
        return 2
    return 0 if artifact_ok else 3


if __name__ == "__main__":
    sys.exit(main())
