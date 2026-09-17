#!/usr/bin/env python3
"""Record successful child tool events; never accept model-declared spawn proof.

This is an execution-integrity gate inside a trusted local Claude session, not a
sandbox against a user/process able to rewrite the hook and its evidence files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

RESEARCHER = "student-presentation-suite:presentation-researcher"
CRITIC = "student-presentation-suite:visual-critic"
PIPELINE_SKILLS = {"sp-research", "sp-deck", "sp-outline"}
NAMED_SPAWN_REFUSAL = (
    "Pipeline evidence agents must not be spawned with a `name`: named Agent "
    "calls become teammates whose agent_type is the name, so SubagentStop "
    "never issues execution receipts. Retry THIS SAME call from the MAIN "
    "session with subagent_type only — foreground, no `name`. Do NOT spawn a "
    "second nested agent to 'fix' the refusal (2026-09-16: outer teammate "
    "burned 0.86M tokens and ran 0 searches)."
)
NESTED_SPAWN_REFUSAL = (
    "Do not nest presentation-researcher or visual-critic inside another "
    "agent. Only the main session may spawn them, once, foreground, without "
    "`name`. If you are a teammate whose WebSearch was blocked, stop — the "
    "main session must respawn the plugin agent correctly."
)
WEB_REFUSAL = "External research must run in the isolated presentation-researcher."


@contextmanager
def event_lock(event: dict):
    """Serialize parallel image Read hooks for the same child (no lost hashes)."""
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id")) + "-" + str(event.get("agent_id")))
    path = project / "outputs/.pptx-work/.guard" / f"lock-{key}"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError("runtime evidence lock unavailable; retry the isolated agent") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            # Windows can keep the exclusive handle visible for a beat after close.
            pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def handle(event: dict) -> int:
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()
    root = project / "outputs" / ".pptx-work"
    agent = event.get("agent_type")
    child = event.get("agent_id")
    kind = event.get("hook_event_name")
    tool = event.get("tool_name")
    inputs = event.get("tool_input") or {}
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id") or "unknown"))
    active = root / ".guard" / f"research-active-{session}.json"
    if kind == "PreToolUse":
        if tool in {"Write", "Edit"}:
            path = Path(inputs.get("file_path") or "").resolve()
            if path.is_relative_to(root) and (path.name in {"research-execution.json", "critic-execution.json"} or path.is_relative_to(root / ".guard")):
                print("Runtime receipts and event ledgers are hook-owned; models cannot write them.", file=sys.stderr)
                return 2
        skill = str(inputs.get("skill") or "").split(":")[-1]
        if tool == "Skill" and skill in PIPELINE_SKILLS:
            active.parent.mkdir(parents=True, exist_ok=True)
            active.write_text(json.dumps({"session_id": event.get("session_id")}), encoding="utf-8")
        if tool == "Agent" and inputs.get("subagent_type") in {RESEARCHER, CRITIC}:
            if inputs.get("name"):
                print(NAMED_SPAWN_REFUSAL, file=sys.stderr)
                return 2
            if child:
                print(NESTED_SPAWN_REFUSAL, file=sys.stderr)
                return 2
            if inputs.get("run_in_background"):
                print("Pipeline evidence agents must run in the foreground.", file=sys.stderr)
                return 2
            if inputs.get("subagent_type") == RESEARCHER:
                active.parent.mkdir(parents=True, exist_ok=True)
                active.write_text(json.dumps({"session_id": event.get("session_id")}), encoding="utf-8")
        if tool in {"WebSearch", "WebFetch"}:
            isolated = agent == RESEARCHER and bool(child)
            if not isolated and (active.is_file() or child):
                print(WEB_REFUSAL, file=sys.stderr)
                return 2
        if agent == CRITIC and tool in {"Write", "Edit"}:
            path = Path(inputs.get("file_path") or "").resolve()
            if path.parent.parent != root or path.name != "visual-review.json":
                print("visual-critic may only write its work-dir/visual-review.json", file=sys.stderr)
                return 2
        return 0
    if agent not in {RESEARCHER, CRITIC} or not child:
        return 0
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id")) + "-" + str(child))
    ledger = root / ".guard" / f"agent-{key}.json"
    data = read_json(ledger)
    if kind == "SubagentStart":
        data = {"agent": agent, "agent_id": child, "session_id": event.get("session_id"), "reads": {}, "writes": {}}
    elif not data or data.get("agent") != agent:
        return 0
    elif kind == "PostToolUse" and tool in {"Read", "Write", "Edit"}:
        path = Path(inputs.get("file_path") or "").resolve()
        if path.is_file() and path.is_relative_to(root):
            data["reads" if tool == "Read" else "writes"][str(path)] = digest(path)
    elif kind == "SubagentStop":
        artifact_name = "research-pack.json" if agent == RESEARCHER else "visual-review.json"
        for name, sha in data["writes"].items():
            artifact = Path(name)
            if artifact.name != artifact_name or artifact.parent.parent != root:
                continue
            if not artifact.is_file() or digest(artifact) != sha:
                continue
            receipt = {**data, "spawn_verified": True, "artifact": {"path": name, "sha256": sha}, "work_id": artifact.parent.name}
            target = artifact.parent / ("research-execution.json" if agent == RESEARCHER else "critic-execution.json")
            target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    event = json.loads(sys.stdin.read())
    if event.get("agent_type") in {RESEARCHER, CRITIC} and event.get("hook_event_name") != "PreToolUse":
        with event_lock(event):
            code = handle(event)
    else:
        code = handle(event)
    raise SystemExit(code)
