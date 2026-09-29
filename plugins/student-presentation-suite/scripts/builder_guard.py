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

4. **Packet scope (runtime, not prose).** When the spawn round generated Builder Packets
   (`builder-packets/active-round.json`), a builder may not re-read the frozen inputs the
   contract lists under `packet.no_reread_files`, and its page-module access is confined to
   its own shard's assigned slides (bound to the packet on first page access). This is the
   enforcement half of `reread_inputs_covered_by_packet: false` and
   `read_other_shard_page_modules: false` — the reason Batch 2's context savings cannot be
   quietly given back by a model that re-reads what the packet already projected. No active
   round (fallback path) means no enforcement, and the fallback stays observable.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

BUILDER = "student-presentation-suite:presentation-builder"
SHELL_TOOLS = {"Bash", "PowerShell"}
# Any interpreter that can take a program on the command line.
SEGMENT_SPLIT = re.compile(r"[;&|\n]+")
INTERPRETER_WORD = re.compile(
    r"^(?:.*[/\\])?(?:python[0-9.]*|py|node|nodejs|perl|ruby|php|pwsh|powershell)(?:\.exe)?$",
    re.I,
)
# 内联 flag 只归属**解释器自己的 flag 段**：`grep -c` / `cut -c` 的 -c 不是 python -c
# （2026-09-28 live：`node --check pages/x.js && grep -c ...` 被误判成"内联脚本碰 work
# 产物"拒绝，理由与命令完全不符，builder 只能重试或放弃语法检查）。
INLINE_FLAG = re.compile(r"--?(?:c|e|command|eval)$", re.I)
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


_FOREIGN_WORK_DIR = re.compile(r"(?:[A-Za-z]:[/\\]|/[A-Za-z]/)[^\s\"'|;]*?\.pptx-work", re.I)


def _foreign_work_refs(text: str, project: Path) -> str | None:
    """Absolute `.pptx-work` references outside THIS project's work tree.

    2026-09-28 live: a builder globbed pages out of eight OTHER projects'
    work dirs (even one with the same work-id) to imitate their layout — a
    boundary the packet never drew because it only scoped writes. Both path
    dialects count (drive-letter and MSYS `/e/...`). Returns the offending
    reference, or None.
    """
    root = (project / "outputs" / ".pptx-work").resolve()
    for match in _FOREIGN_WORK_DIR.finditer(text):
        raw = match.group(0).rstrip("\\/")
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == "/":
            raw = f"{raw[1].upper()}:{raw[2:]}"  # MSYS /e/... -> E:/...
        candidate = Path(raw)
        try:
            candidate.resolve().relative_to(root)
            continue
        except (OSError, ValueError):
            return raw
    return None


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
    """True only when an INTERPRETER takes a program inline.

    按 shell 段判定，flag 必须落在解释器自己的 flag 段里：`node --check x.js` 与
    `grep -c pat file` 都不是内联程序；`node -e "..."` / `python -c "..."` /
    `python - <<'PY'` / `node <<'JS'` 才是。
    """
    for segment in SEGMENT_SPLIT.split(command):
        words = [w for w in segment.strip().split() if not re.match(r"^\w+=", w)]
        if not words or not INTERPRETER_WORD.match(words[0]):
            continue
        for word in words[1:]:
            if not word.startswith("-"):
                break
            if INLINE_FLAG.match(word):
                return True
        if len(words) > 1 and STDIN_PROGRAM.match(words[1]):
            return True
        if HEREDOC.search(segment):
            return True
    return False


def _touches_work_artifacts(command: str) -> bool:
    if PAGE_MODULE_REF.search(command):
        return True
    return bool(WORK_ARTIFACT.search(command) and ARTIFACT_FILE.search(command))


def contract_ref() -> str:
    """Absolute path of the behavior contract, for refusal anchors."""
    return str(plugin_root() / "references" / "agent-behavior-contract.json")


