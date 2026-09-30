#!/usr/bin/env python3
"""Validate a Research Pack against the schema and the research contract.

`research-pack.schema.json` pins the shape; this module enforces the semantic
rules that keep a deck honest: reference integrity, source strength, independent
cross-validation, traceability, D-mode provenance and explicit bookkeeping for
degraded or blocked retrieval. Search/fetch counts are NOT capped here — the
owner forbids runtime count quotas (2026-09-28); the band is an advisory depth
tier, the stop condition is sufficient evidence, not an exhausted quota.

Exit codes: 0 = ok (minor findings allowed), 2 = blocker present.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "references" / "research-pack.schema.json"

# 等级（S/A/B/C/D）是页脚标注元数据，不构成任何门禁（owner 裁定 2026-09-30，
# 落地 v0.23.3）：硬门只有"可追溯"与"独立印证"。观点类来源（论坛/个人博客/厂商博客）
# 支撑的条目不拒绝，只发 minor advisory（opinion_only_support）——owner 裁定 2026-09-30：
# 太严格，不应直接拒绝；页面须把它表述为"社区/厂商观点"并标注来源类型。
OPINION_TYPES = {"community", "personal-blog", "vendor-blog"}

# 独立性按注册域名机械判定：同域（含 gov.cn/com.cn 这类两段后缀）默认并组，
# 因为同域页面通常源自同一个上游。声明相互独立必须写 independence_note，
# 并接受一条 minor advisory 供人工复核。
_TWO_PART_SUFFIXES = frozenset(
    {
        "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
        "co.uk", "org.uk", "ac.uk", "gov.uk",
        "com.hk", "org.hk", "edu.hk",
        "com.tw", "org.tw", "edu.tw", "gov.tw",
        "com.au", "net.au", "org.au", "edu.au",
        "co.jp", "ne.jp", "or.jp", "ac.jp",
    }
)
ID_PATTERNS = {
    "findings": re.compile(r"^F\d{2,}$"),
    "data_points": re.compile(r"^D\d{2,}$"),
    "quotes": re.compile(r"^Q\d{2,}$"),
    "sources": re.compile(r"^S\d{2,}$"),
    "conflicts": re.compile(r"^C\d{2,}$"),
    "visual_candidates": re.compile(r"^V\d{2,}$"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        return [
            issue(
                "critical",
                "schema_validator_unavailable",
                "jsonschema is not installed, so the Research Pack shape cannot be verified. "
                "Install the declared dependency instead of treating an unverified pack as valid.",
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
                out.append(
                    issue(
                        "critical",
                        "bad_id",
                        f"{key} id {value!r} does not match {pattern.pattern}",
                        entry=value,
                    )
                )
            elif value in seen:
                out.append(issue("critical", "duplicate_id", f"{key} id {value!r} is used twice", entry=value))
            seen.add(value)
    return out


def reference_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R1 + R7: every reference resolves, every source is traceable."""
    out: list[dict[str, Any]] = []
    source_ids = {str(entry.get("id")) for entry in items(pack, "sources")}

    for key in ("findings", "data_points"):
        for entry in items(pack, key):
            refs = entry.get("source_ids") or []
            missing = [ref for ref in refs if str(ref) not in source_ids]
            if missing:
                out.append(
                    issue(
                        "critical",
                        "unknown_source_ref",
                        f"{key} {entry.get('id')} references missing sources {missing}",
                        entry=entry.get("id"),
                    )
                )
    for entry in items(pack, "quotes"):
        if str(entry.get("source_id")) not in source_ids:
            out.append(
                issue(
                    "critical",
                    "unknown_source_ref",
                    f"quote {entry.get('id')} references missing source {entry.get('source_id')!r}",
                    entry=entry.get("id"),
                )
            )
    for entry in items(pack, "conflicts"):
        for sub in entry.get("entries") or []:
            if isinstance(sub, dict) and str(sub.get("source_id")) not in source_ids:
                out.append(
                    issue(
                        "critical",
                        "unknown_source_ref",
                        f"conflict {entry.get('id')} references missing source {sub.get('source_id')!r}",
                        entry=entry.get("id"),
                    )
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
                issue(
                    "major",
                    "source_not_traceable",
                    f"source {entry.get('id')} has neither url nor locator",
                    entry=entry.get("id"),
                )
            )
    return out


