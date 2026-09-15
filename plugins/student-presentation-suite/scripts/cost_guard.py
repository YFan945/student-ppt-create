#!/usr/bin/env python3
"""PreToolUse guard for student-presentation-suite cost discipline.

Blocks plugin-source archaeology, teammate-style research, and re-reading the
same PNG (same sha256). Does *not* block first-time image reads — DeepSeek
Flash caps each image at 1024 tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

PLUGIN_HINTS = (
    "student-presentation-suite",
    ".claude-plugin",
    "pptx-helpers.js",
    "ppt_pipeline.py",
    "run_gates",
)
GREP_SED = re.compile(r"\b(grep|rg|sed|awk|head|cat|type|Get-Content)\b", re.I)
PLUGIN_PATH = re.compile(
    r"student-presentation-suite|CLAUDE_PLUGIN_ROOT|skills/sp-deck/scripts",
    re.I,
)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def work_dir_from_cwd(cwd: str) -> Path:
    root = Path(cwd or ".")
    candidate = root / "outputs" / ".pptx-work"
    return candidate if candidate.is_dir() else root


def seen_store(cwd: str) -> Path:
    return work_dir_from_cwd(cwd) / "cost-guard-seen.json"


def load_seen(cwd: str) -> dict:
    path = seen_store(cwd)
    if not path.is_file():
        return {"refs": {}, "images": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"refs": {}, "images": {}}
    if not isinstance(value, dict):
        return {"refs": {}, "images": {}}
    value.setdefault("refs", {})
    value.setdefault("images", {})
    return value


def save_seen(cwd: str, seen: dict) -> None:
    path = seen_store(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def check_bash(command: str) -> str | None:
    if GREP_SED.search(command) and PLUGIN_PATH.search(command):
        return (
            "cost_guard: do not grep/sed/cat plugin source. "
            "Run `ppt_pipeline.py next --work-dir <wd>` or `node pptx-helpers.js --describe`."
        )
    if "--help" in command and any(hint in command for hint in PLUGIN_HINTS):
        if "ppt_pipeline.py next" in command:
            return None
        return (
            "cost_guard: do not --help plugin scripts to discover the next step. "
            "Run `ppt_pipeline.py next --work-dir <wd>`."
        )
    return None


def check_read(path_str: str, cwd: str) -> str | None:
    raw = Path(path_str)
    path = raw if raw.is_absolute() else Path(cwd) / raw
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXT:
        digest = sha256_file(path)
        if not digest:
            return None
        seen = load_seen(cwd)
        previous = (seen.get("images") or {}).get(str(path.resolve()))
        if previous == digest:
            return (
                "cost_guard: same PNG sha256 was already read (CD-9). "
                "Only re-read after a new render changes the hash."
            )
        seen.setdefault("images", {})[str(path.resolve())] = digest
        save_seen(cwd, seen)
        return None
    text = str(path).replace("\\", "/")
    if suffix in {".py", ".js"} and PLUGIN_PATH.search(text):
        return (
            "cost_guard: do not Read plugin source. "
            "Run `ppt_pipeline.py next --work-dir <wd>` or `node pptx-helpers.js --describe`."
        )
    if "/references/" in text and text.endswith(".md"):
        seen = load_seen(cwd)
        key = path.name
        if seen.get("refs", {}).get(key):
            return (
                f"cost_guard: {key} was already read this task (CD-3). "
                "Use the checklist you extracted; do not reload the full reference."
            )
        seen.setdefault("refs", {})[key] = True
        save_seen(cwd, seen)
    return None


def check_agent(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    name = str(tool_input.get("name") or "").strip().lower()
    dest = str(tool_input.get("to") or tool_input.get("recipient") or "").strip().lower()
    if name == "researcher" or dest == "researcher":
        return (
            "cost_guard: do not spawn a generic researcher teammate. "
            "Use Skill `sp-research` (context: fork) only."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    del argv  # stdin event; CLI flags unused
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    name = str(event.get("tool_name") or event.get("tool") or "")
    tool_input = event.get("tool_input") or event.get("input") or {}
    cwd = str(event.get("cwd") or os.getcwd())
    if name == "Bash":
        msg = check_bash(str(tool_input.get("command") or ""))
        return refuse(msg) if msg else 0
    if name in {"Read", "Grep"}:
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if name == "Grep" and PLUGIN_PATH.search(
            str(tool_input.get("path") or "") + str(tool_input.get("pattern") or "")
        ):
            return refuse(
                "cost_guard: do not Grep plugin source. Run `ppt_pipeline.py next`."
            )
        msg = check_read(path, cwd) if path else None
        return refuse(msg) if msg else 0
    if name in {"Agent", "SendMessage"}:
        msg = check_agent({"tool_input": tool_input, **event})
        return refuse(msg) if msg else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
