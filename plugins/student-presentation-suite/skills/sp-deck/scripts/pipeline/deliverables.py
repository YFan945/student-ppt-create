from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from pipeline import core
from pipeline.core import (
    ROOT,
    RefusedError,
    bind,
    binding_is_current,
    load_manifest,
    mirror_workflow_state,
    now,
    pptx_path,
    record,
    render_is_current,
    require_state,
    save_manifest,
    validate_manifest_authorization,
)

SUPPORT_DELIVERABLES = {
    "speaker-notes",
    "full-script",
    "teleprompter",
    "training-cards",
    "references",
}
PREPARED_DELIVERABLES = SUPPORT_DELIVERABLES | {"pdf"}
SUPPORT_SCRIPT = ROOT / "scripts" / "build_support_outputs.py"


def _load_spec(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            value = json.loads(raw)
        else:
            import yaml  # noqa: PLC0415

            value = yaml.safe_load(raw)
    except (OSError, UnicodeDecodeError, ValueError, ImportError) as exc:
        raise RefusedError(f"cannot read deliverables from Slide Spec: {exc}") from exc
    if not isinstance(value, dict):
        raise RefusedError("Slide Spec must be an object")
    return value


def confirmed_deliverables(manifest: dict[str, Any]) -> list[str]:
    spec_binding = (manifest.get("inputs") or {}).get("slide_spec") or {}
    spec_value = str(spec_binding.get("path") or "")
    # Minimal/legacy manifests without a Slide Spec predate optional support
    # outputs. Preserve their PPTX-only behavior instead of trying to read '.'.
    if not spec_value:
        return ["pptx"]
    spec = Path(spec_value)
    data = _load_spec(spec)
    meta = data.get("meta") or {}
    value = meta.get("deliverables") or meta.get("export_formats") or ["pptx"]
    return [str(item) for item in value] if isinstance(value, list) else ["pptx"]


def requested_prepared_deliverables(manifest: dict[str, Any]) -> list[str]:
    return sorted(set(confirmed_deliverables(manifest)) & PREPARED_DELIVERABLES)


def deliverables_are_current(manifest: dict[str, Any]) -> bool:
    requested = requested_prepared_deliverables(manifest)
    if not requested:
        return True
    prepared = manifest.get("deliverables") or {}
    if prepared.get("requested") != requested:
        return False
    if not binding_is_current(prepared.get("source_pptx") or {}):
        return False
    if not binding_is_current(prepared.get("source_slide_spec") or {}):
        return False
    source_notes = prepared.get("source_speaker_notes")
    if source_notes and not binding_is_current(source_notes):
        return False
    outputs = prepared.get("outputs") or {}
    if any(name not in outputs or not binding_is_current(outputs[name]) for name in requested):
        return False
    if "speaker-notes" in requested:
        try:
            notes_path = Path(str(outputs["speaker-notes"]["path"]))
            pptx = Path(str(prepared["source_pptx"]["path"]))
            spec = Path(str(prepared["source_slide_spec"]["path"]))
            if notes_path.read_text(encoding="utf-8") != speaker_notes_markdown(pptx, spec):
                return False
        except (OSError, ValueError, KeyError, RefusedError, zipfile.BadZipFile):
            return False
    report = prepared.get("report")
    return bool(report and binding_is_current(report))


def deliverable_bindings(value: Any) -> list[dict[str, Any]]:
    """Return every file binding carried by a prepared-deliverables snapshot."""
    if not isinstance(value, dict):
        return []
    bindings: list[dict[str, Any]] = []
    for name in ("source_pptx", "source_slide_spec", "source_speaker_notes", "report"):
        item = value.get(name)
        if isinstance(item, dict):
            bindings.append(item)
    outputs = value.get("outputs") or {}
    if isinstance(outputs, dict):
        bindings.extend(item for item in outputs.values() if isinstance(item, dict))
    return bindings


def speaker_notes_markdown(pptx: Path, spec: Path) -> str:
    """Render readable notes from the delivered PPTX, in slide order."""
    from pptx_actual_content_check import extract_pptx_notes  # noqa: PLC0415

    data = _load_spec(spec)
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not slides:
        raise RefusedError("speaker-notes export requires a nonempty Slide Spec")
    notes = extract_pptx_notes(pptx)
    expected = list(range(1, len(slides) + 1))
    if sorted(notes) != expected or any(not notes[number].strip() for number in expected):
        raise RefusedError("speaker-notes export requires notes on every PPTX slide")
    sections = ["# 演讲稿"]
    for number, slide in enumerate(slides, 1):
        title = str(slide.get("title") or "").strip() if isinstance(slide, dict) else ""
        sections.append(f"## 第 {number} 页" + (f" · {title}" if title else ""))
        sections.append(notes[number].strip())
    return "\n\n".join(sections) + "\n"


def export_speaker_notes(pptx: Path, spec: Path, target: Path) -> None:
    target.write_text(speaker_notes_markdown(pptx, spec), encoding="utf-8")


def cmd_prepare_deliverables(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"producing", "qa"}, "prepare-deliverables")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    if not render_is_current(manifest):
        raise RefusedError("prepare-deliverables requires current render evidence")
    requested = requested_prepared_deliverables(manifest)
    if not requested:
        print("ppt_pipeline: no support/export deliverables requested")
        return 0
    if deliverables_are_current(manifest):
        print("ppt_pipeline: deliverables reused — all requested outputs are current")
        return 0

    pptx = pptx_path(manifest)
    spec = Path(str(((manifest.get("inputs") or {}).get("slide_spec") or {}).get("path") or ""))
    suffix = "-presentation"
    prefix = pptx.stem[: -len(suffix)] if pptx.stem.endswith(suffix) else pptx.stem
    outputs: dict[str, dict[str, Any]] = {}

    support = sorted(set(requested) & SUPPORT_DELIVERABLES)
    merged_notes = work_dir / "speaker-notes.md"
    if "speaker-notes" in support or any(
        name in requested for name in {"full-script", "teleprompter"}
    ):
        export_speaker_notes(pptx, spec, merged_notes)
    if "speaker-notes" in support:
        outputs["speaker-notes"] = bind(merged_notes)
        support.remove("speaker-notes")
    if support:
        argv = [
            sys.executable,
            str(SUPPORT_SCRIPT),
            str(spec),
            "--output-dir",
            str(work_dir),
            "--prefix",
            prefix,
            "--json",
            "--pptx",
            str(pptx),
        ]
        if merged_notes.is_file():
            argv += ["--speaker-notes", str(merged_notes)]
        for name in support:
            argv += ["--only", name]
        proc = core._runner(argv)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RefusedError(f"support-output generation failed: {detail[:500]}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RefusedError("support-output generation returned invalid JSON") from exc
        generated = payload.get("outputs") if isinstance(payload, dict) else None
        if not isinstance(generated, dict):
            raise RefusedError("support-output generation reported no outputs")
        for name in support:
            path = Path(str(generated.get(name) or ""))
            if not path.is_file():
                raise RefusedError(f"support-output generation omitted {name}")
            outputs[name] = bind(path)

    if "pdf" in requested:
        render_pdf_binding = (manifest.get("render") or {}).get("pdf") or {}
        render_pdf = Path(str(render_pdf_binding.get("path") or ""))
        if not render_pdf.is_file() or not binding_is_current(render_pdf_binding):
            raise RefusedError("current render has no hash-bound PDF export; rerun render")
        target = pptx.with_suffix(".pdf")
        if render_pdf.resolve() != target.resolve():
            shutil.copyfile(render_pdf, target)
        outputs["pdf"] = bind(target)

    missing = [name for name in requested if name not in outputs]
    if missing:
        raise RefusedError("requested deliverables were not prepared: " + ", ".join(missing))
    report_path = work_dir / "deliverables-report.json"
    report: dict[str, Any] = {
        "ok": True,
        "prepared_at": now(),
        "source_pptx": bind(pptx),
        "source_slide_spec": bind(spec),
        "page_count": int((manifest.get("render") or {}).get("page_count") or 0),
        "requested": requested,
        "outputs": outputs,
    }
    if merged_notes.is_file() and any(
        name in requested for name in {"full-script", "teleprompter"}
    ):
        report["source_speaker_notes"] = bind(merged_notes)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["deliverables"] = {**report, "report": bind(report_path)}
    before = str(manifest.get("state"))
    after = "producing" if before == "qa" else before
    if before == "qa":
        # Recreating a deleted or changed support/export file invalidates the QA
        # result that checked the previous bytes, but it does not change the PPTX
        # or render. Keep the old, hash-bound visual evidence so dispatch can
        # rerun deterministic QA without paying for another critic pass.
        manifest["state"] = after
    record(
        manifest,
        "prepare-deliverables",
        before,
        after,
        requested=requested,
        visual_evidence_retained=before == "qa",
    )
    save_manifest(work_dir, manifest)
    if before == "qa":
        mirror_workflow_state(manifest, after)
    print("ppt_pipeline: prepared deliverables — " + ", ".join(requested))
    return 0
