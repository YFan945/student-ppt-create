#!/usr/bin/env python3
"""Record successful child tool events; never accept model-declared spawn proof.

This is an execution-integrity gate inside a trusted local Claude session, not a
sandbox against a user/process able to rewrite the hook and its evidence files.

Receipt artifacts (research-pack.json / visual-review.json / the calibration
visual review) are credited through
hash snapshots taken at SubagentStart and refreshed after every child tool call,
so script writes (e.g. ``python json.dump``) count the same as Write-tool writes.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shlex
import sys
import time
from contextlib import contextmanager, suppress
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import critic_preview  # noqa: E402
import pipeline_context  # noqa: E402
from hook_events import read_event  # noqa: E402

from shared.retrieval_trail import (  # noqa: E402
    INDEX_EMPTY,
    SEARCH_BACKEND_NOT_EXECUTED,
    UNKNOWN_PAYLOAD,
    is_search_locator,
    search_channel_closed,
    search_payload_signature,
)

RESEARCHER = pipeline_context.RESEARCHER
CRITIC = pipeline_context.CRITIC
PIPELINE_SKILLS = pipeline_context.PIPELINE_SKILLS
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
SEARCH_CLOSED = (
    "This search channel is paused after confirmed non-execution. "
    "Do not cite that response. Continue document retrieval and bounded evidence inspection. "
    "Only the main session may reset the channel after a documented environment change, "
    "using reset_research_channel.py; otherwise close affected claims as unresolved."
)
INDEX_EMPTY_NOTE = (
    "search_signature: index_empty. The search backend ran and returned no links for this phrasing. "
    "That is coverage, not a dead channel. Correct language/name/filter if useful, "
    "or locate the publisher's document URL; avoid pointless duplicates."
)
BACKEND_NOTE = (
    "search_signature: backend_not_executed. Structured runtime metadata reports non-execution. "
    + SEARCH_CLOSED
)
UNKNOWN_NOTE = (
    "search_signature: unknown_payload. This response format is not recognised; "
    "it does not prove that the backend failed or executed. Search remains available; "
    "record this advisory and use any candidate links only to locate readable sources."
)
LOCATOR_REFUSAL = (
    "A search-result page is a locator, not a source. Fetch the document URL with "
    "pptx_tool.py fetch-text. WebFetch of a search-engine result page is refused."
)
BODY_DUMP_REFUSAL = (
    "Fetched page bodies stay on disk. Read text_path with the Read tool using offset and limit. "
    "Do not cat, grep, head, or print .txt/.raw bodies from research/fetched back into the turn."
)
READ_LIMIT_REFUSAL = (
    "Read of a fetched page body requires limit, with offset when you need a later slice. "
    "Do not read the whole file into the turn."
)
SEARCH_PAYLOADS_NAME = "search-payloads.json"
_BODY_DUMP_RE = re.compile(
    r"\b(grep|cat|head|tail|less|more|Get-Content)\b|\bprint\s*\(|\bopen\s*\(|\bread_text\s*\(",
    re.IGNORECASE,
)
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
def event_lock(event: dict, *, project_override: Path | None = None, key_override: str | None = None):
    """Serialize parallel child hook events and recover abandoned lock files."""
    project = project_override or Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()
    key = key_override or re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id")) + "-" + str(event.get("agent_id")))
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
            # Windows delete-pending: an unlink "succeeded" but the name lingers
            # until every handle closes; exists() then reports False while open()
            # still fails. Retry exactly like a collision — the 5s deadline still
            # bounds a genuinely unwritable directory (RuntimeError, not hang).
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


def artifact_snapshot(root: Path) -> dict[str, str]:
    """Hash receipt artifacts across work dirs (a few small JSON files)."""
    snap: dict[str, str] = {}
    if not root.is_dir():
        return snap
    patterns = (
        "*/research-pack.json",
        "*/visual-review.json",
        "*/calibration/calibration-visual-review.json",
    )
    for pattern in patterns:
        for path in root.glob(pattern):
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
    if len(matches) == 1:
        return matches[0]
    # ZCode 等环境下 root/cwd 推导可能落空：提示词里显式写了
    # `.pptx-work/<work-id>` 时，以提示词自认的那个 work-dir 为准——仍是
    # "显式传入的绝对 work-dir"，只是解析更宽容；命名了多个或零个仍拒绝
    # （2026-09-29 live：0.21.12 下 spawn 三连拒，离线复现同 input 却成功）。
    named: set = set()
    for match in re.finditer(r"\.pptx-work[/\\]([\w.-]+)", normalized):
        candidate = root / match.group(1)
        if candidate.is_dir():
            named.add(candidate.resolve())
    return named.pop().resolve() if len(named) == 1 else None


def _hook_owned_preview_path(path: Path, root: Path) -> bool:
    if not path.is_relative_to(root):
        return False
    if path.name == critic_preview.MAP_NAME:
        return True
    return critic_preview.PREVIEW_DIR_NAME in path.parts


def _critic_review_target(path: Path, root: Path) -> tuple[Path, Path] | None:
    """Return (work-dir, receipt path) for an allowed critic report location."""
    if path.name == "visual-review.json" and path.parent.parent == root:
        return path.parent, path.parent / "critic-execution.json"
    if (
        path.name == "calibration-visual-review.json"
        and path.parent.name == "calibration"
        and path.parent.parent.parent == root
    ):
        return path.parent.parent, path.parent / "calibration-critic-execution.json"
    return None


def _is_researcher(event: dict) -> bool:
    """The plugin researcher, including ZCode's `zcode-` prefix on the child runtime."""
    return str(event.get("agent_type") or "").endswith("presentation-researcher")


