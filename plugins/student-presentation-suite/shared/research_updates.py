"""Atomic, ID-based edits of the canonical Pack without regenerating its facts."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from shared.research_io import atomic_json, file_lock

SCHEMA = Path(__file__).resolve().parents[1] / "references/research-pack-update.schema.json"


def _key(kind: str, row: dict):
    return (row["entity_id"], row["source_id"]) if kind == "evidence" else row["id"]


def _merge(existing: dict, changes: dict) -> dict:
    result = copy.deepcopy(existing)
    for key, value in changes.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            result[key] = _merge(result.get(key, {}) if isinstance(result.get(key), dict) else {}, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def apply_updates(pack: dict, update: dict) -> dict:
    errors = list(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).iter_errors(update))
    if errors:
        raise ValueError("Invalid Pack update: " + errors[0].message)
    result = copy.deepcopy(pack)
    for kind, changes in update.get("upsert", {}).items():
        rows = result.setdefault(kind, [])
        seen = set()
        for change in changes:
            key = _key(kind, change)
            if key in seen:
                raise ValueError(f"Duplicate update for {kind}/{key}")
            seen.add(key)
            matches = [index for index, row in enumerate(rows) if _key(kind, row) == key]
            if len(matches) > 1:
                raise ValueError(f"Ambiguous existing ID in {kind}/{key}")
            if matches:
                rows[matches[0]] = _merge(rows[matches[0]], change)
            else:
                rows.append(copy.deepcopy(change))
    removed_entities = set()
    for kind, removals in update.get("remove", {}).items():
        keys = {_key(kind, row) for row in removals} if kind == "evidence" else set(removals)
        if keys & {_key(kind, row) for row in update.get("upsert", {}).get(kind, [])}:
            raise ValueError(f"Cannot update and remove the same {kind} record")
        result[kind] = [row for row in result.get(kind, []) if _key(kind, row) not in keys]
        if kind in {"findings", "data_points", "quotes"}:
            removed_entities.update(keys)
    if removed_entities:
        result["evidence"] = [b for b in result.get("evidence", []) if b.get("entity_id") not in removed_entities]
        for visual in result.get("visual_candidates", []):
            for key in ("finding_ids", "data_point_ids"):
                if key in visual:
                    visual[key] = [ref for ref in visual[key] if ref not in removed_entities]
    return result


def update_current(path: Path, update_path: Path, validator) -> dict:
    if path.resolve() == update_path.resolve():
        raise ValueError("The update file must be separate from the Pack")
    update = validator.load(update_path)
    with file_lock(path.parent / ".research-pack.lock"):
        original = validator.load(path)
        candidate = apply_updates(original, update)

        def structural(pack):
            normalized = validator.normalize(pack)
            issues = validator.schema_issues(normalized)
            if not issues:
                issues = (validator.id_issues(normalized) + validator.reference_issues(normalized)
                          + validator.must_verify_issues(normalized))
            return {(p["code"], p.get("entry"), p["message"]) for p in issues
                    if p["severity"] in {"critical", "major"}}

        introduced = structural(candidate) - structural(original)
        if introduced:
            raise ValueError("Update rejected; original Pack preserved: " + "; ".join(sorted(p[2] for p in introduced)))
        changed = candidate != original
        if changed:
            atomic_json(path, candidate)
        return {"applied": True, "changed": changed, "update": str(update_path.resolve())}
