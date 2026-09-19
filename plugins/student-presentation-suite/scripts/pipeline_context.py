#!/usr/bin/env python3
"""Shared PPT-pipeline scope resolution for the plugin's PreToolUse guards.

Batch 6.1 — Hook Scope Isolation. The guards used to decide "is this a PPT
production call?" implicitly and inconsistently: cost_guard applied PPT cost
discipline to every session in every repository, and runtime_evidence refused
WebSearch/WebFetch for *any* subagent, plugin-owned or not. This module owns
that decision in one place, on deterministic signals only:

- **Agent identity** comes from the hook event itself (`agent_type` names a
  plugin subagent, `agent_id` marks any child context);
- **Task activation** comes from state the plugin itself writes
  (`research-active-<session>.json`, armed by Skill/Agent events, cleared at
  Stop — with a TTL so a crashed session cannot stay armed forever);
- **Resource scope** comes from the path shape: `outputs/.pptx-work/...`.

Natural-language intent ("the user mentioned PPT") is deliberately NOT a
signal: "check the PPT plugin's code" is plugin maintenance, not production.
`session_id` separates concurrent tasks, the work-dir path separates parallel
decks, and `agent_id`/`agent_type` separate builder authority — each has one
job and none substitutes for another.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

PLUGIN_PREFIX = "student-presentation-suite:"
RESEARCHER = PLUGIN_PREFIX + "presentation-researcher"
BUILDER = PLUGIN_PREFIX + "presentation-builder"
CRITIC = PLUGIN_PREFIX + "visual-critic"

# Skills whose activation puts a session into managed production scope.
PIPELINE_SKILLS = {"sp-research", "sp-deck", "sp-outline"}

PLUGIN_ROLES = frozenset({"researcher", "builder", "critic", "plugin-agent"})

# A crash (or a runtime that never delivers Stop) must not leave research
# scope armed for the rest of a session's life. Generous by design: research
# phases run hours, false "inactive" would defeat the isolation.
RESEARCH_ACTIVE_TTL_SECONDS = 6 * 3600

_WORK_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def project_root(event: dict) -> Path:
    return Path(
        os.environ.get("CLAUDE_PROJECT_DIR")
        or str(event.get("cwd") or "")
        or Path.cwd()
    ).resolve()


def agent_role(event: dict) -> str:
    """One of researcher / builder / critic / plugin-agent / subagent / main."""
    agent = str(event.get("agent_type") or "")
    if agent == RESEARCHER:
        return "researcher"
    if agent == BUILDER:
        return "builder"
    if agent == CRITIC:
        return "critic"
    if agent.startswith(PLUGIN_PREFIX):
        return "plugin-agent"
    if event.get("agent_id"):
        return "subagent"
    return "main"


def is_child(event: dict) -> bool:
    return bool(event.get("agent_id"))


def session_id(event: dict) -> str:
    return _WORK_ID_SAFE.sub("_", str(event.get("session_id") or "unknown"))


def is_ppt_resource(text: str) -> bool:
    """True when a command/path text targets the pipeline's work areas."""
    return ".pptx-work" in str(text or "")


def is_ppt_resource_path(path: Path) -> bool:
    """True when a resolved path lives anywhere under a `.pptx-work` root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(part == ".pptx-work" for part in resolved.parts)


def guard_dir(project: Path) -> Path:
    return project / "outputs" / ".pptx-work" / ".guard"


def research_active_path(project: Path, session: str) -> Path:
    return guard_dir(project) / f"research-active-{_WORK_ID_SAFE.sub('_', str(session or 'unknown'))}.json"


def mark_research_active(project: Path, event: dict) -> None:
    """Arm research scope for this session (runtime_evidence owns the triggers)."""
    path = research_active_path(project, session_id(event))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session_id": event.get("session_id"),
                "created_at": time.time(),
            }
        ),
        encoding="utf-8",
    )


def clear_research_active(project: Path, event: dict) -> None:
    with suppress(OSError):
        research_active_path(project, session_id(event)).unlink(missing_ok=True)


def research_active(project: Path, event: dict, *, now: float | None = None) -> bool:
    """Managed research scope is armed AND fresh; stale state self-clears.

    Stop is only the cleanup fallback: a session killed without a Stop event
    expires here instead of blocking WebSearch for the rest of its life.
    """
    path = research_active_path(project, session_id(event))
    if not path.is_file():
        return False
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    if age > RESEARCH_ACTIVE_TTL_SECONDS or age < -5:
        clear_research_active(project, event)
        return False
    return True


@dataclass(frozen=True)
class PipelineContext:
    """Resolved scope of one hook event.

    `managed` means the call happens inside a recognized PPT production task:
    a plugin subagent, or a main session with fresh research/production scope
    armed. Everything else is an ordinary session and must not be constrained
    by PPT-only rules.
    """

    role: str
    child: bool
    managed: bool
    project: Path
    session: str


def resolve(event: dict) -> PipelineContext:
    project = project_root(event)
    role = agent_role(event)
    child = is_child(event)
    session = session_id(event)
    managed = role in PLUGIN_ROLES or (role == "main" and research_active(project, event))
    return PipelineContext(role=role, child=child, managed=managed, project=project, session=session)