def _response_text(value: object) -> str:
    """Keep the complete result so JSON parsing and later replay see the same bytes."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        for key in ("text", "content", "output", "result", "stdout"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                text = inner
                break
        else:
            text = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(parts)
    else:
        text = ""
    return text


def _channel_path(project: Path, event: dict) -> Path:
    key = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        str(event.get("session_id") or "unknown") + "-" + str(event.get("agent_id") or "main"),
    )
    return project / "outputs" / ".pptx-work" / ".guard" / f"search-channel-{key}.json"


def _read_executions(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("executions") if isinstance(data, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _write_executions(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"executions": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _armed_work_dirs(project: Path, event: dict | None = None) -> list[Path]:
    """Resolve the child's recorded task, then the project's single armed work-id.

    The child runtime's session id is not the parent's, so the research-active marker
    written at spawn is found by scanning before its task read is recorded.
    Multiple recorded tasks never fall back to an arbitrary activation marker.
    """
    guard = project / "outputs" / ".pptx-work" / ".guard"
    if not guard.is_dir():
        return []
    # Parent Stop can clear its activation marker while a background researcher
    # is still running. The child's hook-owned task read survives that cleanup
    # and also separates researchers belonging to concurrent decks/sessions.
    if event and event.get("agent_id"):
        key = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id")) + "-" + str(event["agent_id"]))
        ledger = read_json(guard / f"agent-{key}.json")
        if (ledger.get("agent") == RESEARCHER and ledger.get("agent_id") == event["agent_id"]
                and ledger.get("session_id") == event.get("session_id")):
            tasks = []
            for name in ledger.get("reads", {}):
                task = Path(name).resolve()
                if task.name == "research-task.json" and task.parent.parent == guard.parent:
                    tasks.append(task.parent)
            unique = list(dict.fromkeys(tasks))
            if unique:
                return unique if len(unique) == 1 else []
    found: list[Path] = []
    now = time.time()
    for path in guard.glob("research-active-*.json"):
        try:
            if now - path.stat().st_mtime > pipeline_context.RESEARCH_ACTIVE_TTL_SECONDS:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for work_id in data.get("work_ids") or []:
            found.append(project / "outputs" / ".pptx-work" / str(work_id))
    unique = list(dict.fromkeys(found))
    return unique if len(unique) == 1 else []


def _record_search_payload(project: Path, event: dict) -> None:
    """Classify the tool result, persist the payload, and tell the model the signature.

    The payload is what the validator recomputes from. The additionalContext is what
    the model sees beside the prose: ZCode appends hook context, it does not replace
    the tool result, so the note has to say the prose is not evidence.
    """
    response = event.get("tool_response")
    # Preserve structured results instead of flattening a list into empty text.
    payload = json.dumps(response, ensure_ascii=False) if isinstance(response, (dict, list)) else _response_text(response)
    execution_status = str(response.get("execution_status") or "") if isinstance(response, dict) else ""
    signature = search_payload_signature(payload, execution_status=execution_status)
    if not signature:
        return
    row = {
        "query": str((event.get("tool_input") or {}).get("query") or ""),
        "payload": payload,
        "signature": signature,
        "execution_status": execution_status,
    }
    channel = _channel_path(project, event)
    rows = _read_executions(channel)
    rows.append(row)
    _write_executions(channel, rows)
    for work_dir in _armed_work_dirs(project, event):
        trail = work_dir / "research" / SEARCH_PAYLOADS_NAME
        _write_executions(trail, _read_executions(trail) + [row])
    note = {
        SEARCH_BACKEND_NOT_EXECUTED: BACKEND_NOTE,
        UNKNOWN_PAYLOAD: UNKNOWN_NOTE,
        INDEX_EMPTY: INDEX_EMPTY_NOTE,
    }.get(signature)
    if not note:
        return
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}},
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def _bounded_excerpt_command(command: str) -> bool:
    """Recognize only the owned bounded helper and harmless shell bookkeeping."""
    if "research_excerpt.py" not in command or "$(" in command or "`" in command:
        return False
    # A bounded helper may merge stderr and cap its already bounded output.
    command = re.sub(r"\s+2>&1\s*\|\s*head\s+-([1-9]|[1-7][0-9]|80)\s*$", "", command)
    try:
        lexer = shlex.shlex(command.replace("\\\r\n", "").replace("\\\n", ""), posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    segments, current = [], []
    for token in tokens:
        if token in {"&&", ";"}:
            segments.append(current)
            current = []
        elif token in {"|", "||", "&"}:
            return False
        else:
            current.append(token)
    segments.append(current)
    helper = Path(__file__).resolve().parent / "research_excerpt.py"
    found = False
    command_cwd = Path.cwd()
    for args in segments:
        if not args:
            continue
        if len(args) == 2 and args[0] == "cd":
            candidate = Path(args[1])
            command_cwd = candidate.resolve() if candidate.is_absolute() else (command_cwd / candidate).resolve()
            continue
        if len(args) == 1 and re.fullmatch(r"[A-Za-z_]\w*=.*", args[0]):
            continue
        if args == ["echo", "EXIT=$?"]:
            continue
        if len(args) >= 2 and Path(args[0]).name.lower() in {"python", "python.exe", "python3", "python3.exe"} and (Path(args[1]).resolve() if Path(args[1]).is_absolute() else (command_cwd / args[1]).resolve()) == helper:
            if not all(flag in args for flag in ("--text", "--start", "--end")) or any(t in {">", "<", ">>", "-c"} for t in args):
                return False
            found = True
            continue
        return False
    return found


def dumps_fetched_body(command: str) -> bool:
    """True when a shell command would print a fetched page body back into the turn."""
    normalized = str(command or "").replace("\\", "/")
    if "fetch-text" in normalized or "research/fetched" not in normalized:
        return False
    if not re.search(r"\.(txt|raw)\b", normalized, re.IGNORECASE):
        return False
    if _bounded_excerpt_command(command) or _prints_digest_only(command):
        return False
    return _BODY_DUMP_RE.search(command or "") is not None


def _prints_digest_only(command: str) -> bool:
    """Allow metadata hashes and statically bounded excerpts; never full bodies."""
    try:
        parts = shlex.split(command)
        code = parts[parts.index("-c") + 1]
        tree = ast.parse(code)
    except (ValueError, IndexError, SyntaxError):
        return False

    def digest(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "hexdigest" and isinstance(node.func.value, ast.Call)
                and ast.unparse(node.func.value.func) == "hashlib.sha256")

    literals = {}

    def bound(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1:
            value = node.args[0]
            if isinstance(value, ast.Name) and isinstance(literals.get(value.id), str):
                return "", len(literals[value.id])
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return "", node.value
        if isinstance(node, ast.Name):
            return node.id, 0
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left, right = bound(node.left), bound(node.right)
            if left is not None and right is not None and not right[0]:
                return left[0], left[1] + right[1] * (-1 if isinstance(node.op, ast.Sub) else 1)
        return None

    def excerpt(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "repr" and len(node.args) == 1:
            node = node.args[0]
        if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
            return False
        low, high = bound(node.slice.lower), bound(node.slice.upper)
        return low is not None and high is not None and low[0] == high[0] and high[1] > low[1]

    hashes = set()
    printed = False
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr)):
            return False
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    literals.pop(target.id, None)
                    if isinstance(statement.value, ast.Constant):
                        literals[target.id] = statement.value.value
                    hashes.discard(target.id)
                    if digest(statement.value):
                        hashes.add(target.id)
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            if not isinstance(call.func, ast.Name) or call.func.id != "print":
                return False
            if isinstance(call.func, ast.Name) and call.func.id == "print":
                if not call.args or not all(isinstance(arg, (ast.Constant, ast.Compare)) or digest(arg) or excerpt(arg)
                                           or isinstance(arg, ast.Name) and arg.id in hashes for arg in call.args):
                    return False
                printed = True
    # Nested print/control flow is outside this small metadata-only allowance.
    prints = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"]
    top_prints = [s for s in tree.body if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                  and isinstance(s.value.func, ast.Name) and s.value.func.id == "print"]
    return printed and len(prints) == len(top_prints)


def _fetched_body_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/")
    return "research/fetched" in normalized and re.search(r"\.(txt|raw)$", normalized, re.IGNORECASE) is not None


def greps_fetched_body(inputs: dict) -> bool:
    """True when Grep would search fetched page bodies rather than the fetch report."""
    path = str(inputs.get("path") or inputs.get("file_path") or "").replace("\\", "/")
    return "research/fetched" in path and not path.endswith(".json")


def read_fetched_without_limit(inputs: dict) -> bool:
    """True when a fetched body would be read whole. Presence of limit is the slice; no cap."""
    path = str(inputs.get("file_path") or inputs.get("path") or "")
    if not _fetched_body_path(path):
        return False
    limit = inputs.get("limit")
    return not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0


def handle(event: dict) -> int:
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or Path.cwd()).resolve()
    root = project / "outputs" / ".pptx-work"
    agent = event.get("agent_type")
    if _is_researcher(event):
        agent = RESEARCHER
    child = event.get("agent_id")
    kind = event.get("hook_event_name")
    tool = event.get("tool_name")
    inputs = event.get("tool_input") or {}

    if kind == "Stop" and not child:
        pipeline_context.clear_research_active(project, event)
        return 0

    if kind == "PreToolUse":
        if _is_researcher(event):
            works = _armed_work_dirs(project, event)
            task_path = works[0] / "research-task.json" if works else None
            retrieval = tool in {"WebSearch", "WebFetch"} or (
                tool in {"Bash", "PowerShell"} and re.search(r"\bfetch-text(?=[\s\"']|$)", str(inputs.get("command", ""))))
            if retrieval and task_path and task_path.is_file():
                from shared.research_control import status
                decision = status(task_path.parent, retrieval=True)
                if decision["state"] == "stop_requested":
                    stop_note = "Save the current pack, mark remaining gaps and return; no more retrieval."
                    if decision["reason"] == "task_changed":
                        stop_note += (
                            " If the main flow sanctioned a scope convergence, it can re-bind the task via "
                            "`research_control.py --work-dir <wd> --rebind --reason \"<the scope change>\"`."
                        )
                    print(f"Research stop requested: {decision['reason']}. {stop_note}", file=sys.stderr)
                    return 2
            if retrieval and task_path and not task_path.is_file() and (task_path.parent / "research-task-binding.json").is_file():
                print("Bound research task was removed; retrieval is refused.", file=sys.stderr)
                return 2
            if retrieval and task_path and task_path.is_file():
                from validate_research_task import validate_task
                try:
                    task = json.loads(task_path.read_text(encoding="utf-8"))
                    errors = validate_task(task, task_path)
                    frozen = json.loads((task_path.parent / "research-task-binding.json").read_text(encoding="utf-8"))
                    if frozen.get("sha256") != hashlib.sha256(task_path.read_bytes()).hexdigest():
                        errors.append("Task changed after spawn")
                    if errors or task.get("scope") not in {"A", "B"}:
                        print("Research task does not authorize this retrieval: " + "; ".join(errors), file=sys.stderr)
                        return 2
                except (OSError, ValueError, TypeError):
                    print("Research task binding is missing or unreadable.", file=sys.stderr)
                    return 2
            elif retrieval and not works and any(root.glob("*/research-task-binding.json")):
                print("Research work directory is ambiguous; bind one task before retrieval.", file=sys.stderr)
                return 2
            closed = search_channel_closed(_read_executions(_channel_path(project, event)))
            if tool == "WebSearch" and closed:
                print(SEARCH_CLOSED, file=sys.stderr)
                return 2
            if tool == "WebFetch" and is_search_locator(str(inputs.get("url") or "")):
                print(LOCATOR_REFUSAL, file=sys.stderr)
                return 2
            if tool in {"Bash", "PowerShell"}:
                command = str(inputs.get("command") or "")
                if "reset_research_channel" in command:
                    print("Only the main session may reset the research search channel.", file=sys.stderr)
                    return 2
                if "research_control.py" in command and "--resume" in command:
                    print("Only the main session may resume research after new input/environment changes.", file=sys.stderr)
                    return 2
                if dumps_fetched_body(command):
                    print(BODY_DUMP_REFUSAL, file=sys.stderr)
                    return 2
            if tool == "Grep" and greps_fetched_body(inputs) and inputs.get("output_mode") == "content" and (
                    not isinstance(inputs.get("head_limit"), int) or isinstance(inputs.get("head_limit"), bool)
                    or inputs["head_limit"] <= 0
            ):
                if inputs.get("head_limit") is None:
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "updatedInput": {**inputs, "head_limit": 80},
                        "additionalContext": "Using head_limit=80 for focused evidence inspection; narrow the pattern if truncated."}}))
                    return 0
                print("Set a positive head_limit for content searches of fetched bodies.", file=sys.stderr)
                return 2
            if closed and tool == "Read" and read_fetched_without_limit(inputs):
                print(READ_LIMIT_REFUSAL, file=sys.stderr)
                return 2
        if tool in {"Write", "Edit"}:
            path = Path(inputs.get("file_path") or "").resolve()
            if path.is_relative_to(root) and (
                path.name in {
                    "research-execution.json",
                    "critic-execution.json",
                    "calibration-critic-execution.json",
                    SEARCH_PAYLOADS_NAME,
                    "research-task-binding.json",
                    "research-control.json",
                }
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
            pipeline_context.mark_research_active(project, event)
        if tool in {"Agent", "SendMessage"}:
            name = str(inputs.get("name") or "").strip()
            dest = str(inputs.get("to") or inputs.get("recipient") or "").strip()
            # CD-5 governs deck evidence work, so the fuzzy name refusal is
            # scoped to a managed pipeline session like every other Batch 6.1
            # rule. A plain session naming a teammate "research-assistant" is
            # not this guard's business; the exact plugin-agent-type checks
            # below stay unscoped (they cannot false-positive).
            if (
                pipeline_context.research_active(project, event)
                and EVIDENCE_NAME_RE.search(f"{name} {dest}")
            ):
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
                researcher_work = _critic_work_dir(inputs, root)
                if researcher_work and (researcher_work / "research-task.json").is_file():
                    from validate_research_task import validate_task

                    from shared.research_io import atomic_json
                    task_path = researcher_work / "research-task.json"
                    try:
                        errors = validate_task(json.loads(task_path.read_text(encoding="utf-8")), task_path)
                    except (OSError, ValueError, TypeError) as exc:
                        errors = [str(exc)]
                    if errors:
                        print("Invalid researcher task: " + "; ".join(errors), file=sys.stderr)
                        return 2
                    prior = read_json(researcher_work / "research-task-binding.json")
                    if prior.get("session_id") == event.get("session_id") and prior.get("session_id"):
                        print("This session already spawned this research task. Return its saved pack and gaps; do not autonomously restart or respawn it.", file=sys.stderr)
                        return 2
                    atomic_json(researcher_work / "research-task-binding.json", {
                        "path": str(task_path.resolve()),
                        "session_id": event.get("session_id"),
                        "sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
                    })
                    from shared.research_control import status
                    status(researcher_work)
                pipeline_context.mark_research_active(
                    project, event,
                    work_ids=[researcher_work.name] if researcher_work else None,
                )
            else:
                work_dir = _critic_work_dir(inputs, root)
                if work_dir is None:
                    print(CRITIC_WORKDIR_REFUSAL, file=sys.stderr)
                    return 2
                # A deck may legitimately skip external research. Its critic
                # spawn still identifies the exact work-id owned by this main
                # session, so record it before arming/refreshing scope. This
                # prevents an unrelated historical incomplete deck from keeping
                # WebSearch blocked after the current deck completes.
                pipeline_context.mark_research_active(
                    project, event, work_ids=[work_dir.name]
                )
                try:
                    critic_preview.materialize(work_dir)
                except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                    print(f"visual-critic preview preparation failed: {exc}", file=sys.stderr)
                    return 2
        if tool in {"WebSearch", "WebFetch"}:
            if child:
                # Batch 6.1: only THIS plugin's subagents are pipeline-scoped.
                # The isolated researcher owns retrieval; the builder and critic
                # have no retrieval mandate. Subagents from other plugins or user
                # workflows are out of scope entirely and pass through — the old
                # `or child` condition refused every subagent on the machine.
                if agent != RESEARCHER and str(agent or "").startswith(pipeline_context.PLUGIN_PREFIX):
                    print(WEB_REFUSAL, file=sys.stderr)
                    return 2
            elif pipeline_context.research_active(project, event):
                if pipeline_context.release_if_production_complete(project, event):
                    pass  # every work-id delivered: scope released, search allowed
                else:
                    # Main session: refused only while fresh research/production
                    # scope is armed for THIS session; Stop clears it, a TTL
                    # recovers sessions that never delivered Stop, and complete
                    # releases it as soon as all work-ids are delivered.
                    print(WEB_REFUSAL, file=sys.stderr)
                    return 2
        if agent == CRITIC and tool in {"Write", "Edit"}:
            path = Path(inputs.get("file_path") or "").resolve()
            target = _critic_review_target(path, root)
            allowed = None if target is None else critic_preview.assigned_review_output(target[0])
            if allowed is None or path != allowed:
                print(
                    "visual-critic may only write the current review_output declared by "
                    "the hook-owned critic-preview-map.json",
                    file=sys.stderr,
                )
                return 2
        return 0
    if kind == "PostToolUse" and tool == "WebSearch" and _is_researcher(event) and child:
        _record_search_payload(project, event)
    if (
        kind == "PostToolUse"
        and tool in {"Bash", "PowerShell"}
        and pipeline_context.is_pipeline_invocation(str(inputs.get("command") or ""))
    ):
        # A researcher-less deck (D-class structured import, scope-C work) still
        # owns a work-id: record it here so release_if_production_complete can
        # scope to the exact deck instead of falling back to the whole root.
        work_match = re.search(r"--work-dir[ =]+[\"']?([^\"'\s]+)", str(inputs.get("command") or ""))
        if work_match:
            work_name = Path(work_match.group(1)).resolve().name
            if work_name and work_name != ".pptx-work":
                pipeline_context.mark_research_active(project, event, work_ids=[work_name])
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
        if agent == RESEARCHER:
            # 0.27.1：把任务绑定种子化进 ledger——PostToolUse Read 记录在某些
            # runtime 下缺失（run-15：reads 全空），父会话活动标记又在主回合
            # 结束时被清，两相叠加使 SendMessage 续做的检索被 work_dir_ambiguous
            # 永久拒绝。种子内容 = child-ledger 兜底分支读取的同一绑定。
            try:
                works = _armed_work_dirs(project, event)
                if len(works) == 1:
                    task_path = works[0] / "research-task.json"
                    if task_path.is_file():
                        data["reads"][str(task_path.resolve())] = digest(task_path)
            except (OSError, ValueError, KeyError):
                pass
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
        if agent == RESEARCHER:
            from shared.research_control import status
            works = _armed_work_dirs(project, event)
            if works and (works[0] / "research-task.json").is_file():
                decision = status(works[0])
                if decision["state"] == "stop_requested":
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
                        f"Research stop requested: {decision['reason']}. Save/validate remaining gaps and return the handoff; do not search further."}}))
    elif kind == "PostToolUse" and agent == RESEARCHER and tool in {"WebSearch", "WebFetch"}:
        retrieval = data.setdefault("retrieval", {"WebSearch": 0, "WebFetch": 0})
        retrieval[tool] = int(retrieval.get(tool) or 0) + 1
    elif kind == "SubagentStop":
        for name, sha in data["writes"].items():
            artifact = Path(name)
            if agent == RESEARCHER:
                if artifact.name != "research-pack.json" or artifact.parent.parent != root:
                    continue
                work_dir = artifact.parent
                target = work_dir / "research-execution.json"
            else:
                critic_target = _critic_review_target(artifact, root)
                if critic_target is None:
                    continue
                work_dir, target = critic_target
                allowed = critic_preview.assigned_review_output(work_dir)
                if allowed is None or artifact.resolve() != allowed:
                    continue
            if not artifact.is_file() or digest(artifact) != sha:
                continue
            receipt = {
                **data,
                "spawn_verified": True,
                "artifact": {"path": name, "sha256": sha},
                "work_id": work_dir.name,
            }
            target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    event = read_event()
    if (_is_researcher(event) or event.get("agent_type") == CRITIC) and event.get("hook_event_name") != "PreToolUse":
        with event_lock(event):
            code = handle(event)
    else:
        code = handle(event)
    raise SystemExit(code)
