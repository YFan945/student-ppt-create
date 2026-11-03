"""Persistent stop decisions at tool boundaries; does not kill model processes."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from shared.artifact_fingerprints import content_digest
from shared.research_io import atomic_json, file_lock


def read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def evidence_key(work: Path) -> str:
    """A refreshed report or cache annotation is not new evidence."""
    parts = [(name, content_digest(work / name) if (work / name).is_file() else None)
             for name in ("research-task.json", "research-pack.json")]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def requirements_key(task: dict) -> str:
    """Retrieval requirements, independent of JSON formatting and budget notes."""
    claims = [{**{k: c.get(k) for k in ("id", "claim", "acceptance")},
               "importance": c.get("importance", "core"), "verification": c.get("verification", "source")}
              for c in task.get("claims", [])]
    claims.sort(key=lambda c: str(c["id"]))
    return hashlib.sha256(json.dumps([task.get("scope"), claims], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def status(work: Path, *, now: float | None = None, retrieval: bool = False) -> dict:
    now = time.time() if now is None else now
    task_path = work / "research-task.json"
    task = read(task_path)
    if not task:
        return {"state": "legacy", "reason": ""}
    path = work / "research-control.json"
    with file_lock(work / ".research-control.lock"):
        state = read(path)
        task_sha = hashlib.sha256(task_path.read_bytes()).hexdigest()
        requirements = requirements_key(task)
        if not state:
            state = {"started_at": now, "last_progress_at": now, "task_sha256": task_sha, "seen": []}
        if retrieval and "retrieval_started_at" not in state:
            state["retrieval_started_at"] = now
            state["last_progress_at"] = now
        report = read(work / "research-pack-validation.json")
        pack = work / "research-pack.json"
        pack_identity = report.get("research_pack_content_sha256")
        task_identity = report.get("task", {}).get("content_sha256")
        current = pack.is_file() and (pack_identity == content_digest(pack) if pack_identity else
            report.get("research_pack_sha256") == hashlib.sha256(pack.read_bytes()).hexdigest())
        current = current and (task_identity == content_digest(task_path) if task_identity else
            report.get("task", {}).get("sha256") == task_sha)
        useful = set()
        if current and report.get("ok") is True:
            content = read(pack)
            entities = {e.get("id"): e for k in ("findings", "data_points", "quotes") for e in content.get(k, [])}
            task_ids = {c.get("id") for c in task.get("claims", [])}
            for claim in content.get("must_verify", []):
                if claim.get("id") not in task_ids or claim.get("status") not in {"usable", "verified"}:
                    continue
                for eid in claim.get("entity_ids", []):
                    if entities.get(eid, {}).get("claim_id") != claim["id"]:
                        continue
                    for binding in content.get("evidence", []):
                        if binding.get("entity_id") != eid:
                            continue
                        # Content progress is source support, not byte identity of
                        # a parser's output. Hashes remain cache metadata only.
                        token = [claim["id"], claim["status"], binding.get("source_id"),
                                 binding.get("excerpt"), binding.get("support_note")]
                        useful.add(json.dumps(token, ensure_ascii=False))
        if useful - set(state["seen"]):
            state["last_progress_at"] = now
            state["seen"] = sorted(set(state["seen"]) | useful)
        reason = state.get("reason", "")
        if reason in {"time_budget_exhausted", "no_useful_progress"}:
            reason = ""  # old timer decisions do not prevent continuing the task
        # A stale report calls for local validation, not fresh retrieval. Keep
        # sufficiency closed until changed requirements or a current core gap
        # actually establish that the earlier answer no longer suffices.
        if reason == "task_changed" or (reason == "sufficient_evidence" and (
                state.get("requirements_key", requirements) != requirements
                or (current and (report.get("core_gaps") or (
                    report.get("ok") is True and report.get("delivery_status") == "insufficient"))))):
            reason = ""
        state["task_sha256"] = task_sha
        state["requirements_key"] = requirements
        validation_path = work / "research-pack-validation.json"
        report_version = hashlib.sha256(validation_path.read_bytes()).hexdigest() if validation_path.is_file() else None
        explicitly_continuing = (bool(state.get("resume_evidence_key")) and state["resume_evidence_key"] == evidence_key(work)) or (
            not state.get("resume_evidence_key") and bool(state.get("resume_validation_sha256"))
            and state["resume_validation_sha256"] == report_version)
        if not reason and current and not explicitly_continuing and report.get("ok") is True and report.get("delivery_status") in {"ready", "partial"}:
            reason = "sufficient_evidence"
        next_action = ("refresh_validation" if not current else
                       "repair_pack" if not report.get("ok") else "handoff") if reason == "sufficient_evidence" else "resolve_claims"
        state.update(state="stop_requested" if reason else "active", reason=reason,
                     validation_pending=not current, next_action=next_action,
                     elapsed_seconds=round(now - state["started_at"], 3),
                     idle_seconds=round(now - state["last_progress_at"], 3))
        atomic_json(path, state)
        return state
