from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import generator_scaffold as _scaffold  # noqa: E402

from pipeline import core  # noqa: E402
from pipeline.core import (  # noqa: E402
    CONTRACT,
    EVIDENCE_COMPILER,
    HERE,
    MANIFEST_VERSION,
    PPTX_TOOL,
    ROOT,
    RefusedError,
    bind,
    default_workflow_state,
    execution_receipt,
    load_manifest,
    manifest_path,
    mirror_workflow_state,
    record,
    require_state,
    save_manifest,
    validate_intake,
    work_id_receipt_policy,
    write_stage_summary,
)
from shared.quality_tiers import normalize as normalize_quality_level  # noqa: E402


def compile_research_for_plan(
    work_dir: Path, spec: Path, args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    """Compile F/D/Q → evidence-map.json. Agents must not guess this CLI.

    2026-09-16 live run spent ~10 turns probing --evidence-map flags. Plan always
    compiles from pack + validation sitting in the work-dir (or explicit flags).
    """
    pack = (args.research_pack or work_dir / "research-pack.json").resolve()
    validation = (args.research_validation or work_dir / "research-pack-validation.json").resolve()
    missing = [label for label, path in (("research-pack.json", pack), ("research-pack-validation.json", validation)) if not path.is_file()]
    if missing:
        raise RefusedError(
            "research-backed plan needs "
            + " and ".join(missing)
            + f" in {work_dir} (or pass --research-pack / --research-validation). "
            "plan compiles evidence-map.json itself — do not invent --evidence-map."
        )
    evidence_map = work_dir / "evidence-map.json"
    compiled_spec = work_dir / f"slide-spec-compiled{spec.suffix}"
    compiled = core._runner([
        sys.executable, str(EVIDENCE_COMPILER), str(pack),
        "--validation-report", str(validation),
        "--slide-spec", str(spec),
        "--compiled-slide-spec", str(compiled_spec),
        "--output", str(evidence_map),
    ])
    if compiled.returncode != 0 or not evidence_map.is_file():
        detail = (compiled.stderr or compiled.stdout or "").strip()
        raise RefusedError(f"evidence compile failed (exit {compiled.returncode}): {detail[:400]}")
    if compiled_spec.is_file():
        spec = compiled_spec
    return spec, pack, validation, evidence_map.resolve()


def aligned_validation_report(work_dir: Path, spec: Path, report: Path) -> tuple[Path, bool]:
    """Return a validation report that describes `spec` exactly (2026-09-20).

    A research-backed deck is a chicken-and-egg trap: `plan` compiles the source
    spec into `slide-spec-compiled.yaml` and then freezes **that** file, so a
    report the session produced from the source spec can never match. The guard
    refuses, the session only then discovers the compiled file, and plan has to
    run twice — three wasted round-trips on a transition the pipeline itself
    owns. Plan created the compiled spec, so plan re-validates it.

    Re-validation never hides a failure: a spec that does not validate produces
    `valid: false` and the freeze still refuses, now against the right file.
    """
    from slide_spec_guard import sha256_file

    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if (
        isinstance(data, dict)
        and data.get("valid") is True
        and data.get("slide_spec_sha256") == sha256_file(spec)
    ):
        return report, False

    regenerated = work_dir / "slide-spec-report.json"
    proc = core._runner([
        sys.executable, str(ROOT / "scripts" / "validate_slide_spec.py"), str(spec),
        "--output", str(regenerated),
    ])
    if proc.returncode != 0 or not regenerated.is_file():
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RefusedError(
            f"Slide Spec validation failed for the spec being frozen ({spec.name}) "
            f"(exit {proc.returncode}): {detail[:400]}"
        )
    return regenerated, True


def cmd_plan(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    if not args.force:
        require_state(manifest, {"(absent)", "planned"}, "plan")
    if manifest and manifest.get("state") == "planned" and not args.force:
        raise RefusedError("already planned; pass --force to re-plan")

    workflow_state_path = (args.workflow_state or default_workflow_state(work_dir)).resolve()
    if manifest and args.force:
        # Re-planning an approved, still-unbuilt plan is a revision of the same
        # authorization, not a new intake.  Requiring reset + confirm here used
        # to erase the useful state transition while still leaving the old lock
        # behind, after which freeze instructed callers to use an unreachable
        # ``slide_spec_guard revise`` command.
        if manifest.get("state") != "planned":
            raise RefusedError(
                "force re-plan is only allowed while the manifest is planned; "
                "once production starts, create a new work-id"
            )
        intake = core.load_json(workflow_state_path) or {}
        workflow = manifest.get("workflow") or {}
        summary = Path(str(workflow.get("summary_file") or ""))
        summary_sha = str(workflow.get("summary_sha256") or "")
        if (
            intake.get("work_id") != manifest.get("work_id")
            or intake.get("state") != "planned"
            or intake.get("summary_sha256") != summary_sha
            or not summary.is_file()
            or core.sha256_file(summary) != summary_sha
        ):
            raise RefusedError(
                "force re-plan requires the original approved Production Summary "
                "and matching planned workflow state"
            )
    else:
        intake = validate_intake(workflow_state_path)
    if workflow_state_path != default_workflow_state(work_dir) or intake.get("work_id") != work_dir.name:
        raise RefusedError("intake must belong to this work_id and use its workflow-state.json")

    spec = args.slide_spec.resolve()
    validation_report = args.validation_report.resolve()
    art = args.art_direction.resolve()
    for label, path in (("Slide Spec", spec), ("validation report", validation_report), ("Art Direction", art)):
        if not path.is_file():
            raise RefusedError(f"{label} does not exist: {path}")
    import yaml

    sys.path.insert(0, str(ROOT / "scripts"))
    from slide_spec_to_pptx_brief import derive_production_mode, validate_production_source

    spec_data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    if not isinstance(spec_data, dict):
        raise RefusedError("Slide Spec must be an object")
    if spec_data.get("source_deck"):
        source = Path(spec_data["source_deck"]).expanduser()
        spec_data["source_deck"] = str((spec.parent / source).resolve())
    try:
        mode = derive_production_mode(spec_data, getattr(args, "production_mode", None))
        validate_production_source(spec_data, mode)
    except ValueError as exc:
        raise RefusedError(str(exc)) from exc
    work_dir.mkdir(parents=True, exist_ok=True)

    receipt_policy = (
        getattr(args, "receipt_policy", None)
        or work_id_receipt_policy(manifest) or "require"
    )
    fresh: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "contract_version": CONTRACT.get("contract_version"),
        "work_id": work_dir.name,
        "work_dir": str(work_dir),
        "mode": mode,
        "quality_level": normalize_quality_level((spec_data.get("meta") or {}).get("quality_level")),
        "quality_level_raw": str((spec_data.get("meta") or {}).get("quality_level") or ""),
        # Policy is work-id state, not research state: a scope-C deck with no
        # researcher never creates manifest["research"], so hanging the flag
        # there lost the degrade decision for no-research decks entirely.
        "receipt_policy": receipt_policy,
        "source": bind(Path(spec_data["source_deck"])) if spec_data.get("source_deck") else None,
        "edit_contract": {key: spec_data.get(key) for key in ("edit_intent", "review_findings", "preserve", "change_summary_required")},
        "state": "(absent)", "inputs": {},
        "workflow": {
            "state_file": str(workflow_state_path),
            "summary_file": str(Path(str(intake["summary_file"])).resolve()),
            "summary_sha256": str(intake["summary_sha256"]),
        },
        "build": {"build_count": 0, "repair_count": 0, "pending_repair": False},
        "render": {}, "qa": {}, "history": [],
    }
    scope = spec_data.get("research_scope", "C")
    external = any(item.get("source_type") not in {"user-file", "experiment", "interview", "survey"} for item in spec_data.get("evidence_ledger", []))
    pack_on_disk = args.research_pack or work_dir / "research-pack.json"
    if args.research_pack or scope in {"A", "B", "D"} or external or Path(pack_on_disk).is_file():
        spec, pack, validation, evidence_map = compile_research_for_plan(work_dir, spec, args)
        args.research_pack, args.research_validation, args.evidence_map = pack, validation, evidence_map
        spec_data = yaml.safe_load(spec.read_text(encoding="utf-8"))
        if not isinstance(spec_data, dict):
            raise RefusedError("compiled Slide Spec must be an object")
        receipt = execution_receipt(work_dir, "research", pack, policy=receipt_policy)
        fresh["research"] = {
            "required": True,
            "scope": scope,
            "agent": receipt["agent"],
            "spawn_verified": receipt.get("spawn_verified") is True,
            "execution": (
                bind(work_dir / "research-execution.json")
                if receipt.get("spawn_verified") is True else None
            ),
        }
        if receipt.get("degraded"):
            fresh["research"]["receipt_policy"] = "allow-missing"
    if manifest and args.force:
        fresh["build"]["repair_count"] = int((manifest.get("build") or {}).get("repair_count") or 0)
        fresh["history"] = list(manifest.get("history") or [])

    ad_report = work_dir / "art-direction-check.json"
    ad_check = core._runner([
        sys.executable, str(HERE / "art_direction_check.py"), str(art),
        "--work-dir", str(work_dir),
        "--output", str(ad_report), "--json",
    ])
    if ad_report.is_file():
        fresh["inputs"]["art_direction_check"] = bind(ad_report)
    if ad_check.returncode != 0:
        detail = (ad_check.stderr or ad_check.stdout or "").strip()
        raise RefusedError(
            f"Art Direction blocked plan (exit {ad_check.returncode}): {detail[:400]} "
            f"— fix art-direction.yaml against the checker before plan; report: {ad_report}"
        )

    preflight_report = work_dir / "copy-fit-preflight.json"
    pre = core._runner([
        sys.executable, str(HERE / "copy_fit_preflight.py"), "--slide-spec", str(spec),
        "--art-direction", str(art), "--output", str(preflight_report),
    ])
    if preflight_report.is_file():
        fresh["inputs"]["copy_fit_preflight"] = bind(preflight_report)
    if pre.returncode != 0:
        detail = (pre.stderr or pre.stdout or "").strip()
        raise RefusedError(f"copy-fit preflight blocked plan (exit {pre.returncode}): {detail[:400]}")

    validation_report, report_regenerated = aligned_validation_report(work_dir, spec, validation_report)
    if report_regenerated:
        print(
            f"ppt_pipeline: {args.validation_report.name} does not describe {spec.name}; "
            f"re-validated the frozen spec into {validation_report}"
        )
    lock = work_dir / "slide-spec-lock.json"
    lock_action = "revise" if manifest and args.force else "freeze"
    freeze_argv = [
        sys.executable, str(HERE / "slide_spec_guard.py"), lock_action,
        "--slide-spec", str(spec), "--validation-report", str(validation_report),
        "--lock-file", str(lock), "--reason", args.reason,
    ]
    for flag, path in (("--research-pack", args.research_pack), ("--research-validation", args.research_validation), ("--evidence-map", args.evidence_map)):
        if path:
            freeze_argv += [flag, str(path.resolve())]
    frozen = core._runner(freeze_argv)
    if frozen.returncode != 0 or not lock.is_file():
        detail = (frozen.stderr or frozen.stdout or "").strip()
        raise RefusedError(
            f"slide_spec_guard {lock_action} failed (exit {frozen.returncode}): {detail[:400]}"
        )

    fresh["inputs"].update({
        "slide_spec": bind(spec), "spec_lock": bind(lock),
        "slide_spec_report": bind(validation_report), "art_direction": bind(art),
    })
    if report_regenerated:
        # Visible in the manifest so a cost/QA review can see that the source spec
        # and the frozen spec are two different files, not one drifting artifact.
        fresh["spec_report_regenerated"] = {
            "frozen_spec": spec.name,
            "supplied_report": str(args.validation_report),
        }
    for key, path in (("visual_generation_report", args.visual_generation_report), ("evidence_map", args.evidence_map), ("research_pack", args.research_pack), ("research_validation", args.research_validation)):
        if path:
            resolved = path.resolve()
            if not resolved.is_file():
                raise RefusedError(f"{key} does not exist: {resolved}")
            if key == "visual_generation_report":
                fresh.setdefault("generation_evidence", {})[key] = bind(resolved)
            else:
                fresh["inputs"][key] = bind(resolved)

    fresh["state"] = "planned"
    record(fresh, "plan", "(absent)", "planned")
    if mode == "edit_ooxml":
        unpacked = work_dir / "ooxml"
        if unpacked.exists():
            raise RefusedError("ooxml workspace already exists; use a new work-id for a new plan")
        unpack = core._runner([sys.executable, str(PPTX_TOOL), "unpack", fresh["source"]["path"], "--output", str(unpacked)])
        if unpack.returncode != 0 or not unpacked.is_dir():
            raise RefusedError("source unpack failed")
        scaffold_info = {"slides": len(spec_data.get("slides") or []), "pages": []}
    else:
        scaffold_info = _scaffold.scaffold_generator(
            work_dir,
            spec,
            art_direction=Path(str(getattr(args, "art_direction", "") or "")) or None,
        )
        if mode == "rebuild_from_source":
            analysis = work_dir / "source-analysis.md"
            if not analysis.is_file() or not analysis.read_text(encoding="utf-8").strip():
                raise RefusedError("rebuild_from_source requires source-analysis.md before plan")
            fresh["inputs"]["source_analysis"] = bind(analysis)
    fresh["scaffold"] = {
        "slides": scaffold_info["slides"],
        "pages": scaffold_info["pages"],
    }
    # Batch 4.3: plan the deck rhythm (tone per page from the Art Direction's
    # background_rhythm, composition family per archetype) once, at freeze time,
    # so builders see it instead of deciding page tone independently at build time.
    try:
        from deck_rhythm import ensure_rhythm

        rhythm_path = ensure_rhythm(work_dir)
    except Exception as exc:
        # A rhythm regression must be VISIBLE: plan still succeeds, but the
        # manifest records the failure so a benchmark can see Batch 4.3 was off.
        rhythm_path = None
        fresh["deck_rhythm"] = {"status": "failed", "error": str(exc)[:300]}
    else:
        if rhythm_path is not None:
            fresh["deck_rhythm"] = {"status": "ok", **bind(rhythm_path)}
        else:
            fresh["deck_rhythm"] = {"status": "skipped", "reason": "no readable Slide Spec"}
    summary = write_stage_summary(
        work_dir,
        "planned",
        [
            f"- spec: `{spec}`",
            f"- art-direction: `{art}`",
            f"- pages scaffolded: {scaffold_info['slides']} → `pages/`",
            f"- composition dir: `{work_dir / 'composition'}`",
            *([f"- deck rhythm planned: `{rhythm_path}`"] if rhythm_path else []),
            *(
                [f"- deck rhythm FAILED: {fresh['deck_rhythm'].get('error', '')[:160]}"]
                if fresh["deck_rhythm"].get("status") == "failed"
                else []
            ),
            "- next: fill `pages/pNN-*.js` (parallel Edit), then `ppt_pipeline.py build`",
            "- do not re-read the Slide Spec or Art Direction unless the hash changed",
        ],
    )
    fresh["stage_summary"] = bind(summary)
    save_manifest(work_dir, fresh)
    mirror_workflow_state(fresh, "planned")
    print(f"ppt_pipeline: planned — {manifest_path(work_dir)}")
    print(f"ppt_pipeline: scaffolded {scaffold_info['slides']} page module(s) under {work_dir / 'pages'}")
    return 0


def _research_budget(work_dir: Path) -> dict[str, Any] | None:
    """Remaining query quota for an existing pack (gap-fill authorization aid).

    2026-09-17: a gap-fill authorization said "about 6 more" without checking the
    remaining deep-band headroom (7); the researcher ran 8 and the pack hit
    16/15, forcing a full round revert. `next` now reports the exact numbers.
    """
    pack_path = work_dir / "research-pack.json"
    if not pack_path.is_file():
        return None
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(pack, dict):
        return None
    band = str(pack.get("budget") or "")
    used = len(pack.get("queries") or [])
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from validate_research_pack import BUDGET_CAPS  # noqa: PLC0415
    except ImportError:
        return {"band": band, "used": used, "cap": None, "approved_headroom": 0, "remaining": None}
    caps = BUDGET_CAPS.get(band)
    if caps is None:
        return {"band": band, "used": used, "cap": None, "approved_headroom": 0, "remaining": None}
    extension = pack.get("budget_extension")
    headroom = 0
    if isinstance(extension, dict):
        try:
            extra = int(extension.get("extra_queries"))
        except (TypeError, ValueError):
            extra = 0
        if (
            extra >= 1
            and str(extension.get("approved_by") or "") == "user"
            and str(extension.get("reason") or "").strip()
        ):
            headroom = extra
    return {
        "band": band,
        "used": used,
        "cap": caps["queries"],
        "approved_headroom": headroom,
        "remaining": caps["queries"] + headroom - used,
    }


