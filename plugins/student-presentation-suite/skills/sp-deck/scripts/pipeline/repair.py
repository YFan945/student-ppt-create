from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline.convergence import (  # noqa: E402
    repair_budget,
    repair_convergence,
)
from pipeline.core import (  # noqa: E402
    MAX_REPAIRS,
    MAX_REPAIRS_HARD_CAP,
    RefusedError,
    load_manifest,
    mirror_workflow_state,
    record,
    require_state,
    save_manifest,
    validate_manifest_authorization,
)


def cmd_repair(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "repair")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    blockers = int((manifest.get("qa") or {}).get("blockers") or 0)
    if blockers == 0 and not args.force:
        raise RefusedError("QA has no blockers; complete instead of repairing")
    build_info = manifest.setdefault("build", {})
    repairs = int(build_info.get("repair_count") or 0)
    if args.extend:
        # 提额必须写明"这轮要修什么、上轮 blocker 差异是什么"：契约要求的不是更大的预算，
        # 而是不同的做法。trend 一并记录，让"flat/worse 还继续加轮次"在报告里留下痕迹。
        reason = str(args.extend_reason or "").strip()
        if len(reason) < 24:
            raise RefusedError(
                "repair --extend needs --extend-reason describing the round-over-round blocker "
                "diff (what was resolved, what is new). Repeating the same approach with a bigger "
                "budget is not a repair strategy — `next --json` carries repair_convergence."
            )
        budget = repair_budget(manifest)
        if budget["effective"] + int(args.extend) > MAX_REPAIRS_HARD_CAP:
            raise RefusedError(
                f"repair budget hard cap reached: base {MAX_REPAIRS} + granted {budget['granted']} "
                f"+ requested {int(args.extend)} exceeds {MAX_REPAIRS_HARD_CAP} "
                f"(contract max_repairs_hard_cap). Deliver what is on disk as `incomplete` instead."
            )
        convergence = repair_convergence(work_dir) or {}
        suspect = convergence.get("suspect_gate_defect") or {}
        share = suspect.get("share_of_current")
        if isinstance(share, (int, float)) and share >= 0.8:
            codes = ", ".join(f"{code} x{count}" for code, count in (suspect.get("codes") or {}).items())
            raise RefusedError(
                f"repair budget extension refused: {suspect.get('blockers')} of {blockers} blockers "
                f"({share:.0%}) are identical in two consecutive rounds ({codes or 'see gate-history.json'}). "
                "More rounds cannot move a group that no previous round moved — this is a gate-side "
                "candidate, not page work. Check it once against the artifact, then either it is a real "
                "defect with a page-level fix (name it in --extend-reason) or it is a false positive to "
                "record as a known gate limitation and deliver around. "
                f"{suspect.get('advice') or ''}"
            )
        build_info.setdefault("repair_budget_grants", []).append(
            {
                "rounds": int(args.extend),
                "reason": reason,
                "trend": convergence.get("trend"),
                "blockers_at_grant": blockers,
                "repairs_used": repairs,
                "suspect_gate_defect": suspect or None,
            }
        )
        print(
            f"ppt_pipeline: repair budget extended by {int(args.extend)} "
            f"(base {MAX_REPAIRS} + granted {budget['granted'] + int(args.extend)}, "
            f"hard cap {MAX_REPAIRS_HARD_CAP}; trend {convergence.get('trend') or 'unknown'})"
        )
    budget = repair_budget(manifest)
    if repairs >= budget["effective"]:
        raise RefusedError(
            f"repair budget exhausted ({repairs}/{budget['effective']}); mark the task incomplete"
        )
    build_info["repair_count"] = repairs + 1
    build_info["pending_repair"] = True
    build_info["carryover_builds"] = 0
    build_info.setdefault("repair_reasons", []).append(args.reason)
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(manifest, "repair", before, "producing", repair_count=repairs + 1, reason=args.reason)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "producing", reason=args.reason)
    print(f"ppt_pipeline: repair {repairs + 1}/{budget['effective']} — change generator, then build → render → qa")
    return 0


