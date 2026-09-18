#!/usr/bin/env python3
"""Calibration style contract — one compact projection of the established visual
system (v0.15 Batch 4.2).

Problem this solves: an `initial` builder must follow the visual system the
calibration pages established, but it may not read other pages' modules
(`read_other_shard_page_modules: false` — a concurrent builder owns them), and
re-reading the full Art Direction is exactly the duplicated context Batch 2
removed. The contract is the bridge: once the independent calibration review is
green, the pipeline assembles ONE small JSON file that projects the style-bearing
Art Direction sections verbatim, the calibrated slides with their archetypes, the
calibration builder's own treatment summary (`calibration/style-summary.json`,
when it wrote one), and a fixed anti-repetition seed list. Builder packets embed
it as `calibration_style`; builders follow the contract instead of inferring a
style from page JS they are forbidden to read.

Assembly is deterministic — no model runs here — and every byte is traceable to
the hashed sources in `derived_from`.
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
from calibration_review import calibration_review  # noqa: E402
from page_brief import find_spec, load_optional, load_structured  # noqa: E402

STYLE_CONTRACT_NAME = "calibration-style-contract.json"
STYLE_SUMMARY_NAME = "calibration/style-summary.json"

# Art Direction sections that carry the visual system, projected verbatim.
_STYLE_SECTIONS = (
    "concept",
    "style_seed",
    "grammar",
    "color_system",
    "typography",
    "imagery",
    "icon_language",
    "chart_grammar",
    "component_language",
    "motif",
    "background_rhythm",
    "avoid",
)

# Policy-owned seed list: the systemic repetition failures a calibration is meant
# to prevent from spreading. The Art Direction's own `avoid` list is appended.
ANTI_REPETITION_SEED = [
    "do not wrap every page in the same container or card frame",
    "do not reuse the same left-right split on adjacent pages",
    "never repeat one title/body silhouette three pages running",
    "accent colour is for evidence and key numbers only, never page decoration",
    "one focal point per page; do not add competing emphasis blocks",
]

TREATMENT_KEYS = (
    "title_treatment",
    "body_treatment",
    "surface_language",
    "image_language",
    "chart_language",
    "rhythm",
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def style_summary(work_dir: Path) -> dict[str, Any] | None:
    """The calibration builder's own record of what it established (optional)."""
    loaded = load_optional(work_dir / STYLE_SUMMARY_NAME)
    if not isinstance(loaded, dict):
        return None
    established = loaded.get("established") if isinstance(loaded.get("established"), dict) else {}
    treatment = {key: str(established[key]) for key in TREATMENT_KEYS if established.get(key)}
    do_not_repeat = [str(item) for item in loaded.get("do_not_repeat") or [] if str(item).strip()]
    if not treatment and not do_not_repeat:
        return None
    return {"established": treatment, "do_not_repeat": do_not_repeat}


def build_style_contract(work_dir: Path, review: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Assemble the contract; None while calibration is absent or not green.

    `review` accepts a pre-computed `calibration_review()` result; when omitted,
    the check runs here — same single owner either way.
    """
    verdict = review if review is not None else calibration_review(work_dir)
    if not verdict.get("ok") or not verdict.get("required"):
        return None

    art = load_optional(work_dir / "art-direction.yaml")
    art = art if isinstance(art, dict) else {}
    style = {key: art[key] for key in _STYLE_SECTIONS if art.get(key) not in (None, [], {})}

    archetypes: dict[int, str] = {}
    spec_path = find_spec(work_dir)
    if spec_path is not None:
        try:
            spec = load_structured(spec_path)
        except Exception:
            spec = None
        if isinstance(spec, dict):
            for index, item in enumerate(spec.get("slides") or []):
                if isinstance(item, dict):
                    number = int(item.get("id") or index + 1)
                    if number in set(verdict.get("slides") or []):
                        archetypes[number] = archetype_of(item)

    treatment = style_summary(work_dir)
    anti_repetition = list(ANTI_REPETITION_SEED)
    anti_repetition += [str(item) for item in art.get("avoid") or [] if str(item).strip()]
    if treatment:
        anti_repetition += treatment["do_not_repeat"]

    return {
        "schema_version": "1.0",
        "status": "green",
        "calibration_slides": list(verdict.get("slides") or []),
        "calibrated_archetypes": archetypes,
        "style": style,
        "treatment": treatment["established"] if treatment else None,
        "anti_repetition": anti_repetition,
        "derived_from": {
            "art_direction_sha256": _sha256(work_dir / "art-direction.yaml"),
            "calibration_manifest_sha256": _sha256(
                work_dir / "calibration" / "calibration-manifest.json"
            ),
            "calibration_review_sha256": _sha256(
                work_dir / "calibration" / "calibration-visual-review.json"
            ),
        },
    }


def ensure_style_contract(
    work_dir: Path, review: dict[str, Any] | None = None
) -> Path | None:
    """Write the contract when calibration is green; return its path (or None)."""
    contract = build_style_contract(work_dir, review)
    if contract is None:
        return None
    path = work_dir / STYLE_CONTRACT_NAME
    current = load_optional(path)
    if current != contract:
        path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    contract = build_style_contract(args.work_dir)
    if args.json:
        print(json.dumps(contract, ensure_ascii=False, indent=2))
        return 0 if contract is not None else 2
    if contract is None:
        verdict = calibration_review(args.work_dir)
        print(f"style_contract: no contract — {verdict.get('reason') or 'calibration not green'}")
        return 2
    print(
        f"style_contract: green — slides {contract['calibration_slides']} "
        f"({', '.join(contract['calibrated_archetypes'].values()) or 'no archetypes'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
