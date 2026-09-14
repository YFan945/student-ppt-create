#!/usr/bin/env python3
"""Compile a validated Research Pack into a deterministic Evidence Ledger and Slide Spec.

Canonical allocation:

    findings sorted by id -> data_points sorted by id -> quotes sorted by id
    F/D/Q ids            -> E01, E02, ...

When a draft Slide Spec is supplied, its evidence_refs may use either Research
Pack ids (F/D/Q) or already allocated E ids. The compiler rewrites those refs,
recomputes used_on_slides, replaces the ledger with the generated ledger, and can
write a non-destructive compiled Slide Spec. No model hand-copy step is required.

A Research Pack that fails validate_research_pack.py is refused. If a validation
report is supplied, it must be passing and hash-bound to the exact pack. The
resulting evidence map records the pack, validation and Slide Spec hashes so the
freeze gate can verify one provenance chain rather than three unrelated files.

Exit codes: 0 = compiled, 2 = invalid/stale input or unresolved evidence refs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import validate_research_pack as pack_validator  # noqa: E402

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
SCHEMA_PATH = HERE.parent / "references" / "evidence-map.schema.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object: {path}")
    return value


def write_structured(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required to write a YAML Slide Spec.") from exc
        path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def truncate(text: str, limit: int = TITLE_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def source_refs(kind: str, entry: dict[str, Any]) -> list[str]:
    if kind == "quote":
        source_id = str(entry.get("source_id") or "")
        return [source_id] if source_id else []
    return [str(ref) for ref in entry.get("source_ids") or []]


def strongest_source(refs: list[str], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = [by_id[ref] for ref in refs if ref in by_id]
    if not candidates:
        return {}
    return sorted(
        candidates,
        key=lambda source: (
            TIER_RANK.get(str(source.get("tier") or "?"), 5),
            str(source.get("id") or ""),
        ),
    )[0]


def locator_of(source: dict[str, Any]) -> str:
    return str(source.get("url") or source.get("locator") or "").strip() or "(no locator)"


def quote_confidence(source: dict[str, Any]) -> str:
    tier = str(source.get("tier") or "?")
    if tier in {"S", "A"}:
        return "high"
    if tier in {"B", "C"}:
        return "medium"
    return "low"


def build_ledger(pack: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_id = {str(source.get("id")): source for source in pack_validator.items(pack, "sources")}
    findings = sorted(pack_validator.items(pack, "findings"), key=lambda entry: str(entry.get("id")))
    data_points = sorted(pack_validator.items(pack, "data_points"), key=lambda entry: str(entry.get("id")))
    quotes = sorted(pack_validator.items(pack, "quotes"), key=lambda entry: str(entry.get("id")))

    entities = (
        [("finding", entry) for entry in findings]
        + [("data_point", entry) for entry in data_points]
        + [("quote", entry) for entry in quotes]
    )
    ledger: list[dict[str, Any]] = []
    ref_map: dict[str, str] = {}

    for index, (kind, entry) in enumerate(entities, start=1):
        evidence_id = f"E{index:02d}"
        pack_id = str(entry.get("id"))
        ref_map[pack_id] = evidence_id
        refs = source_refs(kind, entry)
        source = strongest_source(refs, by_id)

        if kind == "finding":
            title = truncate(str(entry.get("claim") or ""))
            confidence = str(entry.get("confidence") or "medium")
        elif kind == "data_point":
            title = truncate(f"{entry.get('meaning')}：{entry.get('value')}")
            confidence = str(entry.get("confidence") or "medium")
        else:
            attribution = str(entry.get("attribution") or "").strip()
            quote_text = truncate(str(entry.get("text") or ""))
            title = truncate(f"{attribution}：{quote_text}" if attribution else quote_text)
            confidence = quote_confidence(source)

        record: dict[str, Any] = {
            "id": evidence_id,
            "title": title,
            "source_type": SOURCE_TYPE_MAP.get(str(source.get("type") or "other"), "other"),
            "locator": locator_of(source),
            "source_ids": refs,
            "confidence": confidence,
            "used_on_slides": [],
        }
        if source.get("id"):
            record["primary_source_id"] = str(source["id"])
        if source.get("publisher"):
            record["author"] = str(source["publisher"])
        if source.get("year"):
            record["date"] = str(source["year"])

        limitations: list[str] = []
        if entry.get("conflict"):
            limitations.append("来源存在冲突，页面必须写成区间或加限定语")
        if str(entry.get("notes") or "").strip():
            limitations.append(str(entry["notes"]).strip())
        if str(source.get("tier") or "") == "D":
            limitations.append("仅有 D 级来源，只能作为用户观点引用")
        if limitations:
            record["limitation"] = "；".join(dict.fromkeys(limitations))
        ledger.append(record)

    return ledger, ref_map


def compile_slide_spec(
    spec: dict[str, Any],
    ref_map: dict[str, str],
    ledger: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Return a compiled copy whose refs and ledger are mechanically consistent."""
    compiled = copy.deepcopy(spec)
    by_evidence = {str(entry["id"]): entry for entry in ledger}
    unresolved: list[str] = []

    for entry in ledger:
        entry["used_on_slides"] = []

    for slide in compiled.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        slide_no = slide.get("id")
        converted: list[str] = []
        for ref in slide.get("evidence_refs") or []:
            key = str(ref)
            evidence_id = key if key in by_evidence else ref_map.get(key)
            if evidence_id is None:
                unresolved.append(
                    f"slide {slide_no}: evidence_ref {key!r} does not resolve to any pack finding/data_point/quote"
                )
                continue
            if evidence_id not in converted:
                converted.append(evidence_id)
            if isinstance(slide_no, int):
                used = by_evidence[evidence_id]["used_on_slides"]
                if slide_no not in used:
                    used.append(slide_no)
        if "evidence_refs" in slide or converted:
            slide["evidence_refs"] = converted

    for entry in ledger:
        entry["used_on_slides"] = sorted(entry["used_on_slides"])
    compiled["evidence_ledger"] = copy.deepcopy(ledger)
    return compiled, unresolved


