#!/usr/bin/env python3
"""Guard direct Bash entrypoints into presentation production internals.

Historically cost_guard learned one forbidden internal script at a time. That
approach is brittle: every new production helper creates another way for an
agent to bypass the state machine until a new regex is added.

This hook owns execution-entry integrity. For ``skills/sp-deck/scripts`` it uses
a small public allow-list and denies every other direct script. It also owns the
few plugin-root production wrappers that must never be used to bypass the
pipeline: evidence-map compilation and direct PPTX generation. Normal project
Bash, other skills, and unrelated plugin-root utilities remain out of scope.

One deliberate exception (owner decision 2026-09-28): the plugin's own source
tree — the marketplace checkout or the installed cache — is a maintenance
context, not a production project, so the whole guard passes through there
(``in_source_repository``). Deterministic marker check only; a user project
never carries the marketplace layout, so PPT-production enforcement is
unchanged everywhere it can actually happen.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import pipeline_context  # noqa: E402
from hook_events import read_event, terminal_help_probe  # noqa: E402

PUBLIC_DECK_ENTRYPOINTS = frozenset(
    {
        "ppt_pipeline.py",
        "calibration_preview.py",
        "visual_reference_select.py",
        # page_brief.py: the projection tool the builder is *required* to use
        # (spawn-templates.md) and the one builder_guard redirects inline `node -e`
        # to. Leaving it off this list re-created the 0.13.4 failure — the command
        # the instructions mandate being refused by the guard that polices it.
        "page_brief.py",
        # builder_packet.py: generates the Builder Packet (v0.15 Batch 2). The
        # pipeline generates packets inside `next`; the CLI form exists for a
        # calibration slide override, and refusing it would recreate the same
        # mandated-command-refused-by-guard dead end as page_brief.py above.
        "builder_packet.py",
        # run_gates.py is the canonical gate orchestrator (run_gates.sh only locates
        # an interpreter); on hosts where `sh` resolves to WSL, the .sh wrapper cannot
        # open a `C:/...` path and exits 127, so the python form must stay runnable.
        "run_gates.py",
        "run_gates.sh",
    }
)
BUILDER = "student-presentation-suite:presentation-builder"
# Owned by pipeline_context (shared with runtime_evidence arming and cost_guard
# run recognition); see its PIPELINE_ACTIONS docstring.
PUBLIC_PIPELINE_ACTIONS = pipeline_context.PIPELINE_ACTIONS
ROOT_PRODUCTION_INTERNALS = frozenset(
    {
        "research_pack_to_evidence.py",
        "run_with_pptxgenjs.js",
    }
)
# A path counts as an *invocation* only when an interpreter token immediately
# precedes it, or when the command opens with the path itself (direct exec).
# sed/grep/cat/git-diff text that merely mentions the same path is a read;
# refusing reads was the 2026-09-26 trap (deck maintenance blocked for carrying
# script names). Detection stays conservative: `FOO=bar python x.py` still
# counts (`=` joins the boundary class); exotic shells (`cat x.py | python`)
# stay accepted false negatives — this is a discipline guard, not an adversary.
_INTERPRETER_TOKEN = r"(?:python3?(?:\.\d+)?|py|sh|bash|node|pwsh|powershell|source)(?:\.exe)?"


def _anchored(tail: str) -> re.Pattern[str]:
    """Match *tail* only where a shell would execute it."""
    return re.compile(
        r"(?:"
        # interpreter form: boundary + interpreter + flags + quote + prefix + path
        r"(?:^|[\s;&|(=])(?:" + _INTERPRETER_TOKEN + r")"
        r"(?:\s+(?:-{1,2}[\w.-]+))*\s+[\"']?(?:\./)?[^\s\"';&|]*"
        r"|"
        # direct-exec form: the command opens with the (possibly quoted) path
        r"^[\"']?(?:\./)?[^\s\"';&|]*"
        r")"
        + tail,
        re.IGNORECASE,
    )


_DECK_SCRIPT_RE = _anchored(
    r"skills[\\/]sp-deck[\\/]scripts[\\/](?P<name>[A-Za-z0-9_.-]+\.(?:py|sh))"
)
_ROOT_SCRIPT_RE = _anchored(
    r"(?:\$\{CLAUDE_PLUGIN_ROOT\}|student-presentation-suite(?:[\\/][^\\/\s\"']+)?)"
    r"[\\/]scripts[\\/](?P<name>[A-Za-z0-9_.-]+\.(?:py|js|sh))"
)
_PIPELINE_ACTION_RE = re.compile(
    r"ppt_pipeline\.py(?:[\"']?)(?:\s+)(?P<action>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_RUN_WITH_INVOCATION_RE = _anchored(
    r"[^\"'\s;&|]*run_with_pptxgenjs\.js[\"']?(?P<args>.*?)(?=(?:&&|\|\||;|\n|\|)|$)"
)
_PROBE_TOKEN_RE = re.compile(r"(?:^|\s)--probe(?=$|\s)", re.IGNORECASE)


def _unique_matches(pattern: re.Pattern[str], command: str) -> list[str]:
    normalized = (command or "").replace("\\", "/")
    found: list[str] = []
    for match in pattern.finditer(normalized):
        name = match.group("name")
        if name not in found:
            found.append(name)
    return found


def direct_deck_scripts(command: str) -> list[str]:
    """Return unique sp-deck script basenames referenced by a shell command."""
    return _unique_matches(_DECK_SCRIPT_RE, command)


def direct_root_scripts(command: str) -> list[str]:
    """Return plugin-root scripts referenced through an actual plugin path."""
    return _unique_matches(_ROOT_SCRIPT_RE, command)


def _all_builder_invocations_are_probe(command: str) -> bool:
    """Allow direct builder access only when every invocation is a runtime probe."""
    matches = list(_RUN_WITH_INVOCATION_RE.finditer(command))
    return bool(matches) and all(_PROBE_TOKEN_RE.search(match.group("args")) for match in matches)


def _builder_allowlist() -> str:
    """Absolute-path discovery surface the isolated builder may actually run.

    Main-session refusals point at `ppt_pipeline.py next`, which the builder is
    forbidden to run; a live builder hit that dead end 14 times in one
    calibration round (2026-09-17) and fell back to hand-written evidence.
    """
    here = Path(__file__).resolve().parents[1]
    parts = []
    helper = here / "scripts" / "pptx-helpers.js"
    select = here / "skills" / "sp-deck" / "scripts" / "visual_reference_select.py"
    brief = here / "skills" / "sp-deck" / "scripts" / "page_brief.py"
    if helper.is_file():
        parts.append(f'node "{helper}" --describe')
    if select.is_file():
        parts.append(f'python "{select}" --role <role> --grammar <grammar> --visual-strategy <strategy> --output composition/<id>.json')
    if brief.is_file():
        parts.append(
            f'python "{brief}" --work-dir <wd> --json'
            " (whole deck, initial) or with --slides <ids> (calibration/repair target pages)"
        )
    return "; ".join(parts) or "pptx-helpers.js --describe and visual_reference_select.py"


def _marketplace_marker(base: Path) -> Path:
    """The file only the marketplace checkout (or a vendored copy) carries."""
    return base / "plugins" / "student-presentation-suite" / ".claude-plugin" / "plugin.json"


def in_source_repository(event: dict) -> bool:
    """True when the session lives in the plugin's own source tree.

    Deterministic signals only (Batch 6.1 philosophy, owner decision
    2026-09-28): the marketplace layout above ``CLAUDE_PROJECT_DIR`` or the
    event cwd, or the cwd sitting inside a ``student-presentation-suite``
    plugin tree (source checkout or installed cache). PPT production in a user
    project satisfies neither, so enforcement there is unchanged; plugin
    maintenance may run internals directly to debug them.
    """
    bases = [
        str(os.environ.get("CLAUDE_PROJECT_DIR") or ""),
        str(event.get("cwd") or ""),
    ]
    seen: set[Path] = set()
    for raw in bases:
        if not raw:
            continue
        probe = Path(raw).resolve()
        for ancestor in (probe, *probe.parents):
            if ancestor in seen:
                continue
            seen.add(ancestor)
            if _marketplace_marker(ancestor).is_file():
                return True
            if ancestor.name == "student-presentation-suite" and (
                ancestor / ".claude-plugin" / "plugin.json"
            ).is_file():
                return True
    return False


def check_bash(command: str, builder: bool = False) -> str | None:
    normalized = (command or "").replace("\\", "/")

    root_scripts = [name for name in direct_root_scripts(command) if name in ROOT_PRODUCTION_INTERNALS]
    if "research_pack_to_evidence.py" in root_scripts:
        return (
            "Direct evidence-map compilation is refused. Put research-pack.json in the work-dir "
            "and run `ppt_pipeline.py plan --work-dir <wd>`; the pipeline owns evidence-map "
            "compilation and Slide Spec freezing."
        )
    if "run_with_pptxgenjs.js" in root_scripts and not _all_builder_invocations_are_probe(normalized):
        return (
            "Direct run_with_pptxgenjs.js generation is refused. The pipeline owns build, "
            "normalization and QA binding; run `ppt_pipeline.py next --work-dir <wd> --json` "
            "and invoke the stable command it returns. `--probe` remains allowed for runtime checks."
        )

    scripts = direct_deck_scripts(command)
    if not scripts:
        return None
    blocked = [name for name in scripts if name not in PUBLIC_DECK_ENTRYPOINTS]
    if blocked:
        if terminal_help_probe(normalized):
            return None
        names = ", ".join(blocked)
        if builder:
            return (
                "Direct execution of internal sp-deck production scripts is refused for the "
                f"isolated builder: {names}. Allowed discovery/composition surface: "
                f"{_builder_allowlist()}. Everything else is run by the MAIN session "
                "after you return."
            )
        return (
            "Direct execution of internal sp-deck production scripts is refused: "
            f"{names}. Use ppt_pipeline.py next --work-dir <wd> --json and invoke only "
            "the stable entrypoint it returns. Internal validators/render/build helpers "
            "must be reached through ppt_pipeline.py or run_gates.sh."
        )
    if "ppt_pipeline.py" in scripts:
        match = _PIPELINE_ACTION_RE.search(normalized)
        if (not match or match.group("action") not in PUBLIC_PIPELINE_ACTIONS) and not terminal_help_probe(normalized):
            return (
                "ppt_pipeline.py direct Bash is limited to the stable actions: "
                + ", ".join(sorted(PUBLIC_PIPELINE_ACTIONS))
                + ". Use `ppt_pipeline.py next --work-dir <wd> --json` instead of probing internals."
            )
    return None


def handle(event: dict[str, Any]) -> int:
    if event.get("hook_event_name") not in {None, "PreToolUse"}:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    if in_source_repository(event):
        # Maintenance session in the plugin's own tree: internals may be run
        # directly for debugging; pipeline discipline targets production.
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    builder = str(event.get("agent_type") or "") == BUILDER
    refusal = check_bash(command, builder=builder)
    if refusal:
        print(f"production_entry_guard: {refusal}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    try:
        event = read_event()
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    return handle(event)


if __name__ == "__main__":
    raise SystemExit(main())
