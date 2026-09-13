"""Build the visual template gallery: 12 styles x 9 rendered template pages.

Produces examples/visual-template-gallery/gallery-input.json from
shared.design_tokens.resolve_design_tokens (light + dark palette +
visual_language + svg_reference), then drives gallery.js through the
pptxgenjs wrapper, validates the package and renders every page.

Usage:
    python examples/visual-template-gallery/build.py [--output-dir DIR] [--skip-render]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

STYLE_NAMES = [
    "Academic Rigorous", "Data Driven", "Modern Minimal", "Charcoal Editorial",
    "Midnight Business", "Ocean Tech", "Teal Trust", "Cherry Bold",
    "Creative Student", "Coral Energy", "Forest Moss", "Warm Terracotta",
]

sys.path.insert(0, str(ROOT))
from shared.design_tokens import resolve_design_tokens  # noqa: E402


def py(*args: object) -> list[str]:
    return [sys.executable, *[str(a) for a in args]]


def _replace_with_retry(staging: Path, pptx: Path, attempts: int = 6) -> Path:
    """A viewer may hold the previous artifact open; retry, then fall back.

    Returns the path that actually holds the fresh artifact.
    """
    import time

    for attempt in range(attempts):
        try:
            os.replace(staging, pptx)
            return pptx
        except PermissionError:
            if attempt == attempts - 1:
                fallback = pptx.with_name(pptx.stem + "-rebuild.pptx")
                os.replace(staging, fallback)
                print(f"[warn] {pptx.name} is locked by another process; wrote {fallback.name}")
                return fallback
            time.sleep(1)
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path(os.environ.get("OUTPUT_ROOT", ROOT.parents[1] / "outputs")) / "visual-template-gallery"
    out_dir.mkdir(parents=True, exist_ok=True)

    styles = []
    for name in STYLE_NAMES:
        tokens = resolve_design_tokens(name)
        if "visual_language" not in tokens:
            raise SystemExit(f"{name}: visual_language missing from resolved tokens")
        if "dark_palette" not in tokens:
            raise SystemExit(f"{name}: dark_palette missing from resolved tokens")
        styles.append({"key": tokens["style_key"], "name": name, "tokens": tokens})

    (HERE / "gallery-input.json").write_text(
        json.dumps({"styles": styles}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] gallery-input.json ({len(styles)} styles)")

    pptx = out_dir / "visual-template-gallery.pptx"
    staging = out_dir / f".gallery-{os.getpid()}.pptx"
    if staging.exists():
        staging.unlink()
    env = dict(os.environ, PYTHON=str(sys.executable))
    subprocess.run(
        ["node", str(SCRIPTS / "run_with_pptxgenjs.js"), "--output", str(staging), str(HERE / "gallery.js")],
        check=True, cwd=ROOT, env=env,
    )
    pptx = _replace_with_retry(staging, pptx)
    print(f"[ok] {pptx}")

    # Combined catalog: per-style CJK pairs would collide in one file, so the
    # gallery uses a single generic East Asian font for all latin typefaces.
    latin_fonts = sorted({f for s in styles for f in (s["tokens"]["typography"]["title_font"],
                                                      s["tokens"]["typography"]["body_font"])})
    cjk_cmd = [sys.executable, str(SCRIPTS / "pptx_tool.py"), "cjk-fonts", str(pptx)]
    for latin in latin_fonts:
        cjk_cmd += ["--map", f"{latin}=Microsoft YaHei"]
    subprocess.run(cjk_cmd, check=True, cwd=ROOT)
    print(f"[ok] cjk-fonts ({len(latin_fonts)} latin faces -> Microsoft YaHei)")

    subprocess.run(py(SCRIPTS / "pptx_tool.py", "validate", pptx, "--json"), check=True, cwd=ROOT)
    print("[ok] package validation")

    if not args.skip_render:
        render_dir = out_dir / "render"
        render_dir.mkdir(exist_ok=True)
        subprocess.run(
            py(SCRIPTS / "pptx_tool.py", "render", pptx, "--output-dir", render_dir, "--prefix", "tpl"),
            check=True, cwd=ROOT,
        )
        previews = sorted(render_dir.glob("*.png"))
        print(f"[ok] rendered {len(previews)} pages -> {render_dir}")

    print("[done] visual template gallery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
