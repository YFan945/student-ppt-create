"""Shared automatic task binding and graded delivery checks for consumers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from validate_research_task import validate_task


def task_verdict(pack: dict, work_dir: Path, explicit: Path | None = None) -> tuple[list[str], dict | None, dict | None]:
    path = explicit or work_dir / "research-task.json"
    if not path.is_file():
        missing = bool(explicit) or (work_dir / "research-task-binding.json").is_file()
        return (["Bound research task is missing"] if missing else []), None, None
    binding = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_task(task, path)
        if errors:
            return errors, binding, task
        if Path(task["work_dir"]).resolve() != work_dir.resolve():
            errors.append("Task and pack must belong to the same work directory")
        declared = {c.get("id"): c for c in pack.get("must_verify", [])}
        for claim in task["claims"]:
            actual = declared.get(claim["id"], {})
            if actual.get("claim") != claim["claim"]:
                errors.append(f"Task claim {claim['id']} is absent or changed")
            if claim.get("verification", "source") in {"text", "cross_check"} and actual.get("status") == "usable":
                errors.append(f"Task claim {claim['id']} requires verified evidence")
            entities = {e.get("id"): e for key in ("findings", "data_points", "quotes") for e in pack.get(key, [])}
            for eid in actual.get("entity_ids", []):
                if entities.get(eid, {}).get("claim_id") != claim["id"]:
                    errors.append(f"Task claim {claim['id']} has a mismatched entity {eid}")
            if claim.get("verification") == "cross_check" and actual.get("status") == "verified":
                from validate_research_pack import _effective_groups
                groups, _ = _effective_groups(pack)
                for eid in actual.get("entity_ids", []):
                    refs = entities.get(eid, {}).get("source_ids", [])
                    if len({groups.get(sid, sid) for sid in refs}) < 2:
                        errors.append(f"Task claim {claim['id']} entity {eid} lacks independent cross-check; remove an under-verified auxiliary entity from the claim and pack instead of weakening the task")
        if task["scope"] in {"A", "B"} and pack.get("evidence_contract") not in {"text-bound-v1", "source-backed-v1"}:
            errors.append("New A/B tasks require a source-backed or text-bound evidence contract")
        if task["scope"] in {"C", "D"} and pack.get("queries"):
            errors.append("C/D tasks prohibit web queries")
        if task["scope"] == "D" and any(s.get("type") != "user-file" for s in pack.get("sources", [])):
            errors.append("D tasks may only cite user-file sources")
        frozen = work_dir / "research-task-binding.json"
        if frozen.is_file() and json.loads(frozen.read_text(encoding="utf-8")).get("sha256") != binding["sha256"]:
            errors.append("Research task changed after researcher spawn")
        return errors, binding, task
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)], binding, None


def delivery(pack: dict, task: dict | None) -> dict:
    claims = {c.get("id"): c for c in pack.get("must_verify", [])}
    requirements = task["claims"] if task else list(claims.values())
    gaps = [c["id"] for c in requirements if c.get("importance", "core") == "core"
            and claims.get(c.get("id"), {}).get("status") not in {"usable", "verified"} and c.get("id")]
    usable = sum(c.get("status", "verified" if task is None else "") in {"usable", "verified"} for c in claims.values())
    pending = [c.get("id", c.get("claim")) for c in claims.values() if c.get("status") not in {"usable", "verified"}]
    status = "insufficient" if gaps else "partial" if pending else "ready"
    if requirements and not usable:
        status = "insufficient"
    return {"delivery_status": status, "core_gaps": gaps, "usable_claims": usable, "pending_claims": pending}


def apply_task(report: dict, pack: dict, work_dir: Path, explicit: Path | None = None) -> None:
    errors, binding, task = task_verdict(pack, work_dir, explicit)
    for error in errors:
        report["problems"].append({"severity": "major", "code": "research_task_mismatch", "message": error})
    report["counts"]["major"] += len(errors)
    report["counts"]["blockers"] += len(errors)
    report["ok"] = report["ok"] and not errors
    if binding:
        report["task"] = binding
    report.update(delivery(pack, task))
    if errors:
        report["delivery_status"] = "insufficient"
