"""Publish confirmed, QA-bound deliverables from the work directory."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from pipeline.core import RefusedError, bind, pptx_path
from pipeline.deliverables import (
    _load_spec,
    confirmed_deliverables,
    verify_deliverable,
)


def _source(manifest: dict[str, Any], name: str, work_dir: Path) -> Path:
    if name == "pptx":
        return pptx_path(manifest)
    prepared = (manifest.get("deliverables") or {}).get("outputs") or {}
    if name in prepared:
        return Path(str(prepared[name].get("path") or ""))
    if name in {"preview", "contact-sheet"}:
        return Path(str(((manifest.get("render") or {}).get("contact_sheet") or {}).get("path") or ""))
    if name == "quality-report":
        return Path(str(((manifest.get("qa") or {}).get("report") or {}).get("path") or ""))
    if name == "change-summary":
        return work_dir / "change-summary.md"
    if name == "slide-spec":
        return Path(str(((manifest.get("inputs") or {}).get("slide_spec") or {}).get("path") or ""))
    if name == "revision-manifest":
        return work_dir / "revision-manifest.json"
    if name == "outline":
        return work_dir / "outline.md"
    raise RefusedError(f"no publisher for requested deliverable: {name}")


def publish_deliverables(work_dir: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Copy every confirmed artifact, refusing conflicting existing output files."""
    if work_dir.parent.name != ".pptx-work":
        raise RefusedError("publish requires outputs/.pptx-work/<work-id>")
    output_dir = work_dir.parent.parent.resolve()
    spec = Path(str(((manifest.get("inputs") or {}).get("slide_spec") or {}).get("path") or ""))
    meta = _load_spec(spec).get("meta") or {}
    prefix = str(meta.get("output_prefix") or work_dir.name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", prefix):
        raise RefusedError("output_prefix must be an ASCII-safe filename slug")
    requested = confirmed_deliverables(manifest)
    if "pptx" not in requested:
        requested = ["pptx", *requested]
    spec_data = _load_spec(spec)
    if "revision-manifest" in requested:
        revision = {
            "revision": spec_data.get("revision"),
            "mode": manifest.get("mode"),
            "source_pptx": (manifest.get("inputs") or {}).get("source_deck"),
            "delivered_pptx": (manifest.get("build") or {}).get("pptx"),
            "qa_report": (manifest.get("qa") or {}).get("report"),
        }
        (work_dir / "revision-manifest.json").write_text(
            json.dumps(revision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    render_pages = int((manifest.get("render") or {}).get("page_count") or 0) or None
    counts: dict[str, dict[str, int]] = {}
    destinations: dict[str, tuple[Path, Path]] = {}
    for name in requested:
        source = _source(manifest, name, work_dir)
        if not source.is_file() or not source.resolve().is_relative_to(work_dir):
            raise RefusedError(f"requested deliverable is missing from work-dir: {name}")
        # Content completeness is checked on the work-dir source before any
        # copy: page/section counts must match the frozen Slide Spec, so a
        # truncated script can never reach the outputs directory.
        counts[name] = verify_deliverable(name, source, spec_data, render_pages=render_pages)
        basename = (
            f"{prefix}-presentation{source.suffix}"
            if name in {"pptx", "pdf"}
            else f"{prefix}-{name}{source.suffix}"
        )
        target = output_dir / basename
        if target.exists() and bind(target)["sha256"] != bind(source)["sha256"]:
            raise RefusedError(f"output already exists with different content: {target}")
        destinations[name] = (source, target)
    published: dict[str, dict[str, Any]] = {}
    for name, (source, target) in destinations.items():
        if not target.is_file():
            temporary = output_dir / f".{target.name}.{work_dir.name}.tmp"
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        binding = bind(target)
        if binding["sha256"] != bind(source)["sha256"]:
            raise RefusedError(f"published file hash differs from QA source: {target}")
        published[name] = {**binding, **counts.get(name, {})}
    return published
