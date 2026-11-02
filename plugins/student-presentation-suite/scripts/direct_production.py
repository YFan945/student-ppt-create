#!/usr/bin/env python3
"""Main-session PPTX production: plan, build/render/check, then publish.

This module runs tools; it never dispatches agents or judges aesthetics. The
author reads previews and checks meaning in the same conversation that wrote
the pages. Exact facts and package validity remain deterministic.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "skills" / "sp-deck" / "scripts"
for directory in (ROOT, ROOT / "scripts", HERE):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from shared.artifact_fingerprints import content_digest, visual_digest  # noqa: E402
from shared.hashing import file_sha256  # noqa: E402
from shared.slide_spec_contract import validate_slide_spec  # noqa: E402

EXECUTION_MODE = "main-session"
MANIFEST_VERSION = "3.0"
RENDER_SETTINGS = {"dpi": 144, "format": "png", "pipeline": "libreoffice-poppler-v1"}
VISUAL_REVIEW_TASKS = [
    "Read every full-size slide: wrapping, clipping, unintended overlap, connectors, labels and page markers.",
    "Use the contact sheet for deck rhythm; check information density, hierarchy, color grouping and visual variety on individual slides.",
    "Keep rich visible support and a selective speaking path: use weight, size and color for focus; concise notes need not narrate all detail.",
    "Compare the deck's main visuals and body compositions: icons supplement evidence, charts, images and detailed explanations; inspect expression_findings for registered icon reuse and copy risks.",
    "Check same-level consistency, cross-level distinction, alignment and spacing at the intended viewing scale; improve organization before shrinking type.",
    "Check cover focus, semantic title breaks, grouped metadata and image balance; preserve requested template dimensions, masters and repeated objects.",
    "Actively use topical images and editable evidence visuals; verify allowed designed placeholders and replacement targets without claiming factual evidence.",
    "Compare supplied reference/template pages with the output, including fonts, imagery and richness requested by the user.",
    "Check the actual text and notes against must_convey, evidence and asset provenance; automatic checks do not prove meaning or visual quality.",
    "Check public-facing copy and notes against shared audience-facing standards; move production/verification caveats to the delivery conversation or quality report.",
    "After repairs, inspect changed renders; repeat a deck-wide scan only when shared layout or narrative changes warrant it. Notes-only edits need no repeat image inspection.",
]


class ProductionError(ValueError):
    """A concrete input or artifact problem, returned to the author."""


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProductionError(f"expected an object: {path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bind(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "content_sha256": content_digest(path)}


def current(binding: dict[str, Any] | None) -> bool:
    if not binding or not binding.get("path"):
        return False
    path = Path(binding["path"])
    return path.is_file() and (content_digest(path) == binding["content_sha256"] if binding.get("content_sha256")
                               else file_sha256(path) == binding.get("sha256"))


def preserve_input(work: Path, path: Path) -> dict[str, str]:
    """Preserve source artifacts without locking unrelated external files."""
    destination = work / "_inputs" / (file_sha256(path)[:16] + "-" + path.name)
    destination.parent.mkdir(exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)
    return {**bind(destination), "original_path": str(path.resolve())}


def delivery_directory(work: Path, meta: dict[str, Any]) -> Path:
    project = work.parents[2]
    output = Path(meta.get("output_dir") or f"outputs/{work.name}").expanduser()
    if not output.is_absolute():
        output = project / output
    output = output.resolve()
    if not output.is_relative_to(project / "outputs") or output.is_relative_to(work.parent):
        raise ProductionError("output_dir must stay inside project outputs and outside .pptx-work")
    return output


def replace_build(source: Path, destination: Path) -> None:
    """Atomically replace only our build, tolerating transient Windows sharing locks."""
    for attempt in range(5):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                raise ProductionError(f"build replacement failed at {destination}: {exc}; close the file and run again") from exc
            time.sleep(0.02 * 2 ** attempt)


def publication_health(published: dict[str, Any]) -> dict[str, Any]:
    stale = []
    missing = []
    for name, item in published.items():
        for entry in [item, *item.get("pages", [])]:
            if not current(entry):
                stale.append({"deliverable": name, "path": entry.get("path")})
                if not Path(entry.get("path") or "").is_file():
                    missing.append(stale[-1])
    return {"ok": not missing, "stale": stale, "missing": missing,
            "modified": [entry for entry in stale if entry not in missing]}


def status(args: argparse.Namespace) -> dict[str, Any]:
    """Read stored checks and live delivery bindings without running production."""
    manifest = load(args.work_dir / "build-manifest.json")
    result = {**manifest, "stored_state": manifest.get("state"), "production_performed": False}
    if manifest.get("last_error"):
        result.update(ok=False, action="inspect_latest_failure", latest_failure={
            "attempt": manifest.get("attempts"), "error": manifest["last_error"],
            "report": manifest.get("last_build_report"), "successful_build_is_previous": True})
    published = manifest.get("published") or {}
    if published and isinstance(published, dict) and all(isinstance(item, dict) for item in published.values()):
        result["delivery_health"] = publication_health(published)
        if not result["delivery_health"]["ok"]:
            result.update(ok=False, state="incomplete", action="restore_or_export_delivery")
    check = manifest.get("check") or {}
    if current(check.get("report")):
        report = load(Path(check["report"]["path"]))
        result["check_summary"] = check_summary(report)
    review = manifest.get("author_review")
    result["author_review_status"] = (
        "recorded-current" if review_current(review, manifest)
        else "stale" if review else "unrecorded"
    )
    return result


def measure(args: argparse.Namespace) -> dict[str, Any]:
    """Measure every text block without building; all overflows in one pass."""
    work = work_directory(args.work_dir)
    entry = work / "deck.js"
    if not entry.is_file():
        raise ProductionError("plan first: deck.js does not exist in the work directory")
    report = work / "_tmp" / "measure-report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT),
                   "PPTX_HELPERS_DIR": str(ROOT / "scripts")}
    proc = subprocess.run(
        ["node", str(ROOT / "scripts" / "pptx-measure.js"), str(entry), str(report)],
        cwd=work, env=environment, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=360)
    payload: dict[str, Any] = {}
    if report.is_file():
        with contextlib.suppress(OSError, ValueError):
            payload = load(report)
    overflow = payload.get("overflow") or []
    tight = payload.get("tight") or []
    build_error = payload.get("build_error")
    ok = proc.returncode == 0 and not overflow and not build_error
    return {"ok": ok, "action": "ok" if ok else "fix_layout",
            "block_count": payload.get("block_count", 0),
            "overflow": overflow, "tight": tight, "build_error": build_error,
            "report": bind(report) if report.is_file() else None,
            "stdout": (proc.stdout or "").strip()[-2000:],
            "stderr": (proc.stderr or "").strip()[-2000:]}


def review_current(review: dict[str, Any] | None, manifest: dict[str, Any]) -> bool:
    """An author's account is bound to artifacts, not proof of inspection."""
    if not review:
        return False
    rendered = manifest.get("render") or {}
    return bool(review.get("note") and review.get("pptx") == (manifest.get("build") or {}).get("pptx")
                and review.get("pages") == rendered.get("pages")
                and review.get("slide_spec") == manifest.get("slide_spec")
                and all(current(item) for item in [review.get("pptx"), review.get("slide_spec"), *review.get("pages", [])]))


