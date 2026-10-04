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
import datetime
import ipaddress
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Dependency-free on purpose: a research environment validates a trail without the
# PPTX runtime installed (see shared/retrieval_trail.py).
from shared.hashing import file_sha256 as sha256_file  # noqa: E402
from shared.research_evidence import evidence_issues  # noqa: E402
from shared.retrieval_trail import (  # noqa: E402
    UNKNOWN_PAYLOAD,
    degenerate_channels,
    executions_from_payloads,
    search_backend_never_executed,
)

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
    by_origin: dict[str, list[str]] = {}
    noted: set[str] = set()
    for source_id, entry in sources:
        origin = str(entry.get("origin_id") or "").strip()
        if origin:
            by_origin.setdefault(origin, []).append(source_id)
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
    for members in list(by_domain.values()) + list(by_declared.values()) + list(by_origin.values()):
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
    # New direct-to-document research proves retrieval through text/fetch bindings;
    # it need not invent a WebSearch query just to satisfy a legacy heuristic.
    if not queries and sources and len(user_files) != len(sources) and pack.get("evidence_contract") not in {"text-bound-v1", "source-backed-v1"}:
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
        if str(entry.get("status") or "") in {"unresolved", "located"}:
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
        if entity_ids and not entity_refs:
            out.append(
                issue(
                    "major",
                    "must_verify_unlinked",
                    f"must-verify claim {entry.get('claim')!r} is verified via bare source_ids while "
                    "the pack has findings/data_points — settle the claim as a finding or "
                    "data_point and link it with entity_ids; sources travel with the entity, "
                    "they are not re-typed into the closure ledger",
                    entry=entry.get("claim"),
                )
            )
        if refs and entity_refs:
            entity_sources = {
                str(ref) for eid in entity_refs for ref in entity_ids[eid].get("source_ids") or []
            }
            orphans = sorted(set(refs) - entity_sources)
            if orphans:
                out.append(
                    issue(
                        "major",
                        "must_verify_orphan_source",
                        f"must-verify claim {entry.get('claim')!r} lists sources {orphans} that no "
                        "linked entity rests on — either the entity is missing them or the "
                        "entry over-claims; keep one ledger",
                        entry=entry.get("claim"),
                    )
                )
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
            if entity_ids[ref].get("status") in {"located", "unresolved"}:
                out.append(issue("major", "must_verify_entity_not_usable", f"Claim links unusable entity {ref}"))
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


def _normalize_query(text: str) -> str:
    """Fold whitespace/case/punctuation: CJK queries have no word boundaries, and
    "2025年 光伏" vs "2025年光伏" is the same query typed twice — the audit must
    not call that two different questions."""
    lowered = str(text or "").lower()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", lowered)


def _unit_overlap(left: str, right: str) -> float:
    """Containment of the smaller char set in the larger — a word-boundary-free
    similarity that works for CJK. Two failed queries that restate the same
    主体+指标 share almost all characters even when re-worded."""
    a, b = set(left.replace(" ", "")), set(right.replace(" ", ""))
    if not a or not b:
        return 0.0
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    return len(smaller & larger) / len(smaller)


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _number_tokens(text: str) -> frozenset[str]:
    """Numeric tokens carry the query's target — 主体+指标+时间. Two queries whose
    number sets differ are different units (2025→2026 asks for different data),
    not a re-wording of the same question (owner-calibration, 2026-09-30)."""
    return frozenset(_NUMBER.findall(str(text or "")))


def _is_broad_shape(query: str) -> bool:
    """A query shaped like a pasted claim sentence: clause-stacked rather than
    one 主体+指标+时间 unit."""
    return len(query) > 60 or len(query.split()) > 6


