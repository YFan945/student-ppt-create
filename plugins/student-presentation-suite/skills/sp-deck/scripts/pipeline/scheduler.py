from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import builder_packet as _packet  # noqa: E402
import generator_scaffold as _scaffold  # noqa: E402

from pipeline.core import (  # noqa: E402
    RefusedError,
    load_json,
)


def page_files_by_slide(work_dir: Path) -> dict[int, str]:
    """slide id -> page module filename, read from the scaffolded layout."""
    pages = work_dir / "pages"
    result: dict[int, str] = {}
    for path in _scaffold.listed_page_files(pages):
        match = _scaffold.PAGE_NAME_RE.match(path.name)
        if match:
            result[int(match.group(1))] = path.name
    return result


def remaining_scaffold_slides(work_dir: Path) -> list[int]:
    """Slides whose page module still carries the stub marker (never implemented)."""
    pages = work_dir / "pages"
    by_name = {path.name: path for path in _scaffold.listed_page_files(pages)}
    stubs = set(_scaffold.scaffolded_pages(list(by_name.values())))
    result: list[int] = []
    for name, path in by_name.items():
        if name not in stubs:
            continue
        match = _scaffold.PAGE_NAME_RE.match(path.name)
        if match:
            result.append(int(match.group(1)))
    return sorted(result)


def slides_named_in_reports(work_dir: Path, names: tuple[str, ...]) -> list[int]:
    """Slide numbers carried by the current blocker reports.

    Reports without slide numbers (a deck-level finding) contribute nothing: a shard plan
    built from "unknown pages" would send builders at the wrong targets, so the caller
    falls back to a single builder that reads the reports itself.
    """
    found: set[int] = set()
    for name in names:
        path = work_dir / name
        if not path.is_file():
            continue
        try:
            report = load_json(path)
        except Exception:
            continue
        for item in (report.get("problems") or []) + (report.get("issues") or []):
            if not isinstance(item, dict):
                continue
            # Blockers name pages either singly (`slide`) or as a run
            # (`slides: [4, 5, 6]` — e.g. repetitive_structure_pair/run).
            slide = item.get("slide")
            if isinstance(slide, int) and not isinstance(slide, bool) and slide > 0:
                found.add(slide)
            group = item.get("slides")
            if isinstance(group, list):
                for value in group:
                    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                        found.add(value)
    return sorted(found)


def builder_shards(
    slides: list[int], work_dir: Path, *, max_parallel: int | None = None
) -> dict[str, Any] | None:
    """Split the target pages across isolated builder instances (wall clock only).

    Wall clock is turns x per-turn latency, and nothing about the gate set changes that:
    2026-09-18 measured every gate in the suite at 150s total (1.7% of the run) while the
    critical path was 519 model round-trips. Independent builders hold independent
    contexts and turn sequences, so sharding divides the build phase's wall clock without
    touching a single gate. Shard count and grouping come from builder_packet.split_shards
    (one shard policy: complexity-balanced, tier-capped, disjoint by construction), which
    is also what keeps two builders off the same page module.
    """
    groups = _packet.split_shards(slides, work_dir, max_parallel=max_parallel)
    if not groups:
        return None
    by_slide = page_files_by_slide(work_dir)
    shards: list[dict[str, Any]] = [
        {
            "shard": group["shard"],
            "slides": list(group["slides"]),
            "pages": [by_slide[slide] for slide in group["slides"] if slide in by_slide],
        }
        for group in groups
    ]
    known = sorted({slide for group in groups for slide in group["slides"]})
    return {
        "parallel": len(shards),
        "slides": known,
        "shards": shards,
        "spawn": (
            f"spawn all {len(shards)} shards in ONE message so they run concurrently, each without a "
            "`name`, each with its own slide ids and its own speaker-notes fragment "
            "(speaker-notes-shard-<N>.md). Never give one builder another shard's slides."
        ),
        "why": (
            "wall clock is turns x round-trip latency and every gate in the suite costs ~2.5s, so the "
            "only lever that does not touch a gate is running the page work concurrently"
        ),
    }


