#!/usr/bin/env python3
"""sp-deck deterministic production pipeline.

The agent owns semantic and visual judgement. This CLI owns execution order,
state, rendering, idempotence, QA dependencies, repair budget, and delivery.
Production is driven by one build-manifest.json; the legacy workflow state is
used only as the intake authorization source and is mirrored automatically.

    plan      verify intake, freeze, preflight, scaffold pages/  -> planned
    build     run the generator; refuses unsplitted deck.js      -> producing
    render    raster pages + PDF + contact-sheet.png (hash-cached)
    prepare-deliverables  generate confirmed support/export files
    qa        QA DAG: artifact gates stop, content gates all run -> qa
    repair    QA blockers -> producing (budget from contract)
    complete  qa + delivery ok                                   -> complete
    status    one-line manifest summary
    next      what to read and which command to run next

Exit codes: 0 = ok, 2 = refused (illegal state, failed gate, missing input).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Batch 6 modularization: this file is the CLI facade — argparse, dispatch and
# the compatibility namespace the tests pin (re-exports are INTENTIONAL; F401 is
# suppressed). The implementation lives in the `pipeline/` package beside it:
# core primitives in core.py, one module per production stage, dispatch/advance
# for the machine conversation. Tests patch `pp._core._runner` — the shared
# subprocess seam every command reads at call time.
import builder_packet as _packet  # noqa: E402,F401
import generator_scaffold as _scaffold  # noqa: E402,F401
from pipeline import core as _core  # noqa: E402,F401
from pipeline.advance import (  # noqa: E402,F401
    BUILDER_AGENT,
    CRITIC_AGENT,
    MAX_ADVANCE_STEPS,
    _run_quietly,
    cmd_advance,
)
from pipeline.build import cmd_build, enforce_page_copy_fidelity  # noqa: E402,F401
from pipeline.complete import cmd_complete, cmd_status  # noqa: E402,F401
from pipeline.convergence import (  # noqa: E402,F401
    gate_regressions,
    repair_budget,
    repair_convergence,
)
from pipeline.core import (  # noqa: E402,F401
    BUILD_FROM,
    BUILDER,
    CONTRACT,
    CONTRACT_PATH,
    EVIDENCE_COMPILER,
    GATE_HISTORY_NAME,
    HERE,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    MAX_CARRYOVER_BUILDS,
    MAX_PARALLEL_BUILDERS,
    MAX_PRE_QA_REBUILDS,
    MAX_REPAIRS,
    MAX_REPAIRS_HARD_CAP,
    PARALLEL_MIN_PAGES,
    PPTX_TOOL,
    QA_DERIVED_AFTER_UPSTREAM_FAILURE,
    QA_FROM,
    QA_HARD_STOP_STAGES,
    QA_ORDER,
    ROOT,
    RefusedError,
    Runner,
    Stage,
    _gate_inputs,
    _gate_stage,
    _runner,
    archive_stale_render,
    bind,
    binding_is_current,
    build_qa_stages,
    collect,
    dedupe,
    default_workflow_state,
    execution_receipt,
    generator_changed_since_build,
    generator_files,
    generator_fingerprint,
    load_contract,
    load_json,
    load_manifest,
    manifest_path,
    mirror_workflow_state,
    now,
    pptx_path,
    pre_qa_failed_current,
    pre_qa_stages,
    qa_input_fingerprint,
    record,
    render_is_current,
    require_state,
    run_command,
    run_pre_qa_gates,
    save_manifest,
    sha256_file,
    stable_hash,
    validate_intake,
    validate_manifest_authorization,
    validate_work_dir,
    write_stage_summary,
)
from pipeline.deliverables import (  # noqa: E402,F401
    cmd_prepare_deliverables,
    deliverables_are_current,
    requested_prepared_deliverables,
)
from pipeline.dispatch import build_next_payload, cmd_next  # noqa: E402,F401
from pipeline.doctor import cmd_doctor  # noqa: E402,F401
from pipeline.handoff import cmd_handoff  # noqa: E402,F401
from pipeline.plan import _research_budget, cmd_plan, compile_research_for_plan  # noqa: E402,F401
from pipeline.qa import cmd_qa  # noqa: E402,F401
from pipeline.render import cmd_render, make_contact_sheet, make_contact_thumb  # noqa: E402,F401
from pipeline.repair import cmd_repair  # noqa: E402,F401
from pipeline.scheduler import (  # noqa: E402,F401
    builder_instance_reuse,
    builder_shards,
    merge_speaker_note_shards,
    observe_packet_failure,
    packet_fallbacks,
    page_files_by_slide,
    record_packet_fallback,
    remaining_scaffold_slides,
    slides_named_in_reports,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="verify intake, preflight and freeze -> planned")
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--production-mode", choices=["create", "edit_ooxml", "rebuild_from_source"])
    plan.add_argument("--workflow-state", type=Path, help="confirmed work-dir/workflow-state.json")
    plan.add_argument("--slide-spec", type=Path, required=True)
    plan.add_argument("--validation-report", type=Path, required=True)
    plan.add_argument("--art-direction", type=Path, required=True)
    plan.add_argument("--visual-generation-report", type=Path)
    plan.add_argument("--research-pack", "--pack", type=Path, dest="research_pack")
    plan.add_argument("--research-validation", type=Path)
    plan.add_argument("--evidence-map", type=Path)
    plan.add_argument(
        "--receipt-policy", choices=["require", "allow-missing"], default=None,
        help="allow-missing: continue without the hook-owned isolated-run receipt "
        "(degraded mode, recorded in the manifest and inherited by later stages of "
        "this work-id); default: inherit the recorded policy, else require. Use after "
        "doctor reports receipts suspected-unavailable for this runtime",
    )
    plan.add_argument(
        "--research-execution",
        type=Path,
        help=argparse.SUPPRESS,
    )
    plan.add_argument("--reason", default="initial approved production plan")
    plan.add_argument("--force", action="store_true")
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build", help="build once; repeated builds require repair + changed generator")
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--entry", type=Path)
    build.add_argument("--output-name", default="deck.pptx")
    build.add_argument("generator_args", nargs="*")
    build.set_defaults(func=cmd_build)

    render = sub.add_parser("render", help="render all pages once and create a contact sheet")
    render.add_argument("--work-dir", type=Path, required=True)
    render.add_argument("--prefix", default="slide")
    render.add_argument("--cols", type=int, default=3)
    render.set_defaults(func=cmd_render)

    prepare = sub.add_parser(
        "prepare-deliverables",
        help="generate and hash-bind confirmed support outputs and PDF export",
    )
    prepare.add_argument("--work-dir", type=Path, required=True)
    prepare.set_defaults(func=cmd_prepare_deliverables)

    qa = sub.add_parser("qa", help="run QA DAG (content gates all run, then one blocker set); identical inputs reuse prior result")
    qa.add_argument("--work-dir", type=Path, required=True)
    qa.add_argument("--visual-review", type=Path)
    qa.add_argument("--notes", type=Path)
    qa.add_argument("--preview", type=Path, nargs="+", action="extend")
    qa.add_argument("--allow-missing-preview", action="store_true")
    qa.add_argument(
        "--receipt-policy", choices=["require", "allow-missing"], default=None,
        help="allow-missing: accept the visual review without the hook-owned critic "
        "receipt (degraded mode, recorded in the manifest); default: inherit this "
        "work-id's recorded policy, else require",
    )
    qa.add_argument("--max-items", type=int, default=12)
    qa.set_defaults(func=cmd_qa)

    repair = sub.add_parser("repair", help=f"qa blockers -> producing; base budget {MAX_REPAIRS}")
    repair.add_argument("--work-dir", type=Path, required=True)
    repair.add_argument("--reason", required=True)
    repair.add_argument(
        "--extend",
        type=int,
        default=0,
        help=f"grant N extra rounds beyond the base budget (recorded in the manifest; hard cap {MAX_REPAIRS_HARD_CAP})",
    )
    repair.add_argument(
        "--extend-reason",
        help="required with --extend: the round-over-round blocker diff that justifies more rounds",
    )
    repair.add_argument("--force", action="store_true")
    repair.set_defaults(func=cmd_repair)

    complete = sub.add_parser("complete", help="qa + delivery ok -> complete")
    complete.add_argument("--work-dir", type=Path, required=True)
    complete.set_defaults(func=cmd_complete)

    status = sub.add_parser("status", help="one-line manifest summary")
    status.add_argument("--work-dir", type=Path, required=True)
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser(
        "doctor",
        help="environment probe: receipt deliverability, toolchain, renderers, work-dir writability",
    )
    doctor.add_argument("--work-dir", type=Path, required=True)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    nxt = sub.add_parser("next", help="what to read and which command to run next")
    nxt.add_argument("--work-dir", type=Path, required=True)
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)

    advance = sub.add_parser(
        "advance",
        help=f"run deterministic steps until an agent/user boundary (cap {MAX_ADVANCE_STEPS})",
    )
    advance.add_argument("--work-dir", type=Path, required=True)
    advance.add_argument("--json", action="store_true", help="print the full dispatch (default: brief)")
    advance.add_argument(
        "--brief-json", action="store_true",
        help="alias of the default brief output (status, next action, essential paths)",
    )
    advance.add_argument(
        "--resume-after-handoff", action="store_true",
        help="unlock the CD-8 session brake explicitly (recorded); a real new session unlocks automatically",
    )
    advance.set_defaults(func=cmd_advance)

    handoff = sub.add_parser(
        "handoff",
        help="write the deterministic session-handoff resume brief (CD-8 session budget)",
    )
    handoff.add_argument("--work-dir", type=Path, required=True)
    handoff.add_argument("--json", action="store_true")
    handoff.set_defaults(func=cmd_handoff)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_work_dir(args.work_dir)
        return args.func(args)
    except RefusedError as exc:
        # 只说"为什么拒绝"会让 agent 去猜下一步（2026-09-16 实测：evidence-map
        # 环节靠试不同参数摸了约 10 轮）。这里固定把 next 命令也一并给出。
        print(f"ppt_pipeline: REFUSED — {exc}", file=sys.stderr)
        print(
            "ppt_pipeline: next step — "
            f'"{sys.executable}" "{HERE / "ppt_pipeline.py"}" next --work-dir "{args.work_dir}"',
            file=sys.stderr,
        )
        return 2




if __name__ == "__main__":
    sys.exit(main())