def _coerce_trail(source: Any, label: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Accept a parsed mapping or a path to one — an unreadable trail is an advisory,
    never a crash. The audit is advisory by contract, and `validate()` is a public
    API (tools and tests call it directly), so a caller passing a path string or a
    half-written file must not take the whole validation down (0.23.8 reproved this).
    """
    if source is None:
        return None, []
    if isinstance(source, dict):
        return source, []
    if isinstance(source, (str, Path)):
        try:
            loaded = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, [
                issue(
                    "minor",
                    "retrieval_log_unreadable",
                    f"{label} {str(source)[:80]!r} could not be read ({type(exc).__name__}) — "
                    "the trail audit was skipped, not failed",
                )
            ]
        if isinstance(loaded, dict):
            return loaded, []
        return None, [
            issue(
                "minor",
                "retrieval_log_unreadable",
                f"{label} {str(source)[:80]!r} is not a JSON object — the trail audit was skipped",
            )
        ]
    return None, [
        issue(
            "minor",
            "retrieval_log_unreadable",
            f"{label} got {type(source).__name__}; expected a parsed JSON object or a path "
            "to one — the trail audit was skipped",
        )
    ]


def _payload_rows(search_payloads: Any) -> list[dict[str, Any]] | None:
    """Recomputed rows from hook-stored payloads, or None when the hook wrote nothing.

    None keeps the model's own `signature` field in force (older runs, fail-open when
    the field is absent). An unreadable file is also None: the audit skips rather than
    inventing an outage.
    """
    if search_payloads is None:
        return None
    payloads, problems = _coerce_trail(search_payloads, "search-payloads")
    if problems or not isinstance(payloads, dict):
        return None
    return executions_from_payloads(payloads.get("executions") or [])


def _backend_not_executed_issue(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed_n = sum(1 for row in rows if str(row.get("status") or "") == "failed")
    return issue(
        "minor",
        "search_backend_not_executed",
        f"all {failed_n} failed searches carry the `backend_not_executed` "
        "signature — the search backend did not execute in this run, so these are "
        "not evidence of absence; close the affected claims as `search_unavailable` "
        "and take the direct-source route (research-workflow §七)",
    )


def retrieval_audit_issues(
    pack: dict[str, Any],
    search_log: Any,
    fetch_report: Any,
    search_payloads: Any = None,
) -> list[dict[str, Any]]:
    """Advisory audit of the retrieval trail against the research-workflow §七 rules.

    These are the behavior rules that cannot be enforced at call time (query
    shape, no re-wording, result pages are not sources) — they are audited
    afterwards against the researcher's own telemetry: research/search-log.json
    and research/fetched/fetch-text-report.json (a parsed mapping or a path to
    one; an unreadable trail yields a minor flag, never an exception).
    Everything here is minor on purpose: the audit informs, it never blocks
    delivery, and it counts nothing — no quotas, per owner standing rule.
    """
    out: list[dict[str, Any]] = []
    search_log, search_load = _coerce_trail(search_log, "search-log")
    fetch_report, fetch_load = _coerce_trail(fetch_report, "fetch-report")
    payload_rows = _payload_rows(search_payloads) or []
    if any(row.get("signature") == UNKNOWN_PAYLOAD for row in payload_rows):
        out.append(issue("minor", "search_response_unknown",
                         "Some search response formats were not recognised; execution is uncertain, not a confirmed outage."))
    out.extend(search_load)
    out.extend(fetch_load)
    if search_log is not None:
        executions = search_log.get("search_executions") or []
        queries = [str(entry.get("query") or "") for entry in executions]
        normalized = [_normalize_query(q) for q in queries]
        if not executions:
            if pack.get("queries"):
                out.append(
                    issue(
                        "minor",
                        "search_log_empty",
                        "pack executed queries but search-log.json has no search_executions — "
                        "the retrieval audit has nothing to check (research-workflow §九)",
                    )
                )
            payload_rows = _payload_rows(search_payloads)
            if payload_rows and search_backend_never_executed(payload_rows):
                out.append(_backend_not_executed_issue(payload_rows))
        else:
            logged = {norm for norm in normalized if norm}
            unlogged = [
                str(q) for q in (pack.get("queries") or []) if _normalize_query(q) not in logged
            ]
            if unlogged:
                out.append(
                    issue(
                        "minor",
                        "query_unlogged",
                        f"{len(unlogged)} pack queries absent from search-log.json "
                        f"(first: {unlogged[0][:60]!r}) — log ⊇ queries is the audit contract",
                    )
                )
            seen: dict[str, int] = {}
            for norm in normalized:
                if norm:
                    seen[norm] = seen.get(norm, 0) + 1
            repeats = sorted(norm for norm, count in seen.items() if count > 1)
            if repeats:
                out.append(
                    issue(
                        "minor",
                        "duplicate_query",
                        f"{len(repeats)} query executed more than once in this run "
                        f"(first: {repeats[0][:60]!r}) — a repeat returns the same nothing",
                    )
                )
            failed = [
                (
                    _normalize_query(str(entry.get("query") or "")),
                    str(entry.get("query") or ""),
                    entry,
                )
                for entry in executions
                if str(entry.get("status") or "") == "failed"
            ]
            retried: list[tuple[str, str]] = []
            for index, (norm, raw, _entry) in enumerate(failed):
                if len(norm) < 9:
                    continue
                for other_norm, other_raw, _other in failed[index + 1 :]:
                    if _other.get("adjustment_reason") or _entry.get("adjustment_reason"):
                        continue
                    if len(other_norm) < 9 or _unit_overlap(norm, other_norm) < 0.8:
                        continue
                    if _number_tokens(raw) != _number_tokens(other_raw):
                        continue  # different numbers = a different unit, not a re-word
                    retried.append((norm, other_norm))
                    break
            if retried:
                out.append(
                    issue(
                        "minor",
                        "reworded_retry",
                        f"{len(retried)} failed queries restate an earlier failed one "
                        f"(e.g. {retried[0][0][:50]!r} ≈ {retried[0][1][:50]!r}) — re-wording "
                        "is not a new channel; switch channel (research-workflow §七)",
                    )
                )
            # Over-broad is attributed post-hoc, never guessed: only a query that
            # is BOTH claim-shaped AND failed counts — a successful long query was
            # the n=1 sample's clearest false positive (a 49-char hit on the first
            # try), and flagging successes would train nobody.
            broad = [
                str(entry.get("query") or "")
                for entry in executions
                if str(entry.get("status") or "") == "failed"
                and _is_broad_shape(str(entry.get("query") or ""))
            ]
            if broad:
                out.append(
                    issue(
                        "minor",
                        "over_broad_query",
                        f"{len(broad)} queries look like pasted claim sentences rather than one "
                        f"answerable unit (e.g. {broad[0][:60]!r}) — cut to 主体+指标+时间 "
                        "(research-workflow §七 查询构造)",
                    )
                )
            payload_rows = _payload_rows(search_payloads)
            verdict_rows = payload_rows if payload_rows is not None else executions
            if search_backend_never_executed(verdict_rows):
                out.append(_backend_not_executed_issue(verdict_rows))
    if fetch_report is not None:
        records = fetch_report.get("records") or []
        serp = [str(record.get("url") or "") for record in records if record.get("host_class") == "search_engine"]
        if serp:
            out.append(
                issue(
                    "minor",
                    "result_page_fetched",
                    f"{len(serp)} fetches were search-result pages ({serp[0][:60]!r}…) — locators "
                    "only; never citable sources (research-workflow §七)",
                )
            )
        # Recomputed from `raw_sha256` rather than read from the tool's own
        # `degenerate_channels` field, so a report written before the verdict existed
        # audits the same way and no writer can suppress it by omitting a key.
        degenerate = degenerate_channels(records)
        if degenerate:
            first = degenerate[0]
            out.append(
                issue(
                    "minor",
                    "degenerate_channel",
                    f"{len(degenerate)} endpoint(s) answered distinct requests with one identical "
                    f"body (e.g. {str(first['channel'])[:60]!r}, {first['distinct_requests']} "
                    "requests) — judge that channel once and leave it; its `t=` / `page=` / `q=` "
                    "variations are the same channel (research-workflow §七)",
                )
            )
    return out


def validate(
    pack: dict[str, Any],
    *,
    search_log: Any = None,
    fetch_report: Any = None,
    search_payloads: Any = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    # Verification strength belongs to the task, not to a model-written entity.
    if work_dir and (work_dir / "research-task.json").is_file():
        import copy
        try:
            task = json.loads((work_dir / "research-task.json").read_text(encoding="utf-8"))
            levels = {c["id"]: c.get("verification", "source") for c in task["claims"]}
            pack = copy.deepcopy(pack)
            for key in ("findings", "data_points", "quotes"):
                for entity in pack.get(key, []):
                    if entity.get("claim_id") in levels:
                        entity["verification"] = levels[entity["claim_id"]]
        except (OSError, ValueError, TypeError, KeyError):
            pass  # apply_task reports malformed task contracts to every CLI consumer.
    problems = (
        schema_issues(pack)
        + id_issues(pack)
        + reference_issues(pack)
        + source_kind_issues(pack)
        + cross_validation_issues(pack)
        + contract_issues(pack)
        + must_verify_issues(pack)
        + retrieval_audit_issues(pack, search_log, fetch_report, search_payloads)
        + hygiene_issues(pack)
        + evidence_issues(pack, fetch_report, work_dir)
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
        "evidence_checked": pack.get("evidence_contract") == "text-bound-v1" and not any(
            p["code"].startswith("evidence_") for p in problems
        ),
        "completion": {
            "verified": sum(c.get("status") == "verified" for c in items(pack, "must_verify")),
            "unresolved": sum(c.get("status") == "unresolved" for c in items(pack, "must_verify")),
        },
    }


# Codes produced by retrieval_audit_issues; exported so the evidence compiler and
# the pipeline can surface the advisories downstream — a minor nobody reads is a
# minor that does not exist (owner fix 2, 2026-09-30).
RETRIEVAL_ADVISORY_CODES = frozenset(
    {
        "query_unlogged",
        "search_log_empty",
        "duplicate_query",
        "reworded_retry",
        "over_broad_query",
        "result_page_fetched",
        "retrieval_log_unreadable",
        "degenerate_channel",
        "search_backend_not_executed",
        "search_response_unknown",
    }
)


def retrieval_advisories(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The retrieval-audit minors inside a validation report, in stable order."""
    found = [p for p in report.get("problems", []) if str(p.get("code") or "") in RETRIEVAL_ADVISORY_CODES]
    return sorted(found, key=lambda p: (str(p.get("code")), str(p.get("message"))))


