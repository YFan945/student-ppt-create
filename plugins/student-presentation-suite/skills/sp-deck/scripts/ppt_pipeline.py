#!/usr/bin/env python3
"""sp-deck deterministic production pipeline.

The agent owns semantic and visual judgement. This CLI owns execution order,
state, rendering, idempotence, QA dependencies, repair budget, and delivery.
Production is driven by one build-manifest.json; the legacy workflow state is
used only as the intake authorization source and is mirrored automatically.

    plan      verify intake, freeze, preflight, scaffold pages/  -> planned
    build     run the generator; refuses unsplitted deck.js      -> producing
    render    raster pages + contact-sheet.png (hash-cached)
    qa        fail-fast QA DAG                                   -> qa
    repair    QA blockers -> producing (budget from contract)
    complete  qa + delivery ok                                   -> complete
    status    one-line manifest summary
    next      what to read and which command to run next

Exit codes: 0 = ok, 2 = refused (illegal state, failed gate, missing input).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import generator_scaffold as _scaffold  # noqa: E402

ROOT = HERE.parents[2]
PPTX_TOOL = ROOT / "scripts" / "pptx_tool.py"
BUILDER = ROOT / "scripts" / "run_with_pptxgenjs.js"
CONTRACT_PATH = ROOT / "references" / "pipeline-contract.json"
MANIFEST_NAME = "build-manifest.json"


class RefusedError(Exception):
    """The pipeline refused an illegal or stale operation."""


def load_contract() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusedError(f"pipeline contract unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise RefusedError("pipeline contract root must be an object")
    return value


CONTRACT = load_contract()
MANIFEST_VERSION = str(CONTRACT.get("manifest_version") or "1.1")
MAX_REPAIRS = int(CONTRACT.get("max_repairs") or 3)
QA_ORDER = tuple(CONTRACT.get("qa_order") or ("package", "rendered", "actual_content", "quality", "delivery"))
BUILD_FROM = {"planned", "producing"}
QA_FROM = {"producing", "qa"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_path(work_dir: Path) -> Path:
    return work_dir / MANIFEST_NAME


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_manifest(work_dir: Path) -> dict[str, Any] | None:
    return load_json(manifest_path(work_dir))


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
            f"{action} requires state in {sorted(allowed)}, but manifest is '{current}'"
        )


def bind(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path)}


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_stage_summary(work_dir: Path, state: str, lines: list[str]) -> Path:
    """CD-4: the pipeline writes the ≤30-line stage entry, not the model."""
    path = work_dir / f"stage-{state}-summary.md"
    body = [f"# stage-{state}", ""]
    for line in lines:
        if line is None:
            continue
        body.append(line)
        if len(body) >= 32:
            break
    body.append("")
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def record(manifest: dict[str, Any], command: str, before: str, after: str, **extra: Any) -> None:
    manifest.setdefault("history", []).append(
        {"at": now(), "command": command, "from": before, "to": after, **extra}
    )


def default_workflow_state(work_dir: Path) -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / "outputs" / ".student-presentation-state.json"
    resolved = work_dir.resolve()
    # canonical work dir: <project>/outputs/.pptx-work/<work-id>
    if resolved.parent.name == ".pptx-work" and resolved.parent.parent.name == "outputs":
        return resolved.parent.parent / ".student-presentation-state.json"
    return resolved.parent / ".student-presentation-state.json"


def validate_intake(state_path: Path) -> dict[str, Any]:
    state = load_json(state_path)
    if not state:
        raise RefusedError(
            f"intake state missing: {state_path}; run workflow_guard.py init/confirm first"
        )
    if state.get("state") != "intake_confirmed":
        raise RefusedError(
            f"plan requires workflow state intake_confirmed, got {state.get('state')!r}"
        )
    summary_file = Path(str(state.get("summary_file") or ""))
    summary_sha = str(state.get("summary_sha256") or "")
    if not summary_file.is_file() or not summary_sha:
        raise RefusedError("confirmed workflow state has no valid Production Summary binding")
    if sha256_file(summary_file) != summary_sha:
        raise RefusedError("Production Summary changed after confirmation; confirm it again")
    return state


def validate_manifest_authorization(manifest: dict[str, Any]) -> None:
    workflow = manifest.get("workflow") or {}
    state_path = Path(str(workflow.get("state_file") or ""))
    summary_path = Path(str(workflow.get("summary_file") or ""))
    summary_sha = str(workflow.get("summary_sha256") or "")
    if not state_path.is_file() or not summary_path.is_file() or not summary_sha:
        raise RefusedError("manifest has no valid intake authorization binding; re-plan")
    if sha256_file(summary_path) != summary_sha:
        raise RefusedError("Production Summary changed after plan; re-confirm and re-plan")


def mirror_workflow_state(manifest: dict[str, Any], state: str, *, reason: str | None = None) -> None:
    workflow = manifest.get("workflow") or {}
    path = Path(str(workflow.get("state_file") or ""))
    current = load_json(path)
    if not current:
        raise RefusedError(f"workflow state disappeared after plan: {path}")
    current["state"] = state
    current["updated_at"] = now()
    current["pipeline_manifest"] = str(manifest_path(Path(str(manifest.get("work_dir") or "."))))
    current["pipeline_manifest_version"] = MANIFEST_VERSION
    if reason:
        current["last_pipeline_reason"] = reason
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generator_files(entry: Path) -> list[Path]:
    pages_dir = entry.parent / "pages"
    pages = sorted(pages_dir.glob("*.js")) if pages_dir.is_dir() else []
    return [entry, *pages]


def generator_fingerprint(entry: Path) -> tuple[str, list[dict[str, Any]]]:
    files = generator_files(entry)
    bindings = [bind(path) for path in files]
    return stable_hash([(item["path"], item["sha256"]) for item in bindings]), bindings


def qa_input_fingerprint(
    pptx: Path,
    visual_review: Path | None,
    notes: Path | None,
    previews: list[Path],
) -> str:
    values: list[tuple[str, str | None]] = [("pptx", sha256_file(pptx))]
    for label, path in (("visual_review", visual_review), ("notes", notes)):
        values.append((label, sha256_file(path) if path and path.is_file() else None))
    values.extend((f"preview:{path.resolve()}", sha256_file(path)) for path in previews if path.is_file())
    return stable_hash(values)


@dataclass
class Stage:
    name: str
    argv: list[str]
    report: Path
    artifact: str
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

    candidates: dict[str, Stage] = {
        "package": Stage(
            "package",
            [sys.executable, str(PPTX_TOOL), "validate", pptx, "--output", str(work_dir / "qa-package.json")],
            work_dir / "qa-package.json", "package",
        ),
        "rendered": Stage(
            "rendered",
            gate("pptx_rendered_check.py", "--pptx", pptx, "--output", str(work_dir / "qa-rendered.json")),
            work_dir / "qa-rendered.json", "rendered",
        ),
    }
    if spec:
        candidates["actual_content"] = Stage(
            "actual-content",
            gate("pptx_actual_content_check.py", pptx, spec, "--output", str(work_dir / "qa-actual-content.json")),
            work_dir / "qa-actual-content.json", "actual_content",
        )
    if spec and lock and visual_review:
        candidates["quality"] = Stage(
            "quality",
            gate(
                "pptx_quality_gate_v071.py", "--pptx", pptx, "--slide-spec", spec,
                "--spec-lock", lock, "--visual-report", str(visual_review),
                "--output", str(work_dir / "qa-quality.json"),
            ),
            work_dir / "qa-quality.json", "quality",
        )

    required = {
        "pptx": pptx, "slide-spec": spec, "spec-lock": lock, "art-direction": art,
        "visual-generation-report": vgr, "slide-spec-report": spec_report,
        "visual-review": str(visual_review or ""),
    }
    if not [name for name, value in required.items() if not value] and {
        "package", "actual_content", "quality"
    } <= set(candidates):
        argv = gate(
            "pptx_delivery_check_v08.py",
            "--pptx", pptx, "--slide-spec", spec, "--spec-lock", lock,
            "--art-direction", art, "--visual-generation-report", vgr,
            "--quality-report", str(work_dir / "qa-quality.json"),
            "--package-report", str(work_dir / "qa-package.json"),
            "--slide-spec-report", spec_report,
            "--actual-content-report", str(work_dir / "qa-actual-content.json"),
            "--visual-reviewed", "--visual-review-report", str(visual_review),
            "--output", str(work_dir / "qa-delivery.json"),
        )
        if notes:
            argv += ["--notes", str(notes)]
        for preview in previews or []:
            argv += ["--preview", str(preview)]
        if allow_missing_preview:
            argv.append("--allow-missing-preview")
        candidates["delivery"] = Stage(
            "delivery", argv, work_dir / "qa-delivery.json", "delivery"
        )

    return [candidates[name] for name in QA_ORDER if name in candidates]


def normalise_severity(report: dict[str, Any], issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity") or "").lower()
    if severity in {"critical", "major", "blocker"}:
        return "critical" if severity == "critical" else "major"
    if severity == "minor":
        return "minor"
    return "major" if not report.get("ok", True) else "minor"


def collect(stage: Stage) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    proc = _runner(stage.argv)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not stage.report.is_file():
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, [{
            "gate": stage.name, "severity": "critical",
            "code": f"{stage.name}_missing_report",
            "message": f"{stage.name} produced no report (exit {proc.returncode}): {detail[:200]}",
        }], {"ok": False, "checked": True, "exit_code": proc.returncode, "duration_ms": duration_ms}
    report = json.loads(stage.report.read_text(encoding="utf-8"))
    issues = report.get(stage.issues_key) if isinstance(report.get(stage.issues_key), list) else []
    problems = [{
        "gate": stage.name,
        "severity": normalise_severity(report, issue),
        "code": str(issue.get("code") or f"{stage.name}_issue"),
        "message": str(issue.get("message") or issue.get("detail") or issue.get("problem") or issue),
        **({"slide": issue.get("slide")} if issue.get("slide") is not None else {}),
    } for issue in issues if isinstance(issue, dict)]
    binding = {
        "ok": bool(report.get("ok", proc.returncode == 0)), "checked": True,
        "exit_code": proc.returncode, "duration_ms": duration_ms,
        "issue_count": len(issues), **bind(stage.report),
    }
    if not issues and not binding["ok"]:
        problems.append({
            "gate": stage.name, "severity": "major" if proc.returncode else "minor",
            "code": f"{stage.name}_failed",
            "message": f"{stage.name} reported not ok without itemised issues (exit {proc.returncode}).",
        })
    return binding["ok"], problems, binding


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        marker = (item["severity"], item["code"], str(item["message"]))
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_runner: Runner = run_command


def cmd_plan(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    if not args.force:
        require_state(manifest, {"(absent)", "planned"}, "plan")
    if manifest and manifest.get("state") == "planned" and not args.force:
        raise RefusedError("already planned; pass --force to re-plan")

    workflow_state_path = (args.workflow_state or default_workflow_state(work_dir)).resolve()
    intake = validate_intake(workflow_state_path)

    spec = args.slide_spec.resolve()
    validation_report = args.validation_report.resolve()
    art = args.art_direction.resolve()
    for label, path in (("Slide Spec", spec), ("validation report", validation_report), ("Art Direction", art)):
        if not path.is_file():
            raise RefusedError(f"{label} does not exist: {path}")

    fresh: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "contract_version": CONTRACT.get("contract_version"),
        "work_id": work_dir.name,
        "work_dir": str(work_dir),
        "state": "(absent)", "inputs": {},
        "workflow": {
            "state_file": str(workflow_state_path),
            "summary_file": str(Path(str(intake["summary_file"])).resolve()),
            "summary_sha256": str(intake["summary_sha256"]),
        },
        "build": {"build_count": 0, "repair_count": 0, "pending_repair": False},
        "render": {}, "qa": {}, "history": [],
    }
    if manifest and args.force:
        fresh["build"]["repair_count"] = int((manifest.get("build") or {}).get("repair_count") or 0)
        fresh["history"] = list(manifest.get("history") or [])

    preflight_report = work_dir / "copy-fit-preflight.json"
    pre = _runner([
        sys.executable, str(HERE / "copy_fit_preflight.py"), "--slide-spec", str(spec),
        "--art-direction", str(art), "--output", str(preflight_report),
    ])
    if preflight_report.is_file():
        fresh["inputs"]["copy_fit_preflight"] = bind(preflight_report)
    if pre.returncode != 0:
        detail = (pre.stderr or pre.stdout or "").strip()
        raise RefusedError(f"copy-fit preflight blocked plan (exit {pre.returncode}): {detail[:400]}")

    lock = work_dir / "slide-spec-lock.json"
    freeze_argv = [
        sys.executable, str(HERE / "slide_spec_guard.py"), "freeze",
        "--slide-spec", str(spec), "--validation-report", str(validation_report),
        "--lock-file", str(lock), "--reason", args.reason,
    ]
    for flag, path in (("--research-pack", args.research_pack), ("--research-validation", args.research_validation), ("--evidence-map", args.evidence_map)):
        if path:
            freeze_argv += [flag, str(path.resolve())]
    frozen = _runner(freeze_argv)
    if frozen.returncode != 0 or not lock.is_file():
        detail = (frozen.stderr or frozen.stdout or "").strip()
        raise RefusedError(f"slide_spec_guard freeze failed (exit {frozen.returncode}): {detail[:400]}")

    fresh["inputs"].update({
        "slide_spec": bind(spec), "spec_lock": bind(lock),
        "slide_spec_report": bind(validation_report), "art_direction": bind(art),
    })
    for key, path in (("visual_generation_report", args.visual_generation_report), ("evidence_map", args.evidence_map), ("research_pack", args.research_pack), ("research_validation", args.research_validation)):
        if path:
            resolved = path.resolve()
            if not resolved.is_file():
                raise RefusedError(f"{key} does not exist: {resolved}")
            fresh["inputs"][key] = bind(resolved)

    fresh["state"] = "planned"
    record(fresh, "plan", "(absent)", "planned")
    scaffold_info = _scaffold.scaffold_generator(work_dir, spec)
    fresh["scaffold"] = {
        "slides": scaffold_info["slides"],
        "pages": scaffold_info["pages"],
    }
    summary = write_stage_summary(
        work_dir,
        "planned",
        [
            f"- spec: `{spec}`",
            f"- art-direction: `{art}`",
            f"- pages scaffolded: {scaffold_info['slides']} → `pages/`",
            f"- composition dir: `{work_dir / 'composition'}`",
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


def cmd_build(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, BUILD_FROM, "build")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    state = str(manifest.get("state"))
    build_info = manifest.setdefault("build", {})
    if state == "producing" and not build_info.get("pending_repair"):
        raise RefusedError("repeat build refused; run repair after QA before rebuilding")

    inputs = manifest.get("inputs") or {}
    lock = Path(str((inputs.get("spec_lock") or {}).get("path") or ""))
    spec = Path(str((inputs.get("slide_spec") or {}).get("path") or ""))
    if not lock.is_file():
        raise RefusedError(f"spec lock missing: {lock}")
    check = _runner([
        sys.executable, str(HERE / "slide_spec_guard.py"), "check",
        "--lock-file", str(lock), "--slide-spec", str(spec),
    ])
    if check.returncode != 0:
        detail = (check.stderr or check.stdout or "").strip()
        raise RefusedError(f"spec lock check failed; re-plan first: {detail[:400]}")

    entry = args.entry.resolve()
    if not entry.is_file():
        raise RefusedError(f"generator entry does not exist: {entry}")
    try:
        _scaffold.assert_page_split(entry, spec)
    except ValueError as exc:
        raise RefusedError(str(exc)) from exc
    fingerprint, bindings = generator_fingerprint(entry)
    previous = str(build_info.get("generator_fingerprint") or "")
    if state == "producing" and build_info.get("pending_repair") and previous == fingerprint:
        raise RefusedError("repair produced no generator change; refusing identical rebuild")

    pptx = work_dir / args.output_name
    if pptx.suffix.lower() != ".pptx":
        raise RefusedError("--output-name must end in .pptx")
    node = os.environ.get("NODE") or "node"
    built = _runner([node, str(BUILDER), "--output", str(pptx), str(entry), *args.generator_args])
    if built.returncode != 0 or not pptx.is_file():
        detail = (built.stderr or built.stdout or "").strip()
        raise RefusedError(f"build failed (exit {built.returncode}): {detail[:600]}")

    build_info.update({
        "entry": str(entry), "pptx": bind(pptx), "generator_files": bindings,
        "generator_fingerprint": fingerprint,
        "build_count": int(build_info.get("build_count") or 0) + 1,
        "pending_repair": False,
    })
    manifest["render"] = {}
    manifest["qa"] = {}
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(manifest, "build", before, "producing", generator_fingerprint=fingerprint)
    save_manifest(work_dir, manifest)
    write_stage_summary(
        work_dir,
        "producing",
        [
            f"- pptx: `{pptx}` sha256 {build_info['pptx']['sha256'][:12]}",
            f"- builds: {build_info['build_count']} repairs: {build_info.get('repair_count', 0)}",
            f"- generator files: {len(build_info.get('generator_files') or [])}",
            "- next: `ppt_pipeline.py render`, then Read contact-sheet + blocker PNGs (CD-9)",
        ],
    )
    mirror_workflow_state(manifest, "producing")
    print(f"ppt_pipeline: built {pptx.name} (builds {build_info['build_count']}, repairs {build_info.get('repair_count', 0)})")
    return 0


def make_contact_sheet(pages: list[Path], output: Path, cols: int = 3) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RefusedError("Pillow is required for contact-sheet generation") from exc
    if not pages:
        raise RefusedError("render produced no pages")
    opened = [Image.open(path).convert("RGB") for path in pages]
    width = min(480, max(image.width for image in opened))
    thumbs = []
    for image in opened:
        ratio = width / image.width
        thumb = image.resize((width, max(1, int(image.height * ratio))))
        thumbs.append(thumb)
    cell_h = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (width * cols, cell_h * rows), "white")
    for index, image in enumerate(thumbs):
        framed = ImageOps.expand(image, border=2, fill="black")
        x = (index % cols) * width
        y = (index // cols) * cell_h
        sheet.paste(framed, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    for image in opened:
        image.close()


def cmd_render(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"producing", "qa"}, "render")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    pptx = Path(str(((manifest.get("build") or {}).get("pptx") or {}).get("path") or ""))
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    pptx_sha = sha256_file(pptx)
    previous = manifest.get("render") or {}
    old_pages = [Path(str(item.get("path"))) for item in previous.get("pages") or []]
    old_contact = Path(str((previous.get("contact_sheet") or {}).get("path") or ""))
    if previous.get("pptx_sha256") == pptx_sha and old_contact.is_file() and old_pages and all(p.is_file() for p in old_pages):
        print(f"ppt_pipeline: render reused — {old_contact}")
        return 0

    render_dir = work_dir / "render"
    proc = _runner([
        sys.executable, str(PPTX_TOOL), "render", str(pptx),
        "--output-dir", str(render_dir), "--prefix", args.prefix,
    ])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RefusedError(f"render failed (exit {proc.returncode}): {detail[:500]}")
    payload = None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pass
    page_values = payload.get("pages") if isinstance(payload, dict) else None
    pages = [Path(str(path)) for path in page_values] if isinstance(page_values, list) else sorted(render_dir.glob(f"{args.prefix}*.png"))
    if not pages or not all(path.is_file() for path in pages):
        raise RefusedError("render reported success but page images are missing")
    contact = work_dir / "contact-sheet.png"
    make_contact_sheet(pages, contact, args.cols)
    manifest["render"] = {
        "pptx_sha256": pptx_sha,
        "pages": [bind(path) for path in pages],
        "contact_sheet": bind(contact),
        "page_count": len(pages),
        "rendered_at": now(),
    }
    record(manifest, "render", str(manifest.get("state")), str(manifest.get("state")), page_count=len(pages))
    save_manifest(work_dir, manifest)
    print(f"ppt_pipeline: rendered {len(pages)} pages — contact sheet: {contact}")
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, QA_FROM, "qa")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    pptx = Path(str(((manifest.get("build") or {}).get("pptx") or {}).get("path") or ""))
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    visual_review = args.visual_review.resolve() if args.visual_review else None
    notes = args.notes.resolve() if args.notes else None
    previews = [Path(p).resolve() for p in (args.preview or [])]
    fingerprint = qa_input_fingerprint(pptx, visual_review, notes, previews)
    old_qa = manifest.get("qa") or {}
    old_report = Path(str((old_qa.get("report") or {}).get("path") or ""))
    if manifest.get("state") == "qa" and old_qa.get("input_fingerprint") == fingerprint and old_report.is_file():
        ok = bool(old_qa.get("ok"))
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
        problems.extend(stage_problems)
        if not ok:
            break
    problems = dedupe(problems)
    counts = {s: sum(1 for p in problems if p["severity"] == s) for s in ("critical", "major", "minor")}
    blockers = counts["critical"] + counts["major"]
    qa_report = {
        "ok": blockers == 0, "pipeline_version": MANIFEST_VERSION,
        "qa_order": list(QA_ORDER), "pptx": str(pptx),
        "counts": {"blockers": blockers, **counts}, "problems": problems, "reports": reports,
    }
    qa_report_path = work_dir / "pipeline-qa.json"
    qa_report_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before = str(manifest.get("state"))
    manifest["qa"] = {
        "ok": qa_report["ok"], "blockers": blockers, "input_fingerprint": fingerprint,
        "report": bind(qa_report_path), "stages": reports,
        "visual_review": bind(visual_review) if visual_review and visual_review.is_file() else None,
        "previews": [bind(path) for path in previews if path.is_file()] or None,
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
        f"stages: {names} | report: {qa_report_path}"
    )
    write_stage_summary(
        work_dir,
        "qa",
        [
            f"- {line}",
            f"- report: `{qa_report_path}`",
            "- next: `ppt_pipeline.py complete` if ok, else `repair --reason …` then rebuild",
        ],
    )
    print(line)
    for item in problems[: args.max_items]:
        print(f"  [{item['severity']}] {item['gate']}/{item['code']} — {str(item['message'])[:200]}")
    return 0 if qa_report["ok"] else 2


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
    if repairs >= MAX_REPAIRS:
        raise RefusedError(f"repair budget exhausted ({MAX_REPAIRS}); mark the task incomplete")
    build_info["repair_count"] = repairs + 1
    build_info["pending_repair"] = True
    build_info.setdefault("repair_reasons", []).append(args.reason)
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(manifest, "repair", before, "producing", repair_count=repairs + 1, reason=args.reason)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "producing", reason=args.reason)
    print(f"ppt_pipeline: repair {repairs + 1}/{MAX_REPAIRS} — change generator, then build → render → qa")
    return 0


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
    before = str(manifest.get("state"))
    manifest["state"] = "complete"
    record(manifest, "complete", before, "complete")
    save_manifest(work_dir, manifest)
    write_stage_summary(
        work_dir,
        "complete",
        [
            "- QA green; delivery stage ran and was hash-bound.",
            f"- pptx: `{((manifest.get('build') or {}).get('pptx') or {}).get('path')}`",
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
    print(
        f"ppt_pipeline: {manifest.get('state')} — builds {build.get('build_count', 0)}, "
        f"repairs {build.get('repair_count', 0)}/{MAX_REPAIRS}, rendered {render.get('page_count', 0)} | "
        f"qa {'ok' if qa.get('ok') else str(qa.get('blockers', '-')) + ' blockers'}"
    )
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Tell the model what to read and which command to run. CD-1/CD-3/CD-4/CD-9."""
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    python = sys.executable
    pipeline = HERE / "ppt_pipeline.py"
    if not manifest:
        payload = {
            "state": "(absent)",
            "read": [],
            "forbidden_to_read": ["${CLAUDE_PLUGIN_ROOT}/references/*.md"],
            "read_images": [],
            "next_command": (
                f'{python} "{pipeline}" plan --work-dir "{work_dir}" '
                "--slide-spec <compiled-spec> --validation-report <report> "
                "--art-direction <art-direction.yaml>"
            ),
            "allowed_writes": ["production-summary.md", "art-direction.yaml", "slide-spec.yaml"],
            "notes": "intake first; do not grep plugin source — this command is the discovery API",
        }
    else:
        state = str(manifest.get("state") or "(absent)")
        summary = work_dir / f"stage-{state}-summary.md"
        read = [str(summary)] if summary.is_file() else []
        forbidden = ["slide-spec.yaml", "art-direction.yaml", "research-pack.json"]
        payload = {
            "state": state,
            "read": read,
            "forbidden_to_read": forbidden,
            "read_images": [],
            "next_command": "",
            "allowed_writes": ["pages/pNN-*.js"],
            "notes": "different pages must be Edit'ed in the same turn (CD-1, CD-2)",
        }
        entry = work_dir / "deck.js"
        if state == "planned":
            payload["next_command"] = (
                f'{python} "{pipeline}" build --work-dir "{work_dir}" --entry "{entry}"'
            )
            payload["notes"] = (
                "fill pages/pNN-*.js with parallel Edit, then build. "
                "Put v0.8 composition JSON in composition/."
            )
        elif state == "producing":
            contact = work_dir / "contact-sheet.png"
            if not contact.is_file():
                payload["next_command"] = (
                    f'{python} "{pipeline}" render --work-dir "{work_dir}"'
                )
                payload["notes"] = (
                    "run render first; then Read contact-sheet + blocker page PNGs "
                    "in ONE parallel round (CD-9)"
                )
            else:
                payload["read_images"] = [
                    str(contact),
                    str(work_dir / "render"),
                ]
                payload["next_command"] = (
                    f'{python} "{pipeline}" qa --work-dir "{work_dir}" '
                    f'--visual-review "{work_dir / "visual-review.json"}"'
                )
                payload["notes"] = (
                    "CD-9: Read contact-sheet + blocker page PNGs in ONE parallel round; "
                    "same PPTX hash must not be re-read"
                )
        elif state == "qa":
            qa = manifest.get("qa") or {}
            if qa.get("ok"):
                payload["next_command"] = f'{python} "{pipeline}" complete --work-dir "{work_dir}"'
            else:
                payload["next_command"] = (
                    f'{python} "{pipeline}" repair --work-dir "{work_dir}" --reason "<summary>"'
                )
                payload["notes"] = "fix every blocker page in one parallel Edit round, then build + qa"
        elif state == "complete":
            payload["next_command"] = "(done)"
            payload["notes"] = "do not re-inject /sp-deck"
        else:
            payload["next_command"] = f'{python} "{pipeline}" status --work-dir "{work_dir}"'

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"state: {payload['state']}")
    print("read:")
    for item in payload["read"] or ["(none)"]:
        print(f"  - {item}")
    print("forbidden_to_read:")
    for item in payload["forbidden_to_read"]:
        print(f"  - {item}")
    if payload.get("read_images"):
        print("read_images (same turn, parallel):")
        for item in payload["read_images"]:
            print(f"  - {item}")
    print(f"next_command: {payload['next_command']}")
    print(f"allowed_writes: {', '.join(payload['allowed_writes'])}")
    print(f"notes: {payload['notes']}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="verify intake, preflight and freeze -> planned")
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--workflow-state", type=Path, help="confirmed .student-presentation-state.json")
    plan.add_argument("--slide-spec", type=Path, required=True)
    plan.add_argument("--validation-report", type=Path, required=True)
    plan.add_argument("--art-direction", type=Path, required=True)
    plan.add_argument("--visual-generation-report", type=Path)
    plan.add_argument("--research-pack", type=Path)
    plan.add_argument("--research-validation", type=Path)
    plan.add_argument("--evidence-map", type=Path)
    plan.add_argument("--reason", default="initial approved production plan")
    plan.add_argument("--force", action="store_true")
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build", help="build once; repeated builds require repair + changed generator")
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--entry", type=Path, required=True)
    build.add_argument("--output-name", default="deck.pptx")
    build.add_argument("generator_args", nargs="*")
    build.set_defaults(func=cmd_build)

    render = sub.add_parser("render", help="render all pages once and create a contact sheet")
    render.add_argument("--work-dir", type=Path, required=True)
    render.add_argument("--prefix", default="slide")
    render.add_argument("--cols", type=int, default=3)
    render.set_defaults(func=cmd_render)

    qa = sub.add_parser("qa", help="run fail-fast QA DAG; identical inputs reuse prior result")
    qa.add_argument("--work-dir", type=Path, required=True)
    qa.add_argument("--visual-review", type=Path)
    qa.add_argument("--notes", type=Path)
    qa.add_argument("--preview", type=Path, nargs="+", action="extend")
    qa.add_argument("--allow-missing-preview", action="store_true")
    qa.add_argument("--max-items", type=int, default=12)
    qa.set_defaults(func=cmd_qa)

    repair = sub.add_parser("repair", help=f"qa blockers -> producing; max {MAX_REPAIRS}")
    repair.add_argument("--work-dir", type=Path, required=True)
    repair.add_argument("--reason", required=True)
    repair.add_argument("--force", action="store_true")
    repair.set_defaults(func=cmd_repair)

    complete = sub.add_parser("complete", help="qa + delivery ok -> complete")
    complete.add_argument("--work-dir", type=Path, required=True)
    complete.set_defaults(func=cmd_complete)

    status = sub.add_parser("status", help="one-line manifest summary")
    status.add_argument("--work-dir", type=Path, required=True)
    status.set_defaults(func=cmd_status)

    nxt = sub.add_parser("next", help="what to read and which command to run next")
    nxt.add_argument("--work-dir", type=Path, required=True)
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)

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
