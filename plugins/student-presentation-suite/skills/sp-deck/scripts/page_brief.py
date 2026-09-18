#!/usr/bin/env python3
"""One call that projects a page's work brief out of the work directory.

Why this exists (2026-09-18 transcript analysis): the isolated builder used to pull
the few fields it needed out of `build-manifest.json` / `pipeline-qa.json` /
`research-pack.json` with hand-rolled inline scripts —

    node -e "const q=require('./qa-quality.json'); const s=JSON.stringify(q);
             const idx=s.indexOf('missing_final_reference');
             console.log(s.slice(idx-3000, idx+3000));"

— 19 to 46 times per repair round, each one a full context round-trip at ~150K
resident context, plus 11 re-reads of `slide-spec-compiled.yaml` because the
scaffold only said "this page needs its numbers" without saying which numbers.

This command answers the same questions deterministically in one call, and the
strings it prints come from `pptx_actual_content_check.planned_requirements()`,
so what the builder is told to render is byte-identical to what the readback gate
will judge.

Usage:
    page_brief.py --work-dir <wd> --json                  # whole deck: per-page requirements
    page_brief.py --work-dir <wd> --slides 2 5 8 --json   # target pages (calibration/repair round)
    page_brief.py --work-dir <wd> --slide 7 --json        # one page: requirements + blockers + sources

The strategy is pinned by references/agent-behavior-contract.json
(#presentation_builder.page_brief_strategy): `initial` reads the whole deck once,
`calibration` / `repair` read their target pages once. Neither mode ever calls
this tool once per page — `--slides` exists precisely so a target-pages round
stays a single call.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pptx_actual_content_check as actual_check  # noqa: E402

SPEC_CANDIDATES = ("slide-spec-compiled.yaml", "slide-spec-compiled.json", "slide-spec.yaml", "slide-spec.json")
PAGE_MODULE_RE = re.compile(r"^p(\d+)-")
ON_SCREEN_RULE = (
    "these strings must appear verbatim as visible text runs in the delivered PPTX; "
    "chart data labels are not text runs, so every planned number needs a text element"
)


def load_structured(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    import yaml  # type: ignore

    return yaml.safe_load(text)


def load_optional(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return load_structured(path)
    except (OSError, ValueError):
        return None


def find_spec(work_dir: Path) -> Path | None:
    for name in SPEC_CANDIDATES:
        candidate = work_dir / name
        if candidate.is_file():
            return candidate
    return None


def page_modules(work_dir: Path) -> dict[int, str]:
    """One-based slide number → page module path relative to the work dir."""
    pages = work_dir / "pages"
    found: dict[int, str] = {}
    if not pages.is_dir():
        return found
    for path in sorted(pages.glob("*.js")):
        match = PAGE_MODULE_RE.match(path.name)
        if match:
            found[int(match.group(1))] = f"pages/{path.name}"
    return found


def slide_number(item: dict[str, Any], fallback: int) -> int:
    try:
        value = int(item.get("id"))
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def evidence_for_slide(spec: dict[str, Any], slide: dict[str, Any], number: int) -> list[dict[str, Any]]:
    """Evidence entries this page cites, by either direction of the link."""
    ledger = [item for item in (spec.get("evidence_ledger") or []) if isinstance(item, dict)]
    wanted = {str(ref) for ref in (slide.get("evidence_refs") or []) if str(ref).strip()}
    out: list[dict[str, Any]] = []
    for entry in ledger:
        entry_id = str(entry.get("id") or "")
        used_on = {str(value) for value in (entry.get("used_on_slides") or [])}
        if entry_id in wanted or str(number) in used_on:
            out.append(
                {
                    "id": entry_id,
                    "title": str(entry.get("title") or ""),
                    "source_ids": [str(value) for value in (entry.get("source_ids") or [])],
                    "locator": str(entry.get("locator") or ""),
                    "date": str(entry.get("date") or ""),
                }
            )
    return out


def sources_by_id(pack: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(pack, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in pack.get("sources") or []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        out[entry_id] = {
            "id": entry_id,
            "title": str(entry.get("title") or ""),
            "publisher": str(entry.get("publisher") or ""),
            "year": entry.get("year"),
            "locator": str(entry.get("locator") or entry.get("url") or ""),
        }
    return out


def deck_state(work_dir: Path) -> dict[str, Any]:
    """QA failures and work state, projected from the reports the gates wrote."""
    qa = load_optional(work_dir / "pipeline-qa.json")
    manifest = load_optional(work_dir / "build-manifest.json")
    state = ""
    if isinstance(manifest, dict):
        state = str(manifest.get("state") or "")
    version = ""
    if isinstance(manifest, dict):
        version = str(manifest.get("manifest_version") or "")
    out: dict[str, Any] = {"state": state, "manifest_version": version}
    if isinstance(qa, dict):
        out["ok"] = qa.get("ok")
        out["failed_stages"] = list(qa.get("failed_stages") or [])
        out["blockers_by_gate"] = qa.get("blockers_by_gate") or {}
        out["derived_problems"] = list(qa.get("derived_problems") or [])
        out["problems"] = [
            {
                "gate": item.get("gate"),
                "code": item.get("code"),
                "severity": item.get("severity"),
                "message": str(item.get("message") or "")[:300],
                **({"slide": item["slide"]} if item.get("slide") is not None else {}),
                **({"derived": True} if item.get("derived") else {}),
            }
            for item in (qa.get("problems") or [])
            if isinstance(item, dict)
        ]
    return out


def high_leverage(work_dir: Path) -> list[int]:
    art = load_optional(work_dir / "art-direction.yaml")
    if not isinstance(art, dict):
        return []
    raw = art.get("high_leverage_slides")
    numbers: list[int] = []
    for item in raw or []:
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(numbers)


def page_detail(
    spec: dict[str, Any],
    match: dict[str, Any],
    slide: int,
    modules: dict[int, str],
    deck: dict[str, Any],
    leverage: list[int],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Per-page projection shared by the single-page and target-pages forms."""
    evidence = evidence_for_slide(spec, match["source"], slide)
    cited_sources = []
    for entry in evidence:
        for source_id in entry["source_ids"]:
            if source_id in sources and sources[source_id] not in cited_sources:
                cited_sources.append(sources[source_id])
    return {
        "slide": slide,
        "page_module": modules.get(slide),
        "high_leverage": slide in leverage,
        "on_screen": match["requirements"],
        "evidence": evidence,
        "sources": cited_sources,
        "blockers": [
            problem for problem in deck.get("problems", []) if problem.get("slide") == slide
        ],
    }