def merge_speaker_note_shards(work_dir: Path) -> list[str]:
    """Concatenate per-shard notes fragments into speaker-notes.md in page order.

    Parallel builders cannot each write speaker-notes.md without losing the others' text,
    so each shard writes its own fragment and the pipeline assembles the readable copy.
    A single-builder run produces no fragments and nothing changes.
    """
    fragments = sorted(work_dir.glob("speaker-notes-shard-*.md"))
    if not fragments:
        return []
    target = work_dir / "speaker-notes.md"
    parts: list[str] = []
    # Repair rounds may re-shard pages.  Concatenating files by shard name then
    # duplicates a page whenever its new shard differs from the initial round.
    # Parse page sections and let the most recently written fragment replace the
    # older copy; only legacy fragments without page headings use concatenation.
    # Level-2 headings only, and no bare-dot separator: a body subhead like
    # `## 2. 方法` must never register as a page section and erase page 2.
    section_re = re.compile(
        r"(?m)^##\s+(?:(?:Slide|幻灯片)\s*)?(?:第\s*)?(?P<slide>\d+)"
        r"(?:\s*页|\s*[-—:：·])[^\n]*\n"
    )
    by_slide: dict[int, tuple[int, int, str, str]] = {}
    parsed_any = False
    # The previous merged file is the durable per-page baseline. If a repair
    # builder overwrites an existing shard with only its target page, pages that
    # used to share that shard still survive here. Fresh fragments win by mtime.
    sources = ([target] if target.is_file() else []) + fragments
    for path in sources:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        matches = list(section_re.finditer(text))
        if not matches:
            if path == target:
                continue
            parts.append(text)
            continue
        parsed_any = True
        stamp = path.stat().st_mtime_ns
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            slide = int(match.group("slide"))
            section = text[match.start():end].strip()
            previous = by_slide.get(slide)
            priority = 1 if path != target else 0
            marker = (stamp, priority, path.name)
            if previous is None or marker > (previous[0], previous[1], previous[2]):
                by_slide[slide] = (stamp, priority, path.name, section)
    if parsed_any:
        # Structured merge must not silently drop pages: every scaffolded page
        # needs notes, and a lost page is invisible until delivery. Legacy
        # unheaded fragments cannot be counted, so only the parsed path asserts.
        known = set(page_files_by_slide(work_dir))
        if known:
            missing = sorted(known - set(by_slide))
            if missing:
                raise RefusedError(
                    "speaker-notes fragments dropped pages "
                    + ", ".join(map(str, missing))
                    + " — restore them in a shard fragment or the previous speaker-notes.md before build"
                )
        ordered = [by_slide[slide][3] for slide in sorted(by_slide)]
        parts = ["# 演讲稿", *ordered, *parts]
    if not parts:
        return []
    target.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return [str(path) for path in fragments]


def builder_instance_reuse(work_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Whether ONE builder instance served more than one repair round.

    Measured cost of a never-reset instance (2026-09-18 live): context grew 8.7K -> 699K
    across three rounds, 212 of its 261 requests ran at >=200K, and at the end three
    trivial requests cost 2.1M tokens. Measured counterfactual: resetting per round alone
    takes that instance from 98.7M to 80.9M — round 1 grows to 606K inside itself, which a
    reset cannot fix; the larger saving is not letting a full-deck rework happen at all.

    The pipeline sees rounds; the hook sees instance identity (`.guard/builder-*.json`).
    Cross-referencing them is what turns "spawn a fresh builder each round" from prose
    the main session may skip into a number it can read.
    """
    guard = work_dir.parent / ".guard"
    if not guard.is_dir():
        return None
    rounds = [
        entry
        for entry in (manifest.get("history") or [])
        if isinstance(entry, dict) and entry.get("command") == "repair" and entry.get("at")
    ]
    if len(rounds) < 2:
        return None
    round_times = sorted(str(entry["at"]) for entry in rounds)

    reused: list[dict[str, Any]] = []
    for path in sorted(guard.glob("builder-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("work_ids") and work_dir.name not in data["work_ids"]:
            continue
        first = str(data.get("first_write_at") or "")
        last = str(data.get("last_write_at") or "")
        if not first or not last:
            continue
        spanned = [stamp for stamp in round_times if first <= stamp <= last]
        if len(spanned) >= 2:
            reused.append({
                "agent_id": data.get("agent_id"),
                "writes": data.get("writes"),
                "first_write_at": first,
                "last_write_at": last,
                "repair_rounds_spanned": len(spanned),
            })
    if not reused:
        return None
    return {
        "instances": reused,
        "advice": (
            "one builder instance served several repair rounds, so every request in the later "
            "rounds paid for the context the earlier ones left behind. Spawn a NEW "
            "student-presentation-suite:presentation-builder for each repair round (do not "
            "SendMessage the previous one) and pass it the QA report paths plus a one-line "
            "summary — it re-reads what it needs."
        ),
    }


def packet_fallbacks(work_dir: Path) -> list[dict[str, Any]]:
    """Packet-generation failures recorded for this work dir (observability log)."""
    path = work_dir / _packet.PACKET_DIR_NAME / "fallbacks.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_packet_fallback(work_dir: Path, mode: str, error: str) -> int:
    log = packet_fallbacks(work_dir)
    log.append({"at": datetime.now(UTC).isoformat(), "mode": mode, "error": str(error)[:300]})
    path = work_dir / _packet.PACKET_DIR_NAME / "fallbacks.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # the fallback log must never break dispatch either
    return len(log)


def observe_packet_failure(work_dir: Path, payload: dict[str, Any], mode: str, exc: Exception) -> None:
    """Packet generation failed: dispatch continues, but NOT silently.

    "never breaks dispatch" must not mean "the cost optimization quietly turned
    off and nobody can tell" — the failure is reported in the payload and appended
    to builder-packets/fallbacks.json so a benchmark can see a builder fell back
    to the legacy full-read path.
    """
    count = record_packet_fallback(work_dir, mode, str(exc))
    # The packet round failed, so any builder spawned on the fallback path runs
    # WITHOUT packet enforcement — clear it, the fallback must stay usable.
    _packet.clear_active_round(work_dir)
    payload["builder_packet_status"] = "failed"
    payload["builder_packet_error"] = str(exc)[:300]
    payload["packet_fallback_count"] = count


