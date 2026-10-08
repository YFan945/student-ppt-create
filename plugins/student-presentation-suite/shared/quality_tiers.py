"""The single decision table for delivery tiers (fast / standard / rigorous).

Before tiers, every consumer re-derived the same answers from
``meta.quality_level == "high-score"``: dispatch, the build gate, the quality
gate and two v0.8 gates each had their own branch — and a missing value silently
took the expensive calibration path. One table here; consumers read policy keys.

Tier semantics (owner's spec):

- ``fast`` (default for new intake): one cover-plus-content look, then the
  rest of the deck, then one final visual review. Subjective scores, style
  majors and regressions are advisory; only critical findings and
  deterministic failures block.
- ``standard``: one calibration sample, then full generation (shards <= 2).
  Subjective score floors and style majors stay advisory. Decks at or below
  ``STANDARD_CALIBRATION_PAGE_LINE`` still look at a cover plus one content
  page before the rest is written. Dispatch and build both consult
  :func:`calibration_enabled`.
- ``rigorous``: the high-score path (calibration <= 2 rounds until green,
  shards <= 3). Decks at or below ``STANDARD_CALIBRATION_PAGE_LINE`` use the
  same two-page look. Longer decks keep the archetype sample. Style-major
  and regression findings still block, including a run of three identical
  composition moves. Subjective score floors (hierarchy, focal point,
  composition, visual interest) are recorded and do not block delivery.
  Unreadable critical findings still do.

Legacy values keep working as aliases: ``basic`` -> fast, ``high-score`` ->
rigorous. A missing or unknown value is fast — ordinary tasks stopped paying
the high-assurance path by accident.
"""

from __future__ import annotations

from typing import Any

TIERS = ("fast", "standard", "rigorous")
LEGACY_ALIASES = {"basic": "fast", "high-score": "rigorous"}
DEFAULT_TIER = "fast"
# D1: fast stays single-builder for small decks (the coordination round-trips
# cost more than one builder's extra context), but a long deck split across one
# builder inflates that instance's context past the point of no return (the
# 2026-09-18 live instance grew to 699K). Above this page count fast sharding
# to 2 is the cheaper shape.
FAST_SHARD_PAGE_THRESHOLD = 8
# Owner-approved speed line (2026-09-27): past this many pages fast shards to
# 3 — page work wall clock scales ~1/shards and max_parallel_builders is
# already 3, so the extra coordination round is net-positive from here.
FAST_SHARD_SECOND_LINE = 14
# Decks at or below this page count, and every fast deck, look at a cover plus
# one content page before the rest is written. Longer standard/rigorous decks
# keep the wider archetype sample.
STANDARD_CALIBRATION_PAGE_LINE = 8

_POLICY_ROWS = {
    "fast": {
        "calibration": True,
        "calibration_max_rounds": 0,
        "shard_cap": 1,
        "block_structural": False,
        "block_style_major": False,
        "block_regression": False,
        "block_aesthetic_low": False,
        "score_floor": 5.0,
        "strict_v08": False,
    },
    "standard": {
        "calibration": True,
        "calibration_max_rounds": 1,
        "shard_cap": 2,
        "block_structural": False,
        "block_style_major": False,
        "block_regression": False,
        # 主观分（hierarchy / focal_point / composition / visual_interest）三档都只记录。
        # 模型看图就能判断好不好看；无法阅读的 critical 与确定性失败仍然阻断。
        "block_aesthetic_low": False,
        "score_floor": 5.0,
        "strict_v08": False,
    },
    "rigorous": {
        "calibration": True,
        "calibration_max_rounds": 2,
        "shard_cap": 3,
        "block_structural": False,
        "block_style_major": True,
        "block_regression": True,
        "block_aesthetic_low": False,
        "score_floor": 6.0,
        "strict_v08": True,
    },
}


def normalize(value: Any) -> str:
    """Map any stored quality_level to a canonical tier name."""
    raw = str(value or "").strip().lower()
    if raw in TIERS:
        return raw
    return LEGACY_ALIASES.get(raw, DEFAULT_TIER)


def tier_policy(value: Any) -> dict[str, Any]:
    """The policy keys every consumer branches on, for one quality_level value."""
    tier = normalize(value)
    return {"tier": tier, "raw": value, **_POLICY_ROWS[tier]}


def effective_shard_cap(value: Any, page_count: int | None = None) -> int:
    """The shard cap for a concrete deck: fast splits only above the page line.

    standard/rigorous keep their table caps unconditionally; fast's cap of 1
    becomes 2 above FAST_SHARD_PAGE_THRESHOLD pages and 3 above
    FAST_SHARD_SECOND_LINE pages.
    """
    policy = tier_policy(value)
    cap = int(policy["shard_cap"])
    if policy["tier"] != "fast" or page_count is None:
        return cap
    if page_count > FAST_SHARD_SECOND_LINE:
        return 3
    if page_count > FAST_SHARD_PAGE_THRESHOLD:
        return min(cap + 1, 2)
    return cap


def uses_preview_pair(value: Any, page_count: int | None = None) -> bool:
    """Cover plus one content page, instead of the wider archetype sample."""
    if tier_policy(value)["tier"] == "fast":
        return True
    return page_count is not None and page_count <= STANDARD_CALIBRATION_PAGE_LINE


def calibration_enabled(value: Any, page_count: int | None = None) -> bool:
    """Whether a concrete deck looks at sample pages before the rest are written.

    Every tier does. Fast decks and decks at or below
    ``STANDARD_CALIBRATION_PAGE_LINE`` use a cover plus one content page
    (:func:`uses_preview_pair`). Longer standard and rigorous decks keep the
    archetype sample. ``page_count`` is the frozen spec's total slide count.
    """
    del page_count
    return bool(tier_policy(value)["calibration"])
