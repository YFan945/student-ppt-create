"""Reuse actual research validation across validator, handoff and compilation."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

from shared.artifact_fingerprints import content_digest
from shared.hashing import file_sha256
from shared.research_io import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def scope_candidates(report: dict, pack: dict, used: set[str]) -> None:
    """Candidate observations do not block adopted facts; broken IDs still do."""
    entities = {str(e.get("id")): e for kind in ("findings", "data_points", "quotes")
                for e in pack.get(kind, []) if isinstance(e, dict)}
    # Explicitly requested claims stay in scope even when not yet on a page.
    required = {eid for claim in pack.get("must_verify", []) for eid in claim.get("entity_ids", [])}
    used = used | required
    optional = set(entities) - used
    candidate_codes = {"low_confidence_without_reason", "high_confidence_needs_cross_check",
                       "sources_are_not_independent", "conflict_must_downgrade_confidence", "conflict_not_recorded"}
    for problem in report.get("problems", []):
        code = str(problem.get("code", ""))
        if ((problem.get("entry") in optional and (code.startswith("evidence_") or code in candidate_codes))
                or code == "unknown_visual_ref"):
            problem.update(severity="minor", outside_slide_scope=True)
    counts = {level: sum(p.get("severity") == level for p in report["problems"])
              for level in ("critical", "major", "minor")}
    counts["blockers"] = counts["critical"] + counts["major"]
    report.update(counts=counts, ok=counts["blockers"] == 0,
                  validation_scope={"used_entities": sorted(used)})


def validate_current(pack_path: Path, *, validator=None, task_path: Path | None = None,
                     search_log: Path | None = None, fetch_report: Path | None = None,
                     audit: bool = False, used_entities: set[str] | None = None) -> tuple[dict, dict]:
    validator = validator or importlib.import_module("validate_research_pack")
    from research_task_binding import apply_task, finalize

    pack_path = pack_path.resolve()
    work = pack_path.parent
    explicit_task = task_path is not None
    task_path = task_path or work / "research-task.json"
    search_log = search_log or work / "research/search-log.json"
    fetch_report = fetch_report or work / "research/fetched/fetch-text-report.json"
    payloads = search_log.parent / "search-payloads.json"
    pack = validator.normalize(validator.load(pack_path))
    paths = {pack_path, task_path, fetch_report, ROOT / "package.json",
             ROOT / "references/research-pack.schema.json", ROOT / "references/research-task.schema.json"}
    if audit:
        paths.update((search_log, payloads))
    # Text bytes are dependencies when a binding supplies a local document.
    def documents(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"text_path", "raw_path"} and isinstance(item, str):
                    path = Path(item).expanduser()
                    paths.add(path if path.is_absolute() else work / path)
                else:
                    documents(item)
        elif isinstance(value, list):
            for item in value:
                documents(item)
    documents(pack)
    fetched = validator._coerce_trail(fetch_report, "fetch-report")[0] if fetch_report.is_file() else None
    documents(fetched)
    binding = work / "research-task-binding.json"
    permission = json.loads(binding.read_text(encoding="utf-8")).get("scope") if binding.is_file() else None
    key = hashlib.sha256(json.dumps(["research-validation-v3", audit, permission, sorted(used_entities) if used_entities is not None else None, explicit_task and not task_path.is_file(),
        [(str(path.resolve()), content_digest(path) if path.is_file() else "missing") for path in sorted(paths)]],
        ensure_ascii=False).encode()).hexdigest()
    cache = work / "_tmp/research-validation.json"
    report = None
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("key") == key and isinstance(saved.get("report"), dict):
                report = saved["report"]
                report["validation_reused"] = True
        except (OSError, ValueError, AttributeError):
            pass
    if report is None:
        payload = validator._coerce_trail(payloads, "search-payloads")[0] if audit and payloads.is_file() else None
        report = validator.validate(pack, search_log=search_log if audit and search_log.is_file() else None,
            fetch_report=fetched, search_payloads=payload, work_dir=work, audit=audit)
        apply_task(report, pack, work, task_path if explicit_task else None)
        scope = used_entities
        if scope is None and task_path.is_file() and pack.get("evidence_contract") == "source-backed-v1" and not audit:
            scope = set()  # task-linked entities, not every accumulated candidate
        if scope is not None:
            scope_candidates(report, pack, scope)
        finalize(report)
        report["validation_reused"] = False
        atomic_json(cache, {"key": key, "report": report})
    report["research_pack"] = str(pack_path)
    report["research_pack_sha256"] = file_sha256(pack_path)
    report["research_pack_content_sha256"] = content_digest(pack_path)
    if task_path.is_file() and report.get("task"):
        report["task"]["sha256"] = file_sha256(task_path)
        report["task"]["content_sha256"] = content_digest(task_path)
    return pack, report
