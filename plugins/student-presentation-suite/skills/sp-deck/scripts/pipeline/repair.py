from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

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
    pre_qa_failed_current,
    record,
    require_state,
    save_manifest,
    validate_manifest_authorization,
)
from pipeline.scheduler import slides_named_in_reports  # noqa: E402


def _cancel_pending_repair(
    manifest: dict[str, Any],
    work_dir: Path,
    build_info: dict[str, Any],
    blockers: int,
    args: argparse.Namespace,
) -> int:
    """Cancel a registered repair that turned out not to be page work.

    A repair can be recorded against blockers that later prove to be a gate-side
    defect (fixed in plugin code) — page work then cannot exist and a rebuild is
    refused as unchanged, deadlocking the pipeline at the builder boundary. The
    cancel is the sanctioned exit: it clears pending_repair, keeps the QA round
    and blocker history intact for the audit, and lets advance re-run QA against
    the current evidence. Requires a real reason; never touches repair_count.
    """
    if not build_info.get("pending_repair"):
        raise RefusedError(
            "no pending repair to cancel — register a repair first (or run advance, which "
            "re-runs QA on current evidence when no repair is pending)"
        )
    reason = str(args.reason or "").strip()
    if len(reason) < 24:
        raise RefusedError(
            "repair --cancel needs --reason describing why the registered repair is not page "
            "work (e.g. the blockers trace to a gate defect fixed in plugin code) — the "
            "decision stays in the manifest audit trail"
        )
    repairs = int(build_info.get("repair_count") or 0)
    build_info["pending_repair"] = False
    build_info.setdefault("cancelled_repairs", []).append(
        {
            "reason": reason,
            "blockers_at_cancellation": blockers,
            "repairs_used": repairs,
        }
    )
    # 0.27.1：cancel 是"这是门侧缺陷、页面无可修"的正式认定——run-15 live：认定后
    # advance 立即重新注册同一个 repair，cancel→advance 死循环把 fast 档 13 页卡死
    # 在 producing（qa/render/spec--force 全部无出口）。--waive 把当前 pre-QA 报告里
    # 的 critical/major finding 复制进 manifest 的 gate_waivers（stage+code+slide+
    # message 指纹），pre-QA 聚合在后续 build/QA 里按指纹剔除并保留 waived 计数。
    # 门报告文件本身不动（证据不可变）；豁免是可审计的一等操作，不是静默绕门。
    if getattr(args, "waive", False):
        waived_findings: list[dict[str, Any]] = []
        for report_name in (
            "pre-qa-structural-contract.json",
            "pre-qa-static-risk.json",
            "pre-qa-rendered.json",
            "pre-qa-actual-content.json",
            "pre-qa-quality.json",
        ):
            report_path = work_dir / report_name
            if not report_path.is_file():
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            findings = report.get("findings") or report.get("issues") or []
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                if str(finding.get("severity") or "").lower() not in {"critical", "major"}:
                    continue
                waived_findings.append(
                    {
                        "stage": report_name.removeprefix("pre-qa-").removesuffix(".json"),
                        "code": str(finding.get("code") or ""),
                        "slide": finding.get("slide"),
                        "message": str(finding.get("message") or "")[:200],
                    }
                )
        build_info.setdefault("gate_waivers", []).append(
            {
                "reason": reason,
                "blockers_at_cancellation": blockers,
                "findings": waived_findings,
            }
        )
        pre_qa_state = manifest.get("pre_qa") or {}
        pre_qa_state["ok"] = True
        pre_qa_state["waived"] = len(waived_findings)
        pre_qa_state["waiver_reason"] = reason
        manifest["pre_qa"] = pre_qa_state
        print(
            f"ppt_pipeline: {len(waived_findings)} pre-QA finding(s) waived as known gate "
            "limitations — recorded in build.gate_waivers; advance proceeds to render"
        )
    before = str(manifest.get("state"))
    record(manifest, "repair-cancelled", before, before, reason=reason, blockers=blockers)
    save_manifest(work_dir, manifest)
    if (manifest.get("pre_qa") or {}).get("waived"):
        print(
            "ppt_pipeline: pending repair cancelled; waived pre-QA findings recorded — "
            "advance proceeds to render on the waived state"
        )
    else:
        print(
            f"ppt_pipeline: pending repair cancelled ({blockers} blocker(s) remain recorded) — "
            "advance re-runs QA against the current evidence; a later real repair round is not spent"
        )
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    pre_qa_repair = bool(manifest and manifest.get("state") == "producing" and pre_qa_failed_current(manifest))
    require_state(manifest, {"qa", "producing"} if getattr(args, "cancel", False) or pre_qa_repair else {"qa"}, "repair")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    blockers = int((manifest.get("pre_qa" if pre_qa_repair else "qa") or {}).get("blockers") or 0)
    build_info = manifest.setdefault("build", {})
    if getattr(args, "cancel", False):
        return _cancel_pending_repair(manifest, work_dir, build_info, blockers, args)
    if blockers == 0 and not args.force:
        raise RefusedError("QA has no blockers; complete instead of repairing")
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
                "Inspect the persistent findings and change the approach before extending. "
                "Persistence does not prove a gate defect or authorize bypassing failed gates. "
                f"{suspect.get('advice') or ''}"
            )
        # D3 (informational): does the reason name the pages it claims to fix?
        # A grant whose reason never touches the current blocker pages is recorded
        # with that mismatch for the audit trail — warned about, never refused,
        # because digits in prose are only a hint.
        blocker_pages = slides_named_in_reports(work_dir, ("pipeline-qa.json",))
        digit_tokens = {int(match) for match in re.findall(r"\d{1,3}", reason)}
        named_pages = sorted(digit_tokens & set(blocker_pages))
        if blocker_pages and not named_pages:
            print(
                "ppt_pipeline: WARNING — extend-reason names none of the current blocker pages "
                f"{blocker_pages}; the grant is recorded with that mismatch. Name the pages "
                "(or the deck-level defect) so the next round's convergence is readable."
            )
        build_info.setdefault("repair_budget_grants", []).append(
            {
                "rounds": int(args.extend),
                "reason": reason,
                "trend": convergence.get("trend"),
                "blockers_at_grant": blockers,
                "repairs_used": repairs,
                "suspect_gate_defect": suspect or None,
                "blocker_pages": blocker_pages,
                "reason_named_pages": named_pages,
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
    if pre_qa_repair:
        # Keep the failed result; only a successful rebuild can clear it.
        manifest["pre_qa"]["rounds"] = 0
    build_info["carryover_builds"] = 0
    build_info.setdefault("repair_reasons", []).append(args.reason)
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(manifest, "repair", before, "producing", repair_count=repairs + 1, reason=args.reason)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "producing", reason=args.reason)
    print(f"ppt_pipeline: repair {repairs + 1}/{budget['effective']} — change generator, then build → render → qa")
    return 0


