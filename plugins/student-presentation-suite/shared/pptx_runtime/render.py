"""Cross-platform LibreOffice and Poppler rendering helpers."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .soffice import soffice_environment

COMMON_SOFFICE = (
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
)


def _render_timeout() -> int:
    """Render subprocess timeout in seconds; overridable via PPTX_RENDER_TIMEOUT."""
    try:
        return max(1, int(os.environ.get("PPTX_RENDER_TIMEOUT", "120")))
    except ValueError:
        return 120


def _page_number(path: Path) -> int:
    """Trailing page number from a ``prefix-N.png`` filename (N is not zero-padded)."""
    try:
        return int(Path(path).stem.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return -1


def find_soffice() -> str | None:
    found = shutil.which("soffice")
    if found:
        return found
    return next((str(path) for path in COMMON_SOFFICE if path.is_file()), None)


def find_pdftoppm() -> str | None:
    found = shutil.which("pdftoppm")
    if not found:
        return None
    path = Path(found)
    parents = list(path.parents)
    if len(parents) >= 3:
        bundled = parents[2] / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
        if bundled.is_file():
            return str(bundled)
    return found


def render_pptx(
    source: Path,
    output_dir: Path,
    prefix: str,
    image_format: str,
    dpi: int,
) -> tuple[Path, list[Path], list[str]]:
    soffice = find_soffice()
    pdftoppm = find_pdftoppm()
    if not soffice or not pdftoppm:
        missing = [name for name, value in (("LibreOffice", soffice), ("pdftoppm", pdftoppm)) if not value]
        raise FileNotFoundError("missing render tools: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)
    # prefix 来自用户文件名，`[`/`*`/`?` 会被 glob 当通配符误匹配，必须转义。
    for stale in output_dir.glob(f"{glob.escape(prefix)}-*.{image_format}"):
        stale.unlink()
    generated = output_dir / f"{source.stem}.pdf"
    pdf = output_dir / f"{prefix}.pdf"
    for stale_pdf in {generated, pdf}:
        if stale_pdf.exists():
            stale_pdf.unlink()
    with tempfile.TemporaryDirectory(prefix="lo-profile-") as profile:
        user_installation = Path(profile).resolve().as_uri()
        environment, sandbox_messages = soffice_environment()
        converted = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={user_installation}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=_render_timeout(),
        )
    if converted.returncode or not generated.is_file():
        raise RuntimeError((converted.stderr or converted.stdout or "LibreOffice conversion failed").strip())
    if generated != pdf:
        if pdf.exists():
            pdf.unlink()
        generated.replace(pdf)
    flag = "-jpeg" if image_format == "jpg" else "-png"
    rendered = subprocess.run(
        [pdftoppm, flag, "-r", str(dpi), str(pdf), str(output_dir / prefix)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_render_timeout(),
    )
    if rendered.returncode:
        raise RuntimeError((rendered.stderr or rendered.stdout or "Poppler render failed").strip())
    # pdftoppm 产出 prefix-1..N.png（不补零），必须按数值页号而非字典序排序，
    # 否则 ≥10 页时 prefix-10.png 会排在 prefix-2.png 前导致预览/缩略图错位。
    pages = sorted(output_dir.glob(f"{prefix}-*.{image_format}"), key=_page_number)
    return pdf, pages, [*sandbox_messages, converted.stdout.strip(), rendered.stderr.strip()]


def align_rendered_pages(
    pages: list[Path],
    metadata: list[dict[str, object]],
    output_dir: Path,
    prefix: str,
    image_format: str,
) -> tuple[list[Path], list[int]]:
    """Restore original slide ordering when LibreOffice omits hidden slides."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    visible_count = sum(not bool(item["hidden"]) for item in metadata)
    if len(pages) == len(metadata):
        return pages, []
    if len(pages) != visible_count:
        raise ValueError(
            f"renderer produced {len(pages)} page(s) for {visible_count} visible "
            f"slide(s) of {len(metadata)}"
        )
    with tempfile.TemporaryDirectory(prefix="pptx-page-align-") as tmp:
        staged = []
        for index, page in enumerate(pages, 1):
            target = Path(tmp) / f"{index}.{image_format}"
            shutil.copyfile(page, target)
            staged.append(target)
        for page in output_dir.glob(f"{prefix}-*.{image_format}"):
            page.unlink()
        if staged:
            with Image.open(staged[0]) as sample:
                size = sample.size
        else:
            width = int(metadata[0].get("width_emu") or 0) if metadata else 0
            height = int(metadata[0].get("height_emu") or 0) if metadata else 0
            size = (1280, round(1280 * height / width)) if width and height else (1280, 720)
        aligned = []
        placeholders = []
        rendered_index = 0
        for index, item in enumerate(metadata, 1):
            target = output_dir / f"{prefix}-{index}.{image_format}"
            if bool(item["hidden"]):
                image = Image.new("RGB", size, "#F0F0F0")
                draw = ImageDraw.Draw(image)
                stroke = max(3, min(size) // 80)
                draw.line(((0, 0), size), fill="#C8C8C8", width=stroke)
                draw.line(((0, size[1]), (size[0], 0)), fill="#C8C8C8", width=stroke)
                draw.text((24, 24), f"Hidden slide {index}", fill="#555555")
                image.save(target)
                placeholders.append(index)
            else:
                shutil.copyfile(staged[rendered_index], target)
                rendered_index += 1
            aligned.append(target)
    return aligned, placeholders
