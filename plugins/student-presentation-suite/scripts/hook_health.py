#!/usr/bin/env python3
"""Arm and verify a one-shot PreToolUse health receipt for pipeline plan.

The receipt is intentionally short-lived and bound to one work-dir. It proves
that Claude Code actually executed this plugin's PreToolUse hook immediately
before `ppt_pipeline.py plan`. If hooks are not loaded, no receipt exists and
the pipeline bootstrap refuses before production work starts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

RECEIPT_VERSION = 1
HEALTH_TTL_SECONDS = 30.0
_WORK_DIR_RE = re.compile(
    r"(?:^|\s)--work-dir(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))"
)


def _project_root(event: dict[str, Any] | None = None) -> Path:
    event = event or {}
    return Path(
        os.environ.get("CLAUDE_PROJECT_DIR")
        or str(event.get("cwd") or "")
        or Path.cwd()
    ).resolve()


def _expand_path(value: str, *, base: Path | None = None) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(value))
    # Also support the common Windows %NAME% form if a Bash command contains it.
    expanded = re.sub(
        r"%([A-Za-z_][A-Za-z0-9_]*)%",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    path = Path(expanded)
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return path.resolve()


def extract_work_dir(command: str, *, base: Path | None = None) -> Path | None:
    match = _WORK_DIR_RE.search(command or "")
    if not match:
        return None
    raw = next((group for group in match.groups() if group is not None), "")
    return _expand_path(raw, base=base) if raw else None


def work_dir_from_argv(argv: list[str], *, base: Path | None = None) -> Path | None:
    for index, token in enumerate(argv):
        if token == "--work-dir" and index + 1 < len(argv):
            return _expand_path(argv[index + 1], base=base)
        if token.startswith("--work-dir="):
            return _expand_path(token.split("=", 1)[1], base=base)
    return None


def receipt_path(project: Path, work_dir: Path) -> Path:
    key = hashlib.sha256(str(work_dir.resolve()).encode("utf-8")).hexdigest()[:20]
    return project.resolve() / "outputs" / ".pptx-work" / ".guard" / f"hook-health-plan-{key}.json"


def _is_pipeline_plan(command: str) -> bool:
    text = command or ""
    return "ppt_pipeline.py" in text and re.search(r"(?:^|\s)plan(?:\s|$)", text) is not None


def arm(event: dict[str, Any]) -> Path | None:
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "Bash":
        return None
    command = str((event.get("tool_input") or {}).get("command") or "")
    if not _is_pipeline_plan(command):
        return None
    project = _project_root(event)
    work_dir = extract_work_dir(command, base=project)
    if work_dir is None:
        # The command will fail argument parsing anyway; do not create an
        # unbound receipt that a later command could reuse.
        return None
    target = receipt_path(project, work_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": RECEIPT_VERSION,
        "event": "PreToolUse",
        "tool": "Bash",
        "created_at": time.time(),
        "session_id": event.get("session_id"),
        "project": str(project),
        "work_dir": str(work_dir),
        "plugin_root": str(Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or "").resolve()),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def verify_plan_receipt(work_dir: Path, *, consume: bool = True, now_value: float | None = None) -> dict[str, Any]:
    project = _project_root()
    expected_work = work_dir.resolve()
    target = receipt_path(project, expected_work)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "hook-health receipt missing: Claude plugin PreToolUse hooks are not active for this plan; "
            "reload/restart the plugin session before production"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("hook-health receipt is malformed; reload the plugin session")
    created = payload.get("created_at")
    current = time.time() if now_value is None else now_value
    try:
        age = current - float(created)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("hook-health receipt has no valid timestamp; reload the plugin session") from exc
    if age < -5 or age > HEALTH_TTL_SECONDS:
        raise RuntimeError(
            f"hook-health receipt is stale ({age:.1f}s); rerun plan from a session with active plugin hooks"
        )
    if payload.get("version") != RECEIPT_VERSION or payload.get("event") != "PreToolUse" or payload.get("tool") != "Bash":
        raise RuntimeError("hook-health receipt does not prove a PreToolUse Bash hook")
    if Path(str(payload.get("project") or "")).resolve() != project:
        raise RuntimeError("hook-health receipt belongs to another project")
    if Path(str(payload.get("work_dir") or "")).resolve() != expected_work:
        raise RuntimeError("hook-health receipt belongs to another work-dir")
    configured_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if configured_root and Path(str(payload.get("plugin_root") or "")).resolve() != Path(configured_root).resolve():
        raise RuntimeError("hook-health receipt belongs to another plugin installation")
    if consume:
        try:
            target.unlink()
        except OSError as exc:
            raise RuntimeError("hook-health receipt could not be consumed safely") from exc
    return payload


def enforce_pipeline_plan_bootstrap(argv: list[str] | None = None) -> None:
    """Exit cleanly when a real plugin plan lacks a fresh hook handshake."""
    argv = list(sys.argv if argv is None else argv)
    if not os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return
    if Path(argv[0]).name.lower() != "ppt_pipeline.py" or len(argv) < 2 or argv[1] != "plan":
        return
    project = _project_root()
    work_dir = work_dir_from_argv(argv, base=project)
    if work_dir is None:
        return
    try:
        verify_plan_receipt(work_dir)
    except RuntimeError as exc:
        print(f"ppt_pipeline: REFUSED — {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    try:
        arm(event)
    except OSError as exc:
        # Do not make the hook itself the source of an opaque Bash refusal. The
        # pipeline's verifier will emit the user-facing fail-fast explanation.
        print(f"hook_health: could not write health receipt: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
