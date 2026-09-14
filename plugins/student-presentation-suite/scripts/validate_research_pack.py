#!/usr/bin/env python3
"""Validate a Research Pack against the schema and the research contract.

`research-pack.schema.json` only pins the shape. The rules that actually keep a
deck honest are semantic, and they live here:

  R1 引用完整性   每个 finding / data_point / quote 的 source_ids 必须存在
  R2 来源分级     high 置信度的 finding 需要 S/A 级来源；data_point 至少 S/A/B
  R3 交叉验证     high 置信度的 data_point 需要 >=2 个独立来源；
                  conflict=true 的条目必须 confidence=low 且有对应 conflicts 记录
  R4 未被引用     列了却没人用的来源，先提醒再决定删不删
  R5 预算         queries / sources 不得超过所选档位的上限
  R6 Tier D       tier D 来源不得支撑 medium 及以上的结论
  R7 可追溯       每个来源必须有 url 或 locator

检索受阻必须写进 `unresolved`，不许静默降级——这是上一次真实运行里
"WebFetch 被域名策略拦截、只能拿搜索摘要"却没有留下记录的那条教训。

Exit codes: 0 = ok（可能有 minor）, 2 = 存在 blocker。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "references" / "research-pack.schema.json"

BUDGET_CAPS = {
    "simple": {"queries": 3, "sources": 5},
    "standard": {"queries": 8, "sources": 12},
    "deep": {"queries": 15, "sources": 25},
}
STRONG_TIERS = {"S", "A"}
ACCEPTABLE_DATA_TIERS = {"S", "A", "B"}
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
# A community post cannot be tier S no matter who wrote it. Without a ceiling the
# tier field is self-assigned and therefore meaningless.
TIER_CEILING_BY_TYPE = {
    "community": "D",
    "personal-blog": "D",
    "vendor-blog": "C",
    "news": "B",
    "industry-report": "B",
    "other": "B",
    "research-institute": "A",
    "university": "A",
    "international-organization": "A",
    "company-filing": "A",
    "paper": "S",
    "law-and-regulation": "S",
    "official-document": "S",
    "official-database": "S",
    "standard": "S",
    "user-file": "S",
}
ID_PATTERNS = {
    "findings": re.compile(r"^F\d{2,}$"),
    "data_points": re.compile(r"^D\d{2,}$"),
    "quotes": re.compile(r"^Q\d{2,}$"),
    "sources": re.compile(r"^S\d{2,}$"),
    "conflicts": re.compile(r"^C\d{2,}$"),
    "visual_candidates": re.compile(r"^V\d{2,}$"),
}


def load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else _load_yaml(text)
    if not isinstance(value, dict):
        raise SystemExit("Research Pack root must be an object.")
    return value


def _load_yaml(text: str) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyYAML is required for YAML Research Packs.") from exc
    return yaml.safe_load(text)


def issue(severity: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def items(pack: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = pack.get(key)
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []


def schema_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        # Fail closed. Treating "cannot verify the shape" as "shape is fine" is how
        # an unvalidated pack reaches the deck.
        return [
            issue(
                "critical",
                "schema_validator_unavailable",
                "jsonschema is not installed, so the Research Pack shape cannot be verified. "
                "Install the declared dependency (requirements.txt) instead of treating an unverified pack as valid.",
            )
        ]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    out: list[dict[str, Any]] = []
    for error in sorted(validator.iter_errors(pack), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        out.append(issue("critical", "schema_violation", f"{location}: {error.message}"))
    return out


def id_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, pattern in ID_PATTERNS.items():
        seen: set[str] = set()
        for entry in items(pack, key):
            value = str(entry.get("id") or "")
            if not pattern.match(value):
                out.append(issue("critical", "bad_id", f"{key} id {value!r} does not match {pattern.pattern}", entry=value))
            elif value in seen:
                out.append(issue("critical", "duplicate_id", f"{key} id {value!r} is used twice", entry=value))
            seen.add(value)
    return out


def reference_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R1 + R7: every reference resolves, every source is reachable."""
    out: list[dict[str, Any]] = []
    source_ids = {str(entry.get("id")) for entry in items(pack, "sources")}

    for key, field in (("findings", "source_ids"), ("data_points", "source_ids")):
        for entry in items(pack, key):
            refs = entry.get(field) or []
            missing = [ref for ref in refs if str(ref) not in source_ids]
            if missing:
                out.append(
                    issue("critical", "unknown_source_ref", f"{key} {entry.get('id')} references missing sources {missing}", entry=entry.get("id"))
                )
    for entry in items(pack, "quotes"):
        if str(entry.get("source_id")) not in source_ids:
            out.append(
                issue("critical", "unknown_source_ref", f"quote {entry.get('id')} references missing source {entry.get('source_id')!r}", entry=entry.get("id"))
            )
    for entry in items(pack, "conflicts"):
        for sub in entry.get("entries") or []:
            if isinstance(sub, dict) and str(sub.get("source_id")) not in source_ids:
                out.append(
                    issue("critical", "unknown_source_ref", f"conflict {entry.get('id')} references missing source {sub.get('source_id')!r}", entry=entry.get("id"))
                )

    ref_pools = {
        "source_ids": source_ids,
        "finding_ids": {str(entry.get("id")) for entry in items(pack, "findings")},
        "data_point_ids": {str(entry.get("id")) for entry in items(pack, "data_points")},
    }
    for entry in items(pack, "visual_candidates"):
        for field, pool in ref_pools.items():
            for ref in entry.get(field) or []:
                if str(ref) not in pool:
                    # Major, not minor: a dangling reference here means a chart is
                    # built from data that does not exist in the pack.
                    out.append(
                        issue(
                            "major",
                            "unknown_visual_ref",
                            f"visual_candidate {entry.get('id')} references missing {field.removesuffix('_ids')} {ref!r}",
                            entry=entry.get("id"),
                        )
                    )

    for entry in items(pack, "sources"):
        if not str(entry.get("url") or "").strip() and not str(entry.get("locator") or "").strip():
            out.append(
                issue("major", "source_not_traceable", f"source {entry.get('id')} has neither url nor locator", entry=entry.get("id"))
            )
    return out


