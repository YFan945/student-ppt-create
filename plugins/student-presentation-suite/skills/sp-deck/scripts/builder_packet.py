#!/usr/bin/env python3
"""Generate the Builder Packet: the isolated builder's complete task input.

Batch 2 of the v0.15 pipeline-simplification series (context projection). Today a
spawned builder re-reads the same frozen inputs its siblings read — manifest, Slide
Spec, Art Direction, page briefs, QA reports — so three parallel builders pay for
three copies of one context. This module projects exactly the slice one builder
instance needs into a single JSON file:

    builder-packets/calibration.json
    builder-packets/initial-shard-01.json
    builder-packets/repair-shard-02.json

The builder's entry contract (agents/presentation-builder.md) becomes: the packet
path is the task input; everything it covers — assigned slides, style, evidence,
sources, blockers, allowed files, forbidden actions — must not be re-read from the
work directory. `next --json` generates the packets automatically when it routes to
a builder spawn; this CLI also runs standalone for a calibration slide override.

The projection is derived from the same sources the gates judge:
- per-slide requirements come from `pptx_actual_content_check.planned_requirements()`
  (byte-identical to what the actual-content gate compares against);
- evidence/sources come from the frozen spec ledger and research pack;
- repair blockers come from the QA / pre-QA reports on disk;
- `must_not_regress` comes from `visual-score-history.json` (the R3 regression rail).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import generator_scaffold as _scaffold  # noqa: E402
import pptx_actual_content_check as actual_check  # noqa: E402
from calibration_archetypes import archetype_of  # noqa: E402
from calibration_review import STYLE_SUMMARY_KEYS  # noqa: E402
from page_brief import (  # noqa: E402
    deck_state,
    evidence_for_slide,
    find_spec,
    high_leverage,
    load_optional,
    load_structured,
    page_modules,
    slide_number,
    sources_by_id,
)

PACKET_DIR_NAME = "builder-packets"
ACTIVE_ROUND_NAME = "active-round.json"
SCORE_HISTORY_NAME = "visual-score-history.json"
FORBIDDEN_ACTIONS = [
    "build",
    "render",
    "qa",
    "research",
    "calibration_preview",
    "soffice",
]
NO_REREAD = (
    "this packet is the complete task input for its assigned slides: do not re-read "
    "slide-spec-compiled.yaml, art-direction.yaml, research-pack.json, build-manifest.json "
    "or the QA reports it projects — every field below is byte-derived from those sources"
)

# Shard policy has ONE owner: references/pipeline-contract.json. This module must not
# keep its own copy of the numbers — when the contract changes, the pipeline's
# `builder_shards` and this generator's `split_shards` must move together, or the
# packet shards and the spawn shards silently diverge. Same clamping as ppt_pipeline.
_CONTRACT_PATH = HERE.parents[2] / "references" / "pipeline-contract.json"


def _contract_int(key: str, default: int) -> int:
    try:
        value = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get(key) is not None:
            return int(value[key])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return default


PARALLEL_MIN_PAGES = max(2, _contract_int("parallel_builder_min_pages", 4))
MAX_PARALLEL_BUILDERS = max(1, _contract_int("max_parallel_builders", 3))


def default_calibration_slides(work_dir: Path, limit: int = 3) -> list[int]:
    """Deterministic calibration default: maximum distinct archetypes (Batch 4.1).

    The sample is chosen to cover different visual grammars (cover / data /
    comparison / process …) rather than the first three high-leverage positions;
    high-leverage slides still win ties and fill the sample. The main session may
    still pick its own set; `next --json` names the override command when it hands
    over the packet.
    """
    from calibration_archetypes import default_calibration_slides as coverage_default

    return coverage_default(work_dir, limit)


def calibration_coverage(work_dir: Path, slides: list[int] | None, limit: int = 3) -> dict[str, Any] | None:
    """Archetype coverage of an explicit calibration pick vs. the default set.

    Overriding the default is allowed, but an override that silently drops an
    archetype defeats the point of calibration (one grammar sampled three times
    cannot catch a systemic choice). The comparison is emitted with the packet so
    the decision is made on numbers, not on a feeling about page importance.
    """
    from calibration_archetypes import calibration_coverage as coverage_report

    try:
        return coverage_report(work_dir, slides, limit)
    except Exception:
        return None


def coverage_line(coverage: dict[str, Any] | None) -> str:
    """One human line stating whether an override keeps coverage."""
    if not coverage:
        return ""
    return (
        f"calibration coverage: {coverage['verdict']} — candidate {coverage['candidate']} "
        f"[{', '.join(coverage['candidate_archetypes'])}] vs default {coverage['default']} "
        f"[{', '.join(coverage['default_archetypes'])}]"
    )


def remaining_scaffold_slides(work_dir: Path) -> list[int]:
    """Slides whose page module still carries the stub marker (never implemented)."""
    pages = work_dir / "pages"
    by_name = {path.name: path for path in _scaffold.listed_page_files(pages)}
    stubs = set(_scaffold.scaffolded_pages(list(by_name.values())))
    result: list[int] = []
    for name in sorted(stubs):
        match = _scaffold.PAGE_NAME_RE.match(name)
        if match:
            result.append(int(match.group(1)))
    return sorted(result)


def split_shards(slides: list[int], work_dir: Path) -> list[dict[str, Any]]:
    """Round-robin disjoint shards over the sorted slide list (mirrors the pipeline)."""
    targets = sorted({int(slide) for slide in slides if int(slide) > 0})
    by_slide = page_modules(work_dir)
    known = [slide for slide in targets if slide in by_slide]
    if len(known) < PARALLEL_MIN_PAGES or MAX_PARALLEL_BUILDERS < 2:
        return []
    shard_count = min(MAX_PARALLEL_BUILDERS, len(known))
    shards: list[list[int]] = [[] for _ in range(shard_count)]
    for position, slide in enumerate(known):
        shards[position % shard_count].append(slide)
    return [{"shard": index + 1, "slides": slides_} for index, slides_ in enumerate(shards)]


def score_history(work_dir: Path) -> dict[str, dict[str, Any]]:
    loaded = load_optional(work_dir / SCORE_HISTORY_NAME)
    return loaded if isinstance(loaded, dict) else {}


def report_slide_blockers(report: dict[str, Any], slide: int) -> list[dict[str, Any]]:
    out = []
    for item in (report.get("problems") or []) + (report.get("issues") or []):
        if not isinstance(item, dict):
            continue
        run = item.get("slides") if isinstance(item.get("slides"), list) else []
        # Match single-slide findings and multi-slide runs (repetitive_structure_*),
        # and keep the run list in the projection so the builder sees the span.
        if item.get("slide") == slide or slide in run:
            out.append(
                {
                    "gate": item.get("gate"),
                    "code": item.get("code"),
                    "severity": item.get("severity"),
                    "message": str(item.get("message") or "")[:300],
                    **({"slides": [int(v) for v in run if isinstance(v, int)]} if run else {}),
                }
            )
    return out


def build_packet(
    work_dir: Path,
    mode: str,
    slides: list[int] | None = None,
    shard: int | None = None,
    qa_reports: list[Path] | None = None,
) -> dict[str, Any]:
    """Project one builder instance's complete task input. Raises SystemExit on
    missing spec or unknown slides, exactly like `page_brief.py`."""
    if mode not in {"calibration", "initial", "repair"}:
        raise SystemExit(f"mode must be calibration|initial|repair, got: {mode}")
    spec_path = find_spec(work_dir)
    if spec_path is None:
        raise SystemExit(f"No Slide Spec found in {work_dir}")
    spec = load_structured(spec_path)
    if not isinstance(spec, dict):
        raise SystemExit(f"Slide Spec root must be an object: {spec_path}")

    if slides is None:
        if mode == "initial":
            slides = remaining_scaffold_slides(work_dir)
        elif mode == "calibration":
            slides = default_calibration_slides(work_dir)
        else:
            raise SystemExit("repair packets need explicit slides (or a qa-report to derive them)")
    targets = sorted({int(slide) for slide in (slides or []) if int(slide) > 0})
    if not targets:
        raise SystemExit("no assigned slides: nothing to project")

    modules = page_modules(work_dir)
    deck = deck_state(work_dir)
    leverage = high_leverage(work_dir)
    sources = sources_by_id(load_optional(work_dir / "research-pack.json"))
    spec_slides = [item for item in (spec.get("slides") or []) if isinstance(item, dict)]
    # Batch 4.3: the planned rhythm (tone + composition family + neighbours) rides
    # into every packet so builders alternate deliberately instead of by accident.
    from deck_rhythm import page_rhythm, rhythm_warnings

    rhythm_by_slide = page_rhythm(work_dir)
    warnings = rhythm_warnings(work_dir)

    reports: list[dict[str, Any]] = []
    loaded_reports: list[dict[str, Any]] = []
    for path in qa_reports or []:
        report = load_optional(work_dir / str(path)) if not Path(path).is_absolute() else load_optional(Path(path))
        if isinstance(report, dict):
            loaded_reports.append(report)
            reports.append(str((work_dir / str(path)).resolve()))

    history = score_history(work_dir) if mode == "repair" else {}
    details: list[dict[str, Any]] = []
    for item in spec_slides:
        number = slide_number(item, len(details) + 1)
        if number not in targets:
            continue
        entry: dict[str, Any] = dict(item)
        entry["archetype"] = archetype_of(item)
        if rhythm_by_slide.get(number):
            entry["rhythm"] = rhythm_by_slide[number]
        entry["page_module"] = modules.get(number)
        entry["high_leverage"] = number in leverage
        entry["requirements"] = actual_check.planned_requirements(item)
        entry["evidence"] = evidence_for_slide(spec, item, number)
        cited: list[dict[str, Any]] = []
        for evidence_entry in entry["evidence"]:
            for source_id in evidence_entry["source_ids"]:
                if source_id in sources and sources[source_id] not in cited:
                    cited.append(sources[source_id])
        entry["sources"] = cited
        entry["blockers"] = [
            blocker for report in loaded_reports for blocker in report_slide_blockers(report, number)
        ]
        if not loaded_reports:
            entry["blockers"] = [
                problem for problem in deck.get("problems", []) if problem.get("slide") == number
            ]
        if history.get(str(number)):
            entry["must_not_regress"] = history[str(number)]
        details.append(entry)

    known_slides = {slide_number(item, index + 1) for index, item in enumerate(spec_slides)}
    missing = [slide for slide in targets if slide not in known_slides]
    if missing:
        raise SystemExit(f"Slides {missing} are not in the plan ({spec_path.name})")

    notes_target = f"speaker-notes-shard-{shard}.md" if shard else "speaker-notes.md"
    allowed_files = [modules[slide] for slide in targets if slide in modules] or [
        "pages/pNN-*.js"
    ]
    allowed_files.append(notes_target)
    if mode == "calibration":
        # The style summary is a REQUIRED calibration deliverable (a green review
        # refuses without it), so the packet must both allow and teach it.
        (work_dir / "calibration").mkdir(exist_ok=True)
        allowed_files.append("calibration/style-summary.json")

    packet: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": mode,
        "work_dir": str(work_dir),
        "shard": shard,
        "assigned_slides": targets,
        "speaker_notes_target": notes_target,
        "art_direction_path": str((work_dir / "art-direction.yaml").resolve()),
        "slides": details,
        "allowed_files": allowed_files,
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "do_not_reread": NO_REREAD,
    }
    if warnings:
        packet["rhythm_warnings"] = warnings
    if mode == "calibration":
        packet["style_summary_schema"] = {
            "file": "calibration/style-summary.json",
            "shape": {
                "established": {
                    key: "one factual line about what this calibration established"
                    for key in STYLE_SUMMARY_KEYS
                },
                "do_not_repeat": ["systemic pattern the remaining pages must avoid"],
            },
        }
    if mode == "repair":
        packet["reports"] = reports
        deck_level = [
            {
                "gate": item.get("gate"),
                "code": item.get("code"),
                "severity": item.get("severity"),
                "message": str(item.get("message") or "")[:300],
            }
            for report in loaded_reports
            for item in (report.get("problems") or []) + (report.get("issues") or [])
            if isinstance(item, dict) and item.get("slide") is None
        ]
        packet["deck_blockers"] = deck_level
        packet["must_not_regress_note"] = (
            "pages that already passed review must not drop 1.5+ points; the QA gate "
            "compares this round's per-slide scores against visual-score-history.json"
        )
    if mode in {"initial", "repair"}:
        # Batch 4.2: the established visual system travels as one compact contract,
        # not as calibration page JS (which builders must not read) and not as a
        # second read of the full Art Direction.
        from calibration_review import calibration_review
        from style_contract import STYLE_CONTRACT_NAME, ensure_style_contract

        review = calibration_review(work_dir)
        contract_path = ensure_style_contract(work_dir, review)
        if contract_path is not None:
            packet["calibration_style"] = load_optional(contract_path)
            packet["calibration_style_path"] = str(contract_path)
            packet["calibration_style_note"] = (
                f"this contract IS the visual reference system (generated from the green "
                f"calibration review + Art Direction, see {STYLE_CONTRACT_NAME} derived_from): "
                "follow it for every page; do NOT read calibration page modules to infer style"
            )
        elif review.get("required"):
            packet["calibration_style_note"] = (
                f"calibration exists but its review is not green ({review.get('reason')}); "
                "follow the Art Direction sections in this packet only"
            )
    # Context minimisation (Batch 1-4 closure): with a green style contract the
    # packet embeds it INSTEAD of the AD's style sections — a full Art Direction
    # copy per shard is exactly the duplicated context Batch 2 removed. Without
    # a contract (calibration round or fallback) the full AD stays.
    full_ad = load_optional(work_dir / "art-direction.yaml")
    if isinstance(packet.get("calibration_style"), dict) and isinstance(full_ad, dict):
        from style_contract import STYLE_SECTIONS

        packet["art_direction"] = {
            key: value for key, value in full_ad.items() if key not in STYLE_SECTIONS
        }
        packet["art_direction_note"] = (
            "the AD style sections are projected in calibration_style; this slice "
            "carries only the operational remainder (asset_plan, high_leverage, ...)"
        )
    else:
        packet["art_direction"] = full_ad
    return packet


def record_active_round(work_dir: Path, mode: str, packets: list[dict[str, Any]]) -> None:
    """Publish this spawn round's packet bindings for runtime enforcement.

    builder_guard.py reads builder-packets/active-round.json to enforce the
    behavior contract WITH model tools, not just prose: a builder with an active
    packet may not re-read the frozen inputs the packet projects, and may only
    touch the page modules its shard was assigned. An empty packet list (the
    legacy fallback path) clears the file — fallback stays usable, and its cost
    stays observable via fallbacks.json.

    Dispatch idempotency: re-dispatching the SAME mode with the SAME packet paths
    and slide assignments does NOT rotate the round stamp. The main session may
    legitimately call `next`/`advance` again while shards are in flight; a fresh
    timestamp there would expire every working builder's binding mid-round. A
    genuine re-shard (different packets or slides) still rotates the round and
    expires the old scopes by design.
    """
    out_dir = work_dir / PACKET_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ACTIVE_ROUND_NAME
    if not packets:
        path.unlink(missing_ok=True)
        return
    new_packets = [
        {
            "packet": str(item["packet"]),
            "assigned_slides": item["slides"],
            "speaker_notes_target": item.get("speaker_notes_target"),
            "packet_sha256": actual_check.sha256_file(Path(str(item["packet"]))),
        }
        for item in packets
    ]

    def scope(entry: dict[str, Any]) -> tuple:
        slides = entry.get("assigned_slides") or []
        return (
            entry.get("packet") or "",
            tuple(slides),
            entry.get("packet_sha256") or "",
        )

    existing = load_optional(path)
    if (
        isinstance(existing, dict)
        and existing.get("mode") == mode
        and [scope(p) for p in existing.get("packets") or []]
        == [scope(p) for p in new_packets]
    ):
        return
    path.write_text(
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                "mode": mode,
                "packets": new_packets,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_active_round(work_dir: Path) -> None:
    (work_dir / PACKET_DIR_NAME / ACTIVE_ROUND_NAME).unlink(missing_ok=True)


def active_round(work_dir: Path) -> dict[str, Any] | None:
    loaded = load_optional(work_dir / PACKET_DIR_NAME / ACTIVE_ROUND_NAME)
    return loaded if isinstance(loaded, dict) and loaded.get("packets") else None


def active_packet_descriptors(work_dir: Path, mode: str) -> list[dict[str, Any]]:
    """Return a validated active packet round, or ``[]`` when it is stale.

    Dispatch uses this before generating a default calibration packet. Without
    this read-back, a valid CLI override is immediately overwritten by the next
    `next`/`advance` call and builder_guard keeps the old assignment.
    """
    active = active_round(work_dir)
    if not active or active.get("mode") != mode:
        return []
    descriptors: list[dict[str, Any]] = []
    for item in active.get("packets") or []:
        if not isinstance(item, dict):
            return []
        path = Path(str(item.get("packet") or ""))
        packet = load_optional(path)
        slides = [int(value) for value in item.get("assigned_slides") or []]
        if (
            not isinstance(packet, dict)
            or packet.get("mode") != mode
            or Path(str(packet.get("work_dir") or "")).resolve() != work_dir.resolve()
            or packet.get("assigned_slides") != slides
            or not slides
            or (
                item.get("packet_sha256")
                and actual_check.sha256_file(path) != item.get("packet_sha256")
            )
        ):
            return []
        descriptors.append(
            {
                "shard": packet.get("shard"),
                "slides": slides,
                "speaker_notes_target": packet.get("speaker_notes_target"),
                "packet": str(path.resolve()),
                "packet_sha256": item.get("packet_sha256"),
            }
        )
    return descriptors


def packet_name(mode: str, shard: int | None) -> str:
    return f"{mode}-shard-{shard:02d}.json" if shard else f"{mode}.json"


def write_packet(
    work_dir: Path,
    mode: str,
    slides: list[int] | None = None,
    shard: int | None = None,
    qa_reports: list[Path] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Generate and write one packet; returns (path, packet)."""
    packet = build_packet(work_dir, mode, slides, shard, qa_reports)
    out_dir = work_dir / PACKET_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / packet_name(mode, shard)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, packet


