"""Check text-bound evidence without claiming to automate semantic entailment."""
from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path
from typing import Any


def strict_evidence_issues(pack: dict, fetch_report: Any, work_dir: Path | None) -> list[dict]:
    out: list[dict] = []

    def fail(code: str, message: str, entity: str = "", severity: str = "major") -> None:
        out.append({"severity": severity, "code": code, "message": message, "entry": entity})

    review_required = False
    if work_dir and (work_dir / "research-task.json").is_file():
        import json
        with contextlib.suppress(OSError, ValueError, AttributeError):
            review_required = json.loads((work_dir / "research-task.json").read_text(encoding="utf-8")).get("semantic_review_required") is True

    strict = pack.get("evidence_contract") == "text-bound-v1"
    balanced = pack.get("evidence_contract") == "source-backed-v1"
    def rows(key: str) -> list[dict]:
        value = pack.get(key)
        return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []

    bindings = rows("evidence")
    if not strict and not balanced and not bindings:
        fail("legacy_evidence_unbound", "Legacy pack: source text bindings have not been verified.", severity="minor")
        return out
    if work_dir is None:
        fail("evidence_context_missing", "Text bindings require the pack's work directory.")
        return out
    entities = {
        str(entry["id"]): (key, entry)
        for key in ("findings", "data_points", "quotes")
        for entry in rows(key) if "id" in entry
    }
    sources = {str(entry["id"]): entry for entry in rows("sources") if "id" in entry}
    records = fetch_report.get("records") if isinstance(fetch_report, dict) else []
    records = records if isinstance(records, list) else []
    covered: set[tuple[str, str]] = set()
    cache: dict[Path, tuple[bytes, str]] = {}
    allowed = (work_dir / "research").resolve()
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        eid, sid = str(binding.get("entity_id", "")), str(binding.get("source_id", ""))
        if eid not in entities or sid not in sources:
            fail("evidence_unknown_reference", "Evidence entity/source does not exist.", eid)
            continue
        key, entity = entities[eid]
        refs = entity.get("source_ids", []) if key != "quotes" else [entity.get("source_id")]
        if sid not in refs:
            fail("evidence_unlinked_source", "Binding source is not used by the entity.", eid)
            continue
        path = Path(str(binding.get("text_path", "")))
        path = (path if path.is_absolute() else work_dir / path).resolve()
        if not path.is_relative_to(allowed):
            fail("evidence_path_outside_research", "Evidence text must stay under work-dir/research.", eid)
            continue
        try:
            if path not in cache:
                raw = path.read_bytes()
                cache[path] = (raw, raw.decode("utf-8"))
            raw, text = cache[path]
        except (OSError, UnicodeError):
            fail("evidence_text_unreadable", "Bound text is missing or is not UTF-8.", eid)
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if binding.get("text_sha256") != digest:
            fail("evidence_hash_mismatch", "Evidence hash does not match the file bytes.", eid)
            continue
        record = next((r for r in records if isinstance(r, dict) and r.get("ok")
                       and r.get("url") == sources[sid].get("url")
                       and r.get("text_sha256") == digest
                       and r.get("text_path") and
                       (Path(r["text_path"]) if Path(r["text_path"]).is_absolute()
                        else work_dir / r["text_path"]).resolve() == path), None)
        if sources[sid].get("type") != "user-file" and record is None:
            fail("evidence_fetch_binding_missing", "No successful fetch binds this source URL to this text.", eid)
            continue
        if record and record.get("host_class") in {"search_engine", "listing"}:
            fail("evidence_locator_as_source", "Locator pages cannot substantiate a claim.", eid)
            continue
        excerpt = str(binding.get("excerpt", ""))
        if not excerpt or excerpt not in text:
            fail("evidence_excerpt_mismatch", "The verbatim excerpt is absent from the bound text.", eid)
            continue
        if key == "quotes" and str(entity.get("text", "")) not in excerpt:
            fail("evidence_quote_mismatch", "Quote differs from the bound excerpt.", eid)
            continue
        if key == "data_points":
            value = str(entity.get("value", ""))
            if not value or not value_present(value, excerpt):
                fail("evidence_value_mismatch", "Data value is not stated verbatim in its excerpt.", eid)
                continue
            if balanced and entity.get("verification", "source") == "source":
                covered.add((eid, sid))
                continue
            if any(not str(binding.get(field, "")).strip() for field in ("unit", "region", "metric")):
                fail("evidence_measurement_context_missing", "Data binding requires unit, region and metric.", eid)
                continue
            if entity.get("year") is not None and binding.get("year") != entity["year"]:
                fail("evidence_year_mismatch", "Data year and evidence year disagree.", eid)
                continue
            context = str(binding.get("context_excerpt", ""))
            if context and context not in text:
                fail("evidence_context_mismatch", "Context excerpt is absent from the bound text.", eid)
                continue
            passage = excerpt + "\n" + context
            if entity.get("year") is not None and str(entity["year"]) not in passage:
                fail("evidence_year_not_in_excerpt", "Include the passage stating the data year in the excerpt.", eid)
                continue
            if str(binding["unit"]) not in passage:
                fail("evidence_unit_not_in_excerpt", "The measurement unit is absent from the excerpt.", eid)
                continue
        covered.add((eid, sid))
    # Audit a second reading separately from provenance. This checks the declared
    # review, not natural-language entailment; identical-source models can err.
    if review_required:
        for binding in bindings:
            eid, sid = str(binding.get("entity_id", "")), str(binding.get("source_id", ""))
            if (eid, sid) not in covered:
                continue
            key, entity = entities[eid]
            if entity.get("status") in {"located", "unresolved"}:
                continue
            check = binding.get("support_check", {})
            statement = entity.get({"findings": "claim", "data_points": "meaning", "quotes": "text"}[key])
            if not check or check.get("statement") != statement:
                fail("evidence_support_review_missing", "A second-pass review must bind the exact entity statement.", eid)
            elif check.get("verdict") == "unsupported" or any(check.get(f) == "mismatch" for f in ("subject_scope", "time_scope", "causal_scope")):
                fail("evidence_support_review_rejected", "The review reports unsupported evidence or a scope mismatch; leave this claim unresolved.", eid)
            elif check.get("verdict") == "qualified" and (entity.get("status") != "usable" or entity.get("confidence") != "medium" or not check.get("limitations", "").strip() or not entity.get("notes", "").strip()):
                fail("evidence_support_review_limits_missing", "Qualified support requires usable/medium plus review limitations and entity notes.", eid)
    if strict or balanced:
        for eid, (key, entity) in entities.items():
            refs = entity.get("source_ids", []) if key != "quotes" else [entity.get("source_id")]
            if entity.get("status") in {"located", "unresolved"}:
                continue
            if balanced:
                minimum = 2 if entity.get("verification") == "cross_check" or entity.get("confidence") == "high" else 1
                count = sum((eid, sid) in covered for sid in refs)
                if count < minimum:
                    fail("evidence_support_missing", f"{eid} has {count} readable source binding(s), requires {minimum} for its task verification/confidence. Keep only task-supported entities; put ancillary qualifications in notes instead of adding an under-verified fact.", eid)
                continue
            for sid in refs:
                if (eid, sid) not in covered:
                    fail("evidence_support_missing", f"No valid text binding for {eid}/{sid}.", eid)
        for claim in rows("must_verify"):
            if claim.get("status") != "verified":
                continue
            if not claim.get("entity_ids"):
                fail("evidence_claim_link_missing", "A text-bound verified claim requires linked entities.")
            for eid in claim.get("entity_ids", []):
                entity = entities.get(eid, ("", {}))[1]
                if not claim.get("id") or entity.get("claim_id") != claim["id"]:
                    fail("evidence_claim_link_mismatch", "Verified claim must link to an entity with the same claim_id.", eid)
    return out