def retrieval_advisory_line(report: dict[str, Any]) -> str:
    """One-line summary every consumer prints; empty when the audit is clean."""
    advisories = retrieval_advisories(report)
    if not advisories:
        return ""
    tally: dict[str, int] = {}
    for item in advisories:
        code = str(item.get("code"))
        tally[code] = tally.get(code, 0) + 1
    joined = ", ".join(f"{code}×{count}" if count > 1 else code for code, count in sorted(tally.items()))
    return f"retrieval audit — {len(advisories)} advisory: {joined}"


def render(report: dict[str, Any], path: Path, *, verbose: bool, max_items: int) -> str:
    inv = report["inventory"]
    counts = report["counts"]
    state = "ok" if report["ok"] else "blocked"
    lines = [
        f"validate_research_pack: {state} — blockers {counts['blockers']} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"{inv['findings']}F/{inv['data_points']}D/{inv['quotes']}Q/{inv['sources']}S/"
        f"{inv['conflicts']}C/{inv['visual_candidates']}V/{inv['unresolved']}U | "
        f"budget {report['budget']} | delivery {report.get('delivery_status', 'legacy')} | report: {path}"
    ]
    audit_line = retrieval_advisory_line(report)
    if audit_line:
        lines.append(f"  {audit_line}")
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
    parser.add_argument("--task", type=Path, help="research-task.json; enforces claim coverage and new evidence bindings")
    parser.add_argument(
        "--search-log",
        type=Path,
        help="research/search-log.json — audits query shape, repeats and re-worded retries (all minor)",
    )
    parser.add_argument(
        "--fetch-report",
        type=Path,
        help="research/fetched/fetch-text-report.json — audits result-page fetches among evidence reads (all minor)",
    )
    args = parser.parse_args(argv)

    if not args.pack.is_file():
        print(f"validate_research_pack: Research Pack does not exist: {args.pack}", file=sys.stderr)
        return 2

    # Direct fetch is valid without an invented search query. Consumers and the
    # smoke harness can omit audit flags; use this pack's existing receipts.
    if args.search_log is None:
        candidate = args.pack.parent / "research/search-log.json"
        if candidate.is_file():
            args.search_log = candidate
    if args.fetch_report is None:
        candidate = args.pack.parent / "research/fetched/fetch-text-report.json"
        if candidate.is_file():
            args.fetch_report = candidate

    search_log = None
    search_payloads = None
    if args.search_log:
        search_log = (
            json.loads(args.search_log.read_text(encoding="utf-8"))
            if args.search_log.is_file()
            else {"search_executions": []}
        )
        payloads_path = args.search_log.parent / "search-payloads.json"
        if payloads_path.is_file():
            search_payloads = json.loads(payloads_path.read_text(encoding="utf-8"))
    fetch_report = None
    if args.fetch_report and args.fetch_report.is_file():
        fetch_report = json.loads(args.fetch_report.read_text(encoding="utf-8"))

    pack = load(args.pack)
    report = validate(
        pack,
        search_log=search_log,
        fetch_report=fetch_report,
        search_payloads=search_payloads,
        work_dir=args.pack.resolve().parent,
    )
    from research_task_binding import apply_task
    apply_task(report, pack, args.pack.resolve().parent, args.task)
    from shared.research_io import atomic_json
    atomic_json(args.pack.parent / "research-progress.json", {
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "pack_sha256": sha256_file(args.pack),
        "validation_ok": report["ok"],
        "delivery_status": report["delivery_status"],
        "core_gaps": report["core_gaps"],
        "pending_claims": report["pending_claims"],
        "claims": pack.get("must_verify", []),
    })
    report["research_pack"] = str(args.pack.resolve())
    report["research_pack_sha256"] = sha256_file(args.pack)
    if args.search_log or args.fetch_report:
        binding: dict[str, Any] = {}
        for label, path in (("search_log", args.search_log), ("fetch_report", args.fetch_report)):
            if path:
                binding[label] = {
                    "path": str(path.resolve()),
                    "sha256": sha256_file(path) if path.is_file() else None,
                }
        report["retrieval"] = binding
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