def final_outline(spec: dict[str, Any], texts: list[str], titles: dict[int, str]) -> str:
    """Export final visible content with planning roles, never obsolete claims."""
    sections = []
    for index, slide in enumerate(spec["slides"], 1):
        title = titles.get(index) or slide["title"]
        lines = [line.strip() for line in texts[index - 1].splitlines() if line.strip()]
        body = "\n".join(line for line in lines if line != title)
        role = slide.get("story_role") or slide.get("role")
        sections.append(f"## {index}. {title}\n\n" + (f"页面作用：{role}\n\n" if role else "") + body)
    return "\n\n".join(sections) + "\n"


def check_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {"ok": report.get("ok"), "content": {key: (report.get("content") or {}).get(key)
            for key in ("ok", "planned_slide_count", "actual_slide_count", "issue_count", "blocker_count", "issues")},
            "package_error_count": (report.get("package") or {}).get("error_count"),
            "geometry_errors": (report.get("geometry") or {}).get("errors", []),
            "geometry_warnings": (report.get("geometry") or {}).get("warnings", []),
            "asset_errors": (report.get("assets") or {}).get("errors", []),
            "expression_findings": (report.get("expression_review") or {}).get("findings", []),
            "student_design": report.get("student_design_review"),
            "missing_notes": report.get("missing_notes")}


def work_directory(path: Path) -> Path:
    path = path.resolve()
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    if path.parent != project / "outputs" / ".pptx-work" or path.name.startswith("."):
        raise ProductionError("work-dir must be the active project's outputs/.pptx-work/<work-id>")
    repository = ROOT.parents[1]
    if path.is_relative_to(ROOT) or (
        (repository / ".claude-plugin" / "marketplace.json").is_file()
        and path.is_relative_to(repository)
    ):
        raise ProductionError("generated artifacts must stay outside the plugin and marketplace repository")
    return path


def save(work: Path, manifest: dict[str, Any], state: str) -> None:
    manifest["state"] = state
    write(work / "build-manifest.json", manifest)
    state_path = work / "workflow-state.json"
    workflow = load(state_path)
    workflow["state"] = state
    write(state_path, workflow)


def authorized(work: Path) -> dict[str, Any]:
    manifest = load(work / "build-manifest.json")
    if manifest.get("execution_mode") != EXECUTION_MODE:
        raise ProductionError("legacy manifests are read-only; start a new work-id for main-session production")
    workflow = load(work / "workflow-state.json")
    if workflow.get("work_id") != work.name or workflow.get("state") == "intake_pending":
        raise ProductionError("production needs this work-id's confirmed intake")
    for name in ("summary", "slide_spec", "source", "art_direction"):
        binding = manifest.get(name)
        if binding is not None and not current(binding):
            path = Path(binding["path"])
            if not path.is_file():
                raise ProductionError(f"{name} is missing: {path}; restore or update this plan's input path")
            if name == "summary" and workflow.get("summary_sha256") != file_sha256(path):
                raise ProductionError("Production Summary changed; confirm the revised summary for this same work-id")
            if name == "source":
                raise ProductionError("preserved source changed; restore the original snapshot before editing")
            if name == "slide_spec":
                _, errors, _ = validate_slide_spec(path)
                if errors:
                    raise ProductionError("invalid revised Slide Spec: " + json.dumps(errors, ensure_ascii=False))
            manifest[name] = bind(path)
            manifest.setdefault("input_changes", []).append(name)
    if workflow.get("summary_sha256") not in {manifest["summary"]["sha256"], file_sha256(Path(manifest["summary"]["path"]))}:
        raise ProductionError("Production Summary authorization changed; reconfirm for this work-id")
    for source in manifest.get("template_sources", []):
        if not current(source["file"]):
            path = Path(source["file"]["path"])
            if not path.is_file():
                raise ProductionError(f"template reference missing: {path}")
            source["file"] = bind(path)
            if path.suffix.lower() == ".pptx":
                from shared.template_library import inspect_template
                inspected = inspect_template(path)
                selected = {item["slide"] for item in source.get("selected_slides", [])}
                if selected and max(selected) > inspected["slide_count"]:
                    raise ProductionError(f"template page no longer exists: {source['id']}; update references in this plan")
                source["selected_slides"] = [page for page in inspected["slides"] if page["slide"] in selected]
            manifest.setdefault("input_changes", []).append("template_sources")
        source["reference_assets"] = [bind(Path(item["path"])) for item in source.get("reference_assets", [])
                                      if Path(item["path"]).is_file()]
    return manifest


def execute(command: list[str], cwd: Path) -> str:
    environment = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT), "PPTX_HELPERS_DIR": str(ROOT / "scripts")}
    proc = subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=360)
    if proc.returncode:
        raise ProductionError((proc.stderr or proc.stdout or f"exit {proc.returncode}")[-4000:])
    return proc.stdout


def measured_assets(work: Path) -> list[dict[str, Any]]:
    """Expose actual image dimensions and evidence regions to the author."""
    from PIL import Image

    manifest = work / "asset-manifest.json"
    entries = load(manifest).get("assets", []) if manifest.is_file() else []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = Path(str(entry.get("path") or entry.get("local_path") or ""))
        source = source if source.is_absolute() else work / source
        if not source.is_file():
            result.append({**entry, "error": "asset file missing", "path": str(source)})
            continue
        try:
            with Image.open(source) as image:
                width, height = image.size
            result.append({**entry, "path": str(source.resolve()), "width": width, "height": height,
                           "sha256": file_sha256(source)})
        except OSError as exc:
            result.append({**entry, "error": str(exc), "path": str(source)})
    return result


