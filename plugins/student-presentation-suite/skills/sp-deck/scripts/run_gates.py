#!/usr/bin/env python3
"""One-shot v0.8 gate run: frozen plan, Art Direction, composition, evidence.

The suite used to run its gates as separate commands, and every one of them
printed a complete JSON report. A *passing* run therefore cost a large amount of
context while carrying zero information, and the v0.8 visual-generation gate
re-validated Art Direction and composition candidates that had already been
checked a moment earlier.

This orchestrator runs the same validators in one process, prints only the
problem items, and writes the complete detail to a JSON report on disk. It never
replaces the individual gates: `art_direction_check.py`,
`composition_candidate_check.py`, `pptx_visual_generation_gate_v08.py` and
`slide_spec_guard.py` stay the canonical implementations and remain callable on
their own.

Exit codes: 0 = no blockers, 2 = at least one blocker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import art_direction_check as art_check  # noqa: E402
import composition_candidate_check as candidate_check  # noqa: E402
import pptx_visual_generation_gate_v08 as visual_gate  # noqa: E402
import slide_spec_guard as spec_guard  # noqa: E402

SEVERITIES = ("critical", "major", "minor")
BLOCKING = {"critical", "major"}
DEFAULT_MAX_ITEMS = 12
MESSAGE_LIMIT = 220


def problem(gate: str, severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "gate": gate,
        "severity": severity,
        "code": code,
        "message": message,
        **{key: value for key, value in extra.items() if value is not None},
    }


def problem_from(gate: str, item: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return problem(
        gate,
        str(item.get("severity") or "major"),
        str(item.get("code") or "unknown"),
        str(item.get("message") or ""),
        **extra,
    )


def identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(item.get("severity")),
        str(item.get("code")),
        str(item.get("message")),
        str(item.get("slide")),
    )


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The visual-generation gate re-emits blocking Art Direction issues; keep one copy."""
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        marker = identity(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def shorten(text: str, limit: int = MESSAGE_LIMIT) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def collect_lock(args: argparse.Namespace, gates: dict[str, Any], problems: list[dict[str, Any]]) -> None:
    lock_path = Path(args.lock_file)
    if not lock_path.is_file():
        problems.append(
            problem("slide-spec", "critical", "slide_spec_lock_missing", f"Slide Spec lock does not exist: {lock_path}")
        )
        gates["slide_spec_lock"] = {"ok": False, "checked": False, "error_count": 1}
        return
    result = spec_guard.check_lock(lock_path, Path(args.slide_spec) if args.slide_spec else None)
    errors = list(result.get("errors") or [])
    gates["slide_spec_lock"] = {
        "ok": bool(result.get("ok")),
        "checked": True,
        "error_count": len(errors),
        "slide_spec_sha256": result.get("slide_spec_sha256"),
        "lock_sha256": result.get("lock_sha256"),
    }
    for message in errors:
        problems.append(problem("slide-spec", "critical", "slide_spec_lock", message))


def collect_art_direction(args: argparse.Namespace, gates: dict[str, Any], problems: list[dict[str, Any]]) -> dict[str, Any]:
    art_path = Path(args.art_direction)
    if not art_path.is_file():
        problems.append(
            problem("art-direction", "critical", "art_direction_missing", f"Art Direction file does not exist: {art_path}")
        )
        gates["art_direction"] = {"ok": False, "checked": False, "blocker_count": 1, "issue_count": 1}
        return {}
    report = art_check.validate_art_direction(
        art_check.load_structured(art_path),
        high_score=args.quality == "high-score",
    )
    gates["art_direction"] = {
        "ok": bool(report.get("ok")),
        "checked": True,
        "blocker_count": report.get("blocker_count", 0),
        "issue_count": report.get("issue_count", 0),
        "high_leverage_slides": report.get("high_leverage_slides") or [],
    }
    for item in report.get("issues") or []:
        problems.append(problem_from("art-direction", item))
    return report


def collect_candidates(args: argparse.Namespace, gates: dict[str, Any], problems: list[dict[str, Any]]) -> None:
    paths = [Path(value) for value in (args.candidates or [])]
    if not paths:
        return
    known = candidate_check.load_reference_ids(candidate_check.DEFAULT_LIBRARY)
    summaries: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            problems.append(
                problem("composition", "critical", "candidates_missing", f"Composition candidate file does not exist: {path}")
            )
            summaries.append({"file": str(path), "ok": False, "candidate_count": 0, "selected_id": None})
            continue
        report = candidate_check.validate_candidates(
            candidate_check.load_structured(path),
            known_reference_ids=known,
            high_score=args.quality == "high-score",
        )
        summaries.append(
            {
                "file": str(path),
                "ok": bool(report.get("ok")),
                "candidate_count": report.get("candidate_count"),
                "selected_id": report.get("selected_id"),
                "distinct_silhouettes": report.get("distinct_silhouettes") or [],
            }
        )
        for item in report.get("issues") or []:
            problems.append(problem_from("composition", item))
    gates["composition"] = {
        "ok": all(item["ok"] for item in summaries),
        "checked": True,
        "files": summaries,
    }


def collect_visual_generation(args: argparse.Namespace, gates: dict[str, Any], problems: list[dict[str, Any]]) -> None:
    if not args.evidence_dir:
        return
    report = visual_gate.validate_visual_generation(
        slide_spec=Path(args.slide_spec),
        art_direction=Path(args.art_direction),
        evidence_dir=Path(args.evidence_dir),
        quality=args.quality,
    )
    gates["visual_generation"] = {
        "ok": bool(report.get("ok")),
        "checked": True,
        "blocker_count": report.get("blocker_count", 0),
        "issue_count": report.get("issue_count", 0),
        "high_leverage_slides": report.get("high_leverage_slides") or [],
        "slide_spec_sha256": report.get("slide_spec_sha256"),
        "art_direction_sha256": report.get("art_direction_sha256"),
        "evidence": report.get("evidence") or [],
    }
    for item in report.get("issues") or []:
        nested = item.get("candidate_issues")
        if isinstance(nested, list) and nested:
            for sub in nested:
                problems.append(problem_from("composition", sub, slide=item.get("slide")))
            continue
        problems.append(problem_from("visual-generation", item, slide=item.get("slide")))


def run(args: argparse.Namespace) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    gates: dict[str, Any] = {}

    if getattr(args, "lock_file", None):
        collect_lock(args, gates, problems)
    collect_art_direction(args, gates, problems)
    collect_candidates(args, gates, problems)
    collect_visual_generation(args, gates, problems)

    problems = dedupe(problems)
    counts = {severity: sum(1 for item in problems if item["severity"] == severity) for severity in SEVERITIES}
    blockers = counts["critical"] + counts["major"]
    return {
        "ok": blockers == 0,
        "gates_version": "0.8",
        "quality": args.quality,
        "inputs": {
            "slide_spec": str(args.slide_spec) if args.slide_spec else None,
            "art_direction": str(args.art_direction),
            "evidence_dir": str(args.evidence_dir) if args.evidence_dir else None,
            "lock_file": str(args.lock_file) if args.lock_file else None,
            "candidate_files": [str(value) for value in (args.candidates or [])],
        },
        "gates": gates,
        "counts": {
            "blockers": blockers,
            "critical": counts["critical"],
            "major": counts["major"],
            "minor": counts["minor"],
        },
        "problems": problems,
    }


def render(report: dict[str, Any], report_path: Path, *, verbose: bool, max_items: int, show: bool = True) -> str:
    counts = report["counts"]
    state = "ok" if report["ok"] else "blocked"
    gate_names = ", ".join(report["gates"]) or "none"
    lines = [
        f"run_gates: {state} — blockers {counts['blockers']} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"gates: {gate_names} | {report['quality']} | report: {report_path}"
    ]
    if not show:
        return "\n".join(lines) + "\n"

    visible = [
        item
        for item in report["problems"]
        if item["severity"] in BLOCKING or (verbose and item["severity"] == "minor")
    ]
    limit = len(visible) if max_items <= 0 else max_items
    for item in visible[:limit]:
        slide = f" (slide {item['slide']})" if item.get("slide") else ""
        lines.append(f"  [{item['severity']}] {item['gate']}/{item['code']} — {shorten(item['message'])}{slide}")
    hidden = len(visible) - min(len(visible), limit)
    if hidden > 0:
        lines.append(f"  … {hidden} more (full detail in {report_path})")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--art-direction", type=Path, required=True, help="art-direction.yaml|json (Art Direction gate)")
    parser.add_argument("--evidence-dir", type=Path, help="work dir holding references/candidates/wireframes (v0.8 gate)")
    parser.add_argument("--slide-spec", type=Path, help="frozen Slide Spec; required with --evidence-dir")
    parser.add_argument("--lock-file", type=Path, help="slide-spec-lock.json; enables the frozen-plan check")
    parser.add_argument(
        "--candidates",
        type=Path,
        nargs="+",
        action="extend",
        default=None,
        help="composition-candidates-N.json files to validate directly (per-slide step before wireframes exist)",
    )
    parser.add_argument("--quality", choices=["high-score", "standard"], default="high-score")
    parser.add_argument("--output", type=Path, help="merged report path; defaults to <evidence-dir>/gates-report.json")
    parser.add_argument("--json", action="store_true", help="print the merged report instead of the summary")
    parser.add_argument("--verbose", action="store_true", help="also list minor issues")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS, help="cap listed problems (0 = no cap)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.evidence_dir and not args.candidates:
        print("run_gates: nothing to check — pass --evidence-dir and/or --candidates", file=sys.stderr)
        return 2
    if args.evidence_dir and not args.slide_spec:
        print("run_gates: --slide-spec is required together with --evidence-dir", file=sys.stderr)
        return 2

    report = run(args)
    report_path = args.output or ((args.evidence_dir or Path.cwd()) / "gates-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path, verbose=args.verbose, max_items=args.max_items), end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