def build_brief(
    work_dir: Path,
    slide: int | None = None,
    slides: list[int] | None = None,
) -> dict[str, Any]:
    if slide is not None and slides:
        raise SystemExit("Use --slide or --slides, not both")
    spec_path = find_spec(work_dir)
    if spec_path is None:
        raise SystemExit(f"No Slide Spec found in {work_dir}")
    spec = load_structured(spec_path)
    if not isinstance(spec, dict):
        raise SystemExit(f"Slide Spec root must be an object: {spec_path}")

    modules = page_modules(work_dir)
    deck = deck_state(work_dir)
    leverage = high_leverage(work_dir)
    sources = sources_by_id(load_optional(work_dir / "research-pack.json"))
    spec_slides = [item for item in (spec.get("slides") or []) if isinstance(item, dict)]

    planned: list[dict[str, Any]] = []
    for fallback, item in enumerate(spec_slides, start=1):
        number = slide_number(item, fallback)
        requirements = actual_check.planned_requirements(item)
        planned.append({"slide": number, "source": item, "requirements": requirements})

    if slide is None and not slides:
        return {
            "work_id": work_dir.name,
            "spec": spec_path.name,
            "deck": deck,
            "high_leverage_slides": leverage,
            "on_screen_rule": ON_SCREEN_RULE,
            "slides": [
                {
                    "slide": item["slide"],
                    "page_module": modules.get(item["slide"]),
                    "title": item["requirements"]["title"],
                    "claim": item["requirements"]["claim"],
                    "numbers": item["requirements"]["numbers"],
                    "high_leverage": item["slide"] in leverage,
                    "blockers": [
                        problem for problem in deck.get("problems", [])
                        if problem.get("slide") == item["slide"]
                    ],
                }
                for item in planned
            ],
        }

    if slides:
        details = []
        for wanted in sorted(set(slides)):
            match = next((item for item in planned if item["slide"] == wanted), None)
            if match is None:
                raise SystemExit(f"Slide {wanted} is not in the plan ({spec_path.name})")
            details.append(
                page_detail(spec, match, wanted, modules, deck, leverage, sources)
            )
        return {
            "work_id": work_dir.name,
            "spec": spec_path.name,
            "mode": "target_pages",
            "target_slides": [item["slide"] for item in details],
            "deck": {
                "state": deck.get("state"),
                "failed_stages": deck.get("failed_stages", []),
                "blockers_by_gate": deck.get("blockers_by_gate", {}),
            },
            "on_screen_rule": ON_SCREEN_RULE,
            "slides": details,
        }

    match = next((item for item in planned if item["slide"] == slide), None)
    if match is None:
        raise SystemExit(f"Slide {slide} is not in the plan ({spec_path.name})")
    detail = page_detail(spec, match, slide, modules, deck, leverage, sources)
    return {
        "work_id": work_dir.name,
        "spec": spec_path.name,
        "slide": slide,
        "page_module": detail["page_module"],
        "deck": {
            "state": deck.get("state"),
            "failed_stages": deck.get("failed_stages", []),
            "blockers_by_gate": deck.get("blockers_by_gate", {}),
            "derived_problems": deck.get("derived_problems", []),
        },
        "high_leverage": detail["high_leverage"],
        "on_screen_rule": ON_SCREEN_RULE,
        "on_screen": detail["on_screen"],
        "evidence": detail["evidence"],
        "sources": detail["sources"],
        "blockers": detail["blockers"],
        "deck_blockers": [
            problem for problem in deck.get("problems", [])
            if problem.get("slide") is None and not problem.get("derived")
        ],
    }