def _registrable_domain(value: str) -> str | None:
    """Return the registrable domain of a URL (or URL-shaped locator), else None.

    Two-part public suffixes (gov.cn, com.cn, co.uk, ...) keep three labels, so
    www.gov.cn and www.nea.gov.cn land on different domains while two pages of
    one ministry collapse together.
    """
    text = str(value or "").strip()
    if "://" not in text:
        return None
    host = urllib.parse.urlsplit(text).hostname or ""
    host = host.lower().removesuffix(".")
    if not host or _host_is_ip(host):
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_PART_SUFFIXES:
        return ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return None


def _host_is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def source_kind_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Advisory: a number resting solely on opinion sources needs view wording.

    Tier letters are annotation metadata and are not checked at all. When a
    finding or data_point at medium/high confidence rests only on opinion
    sources (forums, personal blogs, vendor blogs) the pack still passes —
    owner ruling 2026-09-30: do not reject — but the entry is flagged minor so
    the slide attributes it as a community/vendor view instead of an
    established fact.
    """
    out: list[dict[str, Any]] = []
    types = {str(entry.get("id")): str(entry.get("type") or "?") for entry in items(pack, "sources")}
    for entity in ("findings", "data_points"):
        for entry in items(pack, entity):
            used = {types.get(str(ref), "?") for ref in entry.get("source_ids") or []}
            if (
                entry.get("confidence") in {"high", "medium"}
                and used
                and used <= OPINION_TYPES
            ):
                out.append(
                    issue(
                        "minor",
                        "opinion_only_support",
                        f"{entity[:-1]} {entry.get('id')} rests only on opinion sources "
                        f"{sorted(used)} — keep it, but the slide must attribute it as a "
                        "community/vendor view, not an established fact",
                        entry=entry.get("id"),
                    )
                )
    return out


def _effective_groups(pack: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Mechanical independence: same registrable domain collapses into one origin.

    Two relations merge sources into one origin: identical declared group, and
    identical registrable domain (gov.cn / com.cn suffixes handled) — same-domain
    pages usually descend from one upstream, so "two restatements" on one site
    cannot pose as two independent sources. A source may opt out of the domain
    relation with an ``independence_note`` explaining the exception; every use of
    that override is reported as a minor advisory for human review. Sources
    without a URL (user files, arXiv-style locators) merge only through their
    declared group, which is what the D-mode importer already keys on file names.
    """
    sources = [(str(entry.get("id")), entry) for entry in items(pack, "sources")]
    parent: dict[str, str] = {source_id: source_id for source_id, _ in sources}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        parent[find(left)] = find(right)

    by_domain: dict[str, list[str]] = {}
    declared_domains: dict[str, list[str]] = {}
    by_declared: dict[str, list[str]] = {}
    noted: set[str] = set()
    for source_id, entry in sources:
        if str(entry.get("independence_note") or "").strip():
            noted.add(source_id)
        domain = _registrable_domain(str(entry.get("url") or "")) or _registrable_domain(
            str(entry.get("locator") or "")
        )
        if domain:
            declared_domains.setdefault(domain, []).append(source_id)
            if source_id not in noted:
                by_domain.setdefault(domain, []).append(source_id)
        by_declared.setdefault(str(entry.get("independence_group") or source_id), []).append(
            source_id
        )
    for members in list(by_domain.values()) + list(by_declared.values()):
        for other in members[1:]:
            union(members[0], other)

    groups: dict[str, str] = {}
    members_by_root: dict[str, list[str]] = {}
    for source_id, _entry in sources:
        members_by_root.setdefault(find(source_id), []).append(source_id)
    entries_by_id = dict(sources)
    for members in members_by_root.values():
        labels = {
            f"declared:{str(entries_by_id[source_id].get('independence_group') or source_id)}"
            for source_id in members
        }
        for source_id in members:
            domain = _registrable_domain(
                str(entries_by_id[source_id].get("url") or "")
            ) or _registrable_domain(str(entries_by_id[source_id].get("locator") or ""))
            if domain:
                labels.add(f"domain:{domain}")
            groups[source_id] = sorted(labels)[0] if labels else f"source:{members[0]}"

    overrides: list[dict[str, Any]] = []
    for domain, ids in sorted(declared_domains.items()):
        if len(ids) > 1 and noted.intersection(ids):
            overrides.append(
                issue(
                    "minor",
                    "independence_override_used",
                    f"sources {sorted(ids)} share domain {domain!r} "
                    "but claim independence via independence_note — verify the exception is real",
                )
            )
    return groups, overrides