def _contract_packet_policy() -> dict:
    """The contract's packet section — the policy source the guard enforces."""
    try:
        contract = json.loads(Path(contract_ref()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    packet = (contract.get("presentation_builder") or {}).get("packet") or {}
    return packet if isinstance(packet, dict) else {}


def _active_round(work_dir: Path) -> dict | None:
    """The spawn round's packet bindings (written by builder_packet.record_active_round)."""
    try:
        data = json.loads((work_dir / "builder-packets" / "active-round.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    packets = data.get("packets")
    return data if isinstance(data, dict) and isinstance(packets, list) and packets else None


def _norm(name: str) -> str:
    return name.lower().replace("_", "-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_no_reread(path: Path) -> bool:
    """`^` 前缀 = 文件名行首锚定（^qa- 只拦 qa-*.json，不拦 stage-qa-summary.md
    ——后者是 dispatch 明确要读的阶段摘要，此前被 "qa-" 子串误拒）。"""
    name = _norm(path.name)
    for fragment in _contract_packet_policy().get("no_reread_files") or []:
        text = _norm(str(fragment))
        if text.startswith("^"):
            if name.startswith(text[1:]):
                return True
        elif text and text in name:
            return True
    return False


def _page_number(path: Path) -> int | None:
    match = re.search(r"p(\d+)-", path.name.lower())
    return int(match.group(1)) if match else None


def _guard_store(project: Path) -> Path:
    return project / "outputs" / ".pptx-work" / ".guard"


def _binding_path(project: Path, agent_id: str) -> Path:
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(agent_id))[:60]
    return _guard_store(project) / f"packet-binding-{key}.json"


def _load_binding(project: Path, agent_id: str, work_dir: Path, round_at: str) -> dict | None:
    """The instance's binding for THIS work dir and round; stale round → expired."""
    binding_path = _binding_path(project, agent_id)
    try:
        loaded = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    if loaded.get("work_id") != work_dir.name:
        return None
    if str(loaded.get("round_at") or "") != round_at:
        # A binding from an earlier spawn round must not survive into this one —
        # expire it instead of letting an old shard scope leak across rounds.
        with contextlib.suppress(OSError):
            binding_path.unlink(missing_ok=True)
        return None
    packet = Path(str(loaded.get("packet") or ""))
    expected = str(loaded.get("packet_sha256") or "")
    try:
        packet_current = packet.is_file() and bool(expected) and _sha256(packet) == expected
    except OSError:
        packet_current = False
    if not packet_current:
        # Registration is not a one-time waiver. The packet remains the
        # builder's authority for its whole lifetime, so changing it revokes an
        # already registered instance before its next page read/edit.
        with contextlib.suppress(OSError):
            binding_path.unlink(missing_ok=True)
        return None
    return loaded


def _write_binding(project: Path, agent_id: str, binding: dict) -> None:
    try:
        _guard_store(project).mkdir(parents=True, exist_ok=True)
        _binding_path(project, agent_id).write_text(
            json.dumps(binding, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        pass  # enforcement bookkeeping must not take the work down



def _packet_inventory(work_dir: Path) -> str:
    """builder-packets/*.json 清单（名字 + 页号），给拒绝文案做一步恢复指引。

    2026-09-28 live：builder 连吃 5 次拒绝才找对 packet——前 4 次"先读 packet"
    没说读哪个，第 5 次"不在绑定内"没说哪个在。
    """
    entries = []
    try:
        for path in sorted((work_dir / "builder-packets").glob("*.json")):
            if path.name in {"active-round.json", "fallbacks.json"}:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                slides = data.get("assigned_slides") or []
                entries.append(f"{path.name}={list(slides)}")
    except OSError:
        pass
    return "; ".join(entries) or "(builder-packets/ 为空)"

def _enforce_packet_scope(event: dict, path: Path, work_dir: Path) -> str | None:
    """Runtime packet boundary for the isolated builder; None means allowed.

    With an active packet round the contract stops being prose:

    - **Registration.** The builder's Read of its own Builder Packet IS its shard
      registration: the guard binds agent_id → packet (slides included) at that
      moment. This is an explicit spawn-identity binding, not an inference from
      which page was touched first — and page access is refused until the packet
      has been read.
    - `no_reread_files` (agent-behavior-contract.json#presentation_builder.packet)
      may not be Read/Edited — the packet already projects those bytes;
    - page modules may only be used inside the bound packet's assigned slides.
      Pages outside it (other shards, completed pages) are refused outright.
    - Bindings are round-scoped: a new active round expires every previous
      binding, so a stale shard scope can never leak across rounds.

    No active round means the fallback path is in play and enforcement is off —
    the round's cost is still observable via builder-packets/fallbacks.json.
    """
    active = _active_round(work_dir)
    if active is None:
        return None
    project = _project(event)
    event_agent = str(event.get("agent_id"))
    round_at = str(active.get("at") or "")
    packets = [item for item in active.get("packets") or [] if isinstance(item, dict)]

    # Reading the task input registers the instance (and is always allowed).
    packet_dir = (work_dir / "builder-packets").resolve()
    try:
        in_packet_dir = path.resolve().relative_to(packet_dir) is not None
    except (OSError, ValueError):
        in_packet_dir = False
    if in_packet_dir:
        for item in packets:
            try:
                is_own = Path(str(item.get("packet") or "")).resolve() == path.resolve()
            except (OSError, ValueError):
                continue
            if is_own:
                expected = str(item.get("packet_sha256") or "")
                if expected and _sha256(path) != expected:
                    return (
                        "builder_guard: refused — Builder Packet bytes changed after the active "
                        "round was published. The main session must run `ppt_pipeline.py next "
                        "--work-dir <wd> --json` to publish a fresh hash-bound round."
                    )
                existing = _load_binding(project, event_agent, work_dir, round_at)
                if existing is not None:
                    try:
                        same_packet = (
                            Path(str(existing.get("packet") or "")).resolve()
                            == path.resolve()
                        )
                    except (OSError, ValueError):
                        same_packet = False
                    if not same_packet:
                        return (
                            "builder_guard: refused — this Builder instance is already bound "
                            f"to {existing.get('packet')} for the active round and cannot switch "
                            "shards by reading another Packet. The main session must publish a "
                            "fresh round to authorize a genuine re-shard."
                        )
                _write_binding(project, event_agent, {
                    "work_id": work_dir.name,
                    "packet": item.get("packet"),
                    "allowed_slides": item.get("assigned_slides"),
                    "round_at": round_at,
                    "packet_sha256": item.get("packet_sha256"),
                })
        return None

    if _matches_no_reread(path):
        return (
            "builder_guard: refused — this file is projected into your Builder Packet "
            f"({contract_ref()}#presentation_builder.packet.no_reread_files). Re-reading it "
            "pays the packet's context a second time. The packet's bytes are derived from "
            "the same sources; use the packet."
        )
    page = _page_number(path)
    if page is None:
        return None
    binding = _load_binding(project, event_agent, work_dir, round_at)
    if binding is None:
        return (
            "builder_guard: refused — no packet binding for this instance. Read your Builder "
            "Packet first (it is your task input under builder-packets/); that read registers "
            f"your shard scope ({contract_ref()}#presentation_builder.read_other_shard_page_modules "
            f"= false). Page access before registration is refused. 可用 packet：{_packet_inventory(work_dir)}"
        )
    if page not in (binding.get("allowed_slides") or []):
        return (
            f"builder_guard: refused — this instance is bound to packet "
            f"{binding.get('packet')} (slides {binding.get('allowed_slides')}); "
            f"pages/p{page:02d}-* is outside it "
            f"({contract_ref()}#presentation_builder.read_other_shard_page_modules = false). "
            "If your task genuinely needs different pages, return BUILDER_BLOCKED and let the "
            f"main session re-shard. 可用 packet：{_packet_inventory(work_dir)}"
        )
    return None


def page_brief_hint() -> str:
    """Runnable projection commands, one per mode (contract: page_brief_command).

    The templates come from the behavior contract itself — the guard must not
    grow a second copy of a command the contract already owns.
    """
    brief = plugin_root() / "skills" / "sp-deck" / "scripts" / "page_brief.py"
    presentation_builder = {}
    try:
        contract = json.loads(Path(contract_ref()).read_text(encoding="utf-8"))
        presentation_builder = contract.get("presentation_builder") or {}
    except (OSError, json.JSONDecodeError):
        pass
    commands = presentation_builder.get("page_brief_command") or {}
    lines = []
    for key, label in (
        ("whole_deck", "initial: whole deck in one call"),
        ("target_pages", "calibration/repair: target pages in one call"),
    ):
        template = str(commands.get(key) or "page_brief.py --work-dir <wd> --json")
        lines.append(f'  python "{brief}" {template.replace("page_brief.py ", "")}   ({label})')
    return "\n".join(lines)


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
        foreign = _foreign_work_refs(command, _project(event))
        if foreign:
            print(
                f"builder_guard: refused — 一个实例只有一个 work-dir（2026-09-28 live：builder "
                f"跨项目翻其它 deck 的页面仿样式）。引用了别的 work 区：{foreign}。"
                "风格依据走 packet 的 calibration_style / style-summary，不是别人家的页面。",
                file=sys.stderr,
            )
            return 2

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
    if event.get("agent_type") == BUILDER and event.get("agent_id"):
        foreign = _foreign_work_refs(str(path), project)
        if foreign:
            print(
                f"builder_guard: refused — 一个实例只有一个 work-dir；{foreign} 属于别的 work 区。"
                "风格依据走 packet 的 calibration_style / style-summary。",
                file=sys.stderr,
            )
            return 2
    if not _is_page_module(path, project):
        # Builders with an active packet are still scope-checked on non-page files:
        # no_reread artifacts (spec/AD/manifest/QA projections) may not be re-read.
        if event.get("agent_type") == BUILDER and event.get("agent_id"):
            try:
                rel = path.resolve().relative_to(project / "outputs" / ".pptx-work")
                if rel.parts:
                    work_dir = project / "outputs" / ".pptx-work" / rel.parts[0]
                    refusal = _enforce_packet_scope(event, path, work_dir)
                    if refusal:
                        print(refusal, file=sys.stderr)
                        return 2
            except (OSError, ValueError):
                pass
        return 0
    if event.get("agent_type") == BUILDER and event.get("agent_id"):
        try:
            rel = path.resolve().relative_to(project / "outputs" / ".pptx-work")
            if rel.parts:
                work_dir = project / "outputs" / ".pptx-work" / rel.parts[0]
                refusal = _enforce_packet_scope(event, path, work_dir)
                if refusal:
                    print(refusal, file=sys.stderr)
                    return 2
                _record_instance(project, str(event["agent_id"]), rel.parts[0])
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