def source_index(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id = {str(source.get("id")): source for source in pack_validator.items(pack, "sources")}
    return {
        source_id: {
            "title": source.get("title"),
            "tier": source.get("tier"),
            "type": source.get("type"),
            "locator": locator_of(source),
            "publisher": source.get("publisher"),
            "year": source.get("year"),
            "independence_group": source.get("independence_group"),
        }
        for source_id, source in sorted(by_id.items())
    }


def compile_pack(
    pack: dict[str, Any],
    spec: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    ledger, ref_map = build_ledger(pack)
    compiled_spec = None
    unresolved: list[str] = []
    if spec is not None:
        compiled_spec, unresolved = compile_slide_spec(spec, ref_map, ledger)

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "topic": pack.get("topic"),
        "budget": pack.get("budget"),
        "ref_map": ref_map,
        "source_index": source_index(pack),
        "evidence_ledger": ledger,
        "unresolved_retrieval": pack_validator.items(pack, "unresolved"),
        "unresolved_refs": unresolved,
    }
    report["semantic_sha256"] = sha256_json(
        {
            "ref_map": report["ref_map"],
            "source_index": report["source_index"],
            "evidence_ledger": report["evidence_ledger"],
            "unresolved_retrieval": report["unresolved_retrieval"],
            "unresolved_refs": report["unresolved_refs"],
        }
    )
    return report, compiled_spec


def validate_report_for_pack(path: Path, pack_hash: str) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, f"Research Pack validation report does not exist: {path}"
    report = load_json(path)
    if report.get("ok") is not True:
        return False, "Research Pack validation report is not passing."
    if report.get("research_pack_sha256") != pack_hash:
        return False, "Research Pack validation report is stale or belongs to another pack."
    return True, None


def schema_issues(report: dict[str, Any]) -> list[str]:
    """Validate the map against its own schema before it is written.

    `semantic_sha256` and the freeze chain both treat this file as an intermediate
    representation, so its shape has to be enforced rather than assumed. Failing
    closed matters here: reporting "cannot verify" as "fine" is how a malformed IR
    reaches the freeze.
    """
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return ["jsonschema is not installed, so the Evidence Map shape cannot be verified."]
    if not SCHEMA_PATH.is_file():
        return [f"Evidence Map schema is missing: {SCHEMA_PATH}"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(report), key=lambda item: list(item.absolute_path))
    ]