def _normalized(text: str) -> str:
    """Ignore extraction whitespace without joining neighbouring numeric cells."""
    import unicodedata
    return " ".join(unicodedata.normalize("NFKC", text).split())


def value_present(value: str, passage: str) -> bool:
    """Compare numeric tokens, preserving table boundaries and percent meaning."""
    from decimal import Decimal, InvalidOperation
    pattern = r"(?<![\d.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?![\d.]|,\d)"
    expected = _normalized(value).replace(" ", "").replace("％", "%")
    if not expected:
        return False
    try:
        number = Decimal(expected.rstrip("%").replace(",", ""))
    except InvalidOperation:
        return _normalized(value) in _normalized(passage)
    passage = re.sub(r"(?<=\d)\s+(?=[%％])", "", _normalized(passage))
    for token in re.findall(pattern, passage):
        token = token.replace("％", "%")
        if token.endswith("%") != expected.endswith("%"):
            continue
        if Decimal(token.rstrip("%").replace(",", "")) == number:
            return True
    return False


def evidence_issues(pack: dict, fetch_report: Any, work_dir: Path | None) -> list[dict]:
    """Check usable support; tool identity, paths and hashes are not evidence gates.

    The historical byte audit is available only through explicit text-bound-v1.
    Ordinary records can come from PDF/OCR, a browser, a table or a local parser.
    Semantic support remains the researcher's responsibility.
    """
    if pack.get("evidence_contract") == "text-bound-v1":
        return strict_evidence_issues(pack, fetch_report, work_dir)
    if not pack.get("evidence_contract") and not pack.get("evidence"):
        return [{"severity": "minor", "code": "legacy_evidence_unbound",
                 "message": "Legacy pack: source support has not been recorded."}]
    out: list[dict] = []

    def fail(code: str, message: str, eid: str, severity: str = "major") -> None:
        out.append({"severity": severity, "code": code, "message": message, "entry": eid})

    entities = {str(e["id"]): (kind, e) for kind in ("findings", "data_points", "quotes")
                for e in pack.get(kind, []) if isinstance(e, dict) and "id" in e}
    sources = {str(s["id"]): s for s in pack.get("sources", []) if isinstance(s, dict) and "id" in s}
    reviews: dict[str, list[dict]] = {}
    for binding in pack.get("evidence", []):
        eid, sid = str(binding.get("entity_id", "")), str(binding.get("source_id", ""))
        if eid not in entities or sid not in sources:
            fail("evidence_unknown_reference", "Evidence entity/source does not exist.", eid)
            continue
        kind, entity = entities[eid]
        refs = [entity.get("source_id")] if kind == "quotes" else entity.get("source_ids", [])
        if sid not in refs:
            fail("evidence_unlinked_source", "Binding source is not used by the entity.", eid)
            continue
        if entity.get("status") in {"located", "unresolved"}:
            continue
        passage = str(binding.get("excerpt", ""))
        context = str(binding.get("context_excerpt", ""))
        note = str(binding.get("support_note", "")).strip()
        if not passage.strip() and not note:
            continue
        if kind == "quotes":
            if not passage or _normalized(str(entity.get("text", ""))) not in _normalized(passage):
                fail("evidence_quote_mismatch", "Direct quotation differs from its supporting passage.", eid)
                continue
        elif kind == "data_points" and passage:
            value = str(entity.get("source_value", entity.get("value", "")))
            if not value_present(value, passage + "\n" + context) and not entity.get("transformation"):
                # A token search cannot distinguish a table cell, a unit in its
                # header, a calculated value or a different subject. Keep the
                # citation usable and ask for semantic inspection, not a binder.
                fail("evidence_value_unverified", "Numeric extraction is inconclusive. Inspect the cited table/passage for subject, year, units and calculation; do not rewrite the pack or search again just to match tokens.", eid, "minor")
        if isinstance(binding.get("support_check"), dict):
            reviews.setdefault(eid, []).append(binding["support_check"])
    for eid, (kind, entity) in entities.items():
        if entity.get("status") in {"located", "unresolved"}:
            continue
        if (kind == "data_points" and entity.get("source_value") is not None
                and not value_present(str(entity.get("value", "")), str(entity["source_value"]))
                and not str(entity.get("transformation", "")).strip()):
            fail("evidence_transformation_missing", "Check whether rounding or conversion explains the display value; record a brief explanation when it affects interpretation.", eid, "minor")
        checks = reviews.get(eid, []) + ([entity["support_check"]] if isinstance(entity.get("support_check"), dict) else [])
        for check in checks:
            if check.get("verdict") == "unsupported" or any(check.get(f) == "mismatch" for f in ("subject_scope", "time_scope", "causal_scope")):
                fail("evidence_support_review_rejected", "Support was explicitly rejected; correct or leave the claim unresolved.", eid)
            elif check.get("verdict") == "qualified" and not any(str(v).strip() for v in
                    (check.get("limitations", ""), entity.get("notes", ""), entity.get("limitations", ""))):
                fail("evidence_support_review_limits_missing", "Keep one explanation of the qualification in limitations or notes.", eid)
        # Source references are already checked by the pack validator. Ordinary
        # research does not need a second entity/source table to repeat them.
    return out
