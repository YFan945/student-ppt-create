#!/usr/bin/env python3
"""Create low-cost visual-critic previews bound to current render evidence.

The independent critic normally does not need full-resolution render PNGs to
judge hierarchy, composition, whitespace, and deck rhythm. This helper creates
a smaller JPEG for every current rendered page plus an overview. Each preview
is bound to the exact source image SHA so runtime_evidence can credit a preview
Read back to the current original render evidence required by QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

MAP_NAME = "critic-preview-map.json"
PREVIEW_DIR_NAME = "critic-preview"
DEFAULT_LONG_EDGE = 1024
DEFAULT_QUALITY = 68


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _binding_is_current(binding: dict[str, Any]) -> bool:
    path = Path(str(binding.get("path") or ""))
    return path.is_file() and bool(binding.get("sha256")) and digest(path) == binding["sha256"]


def _jpeg_preview(source: Path, target: Path, *, long_edge: int, quality: int) -> None:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency gate owns production setup
        raise RuntimeError("Pillow is required for critic preview generation") from exc
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        scale = min(1.0, long_edge / max(image.width, image.height))
        if scale < 1.0:
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=quality, optimize=True)


def materialize(
    work_dir: Path,
    *,
    long_edge: int = DEFAULT_LONG_EDGE,
    quality: int = DEFAULT_QUALITY,
) -> dict[str, Any]:
    """Build fresh critic previews for the manifest's current render bindings."""
    work_dir = work_dir.resolve()
    manifest_path = work_dir / "build-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"build manifest missing: {manifest_path}")
    manifest = _load_json(manifest_path)
    render = manifest.get("render") or {}
    pages = render.get("pages") or []
    contact = render.get("contact_sheet") or {}
    if not pages or not isinstance(pages, list) or not isinstance(contact, dict):
        raise ValueError("current render evidence is incomplete; run render before visual-critic")
    bindings = [contact, *pages]
    if not all(isinstance(item, dict) and _binding_is_current(item) for item in bindings):
        raise ValueError("render evidence changed or disappeared; rerun render before visual-critic")

    preview_dir = work_dir / PREVIEW_DIR_NAME
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, str]] = []
    overview_source = Path(str(contact["path"]))
    overview_target = preview_dir / "overview.jpg"
    _jpeg_preview(overview_source, overview_target, long_edge=long_edge, quality=quality)
    entries.append(
        {
            "kind": "overview",
            "preview_path": str(overview_target.resolve()),
            "preview_sha256": digest(overview_target),
            "source_path": str(overview_source.resolve()),
            "source_sha256": str(contact["sha256"]),
        }
    )

    for index, binding in enumerate(pages, 1):
        source = Path(str(binding["path"]))
        target = preview_dir / f"p{index:02d}.jpg"
        _jpeg_preview(source, target, long_edge=long_edge, quality=quality)
        entries.append(
            {
                "kind": "page",
                "page": str(index),
                "preview_path": str(target.resolve()),
                "preview_sha256": digest(target),
                "source_path": str(source.resolve()),
                "source_sha256": str(binding["sha256"]),
            }
        )

    payload = {
        "version": 1,
        "work_id": work_dir.name,
        "pptx_sha256": str(render.get("pptx_sha256") or ""),
        "long_edge": long_edge,
        "quality": quality,
        "entries": entries,
    }
    (work_dir / MAP_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def source_binding_for_preview(work_dir: Path, preview: Path) -> tuple[str, str] | None:
    """Return source path/SHA only when both preview and source remain current."""
    map_path = work_dir.resolve() / MAP_NAME
    if not map_path.is_file() or not preview.is_file():
        return None
    try:
        payload = _load_json(map_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    resolved = str(preview.resolve())
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("preview_path") != resolved:
            continue
        if entry.get("preview_sha256") != digest(preview):
            return None
        source = Path(str(entry.get("source_path") or ""))
        source_sha = str(entry.get("source_sha256") or "")
        if not source.is_file() or not source_sha or digest(source) != source_sha:
            return None
        return str(source.resolve()), source_sha
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--long-edge", type=int, default=DEFAULT_LONG_EDGE)
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.long_edge < 640 or not 35 <= args.quality <= 90:
        print("critic_preview: invalid compression settings", file=sys.stderr)
        return 2
    try:
        payload = materialize(args.work_dir, long_edge=args.long_edge, quality=args.quality)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"critic_preview: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"critic_preview: {len(payload['entries']) - 1} page previews ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