def render(report: dict[str, Any], path: Path, compiled_spec: Path | None) -> str:
    blocked = bool(report["unresolved_refs"])
    state = "blocked" if blocked else "ok"
    suffix = f" | compiled spec: {compiled_spec}" if compiled_spec else ""
    return (
        f"research_pack_to_evidence: {state} — {len(report['evidence_ledger'])} ledger entries from "
        f"{len(report['ref_map'])} F/D/Q entities | {len(report['source_index'])} sources | "
        f"unresolved refs {len(report['unresolved_refs'])} | map: {path}{suffix}\n"
        + "".join(f"  [major] {line}\n" for line in report["unresolved_refs"])
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=Path, help="research-pack.json (or .yaml)")
    parser.add_argument("--validation-report", type=Path, help="passing report from validate_research_pack.py")
    parser.add_argument("--slide-spec", type=Path, help="draft spec whose F/D/Q refs should be compiled")
    parser.add_argument(
        "--compiled-slide-spec",
        type=Path,
        help="write the compiled non-destructive Slide Spec; requires --slide-spec",
    )
    parser.add_argument("--output", type=Path, help="defaults to <pack dir>/evidence-map.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.pack.is_file():
        print(f"research_pack_to_evidence: Research Pack does not exist: {args.pack}", file=sys.stderr)
        return 2
    if args.compiled_slide_spec and not args.slide_spec:
        print("research_pack_to_evidence: --compiled-slide-spec requires --slide-spec", file=sys.stderr)
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

    pack_hash = sha256_file(args.pack)
    validation_hash: str | None = None
    if args.validation_report:
        valid, error = validate_report_for_pack(args.validation_report, pack_hash)
        if not valid:
            print(f"research_pack_to_evidence: {error}", file=sys.stderr)
            return 2
        validation_hash = sha256_file(args.validation_report)

    spec = None
    if args.slide_spec:
        if not args.slide_spec.is_file():
            print(f"research_pack_to_evidence: Slide Spec does not exist: {args.slide_spec}", file=sys.stderr)
            return 2
        spec = pack_validator.load(args.slide_spec)

    report, compiled_spec = compile_pack(pack, spec)
    provenance: dict[str, Any] = {
        "research_pack": str(args.pack.resolve()),
        "research_pack_sha256": pack_hash,
        "validation_ok": True,
    }
    if args.validation_report:
        provenance["research_validation"] = str(args.validation_report.resolve())
        provenance["research_validation_sha256"] = validation_hash
    if args.slide_spec:
        provenance["draft_slide_spec"] = str(args.slide_spec.resolve())
        provenance["draft_slide_spec_sha256"] = sha256_file(args.slide_spec)
    if args.compiled_slide_spec and compiled_spec is not None:
        write_structured(args.compiled_slide_spec, compiled_spec)
        provenance["compiled_slide_spec"] = str(args.compiled_slide_spec.resolve())
        provenance["compiled_slide_spec_sha256"] = sha256_file(args.compiled_slide_spec)
    report["provenance"] = provenance

    violations = schema_issues(report)
    if violations:
        print(
            f"research_pack_to_evidence: Evidence Map violates evidence-map.schema.json ({len(violations)} violations):",
            file=sys.stderr,
        )
        for line in violations[:10]:
            print(f"  {line}", file=sys.stderr)
        return 2

    report_path = args.output or (args.pack.parent / "evidence-map.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, report_path, args.compiled_slide_spec), end="")
    return 2 if report["unresolved_refs"] else 0


if __name__ == "__main__":
    sys.exit(main())
