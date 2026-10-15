#!/usr/bin/env python3
"""Main-session PPTX production: plan, build/render/check, then publish.

This module runs tools; it never dispatches agents or judges aesthetics. The
author reads previews and checks meaning in the same conversation that wrote
the pages. Exact facts and package validity remain deterministic.
"""
from __future__ import annotations

import argparse
import contextlib
import io
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
    "Repair affected pages, run again, inspect the current renders and scan the whole deck before complete.",
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
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def current(binding: dict[str, Any] | None) -> bool:
    if not binding or not binding.get("path"):
        return False
    path = Path(binding["path"])
    return path.is_file() and file_sha256(path) == binding.get("sha256")


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
    for name, item in published.items():
        for entry in [item, *item.get("pages", [])]:
            if not current(entry):
                stale.append({"deliverable": name, "path": entry.get("path")})
    return {"ok": not stale, "stale": stale}


def status(args: argparse.Namespace) -> dict[str, Any]:
    """Read stored checks and live delivery bindings without running production."""
    manifest = load(args.work_dir / "build-manifest.json")
    result = {**manifest, "stored_state": manifest.get("state"), "production_performed": False}
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
            raise ProductionError(f"{name} changed after planning; preserve frozen inputs and start a new plan")
    if workflow.get("summary_sha256") != manifest["summary"]["sha256"]:
        raise ProductionError("Production Summary authorization changed")
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
        if allow_missing:
            return {"work_id": work.name, "artifact": bind(artifact), "verification": "receipt-unavailable"}
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
        raise ProductionError("work-id already has a plan; use a new work-id")
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
    art = args.art_direction.resolve() if args.art_direction else None
    if art is not None and not art.is_file():
        raise ProductionError(f"Art Direction does not exist: {art}")
    # Research evidence remains a separate skill. Compile existing evidence in
    # this command rather than asking the model to hand-copy facts or references.
    pack = args.research_pack or work / "research-pack.json"
    scope = spec.get("research_scope", "C")
    external = any(item.get("source_type") not in {"user-file", "experiment", "interview", "survey"}
                   for item in spec.get("evidence_ledger", []))
    research = None
    if scope in {"A", "B", "D"} or external or args.research_pack or pack.is_file():
        validation = work / "research-pack-validation.json"
        if not pack.is_file() or not validation.is_file():
            raise ProductionError("research-backed work needs research-pack.json and its validation report")
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
    scaffold = {} if mode == "edit_ooxml" else generator_scaffold.scaffold_generator(work, spec_path, art)
    if mode == "edit_ooxml":
        from shared.pptx_runtime import safe_extract_package
        safe_extract_package(source, work / "ooxml")
    manifest = {
        "manifest_version": MANIFEST_VERSION, "execution_mode": EXECUTION_MODE,
        "work_id": work.name, "work_dir": str(work), "mode": mode,
        "delivery_dir": str(output),
        "summary": bind(summary), "slide_spec": bind(spec_path),
        "source": bind(source) if source else None,
        "art_direction": bind(art) if art else None,
        "quality_level": meta.get("quality_level", "fast"),
        "design_freedom": meta.get("design_freedom", "auto"),
        "attempts": 0,
        "research": research,
        "scaffold": scaffold, "build": {}, "render": {}, "check": {},
        "semantic_verification": "main-session-self-check",
    }
    save(work, manifest, "planned")
    return {"ok": True, "action": "author_pages", "work_dir": str(work), "assets": measured_assets(work),
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
    authored = load(path) if path.is_file() else {}
    texts, notes = content.extract_pptx_text(pptx), content.extract_pptx_notes(pptx)
    entries = authored.get("slides", [])
    if not entries and (work / "ooxml").is_dir():
        entries = [{"headline": next((line.strip() for line in text.splitlines() if line.strip()), ""), "visual_labels": []}
                   for text in texts]
        authored["slides"] = entries
    if len(entries) != len(texts):
        raise ProductionError("each page must provide presentation_copy with its actual headline and labels")
    for index, entry in enumerate(entries, 1):
        if (work / "ooxml").is_dir() and not str(entry.get("headline") or "").strip():
            entry["headline"] = next((line.strip() for line in texts[index - 1].splitlines() if line.strip()), "")
        entry.update(slide=index, speaker_notes=notes.get(index, ""), text_runs=[texts[index - 1]])
    authored["pptx_sha256"] = file_sha256(pptx)
    write(path, authored)


def check_artifact(work: Path, manifest: dict[str, Any], pptx: Path) -> dict[str, Any]:
    import pptx_actual_content_check as content

    from shared.pptx_runtime import validate_pptx

    spec_path = Path(manifest["slide_spec"]["path"])
    spec, _, _ = validate_slide_spec(spec_path)
    actual_copy(work, pptx, spec)
    package = validate_pptx(pptx, Path(manifest["source"]["path"]) if manifest["source"] else None)
    content_path = work / "content-check.json"
    with contextlib.redirect_stdout(io.StringIO()):
        content.run(argparse.Namespace(pptx=pptx, slide_spec=spec_path, output=content_path, json=False, strict=True))
    content_report = load(content_path)
    notes = content.extract_pptx_notes(pptx)
    missing_notes = [index for index in range(1, len(spec["slides"]) + 1)
                     if (spec.get("meta") or {}).get("include_speaker_notes") and not notes.get(index, "").strip()]
    assets_path = work / "asset-manifest.json"
    from shared.asset_contract import validate_assets
    assets = validate_assets(load(assets_path) if assets_path.is_file() else {"deck": work.name, "assets": []},
                             work, content.extract_pptx_text(pptx))
    if assets_path.is_file():
        assets["manifest"] = bind(assets_path)
        assets["file_bindings"] = [bind(Path(path)) for path in assets["files"]]
    geometry_path = Path(str(pptx) + ".registry-report.json")
    geometry = {"performed": False, "ok": True, "errors": [], "warnings": [],
                "limitation": "No authoring geometry report; inspect rendered pages for layout defects."}
    if geometry_path.is_file():
        authored_geometry = load(geometry_path)
        if authored_geometry.get("pptx_sha256") != file_sha256(pptx):
            raise ProductionError("geometry report does not belong to the current PPTX")
        geometry = {key: authored_geometry.get(key, [] if key in {"errors", "warnings", "font_substitutions"} else 0)
                    for key in ("ok", "errors", "warnings", "error_count", "warning_count", "font_substitutions")}
        geometry.update(performed=True, report=bind(geometry_path))
    report = {
        "ok": package["ok"] and content_report["ok"] and not missing_notes and geometry["ok"] and assets["ok"],
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
    actual = load(copy_path) if spec.get("schema_version") == "2.1" and copy_path.is_file() else {
        "slides": [{"slide": index, "text_runs": [text], "speaker_notes": notes.get(index, "")}
                   for index, text in enumerate(content.extract_pptx_text(pptx), 1)]}
    report["expression_review"] = review_expression(spec, actual)
    write(work / "production-check.json", report)
    return report


def render(work: Path, manifest: dict[str, Any], pptx: Path) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    from shared.pptx_runtime.render import render_pptx

    previous = manifest.get("render") or {}
    if (previous.get("settings") == RENDER_SETTINGS and previous.get("pages")
            and previous.get("pptx_sha256") == file_sha256(pptx) and all(current(item) for item in [
        previous.get("pdf"), previous.get("contact_sheet"), *previous.get("pages", []),
    ])):
        return previous
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
    width, height, columns = 480, 300, min(3, len(final_pages))
    sheet = Image.new("RGB", (columns * width, ((len(final_pages) + columns - 1) // columns) * height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, page in enumerate(final_pages):
        with Image.open(page) as image:
            image.thumbnail((width - 12, height - 30))
            x, y = index % columns * width + 6, index // columns * height + 24
            sheet.paste(image, (x, y))
            draw.text((x, y - 18), str(index + 1), fill="black")
    contact = work / "preview.png"
    sheet.save(contact)
    return {"pptx_sha256": file_sha256(pptx), "settings": RENDER_SETTINGS,
            "pages": [bind(page) for page in final_pages],
            "pdf": bind(final_pdf), "contact_sheet": bind(contact)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    import generator_scaffold

    from shared.pptx_runtime import pack_directory

    work = work_directory(args.work_dir)
    manifest = authorized(work)
    previous_pages = (manifest.get("render") or {}).get("pages", [])
    previous_inputs = (manifest.get("build") or {}).get("authoring_inputs", [])
    manifest["attempts"] += 1
    manifest["check"] = {}
    save(work, manifest, "producing")
    start = time.monotonic()
    pptx = work / "deck.pptx"
    try:
        with tempfile.TemporaryDirectory(prefix="build-", dir=work) as directory:
            staging = Path(directory) / "raw.pptx"
            if manifest["mode"] == "edit_ooxml":
                pack_directory(work / "ooxml", staging)
            else:
                entry = work / "deck.js"
                remaining = generator_scaffold.scaffolded_pages(generator_scaffold.listed_page_files(work / "pages"))
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
        manifest["build"] = {"pptx": bind(pptx), "seconds": round(time.monotonic() - start, 3)}
        # 只绑定作者源码：第一级以 `_`/`.` 开头的路径（如 _tmp/ 探测脚本）不参与绑定；
        # pages/ 内部的共享模块（如 pages/_shared.js）正常参与绑定与变更检测。
        manifest["build"]["authoring_inputs"] = [
            bind(path) for path in sorted(work.rglob("*.js"))
            if not path.relative_to(work).parts[0].startswith(("_", "."))]
        checked = check_artifact(work, manifest, pptx)
        manifest["check"] = {"ok": checked["ok"], "report": bind(work / "production-check.json")}
        if (work / "presentation-copy.json").is_file():
            manifest["check"]["presentation_copy"] = bind(work / "presentation-copy.json")
        render_start = time.monotonic()
        manifest["render"] = render(work, manifest, pptx)
        manifest["render"]["seconds"] = round(time.monotonic() - render_start, 3)
        if len(manifest["render"]["pages"]) != checked["content"]["actual_slide_count"]:
            raise ProductionError("rendered page count differs from the PPTX")
        manifest.pop("last_error", None)
        save(work, manifest, "qa")
        changed_pages = [index for index, page in enumerate(manifest["render"]["pages"], 1)
                         if index > len(previous_pages) or page["sha256"] != previous_pages[index - 1]["sha256"]]
        previous_paths = {item["path"]: item for item in previous_inputs}
        new_paths = {item["path"]: item for item in manifest["build"]["authoring_inputs"]}
        source_changes = [path for path in previous_paths.keys() | new_paths.keys()
                          if previous_paths.get(path) != new_paths.get(path)]
        shared_changed = bool(previous_inputs) and any(not re.match(r"p\d+-", Path(path).name)
                                                       for path in source_changes)
        if shared_changed:
            changed_pages = list(range(1, len(manifest["render"]["pages"]) + 1))
        return {"ok": checked["ok"], "action": "inspect_and_fix" if not checked["ok"] else "inspect_previews",
                "previews": manifest["render"], "check_report": manifest["check"]["report"],
                "technical_checks": checked["check_scope"], "geometry": checked["geometry"],
                "review_required": checked["review_required"],
                "asset_placeholders": checked["assets"]["placeholders"],
                "changed_pages": changed_pages, "shared_source_changed": shared_changed,
                "check_summary": check_summary(checked),
                "must_convey": checked["must_convey"], "semantic_verification": "main-session-self-check"}
    except (ProductionError, OSError, ValueError) as exc:
        manifest["last_error"] = str(exc)
        save(work, manifest, "producing")
        raise


def complete(args: argparse.Namespace) -> dict[str, Any]:
    import build_support_outputs as support

    from shared.slide_spec_contract import load_slide_spec

    work = work_directory(args.work_dir)
    manifest = authorized(work)
    checked = manifest.get("check") or {}
    rendered = manifest.get("render") or {}
    evidence = [checked.get("report"), (manifest.get("build") or {}).get("pptx"),
                rendered.get("pdf"), rendered.get("contact_sheet"), *rendered.get("pages", [])]
    evidence.extend((manifest.get("build") or {}).get("authoring_inputs", []))
    if checked.get("presentation_copy"):
        evidence.append(checked["presentation_copy"])
    if not checked.get("ok") or not all(current(item) for item in evidence):
        raise ProductionError("current build, checks and rendered previews are required before delivery")
    pptx = Path(manifest["build"]["pptx"]["path"])
    if rendered.get("pptx_sha256") != file_sha256(pptx):
        raise ProductionError("previews do not belong to the current PPTX")
    report = load(Path(checked["report"]["path"]))
    assets = report.get("assets") or {}
    if (work / "asset-manifest.json").is_file() != bool(assets.get("manifest")):
        raise ProductionError("asset manifest changed; run again before delivery")
    if assets.get("manifest") and not current(assets["manifest"]):
        raise ProductionError("asset manifest changed; run again before delivery")
    if not all(current(item) for item in assets.get("file_bindings", [])):
        raise ProductionError("asset file changed; run again before delivery")
    if len(rendered.get("pages", [])) != report["content"]["actual_slide_count"]:
        raise ProductionError("current build needs one rendered preview per slide")
    if (report.get("geometry") or {}).get("performed") and not current(report["geometry"].get("report")):
        raise ProductionError("current geometry report is required before delivery")
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
    output = Path(manifest.get("delivery_dir") or work.parent.parent)
    if manifest.get("delivery_dir") and output != delivery_directory(work, meta):
        raise ProductionError("delivery directory changed after planning")
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
    copies = {"pptx": pptx, "pdf": Path(rendered["pdf"]["path"]),
              "contact-sheet": Path(rendered["contact_sheet"]["path"]),
              "slide-spec": Path(manifest["slide_spec"]["path"]),
              "quality-report": Path(checked["report"]["path"])}
    for name in sorted(selected & copies.keys()):
        source = copies[name]
        extra = "" if name in {"pptx", "pdf"} else f"-{name}"
        destination = output / f"{prefix}{extra}{source.suffix}"
        if manifest.get("source") and destination.resolve() == Path(manifest["source"]["path"]).resolve():
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
        if name == "complete":
            command.add_argument("--review-note", help="Record actual author inspection/findings in the existing quality report; not independent verification")
        command.set_defaults(handler=handler)
    inspection = commands.add_parser("status", help="read current reports and delivery health without building")
    inspection.add_argument("--work-dir", type=Path, required=True)
    inspection.set_defaults(handler=status)
    measuring = commands.add_parser("measure", help="measure all text blocks without building; reports every overflow and tight margin in one pass")
    measuring.add_argument("--work-dir", type=Path, required=True)
    measuring.set_defaults(handler=measure)
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
