#!/usr/bin/env python3
"""Deterministic slide archetypes and coverage-based calibration selection.

Batch 4.1 of the v0.15 pipeline-simplification series. Calibration exists to catch
a systemic visual choice before it is copied onto every page, so the sample must
cover as many DISTINCT visual grammars as its 2-3 pages allow — a cover, a data
page and a comparison page carry three different risk profiles, while three text
pages carry one. The old default ("cover + dense/data + representative visual",
i.e. art-direction `high_leverage_slides[:3]`) fixed the sample by page position
and could pick three pages sharing one grammar.

This module classifies every Slide Spec slide into an archetype from fields that
are already frozen in the spec — `kind`, `visual.layout_family`, `visual.emphasis`
— with no new spec field and no model judgement. Selection is deterministic:

1. group slides by archetype, each group represented by its first slide;
2. order the groups so a group containing a high-leverage slide (the art
   direction's own risk flags) comes first, then by first appearance;
3. take up to `limit` slides; pad with unused high-leverage slides, then the
   remaining deck order, so the sample is never thinner than the deck allows.

Every consumer — `builder_packet.default_calibration_slides`, the
`calibration_preview.py` fallback, and the `next`/`advance` spawn notes — reads
the same function, so the packet, the preview and the prose cannot diverge.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from page_brief import find_spec, high_leverage, load_structured  # noqa: E402

# Archetype vocabulary: the visual grammar a page exercises, not its story role.
ARCHETYPES = (
    "hero",
    "section",
    "narrative",
    "comparison",
    "data",
    "process",
    "diagram",
    "image-led",
    "quote",
    "reference",
    "closing",
)

# Top-level `layout` is a free string, so only the documented intent keywords
# (slide-spec.md "Layout Functional Mapping") map to archetypes; unknown strings
# degrade to narrative instead of guessing.
_LAYOUT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cover",), "hero"),
    (("comparison", "before-after"), "comparison"),
    (("timeline",), "process"),
    (("process", "loop-diagram", "workflow", "handoff", "team"), "process"),
    (("data", "chart", "survey", "dashboard"), "data"),
    (("diagram", "matrix", "architecture"), "diagram"),
    (("quote", "quotation"), "quote"),
    (("reference", "appendix"), "reference"),
    (("section",), "section"),
    (("closing",), "closing"),
)


def archetype_of(slide: dict[str, Any]) -> str:
    """Classify one Slide Spec slide into an archetype (never raises)."""
    if not isinstance(slide, dict):
        return "narrative"
    kind = str(slide.get("kind") or "").strip().lower()
    if kind == "cover":
        return "hero"
    if kind == "section-divider":
        return "section"
    if kind == "closing":
        return "closing"
    if kind in {"references", "appendix"}:
        return "reference"
    if kind == "quotation":
        return "quote"
    visual = slide.get("visual") if isinstance(slide.get("visual"), dict) else {}
    family = str(visual.get("layout_family") or "").strip().lower()
    if family == "comparison":
        return "comparison"
    if family == "dashboard":
        return "data"
    if family in {"process-path", "timeline"}:
        return "process"
    if family in {"architecture", "matrix"}:
        return "diagram"
    if family == "quote":
        return "quote"
    if family == "reference":
        return "reference"
    if family == "hero":
        return "hero"
    if family == "visual-dominant":
        return "image-led"
    layout = str(slide.get("layout") or "").strip().lower()
    for keywords, archetype in _LAYOUT_KEYWORDS:
        if any(keyword in layout for keyword in keywords):
            return archetype
    if str(visual.get("emphasis") or "").strip().lower() == "visual":
        return "image-led"
    return "narrative"


def coverage_slides(
    spec: dict[str, Any],
    leverage: list[int] | None = None,
    limit: int = 3,
) -> list[int]:
    """Calibration sample maximising distinct archetypes (see module docstring)."""
    total = sum(1 for item in (spec.get("slides") or []) if isinstance(item, dict))
    flagged = {int(n) for n in (leverage or []) if 1 <= int(n) <= total}
    # Each archetype group is represented by its first high-leverage slide when it
    # has one (the art direction's own risk flag keeps its seat), else its first slide.
    groups: dict[str, int] = {}
    order: list[str] = []
    for index, item in enumerate(spec.get("slides") or []):
        if not isinstance(item, dict):
            continue
        number = int(item.get("id") or index + 1)
        if number <= 0:
            continue
        archetype = archetype_of(item)
        if archetype not in groups:
            groups[archetype] = number
            order.append(archetype)
        elif number in flagged and groups[archetype] not in flagged:
            groups[archetype] = number
    ranked = sorted(
        order,
        key=lambda archetype: (
            0 if groups[archetype] in flagged else 1,
            0 if archetype != "narrative" else 1,
            order.index(archetype),
        ),
    )
    chosen: list[int] = []
    for archetype in ranked:
        if len(chosen) >= limit:
            break
        chosen.append(groups[archetype])
    for number in sorted(flagged):
        if len(chosen) >= limit:
            break
        if number not in chosen:
            chosen.append(number)
    for index in range(1, total + 1):
        if len(chosen) >= limit:
            break
        if index not in chosen:
            chosen.append(index)
    return sorted(chosen[:limit])


def archetype_map(spec: dict[str, Any]) -> dict[int, str]:
    """Slide number -> archetype, for inspection and coverage comparisons."""
    out: dict[int, str] = {}
    for index, item in enumerate(spec.get("slides") or []):
        if not isinstance(item, dict):
            continue
        number = int(item.get("id") or index + 1)
        if number > 0:
            out[number] = archetype_of(item)
    return out


def coverage_verdict(
    lost_count: int,
    lost: list[str],
    gained: list[str],
    leverage_missed: list[int],
) -> str:
    """One sentence a session can act on without re-deriving the rule."""
    if lost_count > 0:
        verdict = (
            f"rejected: covers {lost_count} fewer distinct archetype(s) than the default "
            f"(lost {', '.join(lost) or 'none'}); keep the default or add a page carrying one of them"
        )
    elif lost and gained:
        verdict = f"accepted: trades {', '.join(lost)} for {', '.join(gained)} — same coverage count"
    else:
        verdict = "accepted: same or better archetype coverage as the default"
    if leverage_missed:
        verdict += f"; misses high-leverage page(s) {leverage_missed}"
    return verdict


def coverage_report(
    spec: dict[str, Any],
    leverage: list[int] | None = None,
    candidate: list[int] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Compare a candidate calibration set against the deterministic default.

    2026-09-20: the `next --json` hand-over note projects a default packet and,
    in the same breath, tells the session to "pick 2-3 slides covering DISTINCT
    archetypes". With no rule for when an override is justified, a live session
    argued with itself for rounds over `[1,2,3]` vs `[1,7,9]` — the chart pages it
    cared about were missing from the default, but so was any way to tell whether
    swapping them in lost coverage. The rule is data now: keep the default unless
    the candidate covers at least as many distinct archetypes. Trading one grammar
    for another keeps the count and is a legitimate swap; dropping one is not.
    """
    total = sum(1 for item in (spec.get("slides") or []) if isinstance(item, dict))
    flagged = sorted({int(n) for n in (leverage or []) if 1 <= int(n) <= total})
    default = coverage_slides(spec, leverage, limit)
    chosen = sorted({int(n) for n in (candidate or default) if 1 <= int(n) <= total})[:limit]
    arch = archetype_map(spec)
    default_arch = sorted({arch[n] for n in default if n in arch})
    candidate_arch = sorted({arch[n] for n in chosen if n in arch})
    lost = sorted(set(default_arch) - set(candidate_arch))
    gained = sorted(set(candidate_arch) - set(default_arch))
    lost_count = len(default_arch) - len(candidate_arch)
    return {
        "default": default,
        "candidate": chosen,
        "default_archetypes": default_arch,
        "candidate_archetypes": candidate_arch,
        "archetype_count": {"default": len(default_arch), "candidate": len(candidate_arch)},
        # Count-based, not set-based: swapping a timeline for a chart trades one
        # grammar for another and still samples three.
        "keeps_coverage": len(candidate_arch) >= len(default_arch),
        "archetypes_lost": lost,
        "archetypes_gained": gained,
        "high_leverage": flagged,
        "high_leverage_missed": [n for n in flagged if n not in chosen],
        "verdict": coverage_verdict(lost_count, lost, gained, [n for n in flagged if n not in chosen]),
        "archetype_of": {str(n): arch[n] for n in sorted(arch)},
    }


def calibration_coverage(
    work_dir: Path,
    candidate: list[int] | None = None,
    limit: int = 3,
) -> dict[str, Any] | None:
    """Work-dir entry point for the coverage comparison (None when no spec)."""
    spec_path = find_spec(work_dir)
    if spec_path is None:
        return None
    try:
        spec = load_structured(spec_path)
    except Exception:
        return None
    if not isinstance(spec, dict):
        return None
    return coverage_report(spec, high_leverage(work_dir), candidate, limit)


def default_calibration_slides(work_dir: Path, limit: int = 3) -> list[int]:
    """Work-dir entry point shared by builder_packet and calibration_preview.

    Falls back to the art-direction `high_leverage_slides` when no readable spec
    exists, so a work-dir mid-plan keeps its old behaviour.
    """
    leverage = high_leverage(work_dir)
    spec_path = find_spec(work_dir)
    if spec_path is None:
        return leverage[:limit]
    try:
        spec = load_structured(spec_path)
    except Exception:
        return leverage[:limit]
    if not isinstance(spec, dict):
        return leverage[:limit]
    return coverage_slides(spec, leverage, limit)[:limit]
