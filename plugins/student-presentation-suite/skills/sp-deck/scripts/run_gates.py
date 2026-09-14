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
import subprocess
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


def _qa_severity(report: dict[str, Any], issue: dict[str, Any]) -> str:
    """QA gates are not consistent about severity labels; normalise them."""
    severity = str(issue.get("severity") or "").lower()
    if severity in {"critical", "major", "blocker"}:
        return "critical" if severity == "critical" else "major"
    if severity == "minor":
        return "minor"
    # Unknown label: treat a failing gate's findings as blockers rather than
    # silently dropping them.
    return "major" if not report.get("ok", True) else "minor"


def _qa_gate(
    name: str,
    script: str,
    argv: list[str],
    gates: dict[str, Any],
    problems: list[dict[str, Any]],
    report_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, str(HERE / script), *argv],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not report_path.is_file():
        gates[name] = {"ok": False, "checked": True, "exit_code": result.returncode}
        problems.append(
            problem(
                name,
                "critical",
                f"{script}_missing_report",
                f"{script} produced no report (exit {result.returncode}): "
                f"{shorten((result.stderr or result.stdout or '').strip(), 160)}",
            )
        )
        return

    report = json.loads(report_path.read_text(encoding="utf-8"))
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        severity = _qa_severity(report, issue)
        problems.append(
            problem(
                name,
                severity,
                str(issue.get("code") or f"{script}_issue"),
                str(issue.get("message") or issue.get("detail") or issue.get("problem") or issue),
                slide=issue.get("slide"),
            )
        )
    gates[name] = {
        "ok": bool(report.get("ok", result.returncode == 0)),
        "checked": True,
        "exit_code": result.returncode,
        "issue_count": len(issues),
        "report": str(report_path),
    }
    if issues:
        return
    if not report.get("ok", True):
        problems.append(
            problem(
                name,
                "major" if result.returncode else "minor",
                f"{script}_failed",
                f"{script} reported not ok without itemised issues (exit {result.returncode}).",
            )
        )


def collect_qa(args: argparse.Namespace, gates: dict[str, Any], problems: list[dict[str, Any]], workdir: Path) -> None:
    """Run the QA-side gates in one command.

    These live behind separate CLIs with their own required inputs, so instead of
    reimplementing them this shells out per gate and merges the JSON reports into
    the single problem list. The saving is not process time, it is turning four or
    five round-trips into one.
    """
    if not getattr(args, "pptx", None):
        return
    pptx = str(args.pptx)
    spec = str(args.slide_spec) if args.slide_spec else ""

    if spec:
        _qa_gate(
            "actual-content",
            "pptx_actual_content_check.py",
            [pptx, spec, "--output", str(workdir / "qa-actual-content.json")],
            gates,
            problems,
            workdir / "qa-actual-content.json",
        )

    _qa_gate(
        "rendered",
        "pptx_rendered_check.py",
        ["--pptx", pptx, "--output", str(workdir / "qa-rendered.json")],
        gates,
        problems,
        workdir / "qa-rendered.json",
    )

    if spec and args.spec_lock and args.visual_report:
        _qa_gate(
            "quality",
            "pptx_quality_gate_v071.py",
            [
                "--pptx", pptx,
                "--slide-spec", spec,
                "--spec-lock", str(args.spec_lock),
                "--visual-report", str(args.visual_report),
                "--output", str(workdir / "qa-quality.json"),
            ],
            gates,
            problems,
            workdir / "qa-quality.json",
        )

    delivery_inputs = [
        spec,
        args.spec_lock,
        args.art_direction,
        args.visual_generation_report,
        args.quality_report,
        args.package_report,
        args.slide_spec_report,
        args.actual_content_report,
    ]
    if all(delivery_inputs):
        argv = [
            "--pptx", pptx,
            "--slide-spec", spec,
            "--spec-lock", str(args.spec_lock),
            "--art-direction", str(args.art_direction),
            "--visual-generation-report", str(args.visual_generation_report),
            "--quality-report", str(args.quality_report),
            "--package-report", str(args.package_report),
            "--slide-spec-report", str(args.slide_spec_report),
            "--actual-content-report", str(args.actual_content_report),
            "--visual-reviewed",
            "--output", str(workdir / "qa-delivery.json"),
        ]
        if args.visual_review_report:
            argv += ["--visual-review-report", str(args.visual_review_report)]
        if args.notes:
            argv += ["--notes", str(args.notes)]
        for preview in args.preview or []:
            argv += ["--preview", str(preview)]
        if args.allow_missing_preview:
            argv.append("--allow-missing-preview")
        _qa_gate(
            "delivery",
            "pptx_delivery_check_v08.py",
            argv,
            gates,
            problems,
            workdir / "qa-delivery.json",
        )


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