def print_text(brief: dict[str, Any]) -> None:
    if brief.get("mode") == "target_pages":
        deck = brief["deck"]
        print(
            f"work {brief['work_id']} — target slides {' '.join(str(n) for n in brief['target_slides'])}"
            f" (state {deck.get('state')})"
        )
        for item in brief["slides"]:
            on_screen = item["on_screen"]
            print(f"slide {item['slide']} ({item['page_module'] or 'no module'}): {on_screen['title']}")
            print(f"  title:   {on_screen['title']}")
            if on_screen["claim"]:
                print(f"  claim:   {on_screen['claim']}")
            if on_screen["numbers"]:
                print(f"  numbers: {' '.join(on_screen['numbers'])}")
            for fragment in on_screen["copy_fragments"]:
                print(f"  copy:    {fragment}")
            for source in item["sources"]:
                print(f"  source:  [{source['id']}] {source['title']} — {source['publisher']} {source['year']}")
            for problem in item["blockers"]:
                print(f"  blocker: [{problem['severity']}] {problem['gate']}/{problem['code']} — {problem['message']}")
        failed = deck.get("failed_stages") or []
        if failed:
            print(f"failed gates: {', '.join(failed)}")
        return

    if "slide" not in brief:
        print(f"work {brief['work_id']} — {len(brief['slides'])} slides (state {brief['deck'].get('state')})")
        for item in brief["slides"]:
            marks = []
            if item["high_leverage"]:
                marks.append("high-leverage")
            if item["blockers"]:
                marks.append(f"{len(item['blockers'])} blocker(s)")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            print(f"  {item['slide']:>3} {item['page_module'] or '?':<20} {item['title'][:36]}{suffix}")
            if item["claim"]:
                print(f"      claim: {item['claim']}")
            if item["numbers"]:
                print(f"      numbers: {' '.join(item['numbers'])}")
        failed = brief["deck"].get("failed_stages") or []
        if failed:
            print(f"failed gates: {', '.join(failed)}")
        for problem in brief["deck"].get("problems", []):
            print(f"  [{problem['severity']}] {problem['gate']}/{problem['code']} — {problem['message'][:160]}")
        return

    print(f"work {brief['work_id']} — slide {brief['slide']} ({brief['page_module'] or 'no module'})")
    on_screen = brief["on_screen"]
    print(f"title:   {on_screen['title']}")
    if on_screen["claim"]:
        print(f"claim:   {on_screen['claim']}")
    if on_screen["numbers"]:
        print(f"numbers: {' '.join(on_screen['numbers'])}")
    for fragment in on_screen["copy_fragments"]:
        print(f"copy:    {fragment}")
    for source in brief["sources"]:
        print(f"source:  [{source['id']}] {source['title']} — {source['publisher']} {source['year']}")
    for problem in brief["blockers"]:
        mark = " (derived)" if problem.get("derived") else ""
        print(f"blocker: [{problem['severity']}]{mark} {problem['gate']}/{problem['code']} — {problem['message']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project one page's work brief from the work directory")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--slide", type=int, help="one-based slide number; omit for the whole deck")
    parser.add_argument(
        "--slides",
        type=int,
        nargs="+",
        help="one-based slide numbers of one round's target pages (calibration/repair); one call",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    if not work_dir.is_dir():
        raise SystemExit(f"Work directory does not exist: {work_dir}")
    brief = build_brief(work_dir, args.slide, args.slides)
    if args.json:
        print(json.dumps(brief, ensure_ascii=False, indent=2))
    else:
        print_text(brief)


if __name__ == "__main__":
    main()
