#!/usr/bin/env python3
"""Enforce the presentation-builder context boundary.

Two boundaries, one owner:

1. **Page modules.** The deterministic pipeline scaffolds pages through subprocesses, so
   this hook only controls model tool access. Main-session Read/Edit/Write of `pages/*.js`
   would put page source and repair diffs back into the expensive parent context; only the
   isolated presentation-builder may use those model tools on page modules.

2. **Inline JSON extraction.** The builder used to answer "what does this page need and
   what is failing on it" by hand-rolling scripts over the work directory —

       node -e "const q=require('./qa-quality.json'); const s=JSON.stringify(q);
                const idx=s.indexOf('missing_final_reference'); ..."

   — 19 to 46 of them per repair round in the 2026-09-17 live session, each one a full
   context round-trip at ~150K resident context. `page_brief.py` answers the same questions
   in one call, so the inline form is refused and redirected rather than merely discouraged.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BUILDER = "student-presentation-suite:presentation-builder"
SHELL_TOOLS = {"Bash", "PowerShell"}
INLINE_NODE_EVAL = re.compile(r"\bnode(?:\.exe)?\s+(?:-e|--eval)\b", re.I)
JSON_ACCESS = re.compile(r"require\s*\(|\.json\b", re.I)


def plugin_root() -> Path:
    """Installed plugin root: this hook always lives at <root>/scripts/.

    Refusal text carries a resolved absolute path rather than `${CLAUDE_PLUGIN_ROOT}`:
    which environment a subagent's shell inherits is not ours to assume, and a
    mandatory command that does not expand is the same dead end as a blocked one.
    """
    return Path(__file__).resolve().parents[1]


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
    inputs = event.get("tool_input") or {}

    if tool in SHELL_TOOLS:
        # Only the isolated builder is pushed here; the main session may legitimately use
        # inline node for other work.
        if event.get("agent_type") != BUILDER or not event.get("agent_id"):
            return 0
        command = str(inputs.get("command") or "")
        if not (INLINE_NODE_EVAL.search(command) and JSON_ACCESS.search(command)):
            return 0
        print(
            "builder_guard: reading work-dir JSON with inline node costs one full context "
            "round-trip per field (2026-09-17: 19-46 of them per repair round, plus 11 "
            "re-reads of the Slide Spec). Use the projection tool instead:\n"
            f'  python "{plugin_root() / "skills" / "sp-deck" / "scripts" / "page_brief.py"}" '
            "--work-dir <absolute work-dir> --slide <N> --json\n"
            "One call returns that page's verbatim claim, planned numbers, blockers and "
            "cited sources.",
            file=sys.stderr,
        )
        return 2

    if tool not in {"Read", "Write", "Edit"}:
        return 0
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