def run(args: argparse.Namespace, workdir: Path | None = None) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    gates: dict[str, Any] = {}
    qa_dir = workdir or (args.output.parent if args.output else Path.cwd())

    if getattr(args, "lock_file", None):
        collect_lock(args, gates, problems)
    if getattr(args, "art_direction", None):
        collect_art_direction(args, gates, problems)
    collect_candidates(args, gates, problems)
    collect_visual_generation(args, gates, problems)
    collect_qa(args, gates, problems, qa_dir)

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
    parser.add_argument(
        "--art-direction",
        type=Path,
        help="art-direction.yaml|json (Art Direction gate); required unless --pptx is used alone",
    )
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
    qa = parser.add_argument_group("QA gates", "one command for the post-build gates instead of four round-trips")
    qa.add_argument("--pptx", type=Path, help="candidate PPTX; enables the QA gates")
    qa.add_argument("--spec-lock", type=Path, help="slide-spec-lock.json (quality + delivery)")
    qa.add_argument("--visual-report", type=Path, help="visual-review.json (quality gate)")
    qa.add_argument("--visual-review-report", type=Path, help="visual-review.json bound to the PPTX (delivery)")
    qa.add_argument("--visual-generation-report", type=Path, help="visual-generation-report.json (delivery)")
    qa.add_argument("--quality-report", type=Path, help="quality-report.json (delivery)")
    qa.add_argument("--package-report", type=Path, help="package validation report (delivery)")
    qa.add_argument("--slide-spec-report", type=Path, help="Slide Spec validation report (delivery)")
    qa.add_argument("--actual-content-report", type=Path, help="actual-content report (delivery)")
    qa.add_argument("--notes", type=Path, help="speaker notes file (delivery)")
    qa.add_argument("--preview", type=Path, nargs="+", action="extend", default=None, help="preview images (delivery)")
    qa.add_argument("--allow-missing-preview", action="store_true", help="relax the delivery preview requirement")
    parser.add_argument("--quality", choices=["high-score", "standard"], default="high-score")
    parser.add_argument("--output", type=Path, help="merged report path; defaults to <evidence-dir>/gates-report.json")
    parser.add_argument("--json", action="store_true", help="print the merged report instead of the summary")
    parser.add_argument("--verbose", action="store_true", help="also list minor issues")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS, help="cap listed problems (0 = no cap)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.evidence_dir and not args.candidates and not args.pptx:
        print(
            "run_gates: nothing to check — pass --evidence-dir, --candidates and/or --pptx",
            file=sys.stderr,
        )
        return 2
    if args.evidence_dir and not args.slide_spec:
        print("run_gates: --slide-spec is required together with --evidence-dir", file=sys.stderr)
        return 2
    if not args.art_direction and not args.pptx:
        print("run_gates: --art-direction is required unless running QA gates with --pptx", file=sys.stderr)
        return 2

    report_path = args.output or ((args.evidence_dir or Path.cwd()) / "gates-report.json")
    report = run(args, report_path.parent)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path, verbose=args.verbose, max_items=args.max_items), end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