def cross_validation_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """R3 + conflict bookkeeping + genuine independence."""
    out: list[dict[str, Any]] = []
    groups, overrides = _effective_groups(pack)
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
                    issue(
                        "major",
                        "high_confidence_needs_cross_check",
                        f"data_point {entry.get('id')} claims high confidence from a single source",
                        entry=entry.get("id"),
                    )
                )
            else:
                distinct = {groups.get(ref) or f"?{ref}" for ref in refs}
                if len(distinct) < 2:
                    out.append(
                        issue(
                            "major",
                            "sources_are_not_independent",
                            f"data_point {entry.get('id')} claims high confidence but its {len(refs)} sources "
                            f"collapse to one independent origin {sorted(distinct)} — same registrable "
                            "domain counts as one source; set independence_note to claim an exception",
                            entry=entry.get("id"),
                        )
                    )
        if flagged and entry.get("confidence") != "low":
            out.append(
                issue(
                    "major",
                    "conflict_must_downgrade_confidence",
                    f"data_point {entry.get('id')} is flagged conflicting but not lowered to low confidence",
                    entry=entry.get("id"),
                )
            )
        if flagged and str(entry.get("id")) not in conflict_targets:
            out.append(
                issue(
                    "major",
                    "conflict_not_recorded",
                    f"data_point {entry.get('id')} is flagged conflicting but no conflicts entry references it",
                    entry=entry.get("id"),
                )
            )

    for entry in items(pack, "findings"):
        if entry.get("conflict") and entry.get("confidence") != "low":
            out.append(
                issue(
                    "major",
                    "conflict_must_downgrade_confidence",
                    f"finding {entry.get('id')} is flagged conflicting but not lowered to low confidence",
                    entry=entry.get("id"),
                )
            )
        if entry.get("conflict") and str(entry.get("id")) not in conflict_targets:
            out.append(
                issue(
                    "major",
                    "conflict_not_recorded",
                    f"finding {entry.get('id')} is flagged conflicting but no conflicts entry references it",
                    entry=entry.get("id"),
                )
            )
    return out + overrides


def hygiene_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
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
            out.append(
                issue(
                    "minor",
                    "unused_source",
                    f"source {entry.get('id')} is listed but never used",
                    entry=entry.get("id"),
                )
            )
    return out


