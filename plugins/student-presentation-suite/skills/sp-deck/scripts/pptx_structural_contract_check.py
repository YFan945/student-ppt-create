#!/usr/bin/env python3
"""Deterministic structural-contract gate: the layout's promise must be realized.

layout-library.json `requirements` already declares what each layout needs
(`asset: required`, `data: required`, `items: [min, max]`), and plan/copy-fit
check the SPEC side — but nothing checked the BUILT page: a `visual-*` layout
that rendered zero pictures, or a `data-*` layout with no chart, table or even a
digit, sailed through pre-QA and surfaced only as a critic round (or worse, as
"aesthetically fine but structurally not the promised layout"). This gate reads
each frozen-spec slide's declared layout, resolves its requirements, and checks
deterministic observables in the PPTX:

- zero realization (a required feature completely absent) is critical on every
  tier — deterministic failures block fast too;
- weak realization (a data page promised a chart/table instrument but rendered
  only text numbers) is fast-advisory / standard+ major, so the tier decides
  whether the flattening blocks.

Only what is deterministically observable is checked: pictures, chart parts,
tables and digit-bearing text runs. Quote placement and free-form composition
stay with the visual critic. Layouts (or layout ids) without checkable
requirements are skipped and reported, never guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.quality_tiers import tier_policy  # noqa: E402

DEFAULT_LIBRARY = ROOT / "skills" / "sp-deck" / "references" / "layout-library.json"
# Silhouettes whose data requirement is a rendering INSTRUMENT (chart/table), not
# just numbers: rendering the same numbers as plain text is weak realization.
INSTRUMENT_SILHOUETTES = {"chart-takeaway", "chart-sidebar", "small-multiples", "table-highlight"}
SLIDE_PART_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
CHART_REL_RE = re.compile(r'Target="\.\./charts/(chart\d+\.xml)"')
TEXT_RUN_RE = re.compile(r"<a:t>([^<]*)</a:t>")
DIGIT_RE = re.compile(r"[0-9０-９]")


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def normalize_silhouette(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def slide_observables(archive: zipfile.ZipFile, slide_no: int) -> dict[str, Any]:
    """What the built page deterministically contains."""
    name = f"ppt/slides/slide{slide_no}.xml"
    text = archive.read(name).decode("utf-8", "replace") if name in archive.namelist() else ""
    rels_name = f"ppt/slides/_rels/slide{slide_no}.xml.rels"
    rels = archive.read(rels_name).decode("utf-8", "replace") if rels_name in archive.namelist() else ""
    runs = TEXT_RUN_RE.findall(text)
    return {
        "pictures": len(re.findall(r"<p:pic[\s/>]", text)),
        "tables": len(re.findall(r"<a:tbl>", text)),
        "charts": len(CHART_REL_RE.findall(rels)),
        "digit_runs": sum(1 for run in runs if DIGIT_RE.search(run)),
        "text_runs": len(runs),
    }


def check_pptx(
    pptx: Path,
    slide_spec: Path,
    *,
    layout_library: Path = DEFAULT_LIBRARY,
    quality: Any = "fast",
) -> dict[str, Any]:
    spec = load_structured(slide_spec)
    library = load_structured(layout_library)
    layouts = {
        str(item.get("id")): item
        for item in library.get("layouts") or []
        if isinstance(item, dict) and item.get("id")
    }
    weak_severity = "minor" if tier_policy(quality)["tier"] == "fast" else "major"

    issues: list[dict[str, Any]] = []
    checked: list[int] = []
    skipped: list[dict[str, Any]] = []
    with zipfile.ZipFile(pptx, "r") as archive:
        rendered_slides = {
            int(match.group(1))
            for name in archive.namelist()
            if (match := SLIDE_PART_RE.match(name))
        }
        for slide in spec.get("slides") or []:
            if not isinstance(slide, dict):
                continue
            slide_no = slide.get("id")
            layout_id = str(slide.get("layout") or "").strip()
            layout = layouts.get(layout_id)
            if layout is None:
                skipped.append({"slide": slide_no, "layout": layout_id, "reason": "layout id not in library"})
                continue
            requirements = layout.get("requirements") or {}
            observable_features = {
                key: key in requirements
                for key in ("asset", "data", "quote")
            }
            if not any(observable_features.values()):
                skipped.append({"slide": slide_no, "layout": layout_id, "reason": "no deterministic requirement"})
                continue
            if slide_no not in rendered_slides:
                # build refuses unimplemented scaffold pages before this gate;
                # a missing slide part here is a packaging defect, not a layout one
                skipped.append({"slide": slide_no, "layout": layout_id, "reason": "slide part absent"})
                continue
            checked.append(int(slide_no))
            observed = slide_observables(archive, int(slide_no))

            if requirements.get("asset") == "required" and observed["pictures"] == 0:
                issues.append({
                    "slide": int(slide_no),
                    "severity": "critical",
                    "code": "asset_required_missing",
                    "message": (
                        f"Slide {slide_no} declares layout {layout_id} (asset: required) but "
                        "renders no picture — the layout's structural promise is unrealized."
                    ),
                    "layout": layout_id,
                    "observed": observed,
                })
            if requirements.get("data") == "required":
                has_instrument = bool(observed["charts"] or observed["tables"])
                has_numbers = bool(observed["digit_runs"])
                if not has_instrument and not has_numbers:
                    issues.append({
                        "slide": int(slide_no),
                        "severity": "critical",
                        "code": "data_required_missing",
                        "message": (
                            f"Slide {slide_no} declares layout {layout_id} (data: required) but renders "
                            "no chart, table or numeric text — the data promise is unrealized."
                        ),
                        "layout": layout_id,
                        "observed": observed,
                    })
                elif (
                    not has_instrument
                    and normalize_silhouette(layout.get("silhouette")) in INSTRUMENT_SILHOUETTES
                ):
                    issues.append({
                        "slide": int(slide_no),
                        "severity": weak_severity,
                        "code": "data_instrument_missing",
                        "message": (
                            f"Slide {slide_no} declares layout {layout_id} whose silhouette promises a "
                            "chart/table instrument, but the data renders as text numbers only."
                        ),
                        "layout": layout_id,
                        "observed": observed,
                    })
    return {
        "ok": not any(item["severity"] in {"critical", "major"} for item in issues),
        "pptx": str(pptx.resolve()),
        "slide_spec": str(slide_spec.resolve()),
        "quality_level": tier_policy(quality)["tier"],
        "weak_severity": weak_severity,
        "checked_slides": sorted(checked),
        "skipped_slides": skipped,
        "issue_count": len(issues),
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--slide-spec", type=Path, required=True)
    parser.add_argument("--layout-library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument(
        "--quality",
        choices=["fast", "standard", "rigorous", "basic", "high-score"],
        default="fast",
        help="delivery tier (legacy basic/high-score accepted); weak realization blocks outside fast",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.pptx.is_file():
        raise SystemExit(f"PPTX does not exist: {args.pptx}")
    if not args.slide_spec.is_file():
        raise SystemExit(f"Slide Spec does not exist: {args.slide_spec}")
    report = check_pptx(
        args.pptx, args.slide_spec,
        layout_library=args.layout_library, quality=args.quality,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json or not args.output:
        print(payload, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
