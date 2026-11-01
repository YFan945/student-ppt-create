"""Check text-bound evidence without claiming to automate semantic entailment."""
from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path
from typing import Any

_LOCATORS = {"search_engine", "listing"}


def _research_root(work_dir: Path) -> Path:
    return (work_dir / "research").resolve()


def _resolve_research_file(work_dir: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    resolved = (path if path.is_absolute() else work_dir / path).resolve()
    try:
        if not resolved.is_relative_to(_research_root(work_dir)):
            return None
    except (OSError, ValueError):
        return None
    return resolved


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _url_records(records: list, url: object) -> list[dict]:
    return [row for row in records if isinstance(row, dict) and row.get("url") == url]


def _raw_intact(record: dict, work_dir: Path) -> bool:
    digest = record.get("raw_sha256")
    path = _resolve_research_file(work_dir, record.get("raw_path"))
    return isinstance(digest, str) and path is not None and _sha256(path) == digest


def _text_intact(record: dict, work_dir: Path) -> bool:
    """True when fetch-text's own text file is still the bytes named in the report."""
    digest = record.get("text_sha256")
    path = _resolve_research_file(work_dir, record.get("text_path"))
    return bool(record.get("ok")) and isinstance(digest, str) and path is not None and _sha256(path) == digest


def _same_text(record: dict, work_dir: Path, path: Path, digest: str) -> bool:
    recorded = _resolve_research_file(work_dir, record.get("text_path"))
    return bool(record.get("ok")) and record.get("text_sha256") == digest and recorded == path


def _document_record(candidates: list[dict]) -> dict | None:
    """Prefer a non-locator row. A locator-only set is returned so the caller can reject it."""
    documents = [row for row in candidates if row.get("host_class") not in _LOCATORS]
    if documents:
        return documents[0]
    return candidates[0] if candidates else None


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
        url_rows = _url_records(records, sources[sid].get("url"))
        # source-backed + verification=source may cite a fetched document when no
        # reader produced text. text-bound-v1, quotes, and verification=text still
        # need a passage. A successful extraction on disk closes this fallback.
        source_level = (
            balanced
            and key != "quotes"
            and entity.get("verification", "source") == "source"
            and not str(binding.get("text_path", "")).strip()
        )
        if source_level:
            if sources[sid].get("type") == "user-file":
                fail("evidence_text_unreadable", "A user file still needs a readable passage under work-dir/research.", eid)
                continue
            intact = [row for row in url_rows if _text_intact(row, work_dir) and row.get("host_class") not in _LOCATORS]
            produced = [row for row in url_rows if row.get("ok") and row.get("host_class") not in _LOCATORS]
            if intact or produced:
                fail(
                    "evidence_text_available",
                    "fetch-text already extracted this URL. Bind that text file, or bind a local UTF-8 extraction of the saved raw bytes.",
                    eid,
                )
                continue
            record = _document_record([row for row in url_rows if _raw_intact(row, work_dir)])
            if record is None:
                fail("evidence_fetch_binding_missing", "No fetched document backs this source URL.", eid)
                continue
            if record.get("host_class") in _LOCATORS:
                fail("evidence_locator_as_source", "Locator pages cannot substantiate a claim.", eid)
                continue
            fail(
                "evidence_source_unquoted",
                "Source-level binding: the document was fetched, but this claim is not tied to a verbatim passage. Numbers are not mechanically checked.",
                eid,
                severity="minor",
            )
            covered.add((eid, sid))
            continue
        if not str(binding.get("text_path", "")).strip():
            if key == "quotes":
                fail("evidence_quote_mismatch", "A quote requires a verbatim excerpt from the bound text.", eid)
            else:
                fail("evidence_text_unreadable", "Bound text is missing or is not UTF-8.", eid)
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
        record = next((row for row in url_rows if _same_text(row, work_dir, path, digest)), None)
        local = False
        # Do not let a hand-written file replace a fetch-text extraction that still
        # matches its record. Local text is only the fallback for a saved raw body.
        fetched_text_intact = any(_text_intact(row, work_dir) for row in url_rows)
        if record is None and balanced and sources[sid].get("type") != "user-file" and not fetched_text_intact:
            record = _document_record([row for row in url_rows if _raw_intact(row, work_dir)])
            local = record is not None and record.get("host_class") not in _LOCATORS
        if sources[sid].get("type") != "user-file" and record is None:
            fail("evidence_fetch_binding_missing", "No successful fetch binds this source URL to this text.", eid)
            continue
        if record and record.get("host_class") in _LOCATORS:
            fail("evidence_locator_as_source", "Locator pages cannot substantiate a claim.", eid)
            continue
        if local:
            fail(
                "evidence_local_extraction",
                "Text was extracted locally and bound to the fetched raw bytes. fetch-text did not produce this text file.",
                eid,
                severity="minor",
            )
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
