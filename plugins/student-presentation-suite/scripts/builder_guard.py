#!/usr/bin/env python3
"""Enforce the presentation-builder context boundary for generated page modules.

The deterministic pipeline scaffolds pages through subprocesses, so this hook only
controls model tool access. Main-session Read/Edit/Write of pages/*.js would put
page source and repair diffs back into the expensive parent context; only the
isolated presentation-builder may use those model tools on page modules.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BUILDER = "student-presentation-suite:presentation-builder"


def _project(event: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()


def _is_page_module(path: Path, project: Path) -> bool:
    root = project / "outputs" / ".pptx-work"
    try:
        rel = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    # <work-id>/pages/pNN-*.js; hidden .guard and other work artifacts are not covered.
    return len(rel.parts) >= 3 and rel.parts[1] == "pages" and path.suffix.lower() == ".js"


def handle(event: dict) -> int:
    if event.get("hook_event_name") != "PreToolUse":
        return 0
    tool = str(event.get("tool_name") or "")
    if tool not in {"Read", "Write", "Edit"}:
        return 0
    inputs = event.get("tool_input") or {}
    raw = str(inputs.get("file_path") or inputs.get("path") or "").strip()
    if not raw:
        return 0
    project = _project(event)
    path = Path(raw)
    if not path.is_absolute():
        path = Path(event.get("cwd") or project) / path
    if not _is_page_module(path, project):
        return 0
    if event.get("agent_type") == BUILDER and event.get("agent_id"):
        return 0
    print(
        "builder_guard: pages/*.js belongs to the isolated presentation-builder. "
        "From the MAIN session spawn student-presentation-suite:presentation-builder "
        "without `name`, and pass the absolute work-dir plus initial/repair mode. "
        "Do not Read, Edit, or Write page modules in the parent context.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        raise SystemExit(0)
    raise SystemExit(handle(event if isinstance(event, dict) else {}))
