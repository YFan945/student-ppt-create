#!/usr/bin/env python3
"""sp-deck production pipeline: the deterministic half of deck generation.

The agent's job is the intelligent half — Brief, Slide Spec, Art Direction,
composition intent, and generator code. Everything deterministic — freeze,
preflight, build, package/actual-content/rendered/quality/delivery validation,
repair bookkeeping — lives here, driven by a single `build-manifest.json`.

Why this exists: prompt rules ("must fix all pages in one pass", "do not
re-read images") degraded into a gentleman's agreement with rising marginal
cost. Structure replaces them: an agent simply cannot build before `plan`,
cannot run QA before `build`, and cannot reach `complete` before every QA
stage has passed — each stage's report is fed to the next one by this script
and hash-bound, so the agent no longer passes report paths around at all.

State machine (build half of workflow_guard's SEQUENCE):

    (absent) --plan--> planned --build--> producing --qa--> qa --complete--> complete
                          ^                                        |
                          +--------------- repair <----------------+
                          (qa with blockers -> producing, repair edge)

Subcommands:

    plan      freeze the Slide Spec + run copy-fit preflight   -> planned
    build     run the pptxgenjs generator, hash-bind the PPTX  -> producing
    qa        run the QA DAG, feed each report to the next     -> qa
    repair    record a repair round (requires QA blockers)     -> producing
    complete  close the deck (requires QA ok)                  -> complete
    status    one-line manifest summary

Exit codes: 0 = ok, 2 = refused (illegal state, failed gate, missing input).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PPTX_TOOL = ROOT / "scripts" / "pptx_tool.py"
BUILDER = ROOT / "scripts" / "run_with_pptxgenjs.js"

MANIFEST_NAME = "build-manifest.json"
MANIFEST_VERSION = "1.0"

STATES = ("planned", "producing", "qa", "complete")
# build is legal from planned (first) and producing (post-repair rebuild);
# qa re-runs are allowed while still in qa.
BUILD_FROM = {"planned", "producing"}
QA_FROM = {"producing", "qa"}


class RefusedError(Exception):
    """The pipeline refused an illegal transition or a failed gate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def manifest_path(work_dir: Path) -> Path:
    return work_dir / MANIFEST_NAME


