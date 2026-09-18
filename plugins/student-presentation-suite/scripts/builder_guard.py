#!/usr/bin/env python3
"""Enforce the presentation-builder context boundary.

Policy lives in `references/agent-behavior-contract.json` (single canonical
machine source); this hook only enforces it. Refusal texts stay short: name the
contract anchor, hand back the runnable redirect command, and stop — the guard
must not grow a second natural-language policy that drifts from the contract.

Three boundaries, one owner:

1. **Page modules.** The deterministic pipeline scaffolds pages through subprocesses, so
   this hook only controls model tool access. Main-session Read/Edit/Write of `pages/*.js`
   would put page source and repair diffs back into the expensive parent context; only the
   isolated presentation-builder may use those model tools on page modules.

2. **Inline JSON extraction.** The builder used to hand-roll extraction scripts over the
   work directory (19-46 per repair round in 2026-09-17, then 111 heredocs in 2026-09-18).
   `page_brief.py` answers the same questions in one call, so the inline form is refused
   and redirected. The refusal keys on *what the script touches* (work-dir JSON/YAML, page
   modules) rather than on one interpreter and one spelling.

3. **Render ownership.** `calibration_preview.py` and every render are MAIN-session steps
   (`render_allowed: false` in the contract). The isolated builder calling them re-renders
   inside its own context and pulls fresh PNGs back in — one instance grew 8.7K → 699K
   resident that way (2026-09-18). It returns `BUILDER_DONE`; the main session renders
   and hands back the report.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

BUILDER = "student-presentation-suite:presentation-builder"
SHELL_TOOLS = {"Bash", "PowerShell"}
# Any interpreter that can take a program on the command line.
INTERPRETER = re.compile(
    r"(?<![\w.-])(?:python[0-9.]*|py|node|nodejs|perl|ruby|php|pwsh|powershell)(?:\.exe)?(?=\s|$)",
    re.I,
)
INLINE_EVAL = re.compile(r"(?<![\w-])-(?:c|e|command)\b", re.I)
HEREDOC = re.compile(r"<<\s*['\"]?[A-Za-z_][A-Za-z0-9_]*")
STDIN_PROGRAM = re.compile(r"(?<![\w-])-\s*(?:<<|$|[\r\n])")
# Work-dir artifacts the projection tool (or a plain Edit) is meant to replace digging by hand.
WORK_ARTIFACT = re.compile(
    r"\b(?:qa-[a-z0-9-]+|pipeline-qa|gates-report|build-manifest|gate-history|evidence-map|"
    r"research-pack|research-pack-validation|calibration-manifest|art-direction-check|"
    r"copy-fit-preflight|visual-review|visual-generation-report|page-copy-fidelity|"
    r"slide-spec-report|slide-spec-compiled|slide-spec-lock|page-brief|stage-[\w-]*summary|"
    r"critic-execution|references-slide)\b",
    re.I,
)
ARTIFACT_FILE = re.compile(r"[\w./\\-]+\.(?:json|ya?ml)\b", re.I)
PAGE_MODULE_REF = re.compile(r"pages[/\\][\w.-]*\.js\b|pages[/\\]p\w", re.I)
# Renders and builds belong to the main session, never to the isolated builder.
RENDER_OWNED = re.compile(
    r"calibration_preview\.py|pptx_tool\.py['\"]?\s+render|ppt_pipeline\.py['\"]?\s+render|"
    r"\bsoffice\b|\blibreoffice\b",
    re.I,
)


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


def _record_instance(project: Path, agent_id: str, work_id: str) -> None:
    """Record which work-dir this builder INSTANCE touched, and when.

    One builder instance serving several repair rounds is the single largest cost driver
    measured so far: a never-reset instance reached 699K resident context, and at that size
    three trivial requests cost 2.1M tokens. The pipeline can only see rounds; the hook is
    the only place that sees instance identity, so it writes the window down and
    `ppt_pipeline.py` cross-references the two.
    """
    store = project / "outputs" / ".pptx-work" / ".guard"
    try:
        store.mkdir(parents=True, exist_ok=True)
        key = re.sub(r"[^A-Za-z0-9_-]", "_", str(agent_id))[:60]
        path = store / f"builder-{key}.json"
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        stamp = datetime.now(UTC).isoformat()
        work_ids = data.get("work_ids") or []
        if work_id and work_id not in work_ids:
            work_ids.append(work_id)
        path.write_text(
            json.dumps(
                {
                    "agent_id": str(agent_id),
                    "first_write_at": data.get("first_write_at") or stamp,
                    "last_write_at": stamp,
                    "writes": int(data.get("writes") or 0) + 1,
                    "work_ids": work_ids,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Guard bookkeeping must never take the builder's work down with it.
        pass


def _runs_inline_program(command: str) -> bool:
    if not INTERPRETER.search(command):
        return False
    if INLINE_EVAL.search(command) or HEREDOC.search(command):
        return True
    # `python -` / `python - <<'PY'` reads the program from stdin.
    return bool(STDIN_PROGRAM.search(command))


def _touches_work_artifacts(command: str) -> bool:
    if PAGE_MODULE_REF.search(command):
        return True
    return bool(WORK_ARTIFACT.search(command) and ARTIFACT_FILE.search(command))


def contract_ref() -> str:
    """Absolute path of the behavior contract, for refusal anchors."""
    return str(plugin_root() / "references" / "agent-behavior-contract.json")


def page_brief_hint() -> str:
    """Runnable projection commands, one per mode (contract: page_brief_strategy)."""
    brief = plugin_root() / "skills" / "sp-deck" / "scripts" / "page_brief.py"
    return (
        f'  python "{brief}" --work-dir <absolute work-dir> --json'
        "   (initial: whole deck in one call)\n"
        f'  python "{brief}" --work-dir <absolute work-dir> --slides <ids> --json'
        "   (calibration/repair: target pages in one call)"
    )


def handle(event: dict) -> int:
    if event.get("hook_event_name") != "PreToolUse":
        return 0
    tool = str(event.get("tool_name") or "")
    inputs = event.get("tool_input") or {}

    if tool in SHELL_TOOLS:
        # Only the isolated builder is pushed here; the main session may legitimately use
        # inline scripts and run renders for other work.
        if event.get("agent_type") != BUILDER or not event.get("agent_id"):
            return 0
        command = str(inputs.get("command") or "")

        if RENDER_OWNED.search(command):
            print(
                "builder_guard: refused — render/build/calibration_preview is forbidden for the "
                "isolated builder "
                f"({contract_ref()}#presentation_builder.render_allowed = false); "
                "the MAIN session owns it. Running it here re-renders inside your own context "
                "and every later request in this instance pays that context again.\n"
                "Return BUILDER_DONE with the pages you edited; the main session renders and "
                "hands you the report path.",
                file=sys.stderr,
            )
            return 2

        if not (_runs_inline_program(command) and _touches_work_artifacts(command)):
            return 0
        print(
            "builder_guard: refused — reading work-dir JSON/YAML, or rewriting page modules, "
            "with an inline script is forbidden "
            f"({contract_ref()}#presentation_builder.inline_script_over_work_artifacts = false). "
            "Use the projection tool (one call per round, never once per page) and plain edits:\n"
            f"{page_brief_hint()}\n"
            "One call returns the verbatim claims, planned numbers, blockers and cited sources "
            "for the pages in scope. Edit page modules with the Edit tool, not with a regex in "
            "a shell heredoc.",
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
        try:
            rel = path.resolve().relative_to(project / "outputs" / ".pptx-work")
            _record_instance(project, str(event["agent_id"]), rel.parts[0] if rel.parts else "")
        except (OSError, ValueError):
            pass
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
