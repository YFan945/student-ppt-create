#!/usr/bin/env python3
"""Write the CD-2 generator layout: thin deck.js + one pages/pNN-*.js per slide.

v0.8 still requires composition JSON; this module only creates the *generator*
files so `ppt_pipeline.py build` can refuse a monolithic deck.js. Existing
authored page files (no scaffold marker) are left untouched on replan.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCAFFOLD_MARKER = "student-presentation-suite-scaffold"
PAGE_NAME_RE = re.compile(r"^p(\d{2})-.+\.js$")

DECK_TEMPLATE = """\
'use strict';
/* {marker} — assembly only; page coordinates live in ./pages/pNN-*.js */

const path = require('node:path');
const HELPERS_DIR =
  process.env.PPTX_HELPERS_DIR || path.join(process.env.CLAUDE_PLUGIN_ROOT || '', 'scripts');
const H = require(path.join(HELPERS_DIR, 'pptx-helpers.js'));
const {{ SlideElementRegistry }} = require(path.join(HELPERS_DIR, 'pptx-element-registry.js'));
const pptxgen = require('pptxgenjs');

const PAGES = [
{requires}
];

function main() {{
  const out = process.argv[2];
  if (!out) throw new Error('usage: deck.js <output.pptx>');
  const pptx = new pptxgen();
  H.applyTokens(pptx, {{}}, 'chinese');
  const registry = new SlideElementRegistry({{
    slideW: H.SLIDE_W_IN,
    slideH: H.SLIDE_H_IN,
  }});
  PAGES.forEach((mod, index) => {{
    const n = index + 1;
    const slide = pptx.addSlide();
    slide.background = {{ color: H.color({{ palette: {{ canvas: 'FFFFFF' }} }}, 'canvas') }};
    mod({{ pptx, slide, n, H, registry }});
  }});
  registry.assertSafe();
  return pptx.writeFile({{ fileName: out }});
}}

main();
"""

PAGE_STUB = """\
'use strict';
/* {marker} */
/** Slide {n} — {title} */
module.exports = function (ctx) {{
  const {{ slide, n, H, registry }} = ctx;
  const COPY = {{
    title: {title_js},
    claim: {claim_js},
    slideCopy: {copy_js},
  }};
  /* Keep COPY.* string literals — page_copy_fidelity_check reads this file. */
  slide.addText(COPY.title, {{
    x: 0.6, y: 0.4, w: 8.8, h: 1.0,
    fontSize: 32,
    lineSpacing: Number((32 * H.LINE_SPACING_FACTOR).toFixed(2)),
  }});
  registry.text(n, COPY.title, {{ x: 0.6, y: 0.4, w: 8.8, h: 1.0, fontSize: 32 }});
}};
"""


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        import yaml  # type: ignore

        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"Slide Spec root must be an object: {path}")
    return value


def spec_slides(spec: dict[str, Any]) -> list[dict[str, Any]]:
    slides = spec.get("slides") or []
    result: list[dict[str, Any]] = []
    for item in slides:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.append({**item, "id": number})
    result.sort(key=lambda item: int(item["id"]))
    return result


def page_slug(slide: dict[str, Any]) -> str:
    kind = str(slide.get("kind") or "").strip().lower()
    role = str(slide.get("role") or "").strip().lower()
    for token in (kind, role):
        if token in {"cover", "closing", "section", "hook", "toc"}:
            return token
    title = str(slide.get("title") or "")
    parts = re.findall(r"[a-z0-9]+", title.lower())
    if parts:
        return "-".join(parts)[:24]
    return f"s{int(slide['id']):02d}"


def page_filename(slide: dict[str, Any]) -> str:
    return f"p{int(slide['id']):02d}-{page_slug(slide)}.js"


def listed_page_files(pages_dir: Path) -> list[Path]:
    if not pages_dir.is_dir():
        return []
    files = [path for path in pages_dir.glob("p*.js") if PAGE_NAME_RE.match(path.name)]
    files.sort(key=lambda path: int(PAGE_NAME_RE.match(path.name).group(1)))  # type: ignore[union-attr]
    return files


def js_string(value: str) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def write_if_scaffoldable(path: Path, contents: str) -> bool:
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if SCAFFOLD_MARKER not in existing:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return True


def scaffold_generator(work_dir: Path, spec_path: Path) -> dict[str, Any]:
    """Create deck.js + pages/ stubs. Returns counts for the stage summary."""
    spec = load_spec(spec_path)
    slides = spec_slides(spec)
    pages_dir = work_dir / "pages"
    composition_dir = work_dir / "composition"
    composition_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    written_pages = 0
    kept_pages = 0
    names: list[str] = []
    for slide in slides:
        name = page_filename(slide)
        names.append(name)
        stub = PAGE_STUB.format(
            marker=SCAFFOLD_MARKER,
            n=int(slide["id"]),
            title=str(slide.get("title") or f"Slide {slide['id']}"),
            title_js=js_string(str(slide.get("title") or f"Slide {slide['id']}")),
            claim_js=js_string(str(slide.get("claim") or "")),
            copy_js=js_string(str(slide.get("slide_copy") or "")),
        )
        target = pages_dir / name
        if write_if_scaffoldable(target, stub):
            written_pages += 1
        else:
            kept_pages += 1

    requires = ",\n".join(f"  require('./pages/{name}')" for name in names)
    deck = DECK_TEMPLATE.format(marker=SCAFFOLD_MARKER, requires=requires or "  // no slides")
    deck_path = work_dir / "deck.js"
    wrote_deck = write_if_scaffoldable(deck_path, deck)
    return {
        "slides": len(slides),
        "written_pages": written_pages,
        "kept_pages": kept_pages,
        "wrote_deck": wrote_deck,
        "pages": names,
    }


def scaffolded_pages(files: list[Path]) -> list[str]:
    """Page modules that still carry the stub marker, i.e. never implemented."""
    return [
        path.name for path in files
        if SCAFFOLD_MARKER in path.read_text(encoding="utf-8")
    ]


def assert_page_split(entry: Path, spec_path: Path) -> None:
    """Refuse a build whose generator is not split one-file-per-slide."""
    spec = load_spec(spec_path)
    slides = spec_slides(spec)
    if not slides:
        raise ValueError("Slide Spec has no slides — cannot build a paged generator")
    expected = {int(item["id"]) for item in slides}
    pages_dir = entry.parent / "pages"
    files = listed_page_files(pages_dir)
    found = {
        int(PAGE_NAME_RE.match(path.name).group(1))  # type: ignore[union-attr]
        for path in files
    }
    if found != expected:
        raise ValueError(
            "pages/ must contain one pNN-*.js per Slide Spec id "
            f"(have {sorted(found)}, need {sorted(expected)}). "
            "Run `ppt_pipeline.py plan` so scaffold can create the stubs."
        )
    text = entry.read_text(encoding="utf-8")
    missing = [path.name for path in files if f"./pages/{path.name}" not in text]
    if missing:
        raise ValueError(
            "deck.js must require every page module; missing "
            + ", ".join(missing)
        )
    unimplemented = scaffolded_pages(files)
    if unimplemented:
        raise ValueError(
            "pages/ still contain the scaffold marker — those pages were never implemented: "
            + ", ".join(unimplemented)
            + ". Implement each page and delete the marker comment before building; "
            "a stub-only deck must not reach build, render or QA."
        )
