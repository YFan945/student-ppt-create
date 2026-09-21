from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from calibration_review import QA_BLOCKING_SEVERITIES  # noqa: E402

from pipeline.convergence import (  # noqa: E402
    gate_regressions,
)
from pipeline.core import (  # noqa: E402
    GATE_HISTORY_NAME,
    MANIFEST_VERSION,
    QA_DERIVED_AFTER_UPSTREAM_FAILURE,
    QA_FROM,
    QA_HARD_STOP_STAGES,
    QA_ORDER,
    RefusedError,
    bind,
    binding_is_current,
    build_qa_stages,
    collect,
    dedupe,
    execution_receipt,
    load_json,
    load_manifest,
    mirror_workflow_state,
    pptx_path,
    qa_input_fingerprint,
    record,
    render_is_current,
    require_state,
    save_manifest,
    sha256_file,
    stable_hash,
    validate_manifest_authorization,
    work_id_receipt_policy,
    write_stage_summary,
)
from pipeline.deliverables import (  # noqa: E402
    deliverable_bindings,
    deliverables_are_current,
    requested_prepared_deliverables,
)


def cmd_qa(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, QA_FROM, "qa")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    pptx = pptx_path(manifest)
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    visual_review = args.visual_review.resolve() if args.visual_review else None
    vgr = work_dir / "visual-generation-report.json"
    if vgr.is_file():
        # This report is regenerated after every repair round. Keep it outside
        # frozen plan inputs and refresh the binding under pipeline control.
        manifest.setdefault("inputs", {}).pop("visual_generation_report", None)
        manifest.setdefault("generation_evidence", {})[
            "visual_generation_report"
        ] = bind(vgr)
    notes = args.notes.resolve() if args.notes else None
    previews = [Path(p).resolve() for p in (args.preview or [])]
    if not render_is_current(manifest):
        raise RefusedError("QA requires current, hash-verified render evidence; run render")
    if requested_prepared_deliverables(manifest) and not deliverables_are_current(manifest):
        raise RefusedError(
            "requested support/export deliverables are stale or missing; run prepare-deliverables"
        )
    prepared_outputs = (manifest.get("deliverables") or {}).get("outputs") or {}
    prepared_notes = prepared_outputs.get("speaker-notes") or {}
    if notes is None and prepared_notes.get("path"):
        notes = Path(str(prepared_notes["path"]))
    if notes is None and (work_dir / "speaker-notes.md").is_file():
        notes = work_dir / "speaker-notes.md"
    if not previews:
        # Contact sheet is supplemental evidence, not an extra slide: delivery
        # requires exactly one preview per slide.
        previews = [Path(item["path"]) for item in manifest["render"]["pages"]]
    review = load_json(visual_review) if visual_review else None
    expected_pages = {str(i): item["sha256"] for i, item in enumerate(manifest["render"]["pages"], 1)}
    if not review or review.get("pptx_sha256") != sha256_file(pptx) or review.get("contact_sheet_sha256") != manifest["render"]["contact_sheet"]["sha256"] or review.get("page_sha256") != expected_pages:
        raise RefusedError("visual review must bind the current PPTX, contact sheet and every page SHA256")
    receipt = execution_receipt(
        work_dir, "critic", visual_review,
        policy=getattr(args, "receipt_policy", None)
        or work_id_receipt_policy(manifest) or "require",
    )
    degraded_receipt = bool(receipt.get("degraded"))
    if not degraded_receipt:
        for item in [manifest["render"]["contact_sheet"], *manifest["render"]["pages"]]:
            if receipt.get("reads", {}).get(item["path"]) != item["sha256"]:
                raise RefusedError("independent critic did not read every current render image")
    fingerprint = qa_input_fingerprint(pptx, visual_review, notes, previews)
    receipt_binding = None if degraded_receipt else bind(work_dir / "critic-execution.json")
    # Generation evidence is repair-round state, not a frozen plan input, but
    # it is still a QA input. Without this binding a regenerated VGR could hit
    # the previous QA cache forever while complete correctly rejected the old
    # QA-side hash as stale.
    vgr_binding = (manifest.get("generation_evidence") or {}).get(
        "visual_generation_report"
    )
    fingerprint = stable_hash([
        fingerprint,
        manifest.get("inputs"),
        ("visual_generation_report", vgr_binding),
        ("prepared_deliverables", manifest.get("deliverables")),
        receipt_binding,
        args.allow_missing_preview,
    ])
    old_qa = manifest.get("qa") or {}
    old_report = Path(str((old_qa.get("report") or {}).get("path") or ""))
    cached_bindings = [old_qa.get("report") or {}, *(old_qa.get("stages") or {}).values()]
    if old_qa.get("visual_generation_report") is not None:
        cached_bindings.append(old_qa["visual_generation_report"])
    cached_bindings.extend(deliverable_bindings(old_qa.get("deliverables")))
    if manifest.get("state") == "qa" and old_qa.get("input_fingerprint") == fingerprint and old_report.is_file() and all(binding_is_current(item) for item in cached_bindings):
        ok = bool(old_qa.get("ok"))
        record(manifest, "qa", "qa", "qa", reused=True, blockers=int(old_qa.get("blockers") or 0))
        save_manifest(work_dir, manifest)
        print(f"ppt_pipeline: QA reused — {'ok' if ok else 'blocked'} | {old_report}")
        return 0 if ok else 2

    stages = build_qa_stages(
        manifest, work_dir, visual_review=visual_review, notes=notes,
        previews=previews, allow_missing_preview=args.allow_missing_preview,
    )
    if not stages:
        raise RefusedError("QA DAG is empty")
    problems: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    for stage in stages:
        ok, stage_problems, binding = collect(stage)
        reports[stage.artifact] = binding
        if not ok and stage.name in QA_DERIVED_AFTER_UPSTREAM_FAILURE and any(
            not data.get("ok", True) for name, data in reports.items() if name != stage.artifact
        ):
            for item in stage_problems:
                item["derived"] = True
            binding["derived_from_upstream"] = True
        problems.extend(stage_problems)
        if not ok and stage.name in QA_HARD_STOP_STAGES:
            break
    regressions, gate_history = gate_regressions(work_dir, reports)
    problems.extend(regressions)
    problems = dedupe(problems)
    if set(reports) != set(QA_ORDER):
        problems.append({"gate": "pipeline", "severity": "major", "code": "missing_stages", "message": "All QA stages, including delivery, must run and pass"})
    counts = {s: sum(1 for p in problems if p["severity"] == s and not p.get("derived")) for s in ("critical", "major", "minor")}
    blockers = counts["critical"] + counts["major"]
    blockers_by_gate: dict[str, list[str]] = {}
    # keys follow qa_order (actual_content), not the display name (actual-content), so the
    # report and `failed_stages` can be read with one vocabulary.
    artifact_of = {stage.name: stage.artifact for stage in stages}
    for item in problems:
        if item.get("derived") or item["severity"] not in QA_BLOCKING_SEVERITIES:
            continue
        gate = str(item.get("gate") or "pipeline")
        blockers_by_gate.setdefault(artifact_of.get(gate, gate), []).append(str(item.get("code") or "issue"))
    failed_stages = [name for name, data in reports.items() if not data.get("ok", True)]
    # Round-over-round blocker counts: this is what tells a repair round from a round that
    # only moved blockers around. `next` reports the trend so "keep going or stop" is a
    # reading, not another question to the user.
    rounds = [item for item in (gate_history.get("_rounds") or []) if isinstance(item, dict)]
    # `codes` is what lets the next round tell "the repair is converging" from "this group
    # has not moved and no page edit ever will move it" — the 2026-09-18 session ran three
    # repair rounds against 16 blockers that were identical in every round because the gate
    # matched claim text against a bibliography. Counts alone cannot show that.
    codes = Counter(
        str(item.get("code") or "issue")
        for item in problems
        if not item.get("derived") and item["severity"] in QA_BLOCKING_SEVERITIES
    )
    rounds.append({
        "round": len(rounds) + 1, "blockers": blockers, "failed": failed_stages,
        "codes": dict(sorted(codes.items())),
    })
    gate_history["_rounds"] = rounds[-8:]
    qa_report = {
        "ok": blockers == 0, "pipeline_version": MANIFEST_VERSION,
        "qa_order": list(QA_ORDER), "pptx": str(pptx),
        "counts": {"blockers": blockers, **counts}, "problems": problems, "reports": reports,
        # Every content gate runs before this report is written, so a repair round can be
        # handed the complete blocker set in one go instead of discovering one gate per round.
        "failed_stages": failed_stages, "blockers_by_gate": blockers_by_gate,
        "derived_problems": [item["code"] for item in problems if item.get("derived")],
        "gate_regressions": [item["message"] for item in regressions],
    }
    qa_report_path = work_dir / "pipeline-qa.json"
    qa_report_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work_dir / GATE_HISTORY_NAME).write_text(
        json.dumps(gate_history, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = str(manifest.get("state"))
    manifest["qa"] = {
        "ok": qa_report["ok"], "blockers": blockers, "input_fingerprint": fingerprint,
        "report": bind(qa_report_path), "stages": reports,
        "visual_review": bind(visual_review) if visual_review and visual_review.is_file() else None,
        "visual_generation_report": bind(vgr) if vgr.is_file() else None,
        "deliverables": manifest.get("deliverables") or None,
        "previews": [bind(path) for path in previews if path.is_file()] or None,
        "notes": bind(notes) if notes and notes.is_file() else None,
        "critic_execution": receipt_binding,
        "critic_receipt": "missing-allowed" if degraded_receipt else None,
        "stage_cost_ms": {name: data["duration_ms"] for name, data in reports.items() if "duration_ms" in data},
    }
    manifest["state"] = "qa"
    record(manifest, "qa", before, "qa", input_fingerprint=fingerprint)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "qa")
    names = ", ".join(name for name, data in reports.items() if data.get("checked")) or "none"
    line = (
        f"ppt_pipeline: {'ok' if qa_report['ok'] else 'blocked'} — blockers {blockers} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"stages: {names} | failed: {', '.join(failed_stages) or 'none'} | report: {qa_report_path}"
    )
    summary_lines = [f"- {line}", f"- report: `{qa_report_path}`"]
    if blockers_by_gate:
        summary_lines.append(
            "- blockers by gate: "
            + "; ".join(f"{gate}: {', '.join(codes)}" for gate, codes in sorted(blockers_by_gate.items()))
        )
        summary_lines.append(
            "- every content gate already ran on this build — hand the whole list to ONE repair "
            "round; do not fix one gate per round (that cost 6 rounds and ~199M tokens on 2026-09-17)"
        )
    summary_lines.append("- next: `ppt_pipeline.py complete` if ok, else `repair --reason …` then rebuild")
    write_stage_summary(work_dir, "qa", summary_lines)
    print(line)
    for item in problems[: args.max_items]:
        mark = " (derived)" if item.get("derived") else ""
        print(f"  [{item['severity']}]{mark} {item['gate']}/{item['code']} — {str(item['message'])[:200]}")
    return 0 if qa_report["ok"] else 2


