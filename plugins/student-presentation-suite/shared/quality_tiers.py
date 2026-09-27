"""The single decision table for delivery tiers (fast / standard / rigorous).

Before tiers, every consumer re-derived the same answers from
``meta.quality_level == "high-score"``: dispatch, the build gate, the quality
gate and two v0.8 gates each had their own branch — and a missing value silently
took the expensive calibration path. One table here; consumers read policy keys.

Tier semantics (owner's spec):

- ``fast`` (default for new intake): one-shot build + one final visual review.
  No calibration. Subjective scores, style majors and regressions are advisory;
  only critical findings and deterministic failures block.
- ``standard``: one calibration sample + independent review, then full
  generation (shards <= 2). Structural lows (hierarchy / focal_point) block;
  style majors stay advisory. Short decks (at or below
  ``STANDARD_CALIBRATION_PAGE_LINE``) skip calibration: the whole-deck rework
  that calibration insures against is bounded there, while the calibration
  round (builder + preview + independent critic) costs proportionally more —
  dispatch and build both consult :func:`calibration_enabled`.
- ``rigorous``: the full high-score path (calibration <= 2 rounds until green,
  shards <= 3, structural + style-major + regression findings block, per-slide
  floor 6.0).

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
# Owner-approved speed line (2026-09-27): standard decks at or below this page
# count skip the calibration round entirely. Calibration exists to stop a bad
# visual system from being copied onto every page (CD-9); on a short deck that
# rework is bounded by the page line, while the calibration round (builder +
# preview + independent critic) is a fixed extra round-trip. Rigorous keeps
# calibration unconditionally — its contract buys assurance, not speed.
STANDARD_CALIBRATION_PAGE_LINE = 8

_POLICY_ROWS = {
    "fast": {
        "calibration": False,
        "calibration_max_rounds": 0,
        "shard_cap": 1,
        "block_structural": False,
        "block_style_major": False,
        "block_regression": False,
        "score_floor": 5.0,
        "strict_v08": False,
    },
    "standard": {
        "calibration": True,
        "calibration_max_rounds": 1,
        "shard_cap": 2,
        "block_structural": True,
        "block_style_major": False,
        "block_regression": False,
        "score_floor": 5.0,
        "strict_v08": False,
    },
    "rigorous": {
        "calibration": True,
        "calibration_max_rounds": 2,
        "shard_cap": 3,
        "block_structural": True,
        "block_style_major": True,
        "block_regression": True,
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


def calibration_enabled(value: Any, page_count: int | None = None) -> bool:
    """Whether a concrete deck runs the calibration round at all.

    fast never calibrates. rigorous always does. standard does unless the deck
    is at or below STANDARD_CALIBRATION_PAGE_LINE pages. ``page_count`` is the
    FROZEN spec's total slide count — not the count of still-scaffolded pages —
    so a session resumed mid-calibration keeps the decision it planned with.
    """
    policy = tier_policy(value)
    if not policy["calibration"]:
        return False
    if policy["tier"] == "standard" and page_count is not None:
        return page_count > STANDARD_CALIBRATION_PAGE_LINE
    return True