def load_manifest(work_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(manifest_path(work_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save_manifest(work_dir: Path, manifest: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now()
    manifest_path(work_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def require_state(manifest: dict[str, Any] | None, allowed: set[str], action: str) -> None:
    current = (manifest or {}).get("state") or "(absent)"
    if current not in allowed:
        raise RefusedError(
            f"{action} requires state in {sorted(allowed)}, but the manifest is '{current}'. "
            "Run `ppt_pipeline.py status` to inspect the legal next step."
        )


def bind(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path)}


def record(manifest: dict[str, Any], command: str, before: str, after: str) -> None:
    manifest.setdefault("history", []).append(
        {"at": now(), "command": command, "from": before, "to": after}
    )


# ---------------------------------------------------------------------------
# QA DAG
# ---------------------------------------------------------------------------


@dataclass
class Stage:
    """One node of the QA DAG: a command whose report feeds the next node."""

    name: str
    argv: list[str]
    report: Path
    artifact: str  # key under manifest["qa"]["reports"]
    issues_key: str = "issues"


def build_qa_stages(
    manifest: dict[str, Any],
    work_dir: Path,
    *,
    visual_review: Path | None,
    notes: Path | None = None,
    previews: list[Path] | None = None,
    allow_missing_preview: bool = False,
) -> list[Stage]:
    """Assemble the QA DAG from the manifest alone.

    The delivery stage consumes *this plan's* reports (package / actual-content /
    quality), not caller-passed paths — that is the difference between a batch
    runner and a dependency pipeline. Callers only supply artifacts the agent
    genuinely produces outside the pipeline (visual-review.json, notes, previews).
    """
    inputs = manifest.get("inputs") or {}
    build = manifest.get("build") or {}
    pptx = str((build.get("pptx") or {}).get("path") or "")
    spec = str((inputs.get("slide_spec") or {}).get("path") or "")
    lock = str((inputs.get("spec_lock") or {}).get("path") or "")
    art = str((inputs.get("art_direction") or {}).get("path") or "")
    vgr = str((inputs.get("visual_generation_report") or {}).get("path") or "")
    spec_report = str((inputs.get("slide_spec_report") or {}).get("path") or "")

    def gate(script: str, *args: str) -> list[str]:
        return [sys.executable, str(HERE / script), *args]

    stages: list[Stage] = [
        Stage(
            "package",
            gate(str(PPTX_TOOL), "validate", pptx, "--output", str(work_dir / "qa-package.json")),
            work_dir / "qa-package.json",
            "package",
        ),
        Stage(
            "rendered",
            gate("pptx_rendered_check.py", "--pptx", pptx, "--output", str(work_dir / "qa-rendered.json")),
            work_dir / "qa-rendered.json",
            "rendered",
        ),
    ]
    if spec:
        stages.append(
            Stage(
                "actual-content",
                gate("pptx_actual_content_check.py", pptx, spec, "--output", str(work_dir / "qa-actual-content.json")),
                work_dir / "qa-actual-content.json",
                "actual_content",
            )
        )
    if spec and lock and visual_review:
        stages.append(
            Stage(
                "quality",
                gate(
                    "pptx_quality_gate_v071.py",
                    "--pptx", pptx,
                    "--slide-spec", spec,
                    "--spec-lock", lock,
                    "--visual-report", str(visual_review),
                    "--output", str(work_dir / "qa-quality.json"),
                ),
                work_dir / "qa-quality.json",
                "quality",
            )
        )
    # Delivery: every report comes from this plan or the frozen inputs.
    required = {
        "pptx": pptx,
        "slide-spec": spec,
        "spec-lock": lock,
        "art-direction": art,
        "visual-generation-report": vgr,
        "slide-spec-report": spec_report,
        "visual-review": str(visual_review or ""),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return stages  # delivery cannot run; `complete` will refuse until re-planned
    quality_path = work_dir / "qa-quality.json"
    package_path = work_dir / "qa-package.json"
    actual_path = work_dir / "qa-actual-content.json"
    produced = {stage.artifact for stage in stages}
    if not {"quality", "package", "actual_content"} <= produced:
        return stages
    argv = gate(
        "pptx_delivery_check_v08.py",
        "--pptx", pptx,
        "--slide-spec", spec,
        "--spec-lock", lock,
        "--art-direction", art,
        "--visual-generation-report", vgr,
        "--quality-report", str(quality_path),
        "--package-report", str(package_path),
        "--slide-spec-report", spec_report,
        "--actual-content-report", str(actual_path),
        "--visual-reviewed",
        "--visual-review-report", str(visual_review),
        "--output", str(work_dir / "qa-delivery.json"),
    )
    if notes:
        argv += ["--notes", str(notes)]
    for preview in previews or []:
        argv += ["--preview", str(preview)]
    if allow_missing_preview:
        argv.append("--allow-missing-preview")
    stages.append(Stage("delivery", argv, work_dir / "qa-delivery.json", "delivery"))
    return stages


def normalise_severity(report: dict[str, Any], issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity") or "").lower()
    if severity in {"critical", "major", "blocker"}:
        return "critical" if severity == "critical" else "major"
    if severity == "minor":
        return "minor"
    return "major" if not report.get("ok", True) else "minor"


def collect(stage: Stage) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    """Run one stage and return (ok, problems, manifest binding)."""
    started = time.monotonic()
    proc = _runner(stage.argv)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not stage.report.is_file():
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, [
            {
                "gate": stage.name,
                "severity": "critical",
                "code": f"{stage.name}_missing_report",
                "message": f"{stage.name} produced no report (exit {proc.returncode}): {detail[:200]}",
            }
        ], {"ok": False, "checked": True, "exit_code": proc.returncode, "duration_ms": duration_ms}
    report = json.loads(stage.report.read_text(encoding="utf-8"))
    issues = report.get(stage.issues_key) if isinstance(report.get(stage.issues_key), list) else []
    problems = [
        {
            "gate": stage.name,
            "severity": normalise_severity(report, issue),
            "code": str(issue.get("code") or f"{stage.name}_issue"),
            "message": str(issue.get("message") or issue.get("detail") or issue.get("problem") or issue),
        }
        for issue in issues
        if isinstance(issue, dict)
    ]
    binding = {
        "ok": bool(report.get("ok", proc.returncode == 0)),
        "checked": True,
        "exit_code": proc.returncode,
        "duration_ms": duration_ms,
        "issue_count": len(issues),
        **bind(stage.report),
    }
    if not issues and not binding["ok"]:
        problems.append(
            {
                "gate": stage.name,
                "severity": "major" if proc.returncode else "minor",
                "code": f"{stage.name}_failed",
                "message": f"{stage.name} reported not ok without itemised issues (exit {proc.returncode}).",
            }
        )
    return binding["ok"], problems, binding


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        marker = (item["severity"], item["code"], str(item["message"]))
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_runner: Runner = run_command


def cmd_plan(args: argparse.Namespace) -> int:
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    if not args.force:
        require_state(manifest, {"(absent)", "planned"}, "plan")
    if manifest and manifest.get("state") == "planned" and not args.force:
        raise RefusedError("already planned; pass --force to re-plan (re-freezes the lock)")

    fresh: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "work_id": work_dir.name,
        "state": "(absent)",
        "inputs": {},
        "build": {"build_count": 0, "repair_count": 0},
        "qa": {},
        "history": [],
    }
    if manifest and args.force:
        fresh["build"]["repair_count"] = (manifest.get("build") or {}).get("repair_count", 0)
        fresh["history"] = list(manifest.get("history") or [])

    spec = args.slide_spec.resolve()
    if not spec.is_file():
        raise RefusedError(f"Slide Spec does not exist: {spec}")
    validation_report = args.validation_report.resolve()
    if not validation_report.is_file():
        raise RefusedError(f"Slide Spec validation report does not exist: {validation_report}")
    art = args.art_direction.resolve()
    if not art.is_file():
        raise RefusedError(f"Art Direction does not exist: {art}")

    # Preflight runs before anything is frozen: a spec that cannot fit its copy
    # on the page never reaches the generator.
    preflight_report = work_dir / "copy-fit-preflight.json"
    pre = _runner(
        [
            sys.executable, str(HERE / "copy_fit_preflight.py"),
            "--slide-spec", str(spec),
            "--art-direction", str(art),
            "--output", str(preflight_report),
        ]
    )
    if preflight_report.is_file():
        fresh["inputs"]["copy_fit_preflight"] = bind(preflight_report)
    if pre.returncode != 0:
        detail = (pre.stderr or pre.stdout or "").strip()
        raise RefusedError(f"copy-fit preflight blocked the plan (exit {pre.returncode}): {detail[:400]}")

    lock = work_dir / "slide-spec-lock.json"
    freeze_argv = [
        sys.executable, str(HERE / "slide_spec_guard.py"), "freeze",
        "--slide-spec", str(spec),
        "--validation-report", str(validation_report),
        "--lock-file", str(lock),
        "--reason", args.reason,
    ]
    if args.research_pack:
        freeze_argv += ["--research-pack", str(args.research_pack.resolve())]
    if args.research_validation:
        freeze_argv += ["--research-validation", str(args.research_validation.resolve())]
    if args.evidence_map:
        freeze_argv += ["--evidence-map", str(args.evidence_map.resolve())]
    frozen = _runner(freeze_argv)
    if frozen.returncode != 0 or not lock.is_file():
        detail = (frozen.stderr or frozen.stdout or "").strip()
        raise RefusedError(f"slide_spec_guard freeze failed (exit {frozen.returncode}): {detail[:400]}")

    fresh["inputs"]["slide_spec"] = bind(spec)
    fresh["inputs"]["spec_lock"] = bind(lock)
    fresh["inputs"]["slide_spec_report"] = bind(validation_report)
    fresh["inputs"]["art_direction"] = bind(art)
    if args.visual_generation_report:
        vgr = args.visual_generation_report.resolve()
        if not vgr.is_file():
            raise RefusedError(f"visual-generation report does not exist: {vgr}")
        fresh["inputs"]["visual_generation_report"] = bind(vgr)
    if args.evidence_map:
        fresh["inputs"]["evidence_map"] = bind(args.evidence_map.resolve())
    if args.research_pack:
        fresh["inputs"]["research_pack"] = bind(args.research_pack.resolve())
    if args.research_validation:
        fresh["inputs"]["research_validation"] = bind(args.research_validation.resolve())

    fresh["state"] = "planned"
    record(fresh, "plan", "(absent)", "planned")
    save_manifest(work_dir, fresh)
    print(f"ppt_pipeline: planned — {work_dir / MANIFEST_NAME}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    require_state(manifest, BUILD_FROM, "build")
    assert manifest is not None  # require_state guarantees presence for non-(absent)
    inputs = manifest.get("inputs") or {}
    lock = Path((inputs.get("spec_lock") or {}).get("path") or "")
    spec = Path((inputs.get("slide_spec") or {}).get("path") or "")
    if not lock.is_file():
        raise RefusedError(f"spec lock is missing from the manifest: {lock}")

    # Re-verify the freeze on every build: editing the spec after plan without
    # re-planning is exactly the drift the lock exists to catch.
    check = _runner(
        [
            sys.executable, str(HERE / "slide_spec_guard.py"), "check",
            "--lock-file", str(lock), "--slide-spec", str(spec),
        ]
    )
    if check.returncode != 0:
        detail = (check.stderr or check.stdout or "").strip()
        raise RefusedError(f"spec lock check failed — re-plan first (exit {check.returncode}): {detail[:400]}")

    entry = args.entry.resolve()
    if not entry.is_file():
        raise RefusedError(f"generator entry does not exist: {entry}")
    pptx = work_dir / args.output_name
    if pptx.suffix.lower() != ".pptx":
        raise RefusedError(f"--output-name must end in .pptx: {args.output_name}")
    node = os.environ.get("NODE") or "node"
    built = _runner([node, str(BUILDER), "--output", str(pptx), str(entry), *args.generator_args])
    if built.returncode != 0 or not pptx.is_file():
        detail = (built.stderr or built.stdout or "").strip()
        raise RefusedError(f"build failed (exit {built.returncode}): {detail[:600]}")

    build_info = manifest.setdefault("build", {})
    build_info["entry"] = str(entry)
    build_info["pptx"] = bind(pptx)
    pages = sorted((entry.parent / "pages").glob("*.js")) if (entry.parent / "pages").is_dir() else []
    build_info["generator_files"] = [bind(entry)] + [bind(page) for page in pages]
    build_info["build_count"] = int(build_info.get("build_count") or 0) + 1
    before = manifest.get("state")
    manifest["state"] = "producing"
    record(manifest, "build", before, "producing")
    save_manifest(work_dir, manifest)
    print(
        f"ppt_pipeline: built {pptx.name} (builds {build_info['build_count']}, "
        f"repairs {build_info.get('repair_count', 0)}) — state producing"
    )
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    require_state(manifest, QA_FROM, "qa")
    assert manifest is not None
    pptx = Path(((manifest.get("build") or {}).get("pptx") or {}).get("path") or "")
    if not pptx.is_file():
        raise RefusedError(f"no built PPTX in the manifest: {pptx}")

    stages = build_qa_stages(
        manifest,
        work_dir,
        visual_review=Path(args.visual_review).resolve() if args.visual_review else None,
        notes=Path(args.notes).resolve() if args.notes else None,
        previews=[Path(p) for p in args.preview] if args.preview else None,
        allow_missing_preview=args.allow_missing_preview,
    )
    if not stages:
        raise RefusedError("QA DAG is empty — nothing to check")

    problems: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    for stage in stages:
        ok, stage_problems, binding = collect(stage)
        reports[stage.artifact] = binding
        problems.extend(stage_problems)
        if not ok:
            # The DAG stops at the first failing stage: downstream reports would
            # describe a stale artifact and must not be produced.
            break

    problems = dedupe(problems)
    severities = ("critical", "major", "minor")
    counts = {s: sum(1 for p in problems if p["severity"] == s) for s in severities}
    blockers = counts["critical"] + counts["major"]
    qa_report = {
        "ok": blockers == 0,
        "pipeline_version": MANIFEST_VERSION,
        "pptx": str(pptx),
        "gates": {name: {"ok": (reports.get(name) or {}).get("ok")} for name in
                  ("package", "rendered", "actual_content", "quality", "delivery")},
        "counts": {"blockers": blockers, **counts},
        "problems": problems,
        "reports": reports,
    }
    qa_report_path = work_dir / "pipeline-qa.json"
    qa_report_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    before = manifest.get("state")
    manifest["qa"] = {
        "ok": qa_report["ok"],
        "blockers": blockers,
        "report": bind(qa_report_path),
        "stages": reports,
        # Render-side evidence bindings: what the visual critique actually saw.
        "visual_review": bind(Path(args.visual_review).resolve())
        if args.visual_review and Path(args.visual_review).is_file()
        else None,
        "previews": [bind(Path(p).resolve()) for p in args.preview if Path(p).is_file()]
        if args.preview
        else None,
        "stage_cost_ms": {
            name: data["duration_ms"] for name, data in reports.items() if "duration_ms" in data
        },
    }
    manifest["state"] = "qa"
    record(manifest, "qa", before, "qa")
    save_manifest(work_dir, manifest)

    names = ", ".join(name for name, data in reports.items() if data.get("checked")) or "none"
    line = (
        f"ppt_pipeline: {'ok' if qa_report['ok'] else 'blocked'} — blockers {blockers} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"stages: {names} | report: {qa_report_path}"
    )
    print(line)
    for item in problems[: args.max_items]:
        slide = f" (slide {item['slide']})" if item.get("slide") else ""
        print(f"  [{item['severity']}] {item['gate']}/{item['code']} — {str(item['message'])[:200]}{slide}")
    hidden = len(problems) - min(len(problems), args.max_items)
    if hidden > 0:
        print(f"  … {hidden} more (full detail in {qa_report_path})")
    return 0 if qa_report["ok"] else 2


def cmd_repair(args: argparse.Namespace) -> int:
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "repair")
    assert manifest is not None
    blockers = int((manifest.get("qa") or {}).get("blockers") or 0)
    if blockers == 0 and not args.force:
        raise RefusedError(
            "QA reported no blockers; `repair` is only for rework. Use `complete` to close the deck, "
            "or pass --force with a reason to rebuild anyway."
        )
    build_info = manifest.setdefault("build", {})
    build_info["repair_count"] = int(build_info.get("repair_count") or 0) + 1
    build_info.setdefault("repair_reasons", []).append(args.reason)
    before = manifest.get("state")
    manifest["state"] = "producing"
    record(manifest, "repair", before, "producing")
    save_manifest(work_dir, manifest)
    print(
        f"ppt_pipeline: repair round {build_info['repair_count']} — fix the generator, then build + qa again"
    )
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "complete")
    assert manifest is not None
    qa = manifest.get("qa") or {}
    delivery = (qa.get("stages") or {}).get("delivery") or {}
    if not qa.get("ok"):
        raise RefusedError(
            f"QA still reports {qa.get('blockers', '?')} blocker(s); repair before completing."
        )
    if not delivery.get("checked"):
        raise RefusedError(
            "delivery stage never ran (missing plan inputs, e.g. visual-generation report or "
            "visual-review.json) — re-plan with the complete input set, then qa again."
        )
    before = manifest.get("state")
    manifest["state"] = "complete"
    record(manifest, "complete", before, "complete")
    save_manifest(work_dir, manifest)
    print("ppt_pipeline: complete — deck delivered and evidence hash-bound")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.work_dir)
    if not manifest:
        print(f"ppt_pipeline: no manifest at {manifest_path(args.work_dir)}")
        return 2
    build = manifest.get("build") or {}
    qa = manifest.get("qa") or {}
    pptx_sha = str(((build.get("pptx") or {}).get("sha256")) or "-")[:8]
    spec_sha = str(((manifest.get("inputs") or {}).get("slide_spec") or {}).get("sha256") or "-")[:8]
    qa_note = "ok" if qa.get("ok") else f"{qa.get('blockers', '-')} blockers"
    print(
        f"ppt_pipeline: {manifest.get('state')} — builds {build.get('build_count', 0)}, "
        f"repairs {build.get('repair_count', 0)} | pptx {pptx_sha} | spec {spec_sha} | "
        f"qa {qa_note}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="freeze the Slide Spec + run copy-fit preflight -> planned")
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--slide-spec", type=Path, required=True)
    plan.add_argument("--validation-report", type=Path, required=True)
    plan.add_argument("--art-direction", type=Path, required=True)
    plan.add_argument("--visual-generation-report", type=Path)
    plan.add_argument("--research-pack", type=Path)
    plan.add_argument("--research-validation", type=Path)
    plan.add_argument("--evidence-map", type=Path)
    plan.add_argument("--reason", default="initial approved production plan")
    plan.add_argument("--force", action="store_true", help="re-plan (re-freezes the lock)")
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build", help="run the generator -> producing")
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--entry", type=Path, required=True, help="deck.js entry")
    build.add_argument("--output-name", default="deck.pptx")
    build.add_argument("generator_args", nargs="*", help="extra args forwarded to the deck script")
    build.set_defaults(func=cmd_build)

    qa = sub.add_parser("qa", help="run the QA DAG -> qa")
    qa.add_argument("--work-dir", type=Path, required=True)
    qa.add_argument("--visual-review", type=Path, help="visual-review.json (quality + delivery)")
    qa.add_argument("--notes", type=Path, help="speaker notes file (delivery)")
    qa.add_argument("--preview", type=Path, nargs="+", action="extend", help="preview images (delivery)")
    qa.add_argument("--allow-missing-preview", action="store_true")
    qa.add_argument("--max-items", type=int, default=12)
    qa.set_defaults(func=cmd_qa)

    repair = sub.add_parser("repair", help="qa with blockers -> producing (rework edge)")
    repair.add_argument("--work-dir", type=Path, required=True)
    repair.add_argument("--reason", required=True)
    repair.add_argument("--force", action="store_true")
    repair.set_defaults(func=cmd_repair)

    complete = sub.add_parser("complete", help="qa ok -> complete")
    complete.add_argument("--work-dir", type=Path, required=True)
    complete.set_defaults(func=cmd_complete)

    status = sub.add_parser("status", help="one-line manifest summary")
    status.add_argument("--work-dir", type=Path, required=True)
    status.set_defaults(func=cmd_status)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.func(args)
    except RefusedError as exc:
        print(f"ppt_pipeline: REFUSED — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
