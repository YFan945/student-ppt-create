#!/usr/bin/env python3
"""Compile a Research Pack into Evidence Ledger entries — deterministically.

Before this existed, the chain F03 -> E07 -> Slide 05 was assembled by the model
reading `research-pack.json` and writing `evidence_ledger` by hand. That put free
improvisation back into the one step the Research Pack was built to remove: the
pack ids (F/D/S) and the ledger ids (E) had no mechanical relationship.

This script owns that step. Allocation is fixed and predictable:

    findings sorted by id, then data_points sorted by id  ->  E01, E02, ...

so a caller can reason about ids without running anything, and two runs over the
same pack always produce the same ledger.

It is deliberately non-destructive: it never rewrites the Slide Spec. It emits
`evidence-map.json` (ledger ready to merge, id map, source index, hashes) and, if
given a spec, verifies that every `evidence_refs` entry resolves and records
`used_on_slides` for you.

Refuses to compile a pack that fails `validate_research_pack.py`; an invalid pack
is not a deliverable and must not become evidence.

Exit codes: 0 = compiled, 2 = pack invalid or a spec reference does not resolve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import validate_research_pack as pack_validator  # noqa: E402

# Research Pack source type -> Slide Spec evidence_ledger source_type
SOURCE_TYPE_MAP = {
    "paper": "paper",
    "official-database": "dataset",
    "news": "website",
    "vendor-blog": "website",
    "community": "website",
    "personal-blog": "website",
    "law-and-regulation": "other",
    "official-document": "other",
    "standard": "other",
    "research-institute": "other",
    "university": "other",
    "international-organization": "other",
    "company-filing": "other",
    "industry-report": "other",
    "user-file": "user-file",
    "other": "other",
}
TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "?": 5}
TITLE_LIMIT = 160


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return value


def truncate(text: str, limit: int = TITLE_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def strongest_source(entry: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The highest-tier source backing an entry — that is what the ledger cites."""
    candidates = [by_id[str(ref)] for ref in entry.get("source_ids") or [] if str(ref) in by_id]
    if not candidates:
        return {}
    return sorted(candidates, key=lambda s: (TIER_RANK.get(str(s.get("tier") or "?"), 5), str(s.get("id"))))[0]


def locator_of(source: dict[str, Any]) -> str:
    return str(source.get("url") or source.get("locator") or "").strip() or "(no locator)"