def tier_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R2 + R6: the right evidence strength for the claim being made."""
    out: list[dict[str, Any]] = []
    tiers = {str(entry.get("id")): str(entry.get("tier") or "?") for entry in items(pack, "sources")}

    def tiers_of(entry: dict[str, Any]) -> set[str]:
        return {tiers.get(str(ref), "?") for ref in entry.get("source_ids") or []}

    for entry in items(pack, "findings"):
        used = tiers_of(entry)
        if entry.get("confidence") == "high" and not (used & STRONG_TIERS):
            out.append(
                issue("major", "weak_source_for_high_confidence", f"finding {entry.get('id')} claims high confidence but has no S/A source", entry=entry.get("id"), tiers=sorted(used))
            )
        if entry.get("confidence") in {"high", "medium"} and used and used <= {"D"}:
            out.append(
                issue("major", "tier_d_cannot_support_claim", f"finding {entry.get('id')} rests only on tier D sources", entry=entry.get("id"))
            )

    for entry in items(pack, "data_points"):
        used = tiers_of(entry)
        if not (used & ACCEPTABLE_DATA_TIERS):
            out.append(
                issue("major", "weak_source_for_data_point", f"data_point {entry.get('id')} has no S/A/B source", entry=entry.get("id"), tiers=sorted(used))
            )
    return out


def cross_validation_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R3 + conflict bookkeeping + genuine independence."""
    out: list[dict[str, Any]] = []
    groups = {str(entry.get("id")): str(entry.get("independence_group") or "") for entry in items(pack, "sources")}
    conflict_targets: set[str] = set()
    for entry in items(pack, "conflicts"):
        for ref in entry.get("affected_ids") or []:
            conflict_targets.add(str(ref))

    for entry in items(pack, "data_points"):
        refs = [str(ref) for ref in entry.get("source_ids") or []]
        flagged = bool(entry.get("conflict"))
        if entry.get("confidence") == "high":
            if len(refs) < 2:
                out.append(
                    issue("major", "high_confidence_needs_cross_check", f"data_point {entry.get('id')} claims high confidence from a single source", entry=entry.get("id"))
                )
            else:
                # Two rows are not two sources. A wire story and a site carrying
                # that same wire story share one origin and prove nothing.
                distinct = {groups.get(ref) or f"?{ref}" for ref in refs}
                if len(distinct) < 2:
                    out.append(
                        issue(
                            "major",
                            "sources_are_not_independent",
                            f"data_point {entry.get('id')} claims high confidence but its {len(refs)} sources "
                            f"share independence_group {sorted(distinct)}",
                            entry=entry.get("id"),
                        )
                    )
        if flagged and entry.get("confidence") != "low":
            out.append(
                issue("major", "conflict_must_downgrade_confidence", f"data_point {entry.get('id')} is flagged conflicting but not lowered to low confidence", entry=entry.get("id"))
            )
        if flagged and str(entry.get("id")) not in conflict_targets:
            out.append(
                issue("major", "conflict_not_recorded", f"data_point {entry.get('id')} is flagged conflicting but no conflicts entry references it", entry=entry.get("id"))
            )

    for entry in items(pack, "findings"):
        if entry.get("conflict") and entry.get("confidence") != "low":
            out.append(
                issue("major", "conflict_must_downgrade_confidence", f"finding {entry.get('id')} is flagged conflicting but not lowered to low confidence", entry=entry.get("id"))
            )
        if entry.get("conflict") and str(entry.get("id")) not in conflict_targets:
            out.append(
                issue("major", "conflict_not_recorded", f"finding {entry.get('id')} is flagged conflicting but no conflicts entry references it", entry=entry.get("id"))
            )
    return out


