from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout as _redirect_stdout
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline import core  # noqa: E402
from pipeline.build import (  # noqa: E402
    cmd_build,
)
from pipeline.complete import (  # noqa: E402
    cmd_complete,
)
from pipeline.core import (  # noqa: E402
    HERE,
    RefusedError,
    load_manifest,
    record,
    save_manifest,
)
from pipeline.dispatch import (  # noqa: E402
    build_next_payload,
)
from pipeline.render import (  # noqa: E402
    cmd_render,
)
from pipeline.repair import (  # noqa: E402
    cmd_repair,
)
from pipeline.scheduler import (  # noqa: E402
    packet_fallbacks,
)

MAX_ADVANCE_STEPS = 8
BUILDER_AGENT = "student-presentation-suite:presentation-builder"
CRITIC_AGENT = "student-presentation-suite:visual-critic"


def _run_quietly(func, ns: argparse.Namespace) -> int:
    """Execute one deterministic step with its human log lines on stderr.

    advance --json must keep stdout pure JSON: the wrapped commands (render /
    repair / complete) each print progress lines, and a log line ahead of the
    JSON would break every machine consumer."""
    with _redirect_stdout(sys.stderr):
        return func(ns)


def cmd_advance(args: argparse.Namespace) -> int:
    """Run every deterministic step until a genuine agent/user boundary (Batch 3).

    The model used to drive mechanical transitions by hand — run the calibration
    preview, then read the output, then run render, then read again, then record
    the repair, then spawn. Each of those is a full model round-trip that adds no
    intelligence. `advance` performs the deterministic transitions itself —
    including the builds (first production build once calibration is green and no
    scaffold stubs remain; rebuild once a repair/pre-QA-fix builder's edits moved
    the generator fingerprint) — and stops only where judgement is required:

    - ``needs_agent`` — spawn a builder (packet paths included) or the
      independent critic; the main session spawns, advance never does;
    - ``needs_user`` — intake confirmation, user-provided inputs, or the
      edit-mode OOXML edits that only the main session can apply;
    - ``complete`` — the deck is delivered.

    ``next`` stays as the debug/introspection view of the same dispatch. A step
    cap bounds the loop; a refusal surfaces as ``status: refused`` with the
    error instead of guessing past it. Every call is recorded in the manifest
    history so `pipeline_report.py` can report how many round-trips collapsed.
    """
    work_dir = args.work_dir.resolve()
    actions: list[str] = []
    result: dict[str, Any] = {}
    step_cap_hit = False
    start_state = str((load_manifest(work_dir) or {}).get("state") or "(absent)")
    try:
        for _ in range(MAX_ADVANCE_STEPS):
            payload = build_next_payload(work_dir)
            state = str(payload.get("state") or "(absent)")
            manifest = load_manifest(work_dir)
            if payload.get("agent"):
                result = {"status": "needs_agent", "actions": actions, "dispatch": payload}
                # Hoist the spawn fields so every builder/critic boundary answers the
                # same shape (agent / mode / packets) on top of the full dispatch.
                result["agent"] = payload["agent"]
                if payload.get("builder_mode"):
                    result["mode"] = payload["builder_mode"]
                result["packets"] = payload.get("builder_packets") or []
                if not result["packets"] and payload.get("builder_packet"):
                    result["packet"] = payload["builder_packet"]
                break
            command = str(payload.get("next_command") or "")
            bordered = f" {command} "
            if state in {"(absent)", "intake_pending"} or " plan " in bordered or " status " in command or not command:
                result = {
                    "status": "needs_user", "actions": actions,
                    "reason": "intake confirmation or user-provided inputs required",
                    "dispatch": payload,
                }
                break
            if state == "complete":
                result = {"status": "complete", "actions": actions, "dispatch": payload}
                break
            if " build " in bordered:
                if state == "planned" and str((manifest or {}).get("mode") or "") == "edit_ooxml":
                    # An edit-mode first build before the main session applied the edit
                    # intent would package the unchanged source deck and sail straight
                    # to complete — the edit is the one input advance cannot infer.
                    result = {
                        "status": "needs_user", "actions": actions,
                        "reason": "edit_ooxml: apply the edit intent to ooxml/ in the main session, then run advance",
                        "dispatch": payload,
                    }
                    break
                build_info = (manifest or {}).get("build") or {}
                recorded_entry = Path(str(build_info.get("entry") or "")) if build_info.get("entry") else None
                recorded_pptx = str(((build_info.get("pptx") or {}).get("path")) or "")
                output_name = Path(recorded_pptx).name if recorded_pptx else "deck.pptx"
                _run_quietly(cmd_build, argparse.Namespace(
                    work_dir=work_dir, entry=recorded_entry, output_name=output_name,
                    generator_args=list(build_info.get("generator_args") or []),
                ))
                actions.append("build")
                continue
            if "calibration_preview.py" in command:
                ids: list[str] = []
                if "--slides" in command:
                    for token in command.split("--slides", 1)[1].split():
                        if not token.isdigit():
                            break
                        ids.append(token)
                argv = [sys.executable, str(HERE / "calibration_preview.py"), "--work-dir", str(work_dir)]
                if ids:
                    argv += ["--slides", *ids]
                argv.append("--json")
                proc = core._runner(argv)
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or "").strip()
                    raise RefusedError(f"calibration preview failed: {detail[:300]}")
                actions.append("calibration_preview")
                continue
            if " render " in bordered:
                _run_quietly(cmd_render, argparse.Namespace(work_dir=work_dir, cols=3, prefix="slide"))
                actions.append("render")
                continue
            if " repair " in bordered:
                _run_quietly(cmd_repair, argparse.Namespace(
                    work_dir=work_dir, reason="advance: recorded QA blockers",
                    extend=0, extend_reason=None, force=False,
                ))
                actions.append("repair")
                # The repair builder boundary comes from build_next_payload itself
                # (producing + pending_repair): ONE dispatch resolver, ONE boundary
                # schema — repair_budget, builder_shards, packets and the fallback
                # observability all ride along instead of a hand-built envelope that
                # silently dropped packet failures.
                continue
            if " complete " in bordered:
                _run_quietly(cmd_complete, argparse.Namespace(work_dir=work_dir))
                actions.append("complete")
                continue
            result = {
                "status": "needs_user", "actions": actions,
                "reason": f"unroutable deterministic command: {command[:160]}",
                "dispatch": payload,
            }
            break
        else:
            step_cap_hit = True
            result = {
                "status": "needs_user", "actions": actions,
                "reason": f"step cap {MAX_ADVANCE_STEPS} reached without an agent boundary; inspect with next --json",
            }
    except RefusedError as exc:
        result = {"status": "refused", "actions": actions, "error": str(exc)[:300]}
    result["packet_fallback_count"] = len(packet_fallbacks(work_dir))
    try:
        manifest = load_manifest(work_dir)
        if manifest is not None:
            # The advance ledger (Batch 3.1): one history entry per call, so
            # pipeline_report.py can report collapsed round-trips without parsing
            # session transcripts.
            record(
                manifest, "advance", start_state, str(manifest.get("state") or "?"),
                status=result["status"], actions=list(actions), step_cap=step_cap_hit,
            )
            save_manifest(work_dir, manifest)
    except Exception as exc:  # the ledger must never turn a finished advance into a failure
        result["ledger_error"] = str(exc)[:160]
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        line = f"ppt_pipeline: advance → {result['status']}"
        if result.get("mode"):
            line += f" ({result['mode']})"
        if actions:
            line += f" — executed: {', '.join(actions)}"
        print(line)
    return 0 if result["status"] != "refused" else 2


