#!/usr/bin/env python3
"""Refuse a build whose pages/ no longer carry the Slide Spec copy verbatim.

Why this exists: `pptx_actual_content_check.py` demands `title` / `claim` /
`slide_copy` appear **verbatim** on the rendered slide, but it can only run
*after* the deck has been built and rendered. When a page module paraphrases the
Spec, the failure surfaces at QA — after build, render and the first QA stage
have already been paid for. That cascade has fired repeatedly:

  * v0.8 run 2: 30 blockers and a full generator rewrite
    (see the docstring in `copy_fit_preflight.py`)
  * 0.11.1 pilot: 11 blockers (8 `planned_copy_missing` + 3 `missing_key_claim`);
    repair started and was cut off before it could finish

Both are knowable *before* `build` runs: page modules are plain text and the
Spec strings are already fixed. This check compares the two, so a paraphrased
page is refused while the fix is still one Edit instead of a whole rebuild.

Page modules map to Spec slides **by ordinal** — `p01-*`, `p02-*`, ... match
`spec.slides[0]`, `spec.slides[1]`, ... The filename slug is human-chosen and is
not the slide id (`p03-lcoe.js`, `p05-90.js`), so only the ordinal is reliable.

Exit codes: 0 = every planned string is present, 2 = at least one is missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pptx_actual_content_check import (  # noqa: E402
    compact_fragments,
    load_structured,
    normalize,
    sha256_file,
)

PAGE_RE = re.compile(r"^p(\d+)-", re.IGNORECASE)
MIN_FRAGMENT_CHARS = 6


def source_text(path: Path) -> str:
    """Flatten a page module so split string literals compare equal to their join.

    A module that writes `'度电成本 = ' + '全寿命周期成本 ÷ 全寿命周期上网电量'` does
    carry the planned copy; comparing against the raw source would wrongly flag it.
    Concatenation glue, escapes and quotes are removed before normalizing, so only
    a genuine paraphrase is reported.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    joined = re.sub(r"['\"`]\s*\+\s*['\"`]", "", raw)
    joined = joined.replace("\\n", " ").replace("\\t", " ")
    # Quotes/backticks are JavaScript syntax, but commas are content.  Removing
    # commas here made the source side disagree with ``missing_fragments`` and
    # guaranteed a false negative for every frozen thousands separator.
    return normalize(re.sub(r"['\"`]", "", joined))


def page_for(pages: list[Path], index: int) -> Path | None:
    for page in pages:
        match = PAGE_RE.match(page.name)
        if match and int(match.group(1)) == index:
            return page
    return None


def missing_fragments(slide: dict[str, Any], page_norm: str) -> list[dict[str, Any]]:
    """Planned strings absent from one page module, mirroring the QA codes."""
    missing: list[dict[str, Any]] = []
    candidates: list[tuple[str, str, str]] = []
    title = str(slide.get("title") or "").strip()
    if title:
        candidates.append(("title", "missing_title", title))
    claim = str(slide.get("claim") or slide.get("key_line") or "").strip()
    if claim:
        candidates.append(("claim", "missing_key_claim", claim))
    for fragment in compact_fragments(slide.get("slide_copy")):
        candidates.append(("slide_copy", "planned_copy_missing", fragment))
    for field, code, text in candidates:
        if len(normalize(text)) < MIN_FRAGMENT_CHARS:
            continue
        if normalize(text) not in page_norm:
            missing.append({"field": field, "code": code, "text": text})
    return missing


def check(spec: dict[str, Any], pages: list[Path]) -> dict[str, Any]:
    slides = [item for item in (spec.get("slides") or []) if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []
    per_slide: list[dict[str, Any]] = []

    for index, slide in enumerate(slides, start=1):
        page = page_for(pages, index)
        if page is None:
            issues.append({
                "slide": index,
                "page": None,
                "severity": "major",
                "code": "page_module_missing",
            })
            per_slide.append({
                "slide": index, "id": slide.get("id"), "page": None,
                "missing": [], "ok": False,
            })
            continue
        missing = missing_fragments(slide, source_text(page))
        per_slide.append({
            "slide": index,
            "id": slide.get("id"),
            "page": page.name,
            "missing": missing,
            "ok": not missing,
        })
        issues.extend({
            "slide": index,
            "page": page.name,
            "severity": "major",
            "code": item["code"],
            "field": item["field"],
            "text": item["text"],
        } for item in missing)

    return {
        "ok": not issues,
        "slide_count": len(slides),
        "page_count": len(pages),
        "blocker_count": len(issues),
        "issue_count": len(issues),
        "issues": issues,
        "slides": per_slide,
    }


def render(report: dict[str, Any], report_path: Path, max_items: int) -> str:
    total = report["blocker_count"]
    bad = [item for item in report["slides"] if not item["ok"]]
    state = "ok" if report["ok"] else "blocked"
    lines = [
        f"page_copy_fidelity: {state} — {total} planned string(s) missing across "
        f"{len(bad)} slide(s) | slides {report['slide_count']} pages {report['page_count']} "
        f"| report: {report_path}"
    ]
    limit = len(report["issues"]) if max_items <= 0 else max_items
    for item in report["issues"][:limit]:
        where = item.get("page") or "(no page module)"
        text = item.get("text") or ""
        lines.append(f"  slide {item['slide']} {where} — {item['code']}: {text}")
    hidden = len(report["issues"]) - min(len(report["issues"]), limit)
    if hidden > 0:
        lines.append(f"  … {hidden} more (full detail in {report_path})")
    if not report["ok"]:
        lines.append("  Copy each string above verbatim into the named page module, then re-run build.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--pages-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-items", type=int, default=12)
    args = parser.parse_args(argv)

    if not args.slide_spec.is_file():
        print(f"page_copy_fidelity: Slide Spec does not exist: {args.slide_spec}", file=sys.stderr)
        return 2
    pages = sorted(args.pages_dir.glob("*.js")) if args.pages_dir.is_dir() else []
    if not pages:
        # Nothing scaffolded yet: `assert_page_split` owns that contract, not this check.
        print("page_copy_fidelity: ok — no page modules to compare")
        return 0

    spec = load_structured(args.slide_spec)
    report = check(spec, pages)
    report.update({
        "slide_spec": str(args.slide_spec.resolve()),
        "slide_spec_sha256": sha256_file(args.slide_spec),
    })
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    report_path = args.output or (args.slide_spec.parent / "page-copy-fidelity.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        print(render(report, report_path, args.max_items), end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