def budget_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R5: no searching twenty pages for one sentence."""
    out: list[dict[str, Any]] = []
    band = str(pack.get("budget") or "")
    caps = BUDGET_CAPS.get(band)
    if caps is None:
        return out
    queries = pack.get("queries") or []
    sources = pack.get("sources") or []
    if len(queries) > caps["queries"]:
        out.append(
            issue("major", "budget_exceeded", f"{len(queries)} queries exceed the {band} cap of {caps['queries']}", budget=band)
        )
    if len(sources) > caps["sources"]:
        out.append(
            issue("major", "budget_exceeded", f"{len(sources)} sources exceed the {band} cap of {caps['sources']}", budget=band)
        )
    return out


def hygiene_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R4 + unresolved bookkeeping."""
    out: list[dict[str, Any]] = []
    cited: set[str] = set()
    for key in ("findings", "data_points"):
        for entry in items(pack, key):
            cited.update(str(ref) for ref in entry.get("source_ids") or [])
    for entry in items(pack, "quotes"):
        cited.add(str(entry.get("source_id")))
    for entry in items(pack, "conflicts"):
        for sub in entry.get("entries") or []:
            if isinstance(sub, dict):
                cited.add(str(sub.get("source_id")))

    for entry in items(pack, "sources"):
        if str(entry.get("id")) not in cited:
            out.append(issue("minor", "unused_source", f"source {entry.get('id')} is listed but never used", entry=entry.get("id")))

    for gap in items(pack, "knowledge_gaps"):
        if gap.get("unresolved") and not gap.get("reason"):
            out.append(issue("minor", "unresolved_gap_without_reason", f"knowledge gap {gap.get('claim')!r} is unresolved without a reason"))
    return out


