"""Quality labels and legacy standalone review settings.

Main-session production never calibrates or shards, for any quality level.
Legacy aliases remain readable. Score settings apply only to optional old
standalone review utilities, not the production tools.
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
        "calibration": False,
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
        "calibration": False,
        "calibration_max_rounds": 0,
        "shard_cap": 1,
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
        "calibration": False,
        "calibration_max_rounds": 0,
        "shard_cap": 1,
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
    """Historical accessor; production has one main author at every length."""
    del value, page_count
    return 1


def uses_preview_pair(value: Any, page_count: int | None = None) -> bool:
    """Sample calibration was removed."""
    del value, page_count
    return False


def calibration_enabled(value: Any, page_count: int | None = None) -> bool:
    """All tiers use direct full-deck production."""
    del value, page_count
    return False
