#!/usr/bin/env python3
"""Render 2-3 style preview decks so the user can pick a style from pixels.

P2-11 "show, don't tell" (frontend-slides mechanism), opt-in at intake: when
the user cannot choose between the 12 style families from descriptions, this
tool builds one tiny 2-page deck per candidate style (dark cover + light chart
page, fixed sample copy themed by the topic) through the SAME engine the real
deck will use, renders them to PNG, and writes a manifest the main session can
show. Cost: ~3 node builds + ~3 LibreOffice renders, zero model tokens.

This is an intake aid, not a pipeline stage: it never writes into a work-dir
and never advances state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[2]
SCRIPTS = PLUGIN_ROOT / "scripts"
SOFFICE_CANDIDATES = (
    "soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
)
DEFAULT_STYLES = ["modern-minimal", "ocean-tech", "coral-energy"]


def _soffice() -> str:
    for candidate in SOFFICE_CANDIDATES:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    raise SystemExit(
        "style_previews: LibreOffice (soffice) not found — previews must be rendered to be "
        "usable; install LibreOffice or add it to PATH"
    )


def _pdftoppm() -> str:
    found = shutil.which("pdftoppm")
    if not found:
        raise SystemExit(
            "style_previews: pdftoppm (poppler) not found — install poppler or add it to PATH"
        )
    return found


def _render_pngs(soffice: str, pptx: Path, out_dir: Path) -> list[Path]:
    with tempfile.TemporaryDirectory(prefix="style-preview-") as tmp:
        tmp_dir = Path(tmp)
        convert = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_dir), str(pptx)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        pdf = tmp_dir / (pptx.stem + ".pdf")
        if convert.returncode != 0 or not pdf.is_file():
            raise SystemExit(
                f"style_previews: render failed for {pptx.name}: "
                f"{(convert.stderr or convert.stdout or '').strip()[-200:]}"
            )
        stem = pptx.stem
        subprocess.run(
            [_pdftoppm(), "-png", "-r", "80", str(pdf), str(tmp_dir / stem)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        pngs = sorted(tmp_dir.glob(f"{stem}-*.png"))
        out_dir.mkdir(parents=True, exist_ok=True)
        kept: list[Path] = []
        for png in pngs:
            target = out_dir / f"{stem}-{png.stem.split('-')[-1]}.png"
            shutil.copyfile(png, target)
            kept.append(target)
        return kept


def _build_preview(style: str, topic: str, pptx_path: Path) -> None:
    sys.path.insert(0, str(PLUGIN_ROOT))
    from shared.design_tokens import resolve_design_tokens

    tokens = resolve_design_tokens(style)
    payload = json.dumps({"out": str(pptx_path), "topic": topic, "tokens": tokens})
    result = subprocess.run(
        ["node", str(SCRIPTS / "style_preview_deck.js")],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PPTX_HELPERS_DIR": str(SCRIPTS),
            "NODE_PATH": f"{SCRIPTS}{os.pathsep}{PLUGIN_ROOT / 'node_modules'}",
        },
        timeout=120,
    )
    if result.returncode != 0 or not pptx_path.is_file():
        raise SystemExit(
            f"style_previews: build failed for style {style}: "
            f"{(result.stderr or result.stdout or '').strip()[-300:]}"
        )


def run(args: argparse.Namespace) -> int:
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    soffice = _soffice()
    styles = [style.strip() for style in (args.styles or DEFAULT_STYLES) if style.strip()]
    if not styles:
        raise SystemExit("style_previews: no styles requested")
    previews: list[dict[str, Any]] = []
    warnings: list[str] = []
    for style in styles:
        pptx_path = out_dir / f"style-preview-{style}.pptx"
        try:
            _build_preview(style, args.topic, pptx_path)
        except SystemExit as exc:
            warnings.append(str(exc))
            continue
        entry: dict[str, Any] = {
            "style": style,
            "pptx": str(pptx_path),
            "pptx_sha256": hashlib.sha256(pptx_path.read_bytes()).hexdigest(),
        }
        try:
            pngs = _render_pngs(soffice, pptx_path, out_dir)
            entry["pngs"] = [str(png) for png in pngs]
        except SystemExit as exc:
            warnings.append(str(exc))
            entry["pngs"] = []
        previews.append(entry)
    report = {
        "topic": args.topic,
        "styles": styles,
        "previews": previews,
        "warnings": warnings,
        "note": "intake aid only — sample copy is fixed; the confirmed Production Summary still owns the real content",
    }
    manifest = out_dir / "style-previews.json"
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rendered = sum(1 for item in previews if item.get("pngs"))
    print(
        f"style_previews: {rendered}/{len(styles)} rendered — manifest: {manifest} "
        f"| styles: {', '.join(styles)}"
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if rendered else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True, help="deck topic shown on the sample cover")
    parser.add_argument(
        "--styles",
        nargs="+",
        default=None,
        help=f"style keys to preview (default: {', '.join(DEFAULT_STYLES)} — one per category)",
    )
    parser.add_argument("--out", type=Path, required=True, help="output directory (e.g. outputs/<topic>-style-previews)")
    parser.add_argument("--json", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