def research_receipt(work: Path, artifact: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    """Retain research provenance without any deck-agent receipt machinery."""
    imported = work / "research-import.json"
    if allow_missing:
        path = imported if imported.is_file() else work / "research-execution.json"
        try:
            receipt = load(path) if path.is_file() else {}
        except (OSError, ValueError):
            receipt = {}
        return {**receipt, "work_id": work.name, "artifact": bind(artifact),
                "verification": "observational", "imported": imported.is_file()}
    if imported.is_file():
        receipt = load(imported)
        if receipt.get("work_id") != work.name or receipt.get("pack") != bind(artifact):
            raise ProductionError("research import does not match the current pack")
        for item in receipt.get("files", []):
            if not current(item):
                raise ProductionError("material changed after import")
        return {**receipt, "imported": True}
    path = work / "research-execution.json"
    if not path.is_file():
        raise ProductionError("research receipt missing")
    receipt = load(path)
    if (receipt.get("agent") != "student-presentation-suite:presentation-researcher"
            or not receipt.get("agent_id") or receipt.get("spawn_verified") is not True
            or receipt.get("work_id") != work.name or receipt.get("artifact") != bind(artifact)):
        raise ProductionError("research receipt is stale or invalid")
    return receipt


def plan(args: argparse.Namespace) -> dict[str, Any]:
    import generator_scaffold
    from slide_spec_to_pptx_brief import derive_production_mode, validate_production_source

    work = work_directory(args.work_dir)
    if (work / "build-manifest.json").exists():
        manifest = authorized(work)
        if args.slide_spec.resolve() != Path(manifest["slide_spec"]["path"]):
            _, errors, _ = validate_slide_spec(args.slide_spec)
            if errors:
                raise ProductionError("invalid Slide Spec: " + json.dumps(errors, ensure_ascii=False))
            manifest["slide_spec"] = bind(args.slide_spec)
        if args.art_direction:
            manifest["art_direction"] = bind(args.art_direction)
        if manifest["mode"] != "edit_ooxml":
            manifest["scaffold"] = generator_scaffold.scaffold_generator(work, Path(manifest["slide_spec"]["path"]),
                Path(manifest["art_direction"]["path"]) if manifest.get("art_direction") else None)
        save(work, manifest, "planned")
        return {"ok": True, "action": "author_pages", "work_dir": str(work),
                "preserved_authoring": True, "input_changes": manifest.get("input_changes", []),
                "pages": [str(work / "pages" / name) for name in manifest.get("scaffold", {}).get("pages", [])]}
    workflow = load(work / "workflow-state.json")
    if workflow.get("state") != "intake_confirmed" or workflow.get("work_id") != work.name:
        raise ProductionError("confirm this work-id's Production Summary before planning")
    summary = Path(str(workflow.get("summary_file") or ""))
    if not summary.is_file() or file_sha256(summary) != workflow.get("summary_sha256"):
        raise ProductionError("confirmed Production Summary is missing or changed")
    spec_path = args.slide_spec.resolve()
    spec, errors, _ = validate_slide_spec(spec_path)
    if errors:
        raise ProductionError("invalid Slide Spec: " + json.dumps(errors, ensure_ascii=False))
    output = delivery_directory(work, spec.get("meta") or {})
    if spec.get("source_deck"):
        spec["source_deck"] = str((spec_path.parent / spec["source_deck"]).resolve())
    mode = derive_production_mode(spec, args.production_mode)
    validate_production_source(spec, mode)
    source = Path(spec["source_deck"]) if spec.get("source_deck") else None
    source_binding = preserve_input(work, source) if source else None
    art = args.art_direction.resolve() if args.art_direction else None
    if art is not None and not art.is_file():
        raise ProductionError(f"Art Direction does not exist: {art}")
    # Research evidence remains a separate skill. Compile existing evidence in
    # this command rather than asking the model to hand-copy facts or references.
    pack = args.research_pack or work / "research-pack.json"
    if args.research_pack is not None and not pack.is_file():
        message = f"Research Pack does not exist: {pack}"
        if not pack.is_absolute():
            message += (f" (relative paths resolve against the tool's own working directory"
                        f" {Path.cwd()}, not the calling shell's; pass an absolute path)")
        raise ProductionError(message)
    scope = spec.get("research_scope", "C")
    external = any(item.get("source_type") not in {"user-file", "experiment", "interview", "survey"}
                   for item in spec.get("evidence_ledger", []))
    research = None
    if scope in {"A", "B", "D"} or external or args.research_pack or pack.is_file():
        validation = work / "research-pack-validation.json"
        if not pack.is_file():
            raise ProductionError("research-backed work needs research-pack.json")
        research = research_receipt(work, pack, allow_missing=True)
        compiled = work / "slide-spec-compiled.json"
        execute([sys.executable, str(ROOT / "scripts" / "research_pack_to_evidence.py"),
                 str(pack), "--validation-report", str(validation), "--slide-spec", str(spec_path),
                 "--compiled-slide-spec", str(compiled), "--output", str(work / "evidence-map.json")], work)
        spec_path = compiled
        spec, errors, _ = validate_slide_spec(spec_path)
        if errors:
            raise ProductionError("compiled Slide Spec is invalid: " + json.dumps(errors, ensure_ascii=False))
    meta = spec.get("meta") or {}
    from shared.bundled_templates import catalog_path, metadata, suggestions
    from shared.student_design_review import planning_review
    from shared.template_library import inspect_template

    templates = []
    for entry in spec.get("template_sources", []):
        builtin = entry["path"].startswith("builtin:")
        if builtin:
            if entry["use"] != "inspiration":
                raise ProductionError("built-in references are preview/layout recipes; choose inspiration to rebuild editable objects, or supply an original PPTX for strict reuse")
            inspected = metadata(entry["path"])
            path = Path(inspected.get("recipe") or catalog_path())
        else:
            path = (spec_path.parent / entry["path"]).resolve()
            inspected = inspect_template(path)
        selected = [ref["slide"] for slide in spec["slides"] for ref in slide.get("template_refs", [])
                    if ref["source_id"] == entry["id"]]
        if any(number > inspected["slide_count"] for number in selected):
            raise ProductionError(f"template page out of range: {entry['id']}")
        previews = [page.get("preview") or inspected.get("preview") for page in inspected["slides"] if page["slide"] in selected] if builtin else []
        templates.append({"id": entry["id"], "use": entry["use"], "file": bind(path),
                          "reference_assets": [bind(Path(asset)) for asset in sorted({str(catalog_path()), *[p for p in previews if p]})] if builtin else [],
                          "recipe_command": f"template_library.py recipe {inspected['id']} --slide <source-page>" if builtin else None,
                          "selected_slides": [page for page in inspected["slides"] if page["slide"] in selected],
                          "size_emu": inspected.get("size_emu")})
    scaffold = {} if mode == "edit_ooxml" else generator_scaffold.scaffold_generator(work, spec_path, art)
    if mode == "edit_ooxml":
        from shared.pptx_runtime import safe_extract_package
        safe_extract_package(Path(source_binding["path"]), work / "ooxml")
    manifest = {
        "manifest_version": MANIFEST_VERSION, "execution_mode": EXECUTION_MODE,
        "work_id": work.name, "work_dir": str(work), "mode": mode,
        "delivery_dir": str(output),
        "summary": bind(summary), "slide_spec": bind(spec_path),
        "source": source_binding,
        "art_direction": bind(art) if art else None,
        "quality_level": meta.get("quality_level", "fast"),
        "design_freedom": meta.get("design_freedom", "auto"),
        "attempts": 0,
        "research": research,
        "scaffold": scaffold, "build": {}, "render": {}, "check": {},
        "template_sources": templates,
        "semantic_verification": "main-session-self-check",
    }
    save(work, manifest, "planned")
    return {"ok": True, "action": "author_pages", "work_dir": str(work), "assets": measured_assets(work),
            "reference_library": suggestions(spec),
            "student_design": planning_review(spec), "template_sources": templates,
            "delivery_dir": str(output), "authoring_guide": str(ROOT / "skills/sp-deck/references/authoring-quickstart.md"),
            "pages": [str(work / "pages" / name) for name in scaffold.get("pages", [])],
            "source_directory": str(work / "ooxml") if mode == "edit_ooxml" else None,
            "next_command": f'python "{HERE / "ppt_pipeline.py"}" run --work-dir "{work}"'}


def actual_copy(work: Path, pptx: Path, spec: dict[str, Any]) -> None:
    import pptx_actual_content_check as content

    if spec.get("schema_version") != "2.1":
        return
    # The authored headline/labels must be backed by the actual PPTX. Capture
    # complete text and notes from the artifact, never claim independent review.
    path = work / "presentation-copy.json"
    try:
        authored = load(path) if path.is_file() else {}
    except (OSError, ValueError):
        authored = {}
    texts, notes = content.extract_pptx_text(pptx), content.extract_pptx_notes(pptx)
    hints = authored.get("slides", [])
    entries = []
    for index, text in enumerate(texts):
        hint = hints[index] if isinstance(hints, list) and index < len(hints) and isinstance(hints[index], dict) else {}
        headline = hint.get("headline") if isinstance(hint.get("headline"), str) else ""
        if headline and not content.exact_present(headline, text):
            headline = ""
        labels = hint.get("visual_labels") if isinstance(hint.get("visual_labels"), list) else []
        usage = hint.get("visual_usage") if isinstance(hint.get("visual_usage"), list) else []
        entries.append({"headline": headline, "visual_labels": [label for label in labels
                        if isinstance(label, str) and content.exact_present(label, text)],
                        "visual_usage": [item for item in usage if isinstance(item, dict)]})
    authored["slides"] = entries
    for index, entry in enumerate(entries, 1):
        entry.update(slide=index, speaker_notes=notes.get(index, ""), text_runs=texts[index - 1].splitlines())
    authored["pptx_sha256"] = file_sha256(pptx)
    write(path, authored)


def check_artifact(work: Path, manifest: dict[str, Any], pptx: Path) -> dict[str, Any]:
    import pptx_actual_content_check as content

    spec_path = Path(manifest["slide_spec"]["path"])
    spec, errors, _ = validate_slide_spec(spec_path)
    if errors:
        raise ProductionError("invalid Slide Spec: " + json.dumps(errors, ensure_ascii=False))
    from shared.artifact_validation import validate_artifact

    assets_path = work / "asset-manifest.json"
    core = validate_artifact(pptx, spec_path,
        original=Path(manifest["source"]["path"]) if manifest.get("source") else None,
        assets_path=assets_path if assets_path.is_file() else None,
        cache=work / "_tmp" / "artifact-validation.json")
    if core.get("issues"):
        raise ProductionError("invalid technical inputs: " + json.dumps(core["issues"], ensure_ascii=False))
    package = core["package"]
    content_report = core.get("content", {"ok": False, "actual_slide_count": 0, "issues": [], "blocker_count": 1})
    missing_notes = core.get("missing_notes", [])
    assets = core.get("assets", {"ok": True, "errors": [], "placeholders": [], "files": []})
    write(work / "content-check.json", content_report)
    if package["ok"]:
        actual_copy(work, pptx, spec)
    notes = content.extract_pptx_notes(pptx) if package["ok"] else {}
    if assets_path.is_file():
        assets["manifest"] = bind(assets_path)
        assets["file_bindings"] = [bind(Path(path)) for path in assets["files"]]
    geometry_path = Path(str(pptx) + ".registry-report.json")
    geometry = {"performed": False, "ok": True, "errors": [], "warnings": [],
                "limitation": "No authoring geometry report; inspect rendered pages for layout defects."}
    if geometry_path.is_file():
        authored_geometry = load(geometry_path)
        if authored_geometry.get("pptx_sha256") == file_sha256(pptx):
            geometry = {key: authored_geometry.get(key, [] if key in {"errors", "warnings", "font_substitutions"} else 0)
                        for key in ("ok", "errors", "warnings", "error_count", "warning_count", "font_substitutions")}
            geometry.update(performed=True, report=bind(geometry_path))
            predictive = {"text_overlap", "text_overflow", "out_of_canvas", "text_low_contrast", "content_overflow_bottom", "near_miss_alignment"}
            geometry["warnings"].extend({**item, "severity": "advisory", "requiresRenderedInspection": True}
                                         for item in geometry["errors"] if item.get("code") in predictive)
            geometry["errors"] = [item for item in geometry["errors"] if item.get("code") not in predictive]
            geometry.update(ok=not geometry["errors"], error_count=len(geometry["errors"]), warning_count=len(geometry["warnings"]))
        else:
            geometry["warnings"].append({"code": "geometry_cache_stale", "action": "inspect current renders; stale predictions are not used"})
    report = {
        "ok": package["ok"] and content_report["ok"] and not missing_notes and geometry["ok"] and assets["ok"],
        "validation_reused": core.get("reused", False), "validation_policy": core["policy"],
        "pptx": bind(pptx), "slide_spec": manifest["slide_spec"],
        "package": package, "content": content_report, "missing_notes": missing_notes,
        "geometry": geometry,
        "assets": assets,
        "check_scope": {"kind": "technical-checks", "visual_quality_verified": False,
                        "semantic_verification": "author-self-check-required",
                        "limitation": "ok covers the listed technical checks, not aesthetic approval or completed visual review."},
        "review_required": VISUAL_REVIEW_TASKS,
        "semantic_verification": "main-session-self-check",
        "must_convey": [{"slide": index, "requirements": slide.get("semantic_requirements", {}).get("must_convey", [])}
                        for index, slide in enumerate(spec["slides"], 1)],
    }
    from shared.deck_expression_review import review_expression

    copy_path = work / "presentation-copy.json"
    actual = load(copy_path) if package["ok"] and spec.get("schema_version") == "2.1" and copy_path.is_file() else {
        "slides": [{"slide": index, "text_runs": [text], "speaker_notes": notes.get(index, "")}
                   for index, text in enumerate(content.extract_pptx_text(pptx) if package["ok"] else [], 1)]}
    report["expression_review"] = review_expression(spec, actual)
    from shared.student_design_review import review_actual
    report["student_design_review"] = review_actual(spec, actual, geometry)
    write(work / "production-check.json", report)
    return report


def render(work: Path, manifest: dict[str, Any], pptx: Path) -> dict[str, Any]:
    from shared.pptx_runtime.render import render_pptx

    previous = manifest.get("render") or {}
    visual = visual_digest(pptx)
    spec, _, _ = validate_slide_spec(Path(manifest["slide_spec"]["path"])) if manifest.get("slide_spec") else ({}, [], "")
    selected = set((spec.get("meta") or {}).get("deliverables") or (spec.get("meta") or {}).get("export_formats") or ["pptx"])
    if (previous.get("settings") == RENDER_SETTINGS and previous.get("pages")
            and (previous.get("visual_sha256") == visual or previous.get("pptx_sha256") == file_sha256(pptx))
            and all(current(item) for item in previous["pages"])
            and ("pdf" not in selected or current(previous.get("pdf")))):
        result = {**previous, "pptx_sha256": file_sha256(pptx), "visual_sha256": visual}
        if "contact-sheet" in selected and not current(result.get("contact_sheet")):
            result["contact_sheet"] = bind(make_contact_sheet(work, [Path(page["path"]) for page in result["pages"]]))
        return result
    # A fresh directory avoids mixing old pages with the current deck.
    with tempfile.TemporaryDirectory(prefix="render-", dir=work) as directory:
        pdf, pages, _ = render_pptx(pptx, Path(directory), "slide", "png", 144)
        target = work / "render"
        target.mkdir(exist_ok=True)
        final_pages = []
        for index, page in enumerate(pages, 1):
            final = target / f"slide-{index}.png"
            shutil.copy2(page, final)
            final_pages.append(final)
        # A shorter repaired deck must not leave old pages in the preview directory.
        for stale in target.glob("slide-*.png"):
            if stale not in final_pages:
                stale.unlink()
        final_pdf = target / "deck.pdf"
        shutil.copy2(pdf, final_pdf)
    contact = make_contact_sheet(work, final_pages)
    return {"pptx_sha256": file_sha256(pptx), "visual_sha256": visual, "settings": RENDER_SETTINGS,
            "pages": [bind(page) for page in final_pages],
            "pdf": bind(final_pdf), "contact_sheet": bind(contact)}


def make_contact_sheet(work: Path, pages: list[Path]) -> Path:
    from PIL import Image, ImageDraw

    if not pages:
        raise ProductionError("cannot make a contact sheet without rendered pages")
    width, height, columns = 480, 300, min(3, len(pages))
    sheet = Image.new("RGB", (columns * width, ((len(pages) + columns - 1) // columns) * height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, page in enumerate(pages):
        with Image.open(page) as image:
            image.thumbnail((width - 12, height - 30))
            x, y = index % columns * width + 6, index // columns * height + 24
            sheet.paste(image, (x, y))
            draw.text((x, y - 18), str(index + 1), fill="black")
    contact = work / "preview.png"
    sheet.save(contact)
    return contact


def run(args: argparse.Namespace) -> dict[str, Any]:
    import generator_scaffold

    from shared.pptx_runtime import pack_directory

    work = work_directory(args.work_dir)
    manifest = authorized(work)
    if manifest["mode"] != "edit_ooxml" and manifest.get("input_changes"):
        manifest["scaffold"] = generator_scaffold.scaffold_generator(work, Path(manifest["slide_spec"]["path"]),
            Path(manifest["art_direction"]["path"]) if manifest.get("art_direction") else None)
    manifest.pop("input_changes", None)
    inputs = authoring_inputs(work, manifest)
    previous_build = manifest.get("build") or {}
    if (not manifest.get("last_error") and current(previous_build.get("pptx"))
            and input_identity(inputs) == input_identity(previous_build.get("authoring_inputs", []))):
        pptx = Path(previous_build["pptx"]["path"])
        checked = check_artifact(work, manifest, pptx)
        manifest["check"] = {"ok": checked["ok"], "report": bind(work / "production-check.json")}
        previous_pages = (manifest.get("render") or {}).get("pages", [])
        if not getattr(args, "no_render", False):
            manifest["render"] = render(work, manifest, pptx)
        changed = [number for number, page in enumerate((manifest.get("render") or {}).get("pages", []), 1)
                   if number > len(previous_pages) or page["sha256"] != previous_pages[number - 1]["sha256"]]
        save(work, manifest, "qa")
        return {"ok": checked["ok"], "action": ("inspect_previews" if changed else "unchanged") if checked["ok"] else "inspect_and_fix",
                "build_reused": True, "changed_pages": changed, "previews": manifest.get("render", {}),
                "check_report": manifest["check"]["report"], "check_summary": check_summary(checked),
                "technical_checks": checked["check_scope"]}
    previous_pages = (manifest.get("render") or {}).get("pages", [])
    previous_inputs = (manifest.get("build") or {}).get("authoring_inputs", [])
    manifest["attempts"] += 1
    manifest["check"] = {}
    save(work, manifest, "producing")
    start = time.monotonic()
    pptx = work / "deck.pptx"
    diagnostic = work / "last-build-report.json"
    # 每次新尝试先清掉上一次的失败诊断，避免陈旧报告误导本次定位。
    diagnostic.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="build-", dir=work) as directory:
            staging = Path(directory) / "raw.pptx"
            try:
                if manifest["mode"] == "edit_ooxml":
                    pack_directory(work / "ooxml", staging)
                else:
                    entry = work / "deck.js"
                    active_pages = [work / "pages" / name for name in manifest.get("scaffold", {}).get("pages", [])]
                    remaining = generator_scaffold.scaffolded_pages(active_pages or generator_scaffold.listed_page_files(work / "pages"))
                    if remaining:
                        raise ProductionError("unfinished pages: " + ", ".join(remaining) +
                                              "; implement their empty page functions using authoring-quickstart.md")
                    execute(["node", str(ROOT / "scripts" / "run_with_pptxgenjs.js"), "--output", str(staging), str(entry)], work)
                # The Node wrapper already normalizes XML and injects CJK fonts.
                # OOXML editing packs directly to preserve untouched source parts.
                replace_build(staging, pptx)
                for suffix in (".registry-report.json", ".layout-report.json"):
                    sidecar = Path(str(staging) + suffix)
                    if sidecar.is_file():
                        shutil.copy2(sidecar, Path(str(pptx) + suffix))
                        if suffix == ".registry-report.json":
                            report = load(Path(str(pptx) + suffix))
                            report.update(pptx=str(pptx), pptx_sha256=file_sha256(pptx))
                            write(Path(str(pptx) + suffix), report)
                    else:
                        Path(str(pptx) + suffix).unlink(missing_ok=True)
            except (ProductionError, OSError, ValueError):
                # staging 目录随下面的 TemporaryDirectory 一起删除；构建期几何
                # preflight sidecar（若已落盘）复制到固定诊断路径，失败报告里指向它。
                report = Path(str(staging) + ".registry-report.json")
                if report.is_file():
                    shutil.copy2(report, diagnostic)
                raise
        manifest["build"] = {"pptx": bind(pptx), "seconds": round(time.monotonic() - start, 3)}
        # 只绑定作者源码：第一级以 `_`/`.` 开头的路径（如 _tmp/ 探测脚本）不参与绑定；
        # pages/ 内部的共享模块（如 pages/_shared.js）正常参与绑定与变更检测。
        manifest["build"]["authoring_inputs"] = inputs
        checked = check_artifact(work, manifest, pptx)
        manifest["check"] = {"ok": checked["ok"], "report": bind(work / "production-check.json")}
        if (work / "presentation-copy.json").is_file():
            manifest["check"]["presentation_copy"] = bind(work / "presentation-copy.json")
        no_render = bool(getattr(args, "no_render", False))
        if no_render:
            # 只拿检查报告的迭代：构建+全检后跳过渲染。清空 render 绑定，
            # complete 会因缺少当前预览拒绝交付，不会拿旧预览蒙混。
            manifest["render"] = {}
        else:
            render_start = time.monotonic()
            manifest["render"] = render(work, manifest, pptx)
            manifest["render"]["seconds"] = round(time.monotonic() - render_start, 3)
            if len(manifest["render"]["pages"]) != checked["content"]["actual_slide_count"]:
                raise ProductionError("rendered page count differs from the PPTX")
        manifest.pop("last_error", None)
        manifest.pop("last_build_report", None)
        save(work, manifest, "qa")
        changed_pages = [index for index, page in enumerate(manifest["render"].get("pages", []), 1)
                         if index > len(previous_pages) or page["sha256"] != previous_pages[index - 1]["sha256"]]
        previous_paths = {item["path"]: item for item in previous_inputs}
        new_paths = {item["path"]: item for item in manifest["build"]["authoring_inputs"]}
        source_changes = [path for path in previous_paths.keys() | new_paths.keys()
                          if previous_paths.get(path) != new_paths.get(path)]
        shared_changed = bool(previous_inputs) and any(not re.match(r"p\d+-", Path(path).name)
                                                       for path in source_changes)
        if not checked["ok"]:
            action = "inspect_and_fix"
        elif no_render:
            action = "inspect_check_report"
        else:
            action = "inspect_previews" if changed_pages else "inspect_changed_content"
        result = {"ok": checked["ok"], "action": action,
                  "previews": manifest["render"], "check_report": manifest["check"]["report"],
                  "technical_checks": checked["check_scope"], "geometry": checked["geometry"],
                  "review_required": checked["review_required"],
                  "asset_placeholders": checked["assets"]["placeholders"],
                  "changed_pages": changed_pages, "shared_source_changed": shared_changed,
                  "check_summary": check_summary(checked),
                  "must_convey": checked["must_convey"], "semantic_verification": "main-session-self-check"}
        if no_render:
            result["render_skipped"] = True
        return result
    except (ProductionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        message = str(exc)
        details = load(diagnostic) if diagnostic.is_file() else {}
        details.update(ok=False, attempt=manifest["attempts"], error=message, authoring_inputs=inputs,
                       previous_success_is_not_this_attempt=True)
        write(diagnostic, details)
        manifest["last_build_report"] = str(diagnostic)
        message += f" (latest attempt {manifest['attempts']} diagnostic: {diagnostic})"
        manifest["last_error"] = message
        save(work, manifest, "producing")
        raise ProductionError(message) from exc


def authoring_inputs(work: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Actual build dependencies; exclude derived reports and temporary probes."""
    paths = (list((work / "ooxml").rglob("*")) if manifest["mode"] == "edit_ooxml"
             else list(work.rglob("*.js")))
    paths += [Path(manifest[name]["path"]) for name in ("slide_spec", "art_direction") if manifest.get(name)]
    paths.append(ROOT / "package.json")  # Runtime upgrades invalidate built-source caches.
    assets = work / "asset-manifest.json"
    if assets.is_file():
        paths.append(assets)
        paths += [(work / item["path"]).resolve() for item in load(assets).get("assets", []) if item.get("path")]
    for directory in ("assets", "media", "data"):
        paths.extend(path for path in (work / directory).rglob("*") if path.is_file())
    return [bind(path) for path in sorted(set(paths)) if path.is_file()
            and (not path.is_relative_to(work) or not path.relative_to(work).parts[0].startswith(("_", ".")))]


def input_identity(inputs: list[dict[str, str]]) -> dict[str, str]:
    return {item["path"]: item.get("content_sha256", item["sha256"]) for item in inputs}


def preview(args: argparse.Namespace) -> dict[str, Any]:
    """Build selected page modules without importing unfinished other pages."""
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    import generator_scaffold

    from shared.chart_readback import slide_parts
    from shared.pptx_runtime import pack_directory
    from shared.pptx_runtime.render import render_pptx

    work = work_directory(args.work_dir)
    manifest = authorized(work)
    spec = generator_scaffold.load_spec(Path(manifest["slide_spec"]["path"]))
    selected = []
    for token in args.slides.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", token)
        if not match:
            raise ProductionError("--slides accepts page positions such as 1-3,5")
        first, last = int(match[1]), int(match[2] or match[1])
        if first < 1 or last < first or last > len(spec["slides"]):
            raise ProductionError("preview page positions must be within the current Spec")
        selected.extend(range(first, last + 1))
    selected = list(dict.fromkeys(selected))
    root = work / "_tmp" / "previews"
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="pages-", dir=root))
    candidate = directory / "preview.pptx"
    if manifest["mode"] == "edit_ooxml":
        whole = directory / "whole.pptx"
        pack_directory(work / "ooxml", whole)
        with ZipFile(whole) as source, ZipFile(candidate, "w") as target:
            presentation = ET.fromstring(source.read("ppt/presentation.xml"))
            ids = presentation.find("{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst")
            chosen = [list(ids)[number - 1] for number in selected]
            ids[:] = chosen
            for item in source.infolist():
                target.writestr(item, ET.tostring(presentation, encoding="utf-8", xml_declaration=True)
                                if item.filename == "ppt/presentation.xml" else source.read(item.filename))
        # Unreferenced parts are retained to preserve relationships; only registered slides render.
        with ZipFile(candidate) as package:
            if len(slide_parts(package)) != len(selected):
                raise ProductionError("partial preview slide selection failed")
    else:
        names = manifest["scaffold"]["pages"]
        pages = [work / "pages" / names[number - 1] for number in selected]
        remaining = generator_scaffold.scaffolded_pages(pages)
        if remaining:
            raise ProductionError("selected preview pages are unfinished: " + ", ".join(remaining))
        source = (work / "deck.js").read_text(encoding="utf-8")
        requires = ",\n".join("  require(" + json.dumps(str(page)) + ")" for page in pages)
        source, count = re.subn(r"const PAGES\s*=\s*\[[\s\S]*?\];", lambda _: "const PAGES = [\n" + requires + "\n];", source, count=1)
        if not count:
            raise ProductionError("partial module preview requires the scaffold PAGES array; restore that assembly boundary")
        source = source.replace("const n = index + 1;", "const n = " + json.dumps(selected) + "[index];")
        entry = directory / "deck.js"
        entry.write_text("require = require('node:module').createRequire(" + json.dumps(str(work / "deck.js")) + ");\n" + source, encoding="utf-8")
        execute(["node", str(ROOT / "scripts" / "run_with_pptxgenjs.js"), "--output", str(candidate), str(entry)], work)
    pdf, pages, _ = render_pptx(candidate, directory / "render", "slide", "png", 144)
    return {"ok": True, "scope": "partial-preview", "complete": False, "source_slides": selected,
            "pptx": bind(candidate), "pdf": bind(pdf),
            "pages": [{**bind(page), "source_slide": number} for page, number in zip(pages, selected, strict=True)],
            "full_build_unchanged": True}


def complete(args: argparse.Namespace) -> dict[str, Any]:
    import build_support_outputs as support

    from shared.slide_spec_contract import load_slide_spec

    work = work_directory(args.work_dir)
    manifest = authorized(work)
    if manifest.get("last_error"):
        raise ProductionError(f"latest build failed; inspect {manifest.get('last_build_report')} and run the corrected pages before delivery")
    pptx_binding = (manifest.get("build") or {}).get("pptx")
    if not pptx_binding or not Path(pptx_binding["path"]).is_file():
        raise ProductionError("build a PPTX before delivery")
    pptx = Path(pptx_binding["path"])
    manifest["build"]["pptx"] = bind(pptx)
    # Re-read the deliverable instead of trusting or requiring old report hashes.
    report = check_artifact(work, manifest, pptx)
    checked = {"ok": report["ok"], "report": bind(work / "production-check.json")}
    if (work / "presentation-copy.json").is_file():
        checked["presentation_copy"] = bind(work / "presentation-copy.json")
    manifest["check"] = checked
    if not report["ok"]:
        save(work, manifest, "qa")
        raise ProductionError("current PPTX has technical or factual errors; see production-check.json")
    # Repair only derived previews; source comments, optional reports, PDF and
    # contact-sheet caches do not require rebuilding an otherwise valid deck.
    rendered = render(work, manifest, pptx)
    manifest["render"] = rendered
    if len(rendered.get("pages", [])) != report["content"]["actual_slide_count"]:
        raise ProductionError("current PPTX needs one rendered preview per slide")
    spec = load_slide_spec(Path(manifest["slide_spec"]["path"]))
    note = getattr(args, "review_note", None)
    if note is not None:
        if not note.strip():
            raise ProductionError("review_note must describe the author's actual inspection and findings")
        manifest["author_review"] = {
            "note": note.strip(), "kind": "author-self-report", "independent": False,
            "pptx": manifest["build"]["pptx"], "pages": rendered["pages"],
            "slide_spec": manifest["slide_spec"],
        }
    if review_current(manifest.get("author_review"), manifest):
        report["author_review"] = manifest["author_review"]
    else:
        report.pop("author_review", None)
    report.setdefault("check_scope", {"kind": "technical-checks", "visual_quality_verified": False})
    report["check_scope"]["author_review_status"] = "recorded-current" if report.get("author_review") else "unrecorded"
    report["check_scope"]["semantic_verification"] = "author-self-report" if report.get("author_review") else "author-self-check-unrecorded"
    write(Path(checked["report"]["path"]), report)
    checked["report"] = bind(Path(checked["report"]["path"]))
    meta = spec.get("meta") or {}
    selected = set(meta.get("deliverables") or meta.get("export_formats") or ["pptx"])
    output = delivery_directory(work, meta)
    manifest["delivery_dir"] = str(output)
    output.mkdir(parents=True, exist_ok=True)
    prefix = str(meta.get("output_prefix") or work.name)
    if Path(prefix).name != prefix or any(char in prefix for char in "/\\") or prefix.startswith("."):
        raise ProductionError("output_prefix must be a plain filename prefix")
    published: dict[str, Any] = {}
    # Support material is generated from final PPTX notes, not planning prose.
    if manifest["mode"] != "create" or "change-summary" in selected:
        summary = work / "change-summary.md"
        if not summary.is_file() or not summary.read_text(encoding="utf-8").strip():
            raise ProductionError("editing needs change-summary.md")
    titles = {}
    if spec.get("schema_version") == "2.1" and manifest["mode"] != "edit_ooxml" and checked.get("presentation_copy"):
        copy = load(Path(checked["presentation_copy"]["path"]))
        titles = {entry["slide"]: " ".join(str(entry.get("headline") or "").splitlines()).strip()
                  for entry in copy.get("slides", [])}
    if selected & support.SUPPORTED:
        import pptx_actual_content_check as content
        notes = (support.actual_speaker_notes(spec, None, pptx)
                 if selected & {"full-script", "teleprompter"}
                 else content.extract_pptx_notes(pptx))
        data = support.with_actual_speaker_notes(spec, notes, titles)
        renderers = {"speaker-notes": ("speaker-notes.md", support.speaker_notes_markdown),
                     "full-script": ("full-script.md", support.full_script_markdown),
                     "teleprompter": ("teleprompter.html", support.teleprompter_html),
                     "training-cards": ("training-cards.md", support.training_cards),
                     "references": ("references.md", support.references_markdown)}
        for name in sorted(selected & support.SUPPORTED):
            suffix, renderer = renderers[name]
            text = renderer(data)
            support._assert_page_sections(name, text, data)
            destination = output / f"{prefix}-{suffix}"
            destination.write_text(text, encoding="utf-8")
            published[name] = bind(destination)
    copies = {"pptx": pptx, **({"pdf": Path(rendered["pdf"]["path"])} if rendered.get("pdf") else {}),
              **({"contact-sheet": Path(rendered["contact_sheet"]["path"])} if rendered.get("contact_sheet") else {}),
              "slide-spec": Path(manifest["slide_spec"]["path"]),
              "quality-report": Path(checked["report"]["path"])}
    for name in sorted(selected & copies.keys()):
        source = copies[name]
        extra = "" if name in {"pptx", "pdf"} else f"-{name}"
        destination = output / f"{prefix}{extra}{source.suffix}"
        if manifest.get("source") and any(destination.resolve() == Path(path).resolve()
                for path in (manifest["source"]["path"], manifest["source"].get("original_path")) if path):
            raise ProductionError("delivery must preserve the source deck")
        shutil.copy2(source, destination)
        published[name] = bind(destination)
    if "preview" in selected:
        directory = output / f"{prefix}-slides"
        directory.mkdir(exist_ok=True)
        pages = []
        for index, page in enumerate(rendered["pages"], 1):
            destination = directory / f"slide-{index:02}.png"
            shutil.copy2(page["path"], destination)
            pages.append(bind(destination))
        for stale in directory.glob("slide-*.png"):
            if str(stale.resolve()) not in {item["path"] for item in pages}:
                stale.unlink()
        index_path = output / f"{prefix}-preview.json"
        write(index_path, {"pptx_sha256": rendered["pptx_sha256"], "pages": pages})
        published["preview"] = {**bind(index_path), "pages": pages}
    if "outline" in selected:
        import pptx_actual_content_check as content

        path = output / f"{prefix}-outline.md"
        path.write_text(final_outline(spec, content.extract_pptx_text(pptx), titles), encoding="utf-8")
        published["outline"] = bind(path)
    if "revision-manifest" in selected:
        path = output / f"{prefix}-revision-manifest.json"
        write(path, {"source": manifest["source"], "pptx": bind(pptx), "slide_spec": manifest["slide_spec"],
                     "change_summary": bind(work / "change-summary.md") if (work / "change-summary.md").is_file() else None})
        published["revision-manifest"] = bind(path)
    if manifest["mode"] != "create" or "change-summary" in selected:
        summary = work / "change-summary.md"
        destination = output / f"{prefix}-change-summary.md"
        shutil.copy2(summary, destination)
        published["change-summary"] = bind(destination)
    manifest["published"] = published
    health = publication_health(published)
    if not health["ok"]:
        raise ProductionError("delivery bindings are not current: " + json.dumps(health, ensure_ascii=False))
    save(work, manifest, "complete")
    return {"ok": True, "state": "complete", "outputs": published,
            "semantic_verification": report["check_scope"]["semantic_verification"],
            "author_review_status": report["check_scope"]["author_review_status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan", help="validate approved inputs and create editable page sources")
    planning.add_argument("--work-dir", required=True, type=Path)
    planning.add_argument("--slide-spec", required=True, type=Path)
    planning.add_argument("--art-direction", type=Path, help="optional user/template design configuration")
    planning.add_argument("--research-pack", type=Path)
    planning.add_argument("--production-mode", choices=("create", "edit_ooxml", "rebuild_from_source"))
    planning.add_argument("--repair-limit", type=int, default=None, help=argparse.SUPPRESS)  # legacy no-op
    planning.set_defaults(handler=plan)
    for name, handler in (("run", run), ("complete", complete)):
        command = commands.add_parser(name)
        command.add_argument("--work-dir", type=Path, required=True)
        if name == "run":
            command.add_argument("--no-render", action="store_true",
                                 help="build and run all checks but skip LibreOffice rendering; "
                                      "for report-only iteration without previews")
        if name == "complete":
            command.add_argument("--review-note", help="Record actual author inspection/findings in the existing quality report; not independent verification")
        command.set_defaults(handler=handler)
    inspection = commands.add_parser("status", help="read current reports and delivery health without building")
    inspection.add_argument("--work-dir", type=Path, required=True)
    inspection.set_defaults(handler=status)
    measuring = commands.add_parser("measure", help="measure all text blocks without building; reports every overflow and tight margin in one pass")
    measuring.add_argument("--work-dir", type=Path, required=True)
    measuring.set_defaults(handler=measure)
    partial = commands.add_parser("preview", help="render selected page positions without loading unfinished other modules")
    partial.add_argument("--work-dir", type=Path, required=True)
    partial.add_argument("--slides", required=True, help="page positions, e.g. 1-3,5")
    partial.set_defaults(handler=preview)
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (ProductionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    sys.exit(main())
