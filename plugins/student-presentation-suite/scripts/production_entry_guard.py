#!/usr/bin/env python3
"""Guard direct Bash entrypoints into presentation production internals.

Historically cost_guard learned one forbidden internal script at a time. That
approach is brittle: every new production helper creates another way for an
agent to bypass the state machine until a new regex is added.

This hook owns execution-entry integrity. For ``skills/sp-deck/scripts`` it uses
a small public allow-list and denies every other direct script. It also owns the
few plugin-root production wrappers that must never be used to bypass the
pipeline: evidence-map compilation and direct PPTX generation. Normal project
Bash, other skills, and unrelated plugin-root utilities remain out of scope.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PUBLIC_DECK_ENTRYPOINTS = frozenset(
    {
        "ppt_pipeline.py",
        "calibration_preview.py",
        "visual_reference_select.py",
        "run_gates.sh",
    }
)
BUILDER = "student-presentation-suite:presentation-builder"
PUBLIC_PIPELINE_ACTIONS = frozenset(
    {"plan", "build", "render", "qa", "repair", "complete", "status", "next"}
)
ROOT_PRODUCTION_INTERNALS = frozenset(
    {
        "research_pack_to_evidence.py",
        "run_with_pptxgenjs.js",
    }
)
_DECK_SCRIPT_RE = re.compile(
    r"(?:^|[\\/])skills[\\/]sp-deck[\\/]scripts[\\/]"
    r"(?P<name>[A-Za-z0-9_.-]+\.(?:py|sh))(?=$|[\s\"';&|])",
    re.IGNORECASE,
)
_ROOT_SCRIPT_RE = re.compile(
    r"(?:\$\{CLAUDE_PLUGIN_ROOT\}|student-presentation-suite(?:[\\/][^\\/\s\"']+)?)"
    r"[\\/]scripts[\\/]"
    r"(?P<name>[A-Za-z0-9_.-]+\.(?:py|js|sh))(?=$|[\s\"';&|])",
    re.IGNORECASE,
)
_PIPELINE_ACTION_RE = re.compile(
    r"ppt_pipeline\.py(?:[\"']?)(?:\s+)(?P<action>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_RUN_WITH_INVOCATION_RE = re.compile(
    r"run_with_pptxgenjs\.js[\"']?(?P<args>.*?)(?=(?:&&|\|\||;|\n|\|)|$)",
    re.IGNORECASE,
)
_PROBE_TOKEN_RE = re.compile(r"(?:^|\s)--probe(?=$|\s)", re.IGNORECASE)


def _unique_matches(pattern: re.Pattern[str], command: str) -> list[str]:
    normalized = (command or "").replace("\\", "/")
    found: list[str] = []
    for match in pattern.finditer(normalized):
        name = match.group("name")
        if name not in found:
            found.append(name)
    return found


def direct_deck_scripts(command: str) -> list[str]:
    """Return unique sp-deck script basenames referenced by a shell command."""
    return _unique_matches(_DECK_SCRIPT_RE, command)


def direct_root_scripts(command: str) -> list[str]:
    """Return plugin-root scripts referenced through an actual plugin path."""
    return _unique_matches(_ROOT_SCRIPT_RE, command)


def _all_builder_invocations_are_probe(command: str) -> bool:
    """Allow direct builder access only when every invocation is a runtime probe."""
    matches = list(_RUN_WITH_INVOCATION_RE.finditer(command))
    return bool(matches) and all(_PROBE_TOKEN_RE.search(match.group("args")) for match in matches)


def _builder_allowlist() -> str:
    """Absolute-path discovery surface the isolated builder may actually run.

    Main-session refusals point at `ppt_pipeline.py next`, which the builder is
    forbidden to run; a live builder hit that dead end 14 times in one
    calibration round (2026-09-17) and fell back to hand-written evidence.
    """
    here = Path(__file__).resolve().parents[1]
    parts = []
    helper = here / "scripts" / "pptx-helpers.js"
    select = here / "skills" / "sp-deck" / "scripts" / "visual_reference_select.py"
    if helper.is_file():
        parts.append(f'node "{helper}" --describe')
    if select.is_file():
        parts.append(f'python "{select}" --role <role> --grammar <grammar> --visual-strategy <strategy> --output composition/<id>.json')
    return "; ".join(parts) or "pptx-helpers.js --describe and visual_reference_select.py"


def check_bash(command: str, builder: bool = False) -> str | None:
    normalized = (command or "").replace("\\", "/")

    root_scripts = [name for name in direct_root_scripts(command) if name in ROOT_PRODUCTION_INTERNALS]
    if "research_pack_to_evidence.py" in root_scripts:
        return (
            "Direct evidence-map compilation is refused. Put research-pack.json in the work-dir "
            "and run `ppt_pipeline.py plan --work-dir <wd>`; the pipeline owns evidence-map "
            "compilation and Slide Spec freezing."
        )
    if "run_with_pptxgenjs.js" in root_scripts and not _all_builder_invocations_are_probe(normalized):
        return (
            "Direct run_with_pptxgenjs.js generation is refused. The pipeline owns build, "
            "normalization and QA binding; run `ppt_pipeline.py next --work-dir <wd> --json` "
            "and invoke the stable command it returns. `--probe` remains allowed for runtime checks."
        )

    scripts = direct_deck_scripts(command)
    if not scripts:
        return None
    blocked = [name for name in scripts if name not in PUBLIC_DECK_ENTRYPOINTS]
    if blocked:
        names = ", ".join(blocked)
        if builder:
            return (
                "Direct execution of internal sp-deck production scripts is refused for the "
                f"isolated builder: {names}. Allowed discovery/composition surface: "
                f"{_builder_allowlist()}. Everything else is run by the MAIN session "
                "after you return."
            )
        return (
            "Direct execution of internal sp-deck production scripts is refused: "
            f"{names}. Use ppt_pipeline.py next --work-dir <wd> --json and invoke only "
            "the stable entrypoint it returns. Internal validators/render/build helpers "
            "must be reached through ppt_pipeline.py or run_gates.sh."
        )
    if "ppt_pipeline.py" in scripts:
        match = _PIPELINE_ACTION_RE.search(normalized)
        if not match or match.group("action") not in PUBLIC_PIPELINE_ACTIONS:
            return (
                "ppt_pipeline.py direct Bash is limited to the stable actions: "
                + ", ".join(sorted(PUBLIC_PIPELINE_ACTIONS))
                + ". Use `ppt_pipeline.py next --work-dir <wd> --json` instead of probing internals."
            )
    return None


def handle(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") not in {None, "PreToolUse"}:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    builder = str(event.get("agent_type") or "") == BUILDER
    refusal = check_bash(command, builder=builder)
    if refusal:
        print(f"production_entry_guard: {refusal}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    return handle(event)


if __name__ == "__main__":
    raise SystemExit(main())