def contract_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Claims the pack makes about itself that must be checkable."""
    out: list[dict[str, Any]] = []
    sources = items(pack, "sources")
    queries = pack.get("queries") or []

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
                issue(
                    "major",
                    "blocked_retrieval_without_impact",
                    f"unresolved query {entry.get('query')!r} does not say how it affects the deck",
                )
            )
    return out


def must_verify_issues(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Pre-declared stop condition: every must-verify claim closed or named.

    The researcher lists the claims that actually decide the deck BEFORE
    retrieval starts and stops when every one is closed — a leftover budget is
    not a goal (2026-09-22: one researcher spent 42 minutes / 4.0M tokens
    largely beyond sufficiency). Closure semantics live canonically in
    references/research-workflow.md §七: a verified entry needs traceable,
    conflict-free support — which since 0.23.6 can be declared via ``entity_ids``
    pointing at the findings/data_points that settle it, so the pack does not
    re-type the same sources in two ledgers.

    Severity: only the *count* is a minor everywhere (owner 2026-09-30 — a small
    deck must not pad claims to reach a quota); malformed entries, uncovered
    claims and dangling references stay major because they break the stop
    condition itself.
    """
    entries = pack.get("must_verify")
    if entries is None:
        return []
    if not isinstance(entries, list):
        return [issue("major", "must_verify_invalid", "must_verify must be a list of claim entries")]
    out: list[dict[str, Any]] = []
    if not 3 <= len(entries) <= 5:
        out.append(
            issue(
                "minor",
                "must_verify_count",
                f"must_verify declares {len(entries)} claims; 3-5 keep the stop condition "
                "focused (fewer usually means the deck's load-bearing claims were not all "
                "declared) — advisory, not a blocker",
            )
        )
    known_sources = {str(entry.get("id")) for entry in items(pack, "sources")}
    entity_ids = {
        str(entry.get("id")): entry
        for key in ("findings", "data_points")
        for entry in items(pack, key)
    }
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("claim") or "").strip():
            out.append(issue("major", "must_verify_claim_missing", "each must_verify entry needs a claim statement"))
            continue
        entity_refs = [str(value) for value in (entry.get("entity_ids") or [])]
        unknown_entities = sorted(set(entity_refs) - set(entity_ids))
        if unknown_entities:
            out.append(
                issue(
                    "major",
                    "must_verify_unknown_entity",
                    f"must-verify claim {entry.get('claim')!r} references unknown entities "
                    f"{unknown_entities} (entity_ids must name findings F…/data_points D…)",
                    entry=entry.get("claim"),
                )
            )
            entity_refs = [ref for ref in entity_refs if ref in entity_ids]
        if str(entry.get("status") or "") == "unresolved":
            continue
        refs = [str(value) for value in (entry.get("source_ids") or [])]
        covered = bool(refs) or bool(entity_refs)
        if not covered:
            out.append(
                issue(
                    "major",
                    "must_verify_uncovered",
                    f"must-verify claim {entry.get('claim')!r} has no source_ids/entity_ids and is "
                    "not marked unresolved — cover it with sources or record it as unresolved "
                    "(keep whatever source_ids you did obtain and name the missing primary; "
                    "that is the stop condition, not more searching)",
                )
            )
            continue
        missing = sorted(set(refs) - known_sources)
        if missing:
            out.append(
                issue(
                    "major",
                    "must_verify_unknown_source",
                    f"must-verify claim {entry.get('claim')!r} references unknown sources {missing}",
                    entry=entry.get("claim"),
                )
            )
        for ref in entity_refs:
            if entity_ids[ref].get("conflict"):
                out.append(
                    issue(
                        "major",
                        "must_verify_conflicted_entity",
                        f"must-verify claim {entry.get('claim')!r} is marked verified but linked "
                        f"entity {ref} is flagged conflicting — resolve or downgrade the claim",
                        entry=entry.get("claim"),
                    )
                )
    return out


def validate(pack: dict[str, Any]) -> dict[str, Any]:
    problems = (
        schema_issues(pack)
        + id_issues(pack)
        + reference_issues(pack)
        + source_kind_issues(pack)
        + cross_validation_issues(pack)
        + contract_issues(pack)
        + must_verify_issues(pack)
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
            "quotes": len(items(pack, "quotes")),
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
        f"{inv['findings']}F/{inv['data_points']}D/{inv['quotes']}Q/{inv['sources']}S/"
        f"{inv['conflicts']}C/{inv['visual_candidates']}V/{inv['unresolved']}U | "
        f"budget {report['budget']} | report: {path}"
    ]
    visible = (
        report["problems"]
        if verbose
        else [p for p in report["problems"] if p["severity"] in {"critical", "major"}]
    )
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
    report["research_pack"] = str(args.pack.resolve())
    report["research_pack_sha256"] = sha256_file(args.pack)
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