def contract_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Claims the pack makes about itself that must be checkable, not just asserted."""
    out: list[dict[str, Any]] = []
    sources = items(pack, "sources")
    queries = pack.get("queries") or []

    # A tier is self-assigned, so cap it by source type.
    for entry in sources:
        source_type = str(entry.get("type") or "")
        tier = str(entry.get("tier") or "")
        ceiling = TIER_CEILING_BY_TYPE.get(source_type)
        if ceiling and tier in TIER_ORDER and TIER_ORDER[tier] < TIER_ORDER[ceiling]:
            out.append(
                issue(
                    "major",
                    "tier_above_type_ceiling",
                    f"source {entry.get('id')} is type {source_type!r} but claims tier {tier} "
                    f"(ceiling {ceiling})",
                    entry=entry.get("id"),
                )
            )

    # D mode is a real contract, not a note in the docs: no queries means the only
    # possible provenance is the user's own material, and vice versa.
    user_files = [entry for entry in sources if str(entry.get("type")) == "user-file"]
    if not queries and sources and len(user_files) != len(sources):
        others = sorted(str(entry.get("id")) for entry in sources if str(entry.get("type")) != "user-file")
        out.append(
            issue(
                "major",
                "sources_without_queries",
                f"no queries were recorded, so every source must be user-file; these are not: {others}",
            )
        )
    if queries and user_files and len(user_files) == len(sources):
        out.append(
            issue(
                "major",
                "user_file_only_pack_recorded_queries",
                "every source is user-file but queries were recorded — D mode must not search",
            )
        )

    # Degradation has to be discoverable. A low-confidence entry with no explanation
    # is indistinguishable from one that was simply guessed.
    for key in ("findings", "data_points"):
        for entry in items(pack, key):
            if entry.get("confidence") == "low" and not str(entry.get("notes") or "").strip():
                out.append(
                    issue(
                        "major",
                        "low_confidence_without_reason",
                        f"{key[:-1]} {entry.get('id')} is low confidence but carries no notes explaining why",
                        entry=entry.get("id"),
                    )
                )

    for entry in items(pack, "unresolved"):
        if not str(entry.get("impact") or "").strip():
            out.append(
                issue("major", "blocked_retrieval_without_impact", f"unresolved query {entry.get('query')!r} does not say how it affects the deck")
            )
    return out


def validate(pack: dict[str, Any]) -> dict[str, Any]:
    problems = (
        schema_issues(pack)
        + id_issues(pack)
        + reference_issues(pack)
        + tier_issues(pack)
        + cross_validation_issues(pack)
        + contract_issues(pack)
        + budget_issues(pack)
        + hygiene_issues(pack)
    )
    blockers = [p for p in problems if p["severity"] in {"critical", "major"}]
    return {
        "ok": not blockers,
        "version": pack.get("version"),
        "topic": pack.get("topic"),
        "budget": pack.get("budget"),
        "counts": {
            "blockers": len(blockers),
            "critical": sum(1 for p in problems if p["severity"] == "critical"),
            "major": sum(1 for p in problems if p["severity"] == "major"),
            "minor": sum(1 for p in problems if p["severity"] == "minor"),
        },
        "inventory": {
            "queries": len(pack.get("queries") or []),
            "findings": len(items(pack, "findings")),
            "data_points": len(items(pack, "data_points")),
            "sources": len(items(pack, "sources")),
            "conflicts": len(items(pack, "conflicts")),
            "visual_candidates": len(items(pack, "visual_candidates")),
            "unresolved": len(items(pack, "unresolved")),
        },
        "problems": problems,
    }


def render(report: dict[str, Any], path: Path, *, verbose: bool, max_items: int) -> str:
    inv = report["inventory"]
    counts = report["counts"]
    state = "ok" if report["ok"] else "blocked"
    lines = [
        f"validate_research_pack: {state} — blockers {counts['blockers']} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"{inv['findings']}F/{inv['data_points']}D/{inv['sources']}S/{inv['conflicts']}C/"
        f"{inv['visual_candidates']}V/{inv['unresolved']}U | budget {report['budget']} | report: {path}"
    ]
    visible = report["problems"] if verbose else [p for p in report["problems"] if p["severity"] in {"critical", "major"}]
    limit = len(visible) if max_items <= 0 else max_items
    for item in visible[:limit]:
        lines.append(f"  [{item['severity']}] {item['code']} — {item['message']}")
    hidden = len(visible) - min(len(visible), limit)
    if hidden > 0:
        lines.append(f"  … {hidden} more (full detail in {path})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=Path, help="research-pack.json (or .yaml)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="also list minor findings")
    parser.add_argument("--max-items", type=int, default=12)
    args = parser.parse_args(argv)

    if not args.pack.is_file():
        print(f"validate_research_pack: Research Pack does not exist: {args.pack}", file=sys.stderr)
        return 2

    report = validate(load(args.pack))
    report_path = args.output or (args.pack.parent / "research-pack-validation.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path, verbose=args.verbose, max_items=args.max_items), end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
