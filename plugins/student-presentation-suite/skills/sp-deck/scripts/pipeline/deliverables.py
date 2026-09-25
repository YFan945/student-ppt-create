from __future__ import annotations

import argparse
import json
import re
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

PPTX_SLIDE_RE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
PDF_PAGE_RE = re.compile(rb"/Type\s*/Page(?![s/A-Za-z])")
NOTES_SECTION_RE = re.compile(r"(?m)^##\s+第\s*(\d+)\s*页(?:\s*[-—:：·][^\n]*)?\s*$")
SCRIPT_SECTION_RE = re.compile(r"(?m)^##\s+Slide\s+(\d+)\s*:")
TELEPROMPTER_SECTION_RE = re.compile(r'data-slide="(\d+)"')
REFERENCE_ENTRY_RE = re.compile(r"(?m)^-\s+\[")


def _slide_id(slide: Any, fallback: int) -> int:
    try:
        value = int(slide.get("id")) if isinstance(slide, dict) else 0
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else fallback


def expected_slide_ids(spec: dict[str, Any]) -> list[int]:
    """One deliverable page per Slide Spec slide, by slide id (position fallback)."""
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        return []
    return [_slide_id(slide, position) for position, slide in enumerate(slides, 1)]


def pdf_page_count(path: Path) -> int:
    """Count pages of a PDF export without new dependencies.

    The only PDF the pipeline ever publishes is the render-owned LibreOffice
    export, whose page objects are plain indirect objects. Undeterminable input
    is refused rather than waved through: a page count nobody can check is
    exactly the gap that once shipped a 12-page script with 1-3 pages missing.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RefusedError(f"cannot read PDF deliverable: {path}") from exc
    if not data.startswith(b"%PDF-"):
        raise RefusedError(f"PDF deliverable is not a PDF file: {path}")
    count = len(PDF_PAGE_RE.findall(data))
    if count < 1:
        raise RefusedError(
            f"cannot determine the page count of {path.name}; refusing to publish an unverified PDF"
        )
    return count


def _section_bodies(text: str, heading_re: re.Pattern[str]) -> dict[int, str]:
    matches = list(heading_re.finditer(text))
    bodies: dict[int, str] = {}
    for index, match in enumerate(matches):
        # Body starts on the line BELOW the heading: a heading suffix such as
        # "## Slide 2: 方法" leaves "方法" after the colon, which is title text.
        line_end = text.find("\n", match.end())
        start = len(text) if line_end == -1 else line_end + 1
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bodies[int(match.group(1))] = text[start:end].strip()
    return bodies


def verify_deliverable(
    name: str, path: Path, spec: dict[str, Any], *, render_pages: int | None = None
) -> dict[str, int]:
    """Check artifact completeness against the frozen Slide Spec before binding.

    Hash bindings prove bytes did not change; this proves the bytes cover every
    page. Both are required before a deliverable may be published — the page
    count is returned so the published record carries it.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise RefusedError(f"deliverable is missing or empty: {path}")
    ids = expected_slide_ids(spec)

    def require_coverage(found: set[int], unit: str) -> int:
        if not ids:
            return len(found)
        expected = set(ids)
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        if missing or extra or len(ids) != len(set(ids)):
            detail = []
            if missing:
                detail.append(f"missing {unit} {missing}")
            if extra:
                detail.append(f"unexpected {unit} {extra}")
            raise RefusedError(
                f"{name} does not cover the Slide Spec ({len(ids)} slides): "
                + "; ".join(detail)
                + f" — regenerate before delivery: {path}"
            )
        return len(ids)

    if name == "pptx":
        try:
            with zipfile.ZipFile(path) as archive:
                found = {
                    int(match.group(1))
                    for member in archive.namelist()
                    if (match := PPTX_SLIDE_RE.search(member))
                }
        except zipfile.BadZipFile as exc:
            raise RefusedError(f"delivered PPTX is not a readable package: {path}") from exc
        return {"pages": require_coverage(found, "slides")}
    if name == "pdf":
        pages = pdf_page_count(path)
        if ids and pages != len(ids):
            raise RefusedError(
                f"PDF page count {pages} does not match the {len(ids)} planned slides: {path}"
            )
        if render_pages and pages != render_pages:
            raise RefusedError(
                f"PDF page count {pages} does not match the {render_pages} rendered pages: {path}"
            )
        return {"pages": pages}
    if name == "speaker-notes":
        bodies = _section_bodies(path.read_text(encoding="utf-8"), NOTES_SECTION_RE)
        if any(not body for body in bodies.values()):
            raise RefusedError(f"speaker-notes has an empty page section: {path}")
        return {"pages": require_coverage(set(bodies), "sections")}
    if name in {"full-script", "training-cards"}:
        bodies = _section_bodies(path.read_text(encoding="utf-8"), SCRIPT_SECTION_RE)
        if name == "full-script" and any(not body for body in bodies.values()):
            raise RefusedError(f"full-script has an empty page section: {path}")
        return {"pages": require_coverage(set(bodies), "sections")}
    if name == "teleprompter":
        found = {int(value) for value in TELEPROMPTER_SECTION_RE.findall(path.read_text(encoding="utf-8"))}
        return {"pages": require_coverage(found, "sections")}
    if name == "references":
        ledger = spec.get("evidence_ledger")
        entries = len(REFERENCE_ENTRY_RE.findall(path.read_text(encoding="utf-8")))
        if isinstance(ledger, list) and ledger and entries != len(ledger):
            raise RefusedError(
                f"references lists {entries} entries but the Slide Spec ledger has "
                f"{len(ledger)}: {path}"
            )
        return {"entries": entries}
    return {}


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
    for position, slide in enumerate(slides, 1):
        title = str(slide.get("title") or "").strip() if isinstance(slide, dict) else ""
        # Headings carry the Slide Spec id (position fallback) so downstream
        # parsers key sections by the same identifier the spec uses; the body
        # still comes from the PPTX notes pane, which is numbered by position.
        number = _slide_id(slide, position)
        sections.append(f"## 第 {number} 页" + (f" · {title}" if title else ""))
        sections.append(notes[position].strip())
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
    spec_data = _load_spec(spec)
    render_pages = int((manifest.get("render") or {}).get("page_count") or 0) or None
    for name, binding in outputs.items():
        binding.update(
            verify_deliverable(name, Path(str(binding.get("path") or "")), spec_data, render_pages=render_pages)
        )
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
