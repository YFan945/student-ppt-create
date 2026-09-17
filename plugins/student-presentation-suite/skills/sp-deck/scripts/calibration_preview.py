#!/usr/bin/env python3
"""Build and render a temporary calibration deck from selected implemented pages.

This is intentionally outside the production manifest/state machine. It lets the
builder implement a few high-leverage pages, render them, and get visual feedback
before the remaining scaffold pages are authored. The production build still goes
through ppt_pipeline.py after every page is implemented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILDER = ROOT / "scripts" / "run_with_pptxgenjs.js"
PPTX_TOOL = ROOT / "scripts" / "pptx_tool.py"
SCAFFOLD_MARKER = "student-presentation-suite-scaffold"
PAGE_RE = re.compile(r"^p(\d{2})-.+\.js$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def high_leverage_slides(art_direction: Path) -> list[int]:
    data = load_structured(art_direction)
    result: list[int] = []
    for item in data.get("high_leverage_slides") or []:
        raw = item.get("slide") if isinstance(item, dict) else item
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result[:3]


def page_map(work_dir: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in sorted((work_dir / "pages").glob("p*.js")):
        match = PAGE_RE.match(path.name)
        if match:
            result[int(match.group(1))] = path.resolve()
    return result


def require_implemented_pages(work_dir: Path, slides: list[int]) -> list[Path]:
    available = page_map(work_dir)
    missing = [slide for slide in slides if slide not in available]
    if missing:
        raise ValueError(f"calibration pages do not exist: {missing}")
    paths = [available[slide] for slide in slides]
    scaffolded = [path.name for path in paths if SCAFFOLD_MARKER in path.read_text(encoding="utf-8")]
    if scaffolded:
        raise ValueError(
            "calibration pages are still scaffold stubs: " + ", ".join(scaffolded)
        )
    return paths


def write_calibration_deck(target: Path, pages: list[tuple[int, Path]]) -> None:
    rows = ",\n".join(
        f"  {{ n: {number}, mod: require({json.dumps(str(path))}) }}" for number, path in pages
    )
    source = f"""'use strict';
const path = require('node:path');
const HELPERS_DIR = process.env.PPTX_HELPERS_DIR || path.join(process.env.CLAUDE_PLUGIN_ROOT || '', 'scripts');
const H = require(path.join(HELPERS_DIR, 'pptx-helpers.js'));
const {{ SlideElementRegistry }} = require(path.join(HELPERS_DIR, 'pptx-element-registry.js'));
const pptxgen = require('pptxgenjs');
const PAGES = [
{rows}
];
async function main() {{
  const out = process.argv[2];
  if (!out) throw new Error('usage: calibration-deck.js <output.pptx>');
  const pptx = new pptxgen();
  H.applyTokens(pptx, {{}}, 'chinese');
  const registry = new SlideElementRegistry({{ slideW: H.SLIDE_W_IN, slideH: H.SLIDE_H_IN }});
  for (const item of PAGES) {{
    const slide = pptx.addSlide();
    slide.background = {{ color: H.color({{ palette: {{ canvas: 'FFFFFF' }} }}, 'canvas') }};
    item.mod({{ pptx, slide, n: item.n, H, registry }});
  }}
  registry.assertSafe();
  await pptx.writeFile({{ fileName: out }});
}}
main();
"""
    target.write_text(source, encoding="utf-8")


def run_checked(argv: list[str], label: str) -> None:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"{label} failed (exit {proc.returncode}): {detail[:500]}")


def build_preview(work_dir: Path, slides: list[int]) -> dict[str, Any]:
    work_dir = work_dir.resolve()
    if not slides:
        raise ValueError("no calibration slides selected")
    pages = require_implemented_pages(work_dir, slides)
    target = work_dir / "calibration"
    render_dir = target / "render"
    target.mkdir(parents=True, exist_ok=True)
    if render_dir.exists():
        for old in render_dir.glob("*.png"):
            old.unlink()
    render_dir.mkdir(parents=True, exist_ok=True)

    deck_js = target / "calibration-deck.js"
    pptx = target / "calibration.pptx"
    # calibration.pptx is disposable preview evidence, exactly like the PNGs above:
    # clearing one and not the other made the documented resume path unusable. A
    # calibration fix round is followed by "rerun the helper", but
    # run_with_pptxgenjs.js refuses to overwrite an existing output, so the second
    # run died at exit 2 (2026-09-17 live) and the round went to deleting the file
    # by hand.
    if pptx.exists():
        pptx.unlink()
    write_calibration_deck(deck_js, list(zip(slides, pages, strict=True)))
    run_checked(
        ["node", str(BUILDER), "--output", str(pptx), str(deck_js)],
        "calibration build",
    )
    run_checked(
        [sys.executable, str(PPTX_TOOL), "render", str(pptx), "--output-dir", str(render_dir), "--prefix", "calibration"],
        "calibration render",
    )
    images = sorted(render_dir.glob("*.png"))
    if len(images) != len(slides):
        raise RuntimeError(f"calibration render produced {len(images)} images for {len(slides)} slides")
    manifest = {
        "version": "1.0",
        "slides": slides,
        "pages": [
            {"slide": number, "path": str(path), "sha256": sha256_file(path)}
            for number, path in zip(slides, pages, strict=True)
        ],
        "pptx": {"path": str(pptx), "sha256": sha256_file(pptx)},
        "render": [
            {"slide": number, "path": str(path.resolve()), "sha256": sha256_file(path)}
            for number, path in zip(slides, images, strict=True)
        ],
    }
    out = target / "calibration-manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "manifest": str(out)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--slides", type=int, nargs="*")
    parser.add_argument("--art-direction", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    slides = list(dict.fromkeys(args.slides or []))
    if not slides:
        art = args.art_direction or args.work_dir / "art-direction.yaml"
        if not art.is_file():
            raise SystemExit("calibration_preview: pass --slides or provide art-direction.yaml")
        slides = high_leverage_slides(art)
    try:
        result = build_preview(args.work_dir, slides[:3])
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"calibration_preview: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"calibration_preview: rendered slides {result['slides']} → {result['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
