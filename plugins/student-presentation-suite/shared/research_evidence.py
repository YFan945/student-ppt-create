"""Check text-bound evidence without claiming to automate semantic entailment."""
from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path
from typing import Any


def evidence_issues(pack: dict, fetch_report: Any, work_dir: Path | None) -> list[dict]:
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
            value = re.sub(r"\s+", "", str(entity.get("value", "")))
            compact = re.sub(r"\s+", "", excerpt)
            if not value or not re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", compact):
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
