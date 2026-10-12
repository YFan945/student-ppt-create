#!/usr/bin/env python3
"""Research-only hooks; main-session page authoring has no agent guards."""
import sys

import pipeline_context
import runtime_evidence
from hook_events import read_event


def dispatch(event: dict) -> int:
    if event.get("agent_type") in {
        "student-presentation-suite:presentation-builder",
        "student-presentation-suite:visual-critic",
    }:
        return 0
    inputs = event.get("tool_input") or {}
    if event.get("tool_name") in {"Bash", "PowerShell"} and pipeline_context.is_pipeline_invocation(inputs.get("command", "")):
        return 0
    if event.get("tool_name") == "Skill" and str(inputs.get("skill", "")).split(":")[-1] != "sp-research":
        return 0
    return runtime_evidence.handle(event)


if __name__ == "__main__":
    sys.exit(dispatch(read_event()))
