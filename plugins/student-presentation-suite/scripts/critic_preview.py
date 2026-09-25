#!/usr/bin/env python3
"""Create low-cost visual-critic previews bound to current render evidence.

The independent critic normally does not need full-resolution render PNGs to
judge hierarchy, composition, whitespace, and deck rhythm. This helper creates
a smaller JPEG for every current rendered page plus an overview when the full
deck has one. It supports both production render evidence and the temporary
calibration render written before the production state reaches ``producing``.
Each preview is bound to the exact source image SHA so runtime_evidence can
credit a preview Read back to the current original render evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.quality_tiers import normalize as normalize_tier  # noqa: E402

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


def _production_evidence(work_dir: Path) -> dict[str, Any] | None:
    manifest_path = work_dir / "build-manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _load_json(manifest_path)
    render = manifest.get("render") or {}
    pages = render.get("pages") or []
    contact = render.get("contact_sheet") or {}
    if not pages or not isinstance(pages, list) or not isinstance(contact, dict):
        return None
    bindings = [contact, *pages]
    if not all(isinstance(item, dict) and _binding_is_current(item) for item in bindings):
        raise ValueError("render evidence changed or disappeared; rerun render before visual-critic")
    return {
        "scope": "production",
        "pptx_sha256": str(render.get("pptx_sha256") or ""),
        "overview": contact,
        "pages": [
            {"page": index, **item}
            for index, item in enumerate(pages, 1)
        ],
        "review_output": str((work_dir / "visual-review.json").resolve()),
        "receipt_output": str((work_dir / "critic-execution.json").resolve()),
    }


def _calibration_evidence(work_dir: Path) -> dict[str, Any] | None:
    calibration = work_dir / "calibration"
    manifest_path = calibration / "calibration-manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _load_json(manifest_path)
    pptx = manifest.get("pptx") or {}
    pages = manifest.get("render") or []
    if not isinstance(pptx, dict) or not _binding_is_current(pptx):
        raise ValueError("calibration PPTX changed or disappeared; rerun calibration_preview.py")
    if not pages or not isinstance(pages, list):
        raise ValueError("calibration render evidence is incomplete; rerun calibration_preview.py")
    if not all(isinstance(item, dict) and _binding_is_current(item) for item in pages):
        raise ValueError("calibration render evidence changed or disappeared; rerun calibration_preview.py")
    slide_ids = [item.get("slide") for item in pages]
    if slide_ids != list(manifest.get("slides") or []):
        raise ValueError("calibration render slide ids do not match calibration-manifest.json")
    return {
        "scope": "calibration",
        "pptx_sha256": str(pptx.get("sha256") or ""),
        "overview": None,
        "pages": pages,
        "review_output": str((calibration / "calibration-visual-review.json").resolve()),
        "receipt_output": str((calibration / "calibration-critic-execution.json").resolve()),
    }


def current_evidence(work_dir: Path) -> dict[str, Any]:
    """Resolve the one render scope the next critic must inspect.

    A current production render wins once it exists. Before production build,
    calibration evidence is the only legitimate source. This ordering prevents
    a stale calibration directory from hijacking a later full-deck review.
    """
    production = _production_evidence(work_dir)
    if production is not None:
        return production
    calibration = _calibration_evidence(work_dir)
    if calibration is not None:
        return calibration
    raise ValueError(
        "current render evidence is incomplete; run calibration_preview.py for a planned "
        "deck or render for a production deck before visual-critic"
    )


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
    """Build fresh critic previews for the current production or calibration render."""
    work_dir = work_dir.resolve()
    evidence = current_evidence(work_dir)
    pages = evidence["pages"]
    contact = evidence["overview"]

    preview_dir = work_dir / PREVIEW_DIR_NAME
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, str]] = []
    if contact is not None:
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
                "page": str(binding.get("page") or binding.get("slide") or index),
                "preview_path": str(target.resolve()),
                "preview_sha256": digest(target),
                "source_path": str(source.resolve()),
                "source_sha256": str(binding["sha256"]),
            }
        )

    try:
        manifest = _load_json(work_dir / "build-manifest.json")
    except (OSError, ValueError, json.JSONDecodeError):
        manifest = {}
    payload = {
        "version": 1,
        "work_id": work_dir.name,
        "scope": evidence["scope"],
        # The tier travels with the bindings: the critic judges per tier without
        # opening the frozen Slide Spec (26KB+ for one enum value).
        "quality_level": normalize_tier(manifest.get("quality_level")),
        "pptx_sha256": evidence["pptx_sha256"],
        "review_output": evidence["review_output"],
        "receipt_output": evidence["receipt_output"],
        "long_edge": long_edge,
        "quality": quality,
        "entries": entries,
    }
    (work_dir / MAP_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def assigned_review_output(work_dir: Path) -> Path | None:
    """Return the current hook-authorized critic output from the preview map."""
    map_path = work_dir.resolve() / MAP_NAME
    if not map_path.is_file():
        return None
    try:
        payload = _load_json(map_path)
        expected = current_evidence(work_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("scope") != expected["scope"]:
        return None
    if payload.get("pptx_sha256") != expected["pptx_sha256"]:
        return None
    output = Path(str(payload.get("review_output") or ""))
    expected_output = Path(expected["review_output"])
    if output.resolve() != expected_output.resolve():
        return None
    return expected_output.resolve()


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
