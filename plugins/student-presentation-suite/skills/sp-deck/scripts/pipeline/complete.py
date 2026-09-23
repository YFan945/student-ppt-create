from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline.convergence import (  # noqa: E402
    repair_budget,
)
from pipeline.core import (  # noqa: E402
    RefusedError,
    binding_is_current,
    load_manifest,
    manifest_path,
    mirror_workflow_state,
    record,
    render_is_current,
    require_state,
    save_manifest,
    validate_manifest_authorization,
    write_stage_summary,
)
from pipeline.deliverables import (  # noqa: E402
    deliverable_bindings,
    deliverables_are_current,
    requested_prepared_deliverables,
)
from pipeline.publish import publish_deliverables  # noqa: E402


def cmd_complete(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "complete")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    qa = manifest.get("qa") or {}
    delivery = (qa.get("stages") or {}).get("delivery") or {}
    if not qa.get("ok"):
        raise RefusedError(f"QA still has {qa.get('blockers', '?')} blocker(s)")
    if not delivery.get("checked") or not delivery.get("ok"):
        raise RefusedError("delivery stage did not pass")
    # Degraded QA (critic receipt missing-allowed) has critic_execution=None by
    # design; treating that None as "evidence disappeared" dead-ended delivery —
    # a degraded run could plan, build and pass QA but never complete.
    degraded_receipt = qa.get("critic_receipt") == "missing-allowed"
    # Optional deliverables are already enforced by the delivery stage. A
    # PPTX-only run legitimately records ``notes=None``; treating that absence
    # as vanished QA evidence made a green delivery impossible to complete.
    evidence = [
        qa.get("report"),
        qa.get("visual_review"),
        *(qa.get("previews") or []),
        *(qa.get("stages") or {}).values(),
    ]
    if qa.get("visual_generation_report") is not None:
        evidence.append(qa.get("visual_generation_report"))
    if qa.get("notes") is not None:
        evidence.append(qa.get("notes"))
    evidence.extend(deliverable_bindings(qa.get("deliverables")))
    if not degraded_receipt:
        evidence.append(qa.get("critic_execution"))
    if (
        not render_is_current(manifest)
        or (
            requested_prepared_deliverables(manifest)
            and not deliverables_are_current(manifest)
        )
        or any(not item or not binding_is_current(item) for item in evidence)
    ):
        raise RefusedError("QA evidence changed or disappeared after QA; run QA again")
    if manifest.get("mode") != "create":
        change_summary = work_dir / "change-summary.md"
        if not change_summary.is_file() or not change_summary.read_text(encoding="utf-8").strip():
            raise RefusedError("source-based delivery requires change-summary.md")
    published = publish_deliverables(work_dir, manifest)
    before = str(manifest.get("state"))
    manifest["published"] = published
    manifest["state"] = "complete"
    record(manifest, "complete", before, "complete")
    save_manifest(work_dir, manifest)
    write_stage_summary(
        work_dir,
        "complete",
        [
            "- QA green; delivery stage ran and was hash-bound.",
            f"- pptx: `{((manifest.get('build') or {}).get('pptx') or {}).get('path')}`",
            *[f"- published {name}: `{item['path']}`" for name, item in published.items()],
            *(
                []
                if not degraded_receipt
                else [
                    "- degraded: independent-critic receipt was missing-allowed "
                    "(--receipt-policy allow-missing); visual review exists but carries no "
                    "hook-verified hash binding — state this to the user at delivery"
                ]
            ),
            "- do not re-inject /sp-deck; run sp-review only if the user asks",
        ],
    )
    mirror_workflow_state(manifest, "complete")
    print("ppt_pipeline: complete — delivery and intake authorization are hash-bound")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.work_dir.resolve())
    if not manifest:
        print(f"ppt_pipeline: no manifest at {manifest_path(args.work_dir.resolve())}")
        return 2
    build = manifest.get("build") or {}
    qa = manifest.get("qa") or {}
    render = manifest.get("render") or {}
    pre_qa = manifest.get("pre_qa") or {}
    budget = repair_budget(manifest)
    granted = f" (base {budget['base']} + granted {budget['granted']})" if budget["granted"] else ""
    pre_qa_state = (
        "green" if pre_qa.get("ok") else
        f"{pre_qa.get('blockers', '-')} blockers (round {pre_qa.get('rounds', '-')}/{pre_qa.get('max_rounds', '-')})"
        if pre_qa else "-"
    )
    print(
        f"ppt_pipeline: {manifest.get('state')} — builds {build.get('build_count', 0)}, "
        f"repairs {build.get('repair_count', 0)}/{budget['effective']}{granted}, "
        f"pre-qa {pre_qa_state}, rendered {render.get('page_count', 0)} | "
        f"qa {'ok' if qa.get('ok') else str(qa.get('blockers', '-')) + ' blockers'}"
    )
    return 0


