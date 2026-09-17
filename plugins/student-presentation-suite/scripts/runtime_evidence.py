#!/usr/bin/env python3
"""Record successful child tool events; never accept model-declared spawn proof.

This is an execution-integrity gate inside a trusted local Claude session, not a
sandbox against a user/process able to rewrite the hook and its evidence files.

Receipt artifacts (research-pack.json / visual-review.json) are credited through
hash snapshots taken at SubagentStart and refreshed after every child tool call,
so script writes (e.g. ``python json.dump``) count the same as Write-tool writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import critic_preview  # noqa: E402

RESEARCHER = "student-presentation-suite:presentation-researcher"
CRITIC = "student-presentation-suite:visual-critic"
PIPELINE_SKILLS = {"sp-research", "sp-deck", "sp-outline"}
LOCK_STALE_SECONDS = 30.0
EVIDENCE_NAME_RE = re.compile(r"research|critic", re.I)
NAMED_TEAMMATE_REFUSAL = (
    "Do not create or message named researcher/critic teammates. Evidence work must use "
    "the isolated presentation-researcher or visual-critic subagent directly from the MAIN "
    "session, without `name`."
)
NAMED_SPAWN_REFUSAL = (
    "Pipeline evidence agents must not be spawned with a `name`: named Agent "
    "calls become teammates whose agent_type is the name, so SubagentStop "
    "never issues execution receipts. Retry THIS SAME call from the MAIN "
    "session with subagent_type only — no `name`. Do NOT spawn a "
    "second nested agent to 'fix' the refusal (2026-09-16: outer teammate "
    "burned 0.86M tokens and ran 0 searches)."
)
NESTED_SPAWN_REFUSAL = (
    "Do not nest presentation-researcher or visual-critic inside another "
    "agent. Only the main session may spawn them, once, without "
    "`name`. If you are a teammate whose WebSearch was blocked, stop — the "
    "main session must respawn the plugin agent correctly."
)
WEB_REFUSAL = "External research must run in the isolated presentation-researcher."
CRITIC_WORKDIR_REFUSAL = (
    "visual-critic spawn must include the absolute outputs/.pptx-work/<work-id> path "
    "in its prompt so the hook can materialize hash-bound compressed previews."
)


def _lock_is_stale(path: Path) -> bool:
    """A hook lock should live for milliseconds; recover files left by dead hooks."""
    try:
        return time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


def _wait_for_lock(path: Path, deadline: float) -> None:
    """Back off after a legitimate lock collision, recovering abandoned locks."""
    if _lock_is_stale(path):
        with suppress(OSError):
            path.unlink()
        return
    if time.monotonic() >= deadline:
        raise RuntimeError("runtime evidence lock unavailable; retry the isolated agent") from None
    time.sleep(0.02)


@contextmanager
def event_lock(event: dict):
    """Serialize parallel child hook events and recover abandoned lock files."""
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id")) + "-" + str(event.get("agent_id")))
    path = project / "outputs/.pptx-work/.guard" / f"lock-{key}"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(
                descriptor,
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": time.time(),
                        "session_id": event.get("session_id"),
                        "agent_id": event.get("agent_id"),
                    }
                ).encode("utf-8"),
            )
            break
        except FileExistsError:
            _wait_for_lock(path, deadline)
            continue
        except PermissionError:
            if not path.exists():
                raise
            _wait_for_lock(path, deadline)
            continue
    try:
        yield
    finally:
        os.close(descriptor)
        with suppress(PermissionError):
            path.unlink(missing_ok=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


RECEIPT_ARTIFACTS = ("research-pack.json", "visual-review.json")


def artifact_snapshot(root: Path) -> dict[str, str]:
    """Hash receipt artifacts across work dirs (a few small JSON files)."""
    snap: dict[str, str] = {}
    if not root.is_dir():
        return snap
    for name in RECEIPT_ARTIFACTS:
        for path in root.glob(f"*/{name}"):
            try:
                snap[str(path)] = digest(path)
            except OSError:
                continue
    return snap


def record_artifact_changes(data: dict, root: Path) -> None:
    """Credit receipt-artifact writes made by any mechanism, not just Write.

    2026-09-17: the researcher created research-pack.json with Write but made
    every later edit via `python json.dump`; the Write-tool-only receipt stayed
    empty and `plan` refused a healthy pack. Snapshot diffs make the receipt
    command-agnostic: any change between this agent's tool calls counts as a
    write, while artifacts that already exist at SubagentStart are baselined
    and never re-credited to the agent.
    """
    current = artifact_snapshot(root)
    previous = data.get("snap")
    if previous is None:
        data["snap"] = current
        return
    for path_str, sha in current.items():
        if previous.get(path_str) != sha:
            data.setdefault("writes", {})[path_str] = sha
    data["snap"] = current


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _critic_work_dir(inputs: dict, root: Path) -> Path | None:
    """Find exactly one absolute work-dir explicitly passed in the Agent input."""
    if not root.is_dir():
        return None
    text = "\n".join(_strings(inputs))
    normalized = text.replace("\\", "/")
    matches: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        absolute = str(child.resolve())
        if absolute in text or absolute.replace("\\", "/") in normalized:
            matches.append(child.resolve())
    return matches[0] if len(matches) == 1 else None


def _hook_owned_preview_path(path: Path, root: Path) -> bool:
    if not path.is_relative_to(root):
        return False
    if path.name == critic_preview.MAP_NAME:
        return True
    return critic_preview.PREVIEW_DIR_NAME in path.parts


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

    if kind == "Stop" and not child:
        with suppress(OSError):
            active.unlink(missing_ok=True)
        return 0

    if kind == "PreToolUse":
        if tool in {"Write", "Edit"}:
            path = Path(inputs.get("file_path") or "").resolve()
            if path.is_relative_to(root) and (
                path.name in {"research-execution.json", "critic-execution.json"}
                or path.is_relative_to(root / ".guard")
                or _hook_owned_preview_path(path, root)
            ):
                print(
                    "Runtime receipts, critic previews and event ledgers are hook-owned; models cannot write them.",
                    file=sys.stderr,
                )
                return 2
        skill = str(inputs.get("skill") or "").split(":")[-1]
        if tool == "Skill" and skill in PIPELINE_SKILLS:
            active.parent.mkdir(parents=True, exist_ok=True)
            active.write_text(json.dumps({"session_id": event.get("session_id")}), encoding="utf-8")
        if tool in {"Agent", "SendMessage"}:
            name = str(inputs.get("name") or "").strip()
            dest = str(inputs.get("to") or inputs.get("recipient") or "").strip()
            if EVIDENCE_NAME_RE.search(f"{name} {dest}"):
                print(NAMED_TEAMMATE_REFUSAL, file=sys.stderr)
                return 2
        if tool == "Agent" and inputs.get("subagent_type") in {RESEARCHER, CRITIC}:
            if inputs.get("name"):
                print(NAMED_SPAWN_REFUSAL, file=sys.stderr)
                return 2
            if child:
                print(NESTED_SPAWN_REFUSAL, file=sys.stderr)
                return 2
            if inputs.get("subagent_type") == RESEARCHER:
                active.parent.mkdir(parents=True, exist_ok=True)
                active.write_text(json.dumps({"session_id": event.get("session_id")}), encoding="utf-8")
            else:
                work_dir = _critic_work_dir(inputs, root)
                if work_dir is None:
                    print(CRITIC_WORKDIR_REFUSAL, file=sys.stderr)
                    return 2
                try:
                    critic_preview.materialize(work_dir)
                except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                    print(f"visual-critic preview preparation failed: {exc}", file=sys.stderr)
                    return 2
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
        data = {
            "agent": agent,
            "agent_id": child,
            "session_id": event.get("session_id"),
            "reads": {},
            "writes": {},
            "snap": artifact_snapshot(root),
        }
    elif not data or data.get("agent") != agent:
        return 0
    elif kind == "PostToolUse" and tool in {"Read", "Write", "Edit"}:
        path = Path(inputs.get("file_path") or "").resolve()
        if path.is_file() and path.is_relative_to(root):
            target = data["reads" if tool == "Read" else "writes"]
            target[str(path)] = digest(path)
            if agent == CRITIC and tool == "Read" and path.parent.name == critic_preview.PREVIEW_DIR_NAME:
                source = critic_preview.source_binding_for_preview(path.parent.parent, path)
                if source is not None:
                    source_path, source_sha = source
                    data["reads"][source_path] = source_sha
        record_artifact_changes(data, root)
    elif kind == "PostToolUse" and tool in {"Bash", "PowerShell"}:
        record_artifact_changes(data, root)
    elif kind == "SubagentStop":
        artifact_name = "research-pack.json" if agent == RESEARCHER else "visual-review.json"
        for name, sha in data["writes"].items():
            artifact = Path(name)
            if artifact.name != artifact_name or artifact.parent.parent != root:
                continue
            if not artifact.is_file() or digest(artifact) != sha:
                continue
            receipt = {
                **data,
                "spawn_verified": True,
                "artifact": {"path": name, "sha256": sha},
                "work_id": artifact.parent.name,
            }
            target = artifact.parent / (
                "research-execution.json" if agent == RESEARCHER else "critic-execution.json"
            )
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
