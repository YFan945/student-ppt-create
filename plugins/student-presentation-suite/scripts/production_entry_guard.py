#!/usr/bin/env python3
"""Allow-list direct Bash entrypoints into the sp-deck production runtime.

Historically cost_guard learned one forbidden internal script at a time. That
approach is brittle: every new internal validator/helper creates another way for
an agent to bypass the state machine until a new regex is added.

This hook flips the rule for ``skills/sp-deck/scripts``: direct Agent Bash may
invoke only the small public surface declared here. Every other script in that
directory is pipeline-internal and must be reached through ``ppt_pipeline.py``
or ``run_gates.sh``. Normal project Bash and scripts belonging to other skills
are intentionally out of scope.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

PUBLIC_DECK_ENTRYPOINTS = frozenset(
    {
        "ppt_pipeline.py",
        "calibration_preview.py",
        "visual_reference_select.py",
        "run_gates.sh",
    }
)
PUBLIC_PIPELINE_ACTIONS = frozenset(
    {"plan", "build", "render", "qa", "repair", "complete", "status", "next"}
)
_DECK_SCRIPT_RE = re.compile(
    r"(?:^|[\\/])skills[\\/]sp-deck[\\/]scripts[\\/]"
    r"(?P<name>[A-Za-z0-9_.-]+\.(?:py|sh))(?=$|[\s\"';&|])",
    re.IGNORECASE,
)
_PIPELINE_ACTION_RE = re.compile(
    r"ppt_pipeline\.py(?:[\"']?)(?:\s+)(?P<action>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def direct_deck_scripts(command: str) -> list[str]:
    """Return unique sp-deck script basenames referenced by a shell command."""
    normalized = (command or "").replace("\\", "/")
    found: list[str] = []
    for match in _DECK_SCRIPT_RE.finditer(normalized):
        name = match.group("name")
        if name not in found:
            found.append(name)
    return found


def check_bash(command: str) -> str | None:
    scripts = direct_deck_scripts(command)
    if not scripts:
        return None
    blocked = [name for name in scripts if name not in PUBLIC_DECK_ENTRYPOINTS]
    if blocked:
        names = ", ".join(blocked)
        return (
            "Direct execution of internal sp-deck production scripts is refused: "
            f"{names}. Use ppt_pipeline.py next --work-dir <wd> --json and invoke only "
            "the stable entrypoint it returns. Internal validators/render/build helpers "
            "must be reached through ppt_pipeline.py or run_gates.sh."
        )
    if "ppt_pipeline.py" in scripts:
        match = _PIPELINE_ACTION_RE.search((command or "").replace("\\", "/"))
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
    refusal = check_bash(command)
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