def build_ledger(pack: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_id = {str(s.get("id")): s for s in pack_validator.items(pack, "sources")}
    findings = sorted(pack_validator.items(pack, "findings"), key=lambda e: str(e.get("id")))
    data_points = sorted(pack_validator.items(pack, "data_points"), key=lambda e: str(e.get("id")))

    ledger: list[dict[str, Any]] = []
    ref_map: dict[str, str] = {}

    for index, (kind, entry) in enumerate(
        [("finding", e) for e in findings] + [("data_point", e) for e in data_points],
        start=1,
    ):
        evidence_id = f"E{index:02d}"
        ref_map[str(entry.get("id"))] = evidence_id
        source = strongest_source(entry, by_id)
        if kind == "finding":
            title = truncate(str(entry.get("claim") or ""))
        else:
            title = truncate(f"{entry.get('meaning')}：{entry.get('value')}")
        record: dict[str, Any] = {
            "id": evidence_id,
            "title": title,
            "source_type": SOURCE_TYPE_MAP.get(str(source.get("type") or "other"), "other"),
            "locator": locator_of(source),
            "confidence": str(entry.get("confidence") or "medium"),
            "used_on_slides": [],
        }
        if source.get("publisher"):
            record["author"] = str(source["publisher"])
        if source.get("year"):
            record["date"] = str(source["year"])
        limitations = []
        if entry.get("conflict"):
            limitations.append("来源存在冲突，页面必须写成区间或加限定语")
        if str(source.get("tier") or "") == "D":
            limitations.append("仅有 D 级来源，只能作为用户观点引用")
        if limitations:
            record["limitation"] = "；".join(limitations)
        ledger.append(record)

    return ledger, ref_map


def apply_used_on_slides(spec: dict[str, Any], ref_map: dict[str, str], ledger: list[dict[str, Any]]) -> list[str]:
    """Fill used_on_slides; return the references that could not be resolved."""
    by_evidence = {str(e["id"]): e for e in ledger}
    unresolved: list[str] = []
    for slide in (spec.get("slides") or []):
        if not isinstance(slide, dict):
            continue
        slide_no = slide.get("id")
        if not isinstance(slide_no, int):
            continue
        for ref in slide.get("evidence_refs") or []:
            key = str(ref)
            evidence_id = key if key in by_evidence else ref_map.get(key)
            if evidence_id is None:
                unresolved.append(f"slide {slide_no}: evidence_ref {key!r} does not resolve to any pack finding/data_point")
                continue
            used = by_evidence[evidence_id]["used_on_slides"]
            if slide_no not in used:
                used.append(slide_no)
    for entry in ledger:
        entry["used_on_slides"] = sorted(entry["used_on_slides"])
    return unresolved


def compile_pack(pack: dict[str, Any], spec: dict[str, Any] | None) -> dict[str, Any]:
    ledger, ref_map = build_ledger(pack)
    unresolved: list[str] = []
    if spec is not None:
        unresolved = apply_used_on_slides(spec, ref_map, ledger)

    by_id = {str(s.get("id")): s for s in pack_validator.items(pack, "sources")}
    return {
        "version": "0.9",
        "generated_at": datetime.now(UTC).isoformat(),
        "topic": pack.get("topic"),
        "budget": pack.get("budget"),
        "ref_map": ref_map,
        "source_index": {
            sid: {
                "title": source.get("title"),
                "tier": source.get("tier"),
                "type": source.get("type"),
                "locator": locator_of(source),
                "publisher": source.get("publisher"),
                "year": source.get("year"),
            }
            for sid, source in sorted(by_id.items())
        },
        "evidence_ledger": ledger,
        "unresolved_retrieval": pack_validator.items(pack, "unresolved"),
        "unresolved_refs": unresolved,
    }


def render(report: dict[str, Any], path: Path) -> str:
    ledger = report["evidence_ledger"]
    blocked = bool(report["unresolved_refs"])
    state = "blocked" if blocked else "ok"
    return (
        f"research_pack_to_evidence: {state} — {len(ledger)} ledger entries from "
        f"{len(report['ref_map'])} pack entities | {len(report['source_index'])} sources | "
        f"unresolved refs {len(report['unresolved_refs'])} | map: {path}\n"
        + "".join(f"  [major] {line}\n" for line in report["unresolved_refs"])
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=Path, help="research-pack.json")
    parser.add_argument("--slide-spec", type=Path, help="draft spec whose evidence_refs should be resolved")
    parser.add_argument("--output", type=Path, help="defaults to <pack dir>/evidence-map.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.pack.is_file():
        print(f"research_pack_to_evidence: Research Pack does not exist: {args.pack}", file=sys.stderr)
        return 2

    pack = pack_validator.load(args.pack)
    verdict = pack_validator.validate(pack)
    if not verdict["ok"]:
        print(
            "research_pack_to_evidence: refusing to compile an invalid Research Pack "
            f"({verdict['counts']['blockers']} blockers). Run validate_research_pack.py first.",
            file=sys.stderr,
        )
        return 2

    spec = None
    if args.slide_spec:
        if not args.slide_spec.is_file():
            print(f"research_pack_to_evidence: Slide Spec does not exist: {args.slide_spec}", file=sys.stderr)
            return 2
        spec = pack_validator.load(args.slide_spec)

    report = compile_pack(pack, spec)
    report["provenance"] = {
        "research_pack": str(args.pack),
        "research_pack_sha256": sha256_file(args.pack),
        "validation_ok": True,
    }
    if args.slide_spec:
        report["provenance"]["slide_spec"] = str(args.slide_spec)
        report["provenance"]["slide_spec_sha256"] = sha256_file(args.slide_spec)

    report_path = args.output or (args.pack.parent / "evidence-map.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path), end="")
    return 2 if report["unresolved_refs"] else 0


if __name__ == "__main__":
    sys.exit(main())