def prepare_packets(
    work_dir: Path,
    mode: str,
    slides: list[int] | None = None,
    qa_reports: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Generate one packet per builder instance for a spawn, disjoint by shard.

    Returns the descriptor list `next --json` embeds; an empty slide list yields []."""
    if mode == "initial" and slides is None:
        slides = remaining_scaffold_slides(work_dir)
    targets = [int(slide) for slide in (slides or [])]
    if not targets:
        return []
    shards = split_shards(targets, work_dir) if mode != "calibration" else []
    out: list[dict[str, Any]] = []
    if shards:
        for shard in shards:
            path, packet = write_packet(work_dir, mode, shard["slides"], shard["shard"], qa_reports)
            out.append(
                {
                    "shard": shard["shard"],
                    "slides": packet["assigned_slides"],
                    "speaker_notes_target": packet["speaker_notes_target"],
                    "packet": str(path),
                }
            )
    else:
        path, packet = write_packet(work_dir, mode, targets, None, qa_reports)
        out.append(
            {
                "shard": None,
                "slides": packet["assigned_slides"],
                "speaker_notes_target": packet["speaker_notes_target"],
                "packet": str(path),
            }
        )
    record_active_round(work_dir, mode, out)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Builder Packet (one builder's complete task input)")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["calibration", "initial", "repair"], required=True)
    parser.add_argument("--slides", type=int, nargs="+", help="assigned slides; defaults depend on mode")
    parser.add_argument("--shard", type=int, help="shard number for the speaker-notes fragment name")
    parser.add_argument(
        "--qa-report",
        action="append",
        default=[],
        help="QA / pre-QA report (relative to work-dir or absolute); repair blockers come from here",
    )
    parser.add_argument("--json", action="store_true", help="print the generated packet descriptor")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "write the packet even when an explicit calibration override drops an "
            "archetype; the coverage block still records the loss"
        ),
    )
    return parser.parse_args(argv)


def enforce_coverage(coverage: dict[str, Any] | None, *, requested: list[int] | None) -> bool:
    """Refuse an override that covers fewer archetypes than the default.

    Coverage is a HARD gate on an explicit `--slides` override and advisory on
    the default set. The asymmetry is the rule, not a feeling: overriding the
    deterministic default is the only way to lose an archetype, and it is the
    model — not the script — that picks the override. Running with no `--slides`
    cannot fail, because the default set is by construction the widest sample.

    The check must run BEFORE the packet is written: a packet on disk is what the
    builder is told to trust, and leaving a rejected packet behind is how a bad
    sample still gets built. Returns True when the caller may proceed.
    """
    if not requested or not coverage:
        return True
    return bool(coverage["keeps_coverage"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_dir = args.work_dir.resolve()
    if not work_dir.is_dir():
        raise SystemExit(f"Work directory does not exist: {work_dir}")
    coverage = calibration_coverage(work_dir, args.slides) if args.mode == "calibration" else None
    if not enforce_coverage(coverage, requested=args.slides) and not args.force:
        line = coverage_line(coverage)
        if line:
            print(line)
        raise SystemExit(
            "calibration override rejected: it covers fewer distinct archetypes than the default. "
            "Keep the default set, add a page carrying one of the dropped grammars, "
            "or pass --force to record the trade."
        )
    if args.mode == "calibration":
        slides = args.slides or default_calibration_slides(work_dir)
        descriptors = prepare_packets(work_dir, args.mode, slides, args.qa_report)
        if len(descriptors) != 1:
            raise SystemExit("calibration packet generation did not produce exactly one packet")
        descriptor = descriptors[0]
        path = Path(descriptor["packet"])
        packet = load_optional(path)
    else:
        path, packet = write_packet(work_dir, args.mode, args.slides, args.shard, args.qa_report)
    if args.json:
        payload = {
            "packet": str(path),
            "mode": packet["mode"],
            "shard": packet["shard"],
            "slides": packet["assigned_slides"],
            "speaker_notes_target": packet["speaker_notes_target"],
        }
        if coverage:
            payload["coverage"] = coverage
            payload["coverage_enforced"] = bool(args.slides) and not args.force
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"packet: {path} (mode={packet['mode']} slides={packet['assigned_slides']})")
        line = coverage_line(coverage)
        if line:
            print(line)
            print("coverage is enforced for explicit --slides overrides" if args.slides else "coverage is advisory for the default set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
