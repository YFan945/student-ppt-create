#!/usr/bin/env python3
"""PreToolUse guard for student-presentation-suite cost discipline.

Blocks plugin-source archaeology, re-reading the same PNG (same sha256),
repeated read-only inspection commands (ls/cat/find run a 3rd time in one
session), and main-session reads of full-size render images beyond a small
budget (per-page review belongs to the isolated visual-critic; the cheap
overview is contact-sheet-thumb.jpg). Does *not* block first-time image reads —
DeepSeek Flash caps each image at 1024 tokens.

Agent execution integrity (named/background/nested evidence-agent spawn rules,
receipts, and isolated research/critic ownership) belongs to
``runtime_evidence.py``. Direct production-script entrypoints are controlled by
``production_entry_guard.py``. This module intentionally stays focused on
context and inspection cost.

Seen state lives at `outputs/.pptx-work/.guard/seen-<session>.json`: scoped to
the hook session, so one task's read never silences the next task's first read.
References are keyed by resolved path + sha256, so same-named files in different
directories do not collide and an updated reference may be re-read.
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
    "validate_research_pack",
    "research_pack_to_evidence",
    "slide_spec_guard",
    "visual_reference_select",
    "art_direction_check",
)
_COMMAND_POSITION = r"(?:^|[;&]|&&|\|\|)\s*(?:sudo\s+)?"
LIST_VERBS = r"(ls|dir|tree|find|stat|du|Get-ChildItem)"
VIEW_VERBS = r"(grep|rg|sed|awk|head|tail|cat|type|Get-Content)"
# The verb must sit in *command position* (start of a command, or after a separator).
# Matching it anywhere in the line made `--work-dir` match `dir`, so the pipeline's own
# recommended invocation — `python "…/ppt_pipeline.py" next --work-dir <wd>` — came back as
# "do not ls/grep/cat plugin source": the command the skills require and the guard that
# polices it disagreed (2026-09-17 live: 6 cost_guard refusals, half of them this shape).
# Piping into `head`/`tail` is also left alone now: that is how output is *kept small*.
GREP_SED = re.compile(_COMMAND_POSITION + VIEW_VERBS + r"\b", re.I | re.M)
PLUGIN_INSPECT = re.compile(_COMMAND_POSITION + LIST_VERBS + r"\b", re.I | re.M)
# A path shape, not a bare name: `grep -l "student-presentation-suite-scaffold" *.js` is a
# scaffold-marker check, and the marker happens to share the plugin's name.
PLUGIN_PATH = re.compile(
    r"student-presentation-suite[/\\]|[/\\]student-presentation-suite\b|CLAUDE_PLUGIN_ROOT|skills[/\\]sp-deck[/\\]scripts",
    re.I,
)
# The CLI path may be quoted (`python "…/ppt_pipeline.py" next`), which is how the skills
# write it. A bare `.py\s+next` never matched that form, so the allow-list silently failed.
PIPELINE_RUN = re.compile(
    r"ppt_pipeline\.py['\"]?\s+(next|plan|build|render|qa|repair|complete|status|advance)\b",
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


def repo_root_from_cwd(cwd: str) -> Path:
    """Find the project root so all work-ids share one guard directory."""
    start = Path(cwd or ".").resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "outputs" / ".pptx-work").is_dir():
            return candidate
    return start


def session_key(event: dict) -> str:
    """Seen state is per session.

    One task must never silence the next task's first read, so the store is
    keyed by the hook's session id rather than shared across the whole
    `.pptx-work` root (which was the pre-0.12.0 behaviour).
    """
    session = str(event.get("session_id") or "").strip()
    if event.get("agent_id"):
        session += "-" + str(event["agent_id"])
    if not session:
        cwd = str(event.get("cwd") or os.getcwd())
        session = "cwd-" + hashlib.sha256(str(Path(cwd or ".").resolve()).encode("utf-8")).hexdigest()[:12]
    return re.sub(r"[^A-Za-z0-9._-]", "_", session)[:80]


def seen_store(cwd: str, session: str) -> Path:
    return repo_root_from_cwd(cwd) / "outputs" / ".pptx-work" / ".guard" / f"seen-{session}.json"


def load_seen(cwd: str, session: str) -> dict:
    path = seen_store(cwd, session)
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


def save_seen(cwd: str, session: str, seen: dict) -> None:
    path = seen_store(cwd, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def plugin_root() -> Path:
    """Installed plugin root: this hook always lives at <root>/scripts/."""
    return Path(__file__).resolve().parents[1]


def pipeline_hint(command: str = "next") -> str:
    """Runnable pipeline command with a resolved script path.

    Earlier versions suggested a bare `ppt_pipeline.py`, which is not on PATH and
    does not sit next to this hook (it lives under skills/sp-deck/scripts). Agents
    followed it and burned a round on "No such file or directory" (2026-09-16).
    """
    pipeline = plugin_root() / "skills" / "sp-deck" / "scripts" / "ppt_pipeline.py"
    if pipeline.is_file():
        return f'"{sys.executable}" "{pipeline}" {command} --work-dir <wd>'
    return f"ppt_pipeline.py {command} --work-dir <wd>"


def helpers_hint() -> str:
    helper = plugin_root() / "scripts" / "pptx-helpers.js"
    if helper.is_file():
        return f'node "{helper}" --describe'
    return "node pptx-helpers.js --describe"


BUILDER = "student-presentation-suite:presentation-builder"


def builder_hint() -> str:
    """Runnable discovery surface for the isolated builder (2026-09-17).

    Main-session hints point at `ppt_pipeline.py next`, which the builder is
    forbidden to run; that dead end pushed a live builder into hand-writing
    composition evidence instead of calling the real helpers.
    """
    select = plugin_root() / "skills" / "sp-deck" / "scripts" / "visual_reference_select.py"
    parts = [f"`{helpers_hint()}`"]
    if select.is_file():
        parts.append(
            f'`"{sys.executable}" "{select}" --role <role> --grammar <grammar> '
            "--visual-strategy <strategy> --output <work-dir>/composition/<id>.json --json`"
        )
    return (
        "Allowed for the isolated builder: " + " or ".join(parts) + ". "
        "Everything else is run by the MAIN session after you return."
    )


# 只读巡检命令的同会话重复上限：2026-09-16 实测 `ls critic-execution.json` 连跑
# 5 次、`ls -la` ×4 —— 状态查询一律走 `next`（一次给全 read/forbidden/next_command）。
# 只限制 ls/cat/find 等纯只读巡检；build/gates/qa 等动作命令不限制（修复后重跑是合法路径）。
INSPECT_RE = re.compile(r"^\s*(sudo\s+)?(ls|cat|head|tail|find|stat|dir|tree|du)\b", re.I)
REPEAT_INSPECT_LIMIT = 3
# 主会话大图预算：2026-09-16 实测 19 张图进主上下文共 3.27MB（回灌的 92%），
# 而 per-page 复核本就属于隔离的 visual-critic。只限制主会话（无 agent_id）；
# 大图 = >150KB；超出预算后指向 contact-sheet-thumb.jpg（render 会产出）。
BIG_IMAGE_BYTES = 150 * 1024
MAIN_SESSION_BIG_IMAGE_BUDGET = 6


def check_inspection_repeat(command: str, cwd: str, session: str, builder: bool = False) -> str | None:
    if not INSPECT_RE.match(command):
        return None
    key = "inspect:" + hashlib.sha256(
        re.sub(r"\s+", " ", command).strip().encode("utf-8")
    ).hexdigest()[:16]
    seen = load_seen(cwd, session)
    counts = seen.setdefault("inspections", {})
    count = int(counts.get(key, 0)) + 1
    counts[key] = count
    save_seen(cwd, session, seen)
    if count >= REPEAT_INSPECT_LIMIT:
        if builder:
            return (
                f"cost_guard: the same inspection command already ran {count - 1} times this "
                f"session; repeating it yields no new information. {builder_hint()}"
            )
        return (
            f"cost_guard: the same inspection command already ran {count - 1} times this "
            "session; repeating it yields no new information. Run the pipeline `next` "
            "command instead — it returns state, what to read and the next command in one call."
        )
    return None


def cheap_overview_hint(path: Path) -> str:
    try:
        for parent in path.parents:
            if parent.name == ".pptx-work":
                rel = path.relative_to(parent)
                if len(rel.parts) >= 2:
                    thumb = parent / rel.parts[0] / "contact-sheet-thumb.jpg"
                    if thumb.is_file():
                        return str(thumb)
                break
    except OSError:
        pass
    return "(run `ppt_pipeline.py render` to produce it)"


def check_bash(command: str, builder: bool = False) -> str | None:
    if PLUGIN_PATH.search(command) and PLUGIN_INSPECT.search(command) and not PIPELINE_RUN.search(command):
        if builder:
            return (
                "cost_guard: the isolated builder must not ls/grep/cat plugin source or the plugin cache. "
                f"{builder_hint()}"
            )
        return (
            "cost_guard: do not ls/grep/cat plugin source or the plugin cache. "
            f"Run `{pipeline_hint()}` or `{helpers_hint()}`."
        )
    if GREP_SED.search(command) and PLUGIN_PATH.search(command):
        if builder:
            return (
                "cost_guard: the isolated builder must not grep/sed/cat plugin source. "
                f"{builder_hint()}"
            )
        return (
            "cost_guard: do not grep/sed/cat plugin source. "
            f"Run `{pipeline_hint()}` or `{helpers_hint()}`."
        )
    if "--help" in command and any(hint in command for hint in PLUGIN_HINTS):
        # `ppt_pipeline.py` is the agent's operating surface, and its --help is a few dozen
        # lines. Refusing it does not save a round trip — the model goes looking for the
        # invocation by trial and error, which costs the same round trip and produces a
        # failure instead of information (2026-09-17: after one refusal the next two
        # attempts were chained --help probes on other scripts). A bare script name is
        # still refused so the hint can hand over the absolute path it needs anyway.
        if re.search(r"[/\\]ppt_pipeline\.py", command):
            return None
        if builder:
            return (
                "cost_guard: the isolated builder must not --help plugin scripts. "
                f"{builder_hint()}"
            )
        return (
            "cost_guard: do not --help plugin scripts to discover the next step. "
            f"Run `{pipeline_hint()}`."
        )
    return None


def check_read(path_str: str, cwd: str, session: str, is_main: bool = False) -> str | None:
    raw = Path(path_str)
    path = raw if raw.is_absolute() else Path(cwd) / raw
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXT:
        digest = sha256_file(path)
        if not digest:
            return None
        seen = load_seen(cwd, session)
        resolved = str(path.resolve())
        if (seen.get("images") or {}).get(resolved) == digest:
            return (
                "cost_guard: same PNG sha256 was already read (CD-9). "
                "Only re-read after a new render changes the hash."
            )
        seen.setdefault("images", {})[resolved] = digest
        if is_main:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > BIG_IMAGE_BYTES:
                used = int((seen.get("big_images") or {}).get("used", 0)) + 1
                seen["big_images"] = {"used": used}
                if used > MAIN_SESSION_BIG_IMAGE_BUDGET:
                    save_seen(cwd, session, seen)
                    return (
                        f"cost_guard: main-session full-size image budget exhausted "
                        f"({MAIN_SESSION_BIG_IMAGE_BUDGET} images >150KB this session). "
                        "Per-page review belongs to the isolated visual-critic — spawn "
                        "student-presentation-suite:visual-critic WITHOUT a `name`. "
                        f"Cheap overview: {cheap_overview_hint(path)}"
                    )
        save_seen(cwd, session, seen)
        return None
    text = str(path).replace("\\", "/")
    if suffix in {".py", ".js"} and PLUGIN_PATH.search(text):
        return (
            "cost_guard: do not Read plugin source. "
            f"Run `{pipeline_hint()}` or `{helpers_hint()}`."
        )
    if "/references/" in text and text.endswith(".md"):
        seen = load_seen(cwd, session)
        key = str(path.resolve())
        digest = sha256_file(path)
        previous = (seen.get("refs") or {}).get(key)
        if previous is not None and (digest is None or previous == digest):
            return (
                f"cost_guard: {path.name} was already read this session (CD-3). "
                "Use the checklist you extracted; do not reload the full reference."
            )
        seen.setdefault("refs", {})[key] = digest or True
        save_seen(cwd, session, seen)
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
    session = session_key({**event, "cwd": cwd})
    if name == "Bash":
        command = str(tool_input.get("command") or "")
        builder = str(event.get("agent_type") or "") == BUILDER
        msg = check_bash(command, builder=builder)
        if msg:
            return refuse(msg)
        msg = check_inspection_repeat(command, cwd, session, builder=builder)
        return refuse(msg) if msg else 0
    if name in {"Read", "Grep"}:
        path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if name == "Grep" and PLUGIN_PATH.search(
            str(tool_input.get("path") or "") + str(tool_input.get("pattern") or "")
        ):
            return refuse(
                "cost_guard: do not Grep plugin source. "
                f"Run `{pipeline_hint()}`."
            )
        msg = check_read(path, cwd, session, is_main=not event.get("agent_id")) if path else None
        return refuse(msg) if msg else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
