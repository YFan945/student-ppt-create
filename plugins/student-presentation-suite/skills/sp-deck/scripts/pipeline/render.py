from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline import core  # noqa: E402
from pipeline.core import (  # noqa: E402
    PPTX_TOOL,
    RefusedError,
    bind,
    load_manifest,
    now,
    pptx_path,
    pre_qa_failed_current,
    record,
    render_is_current,
    require_state,
    save_manifest,
    sha256_file,
    validate_manifest_authorization,
)


def make_contact_sheet(
    pages: list[Path], output: Path, cols: int = 3,
    thumb_output: Path | None = None, thumb_width: int = 1024,
) -> None:
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
    if thumb_output is not None:
        # 主会话用的廉价概览：2026-09-16 实测全尺寸 contact-sheet.png 有 844KB，
        # 12 页逐页 PNG 更是每张 200-500KB。缩略图 ~100KB，token 当量差一个量级。
        ratio = min(1.0, thumb_width / sheet.width)
        small = sheet.resize((max(1, int(sheet.width * ratio)), max(1, int(sheet.height * ratio))))
        small.save(thumb_output, "JPEG", quality=72)
    for image in opened:
        image.close()


def make_contact_thumb(pages: list[Path], output: Path, thumb_width: int = 1024) -> None:
    """Regenerate only the cheap overview thumb (render cache-hit path)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RefusedError("Pillow is required for contact-sheet generation") from exc
    if not pages:
        return
    opened = [Image.open(path).convert("RGB") for path in pages]
    width = min(480, max(image.width for image in opened))
    thumbs = []
    for image in opened:
        ratio = width / image.width
        thumbs.append(image.resize((width, max(1, int(image.height * ratio)))))
    cols = 3
    cell_h = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (width * cols, cell_h * rows), "white")
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % cols) * width, (index // cols) * cell_h))
    ratio = min(1.0, thumb_width / sheet.width)
    small = sheet.resize((max(1, int(sheet.width * ratio)), max(1, int(sheet.height * ratio))))
    output.parent.mkdir(parents=True, exist_ok=True)
    small.save(output, "JPEG", quality=72)
    for image in opened:
        image.close()


def cmd_render(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"producing", "qa"}, "render")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    if pre_qa_failed_current(manifest):
        raise RefusedError(
            "pre-QA gates failed for this build — fix the reported pages and rebuild before "
            "rendering (run `next --json`: that path consumes no repair round)"
        )
    pptx = pptx_path(manifest)
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    pptx_sha = sha256_file(pptx)
    if render_is_current(manifest):
        render = manifest.get("render") or {}
        old_contact = Path(str((render.get("contact_sheet") or {}).get("path") or ""))
        old_thumb = Path(str((render.get("contact_sheet_thumb") or {}).get("path") or ""))
        if old_thumb and not old_thumb.is_file():
            # 旧 manifest 没有缩略图字段或文件丢失：从已绑定的页图补生成。
            page_paths = [Path(str(item.get("path"))) for item in render.get("pages") or []]
            existing = [path for path in page_paths if path.is_file()]
            if existing:
                make_contact_thumb(existing, old_thumb or work_dir / "contact-sheet-thumb.jpg")
        record(
            manifest, "render", str(manifest.get("state")), str(manifest.get("state")),
            page_count=int(render.get("page_count") or 0), reused=True,
        )
        save_manifest(work_dir, manifest)
        print(f"ppt_pipeline: render reused — {old_contact}")
        return 0

    render_dir = work_dir / "render"
    if args.cols < 1 or not args.prefix or Path(args.prefix).name != args.prefix or any(ch in args.prefix for ch in "/\\"):
        raise RefusedError("render requires positive cols and a plain filename prefix")
    if not render_dir.resolve().is_relative_to(work_dir):
        raise RefusedError("render directory must stay inside work-dir")
    proc = core._runner([
        sys.executable, str(PPTX_TOOL), "render", str(pptx),
        "--output-dir", str(render_dir), "--prefix", args.prefix,
    ])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RefusedError(f"render failed (exit {proc.returncode}): {detail[:500]}")
    payload = None
    with contextlib.suppress(json.JSONDecodeError):
        payload = json.loads(proc.stdout)
    page_values = payload.get("pages") if isinstance(payload, dict) else None
    pdf_value = payload.get("pdf") if isinstance(payload, dict) else None
    pages = [Path(str(path)) for path in page_values] if isinstance(page_values, list) else sorted(render_dir.glob(f"{args.prefix}*.png"))
    if not pages or not all(path.is_file() for path in pages):
        raise RefusedError("render reported success but page images are missing")
    rendered_pdf = Path(str(pdf_value)) if pdf_value else render_dir / f"{args.prefix}.pdf"
    if not rendered_pdf.is_file():
        raise RefusedError("render reported success but the PDF export is missing")
    contact = work_dir / "contact-sheet.png"
    thumb = work_dir / "contact-sheet-thumb.jpg"
    make_contact_sheet(pages, contact, args.cols, thumb_output=thumb)
    manifest["render"] = {
        "pptx_sha256": pptx_sha,
        "pages": [bind(path) for path in pages],
        "contact_sheet": bind(contact),
        "contact_sheet_thumb": bind(thumb),
        "pdf": bind(rendered_pdf),
        "page_count": len(pages),
        "rendered_at": now(),
    }
    record(manifest, "render", str(manifest.get("state")), str(manifest.get("state")), page_count=len(pages))
    save_manifest(work_dir, manifest)
    print(f"ppt_pipeline: rendered {len(pages)} pages — contact sheet: {contact}")
    print(f"ppt_pipeline: cheap overview thumb: {thumb}")
    return 0


