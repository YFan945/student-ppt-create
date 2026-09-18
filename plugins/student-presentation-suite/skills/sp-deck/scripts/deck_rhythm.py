#!/usr/bin/env python3
"""Deck rhythm plan — per-page tone and composition family, planned not hoped
(v0.15 Batch 4.3).

`background_rhythm` already exists in every high-score Art Direction, and every
Slide Spec slide already carries a role — but nothing joined them, so page tone
was decided per-builder at build time and the deck's rhythm only became visible
when the critic counted repeated structures at QA. This module joins those two
frozen inputs into one small plan at `plan` time:

- `tone` per page: the Art Direction `background_rhythm` entry for the page's
  rhythm role (explicit beats default; `tone_source` records which);
- `family` per page: a stable letter per distinct archetype (Batch 4.1's
  classification — same grammar, same letter), so builders see which pages share
  a visual grammar and which neighbours must differ;
- `warnings`: any run of three consecutive pages in one family. The plan cannot
  force variety by itself — the observed outcome is still judged by the critic's
  `repetitive_structure_run` gate — but the builders are told here, at generation
  time, where they must deliberately vary the composition instead of discovering
  the repetition in a repair round (the owner's repair-budget stance: fix problems
  at generation time, not after the gate).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from calibration_archetypes import archetype_of  # noqa: E402
from page_brief import find_spec, load_optional, load_structured  # noqa: E402

RHYTHM_NAME = "deck-rhythm.json"

# Slide `role`/`kind` → Art Direction `background_rhythm` role.
_ROLE_TO_RHYTHM = {
    "opening": "cover",
    "evidence": "evidence",
    "conclusion": "closing",
    "qa": "closing",
    "closing": "closing",
    "cover": "cover",
    "section-divider": "section",
}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rhythm_role(item: dict[str, Any]) -> str:
    return _ROLE_TO_RHYTHM.get(str(item.get("kind") or "").strip().lower()) or _ROLE_TO_RHYTHM.get(
        str(item.get("role") or "").strip().lower()
    ) or "content"


def build_rhythm(work_dir: Path) -> dict[str, Any] | None:
    """Assemble the plan; None when there is no readable spec."""
    spec_path = find_spec(work_dir)
    if spec_path is None:
        return None
    try:
        spec = load_structured(spec_path)
    except Exception:
        return None
    if not isinstance(spec, dict) or not (spec.get("slides") or []):
        return None

    art = load_optional(work_dir / "art-direction.yaml")
    art = art if isinstance(art, dict) else {}
    tone_by_role: dict[str, str] = {}
    for entry in art.get("background_rhythm") or []:
        if isinstance(entry, dict) and entry.get("role") and entry.get("mode"):
            tone_by_role[str(entry["role"]).strip().lower()] = str(entry["mode"]).strip().lower()

    families: dict[str, str] = {}
    pages: list[dict[str, Any]] = []
    for index, item in enumerate(spec.get("slides") or []):
        if not isinstance(item, dict):
            continue
        number = int(item.get("id") or index + 1)
        archetype = archetype_of(item)
        if archetype not in families:
            families[archetype] = chr(ord("A") + len(families) % 26)
        role = rhythm_role(item)
        pages.append(
            {
                "slide": number,
                "role": str(item.get("role") or item.get("kind") or "content"),
                "archetype": archetype,
                "family": families[archetype],
                "tone": tone_by_role.get(role) or tone_by_role.get("content") or "light",
            }
        )
    tone_source = "art_direction" if tone_by_role else "default"

    warnings: list[str] = []
    run: list[dict[str, Any]] = []
    for page in pages + [None]:  # sentinel flushes a run that ends at the deck's tail
        if page is not None and run and page["family"] == run[-1]["family"]:
            run.append(page)
            continue
        if len(run) >= 3:
            first, last = run[0]["slide"], run[-1]["slide"]
            warnings.append(
                f"slides {first}-{last} share composition family {run[0]['family']}: vary the "
                "structure deliberately — the critic's repetitive_structure_run gate judges the "
                "observed outcome"
            )
        run = [page] if page is not None else []

    return {
        "schema_version": "1.0",
        "tone_source": tone_source,
        "families": {archetype: letter for archetype, letter in families.items()},
        "pages": pages,
        "warnings": warnings,
        "derived_from": {
            "art_direction_sha256": _sha256(work_dir / "art-direction.yaml"),
            "slide_spec_sha256": _sha256(spec_path) if spec_path else None,
        },
    }


def ensure_rhythm(work_dir: Path) -> Path | None:
    """Write the plan at plan-time; idempotent, returns the path (or None)."""
    plan = build_rhythm(work_dir)
    if plan is None:
        return None
    path = work_dir / RHYTHM_NAME
    current = load_optional(path)
    if current != plan:
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def page_rhythm(work_dir: Path) -> dict[int, dict[str, Any]]:
    """Loaded plan keyed by slide number, for packet projection."""
    plan = load_optional(work_dir / RHYTHM_NAME)
    if not isinstance(plan, dict):
        return {}
    pages = plan.get("pages") if isinstance(plan.get("pages"), list) else []
    result: dict[int, dict[str, Any]] = {}
    for position, page in enumerate(pages):
        if isinstance(page, dict) and isinstance(page.get("slide"), int):
            neighbours = {}
            if position > 0 and isinstance(pages[position - 1], dict):
                neighbours["prev_family"] = pages[position - 1].get("family")
                neighbours["prev_tone"] = pages[position - 1].get("tone")
            if position + 1 < len(pages) and isinstance(pages[position + 1], dict):
                neighbours["next_family"] = pages[position + 1].get("family")
                neighbours["next_tone"] = pages[position + 1].get("tone")
            result[page["slide"]] = {
                "tone": page.get("tone"),
                "family": page.get("family"),
                **neighbours,
            }
    return result


def rhythm_warnings(work_dir: Path) -> list[str]:
    plan = load_optional(work_dir / RHYTHM_NAME)
    if isinstance(plan, dict) and isinstance(plan.get("warnings"), list):
        return [str(item) for item in plan["warnings"]]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    plan = build_rhythm(args.work_dir)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan is not None else 2
    if plan is None:
        print("deck_rhythm: no readable Slide Spec — nothing to plan")
        return 2
    print(f"deck_rhythm: {len(plan['pages'])} pages, {len(plan['families'])} families, "
          f"{len(plan['warnings'])} run warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
