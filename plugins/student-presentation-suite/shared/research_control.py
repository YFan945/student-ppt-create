"""Persistent stop decisions at tool boundaries; does not kill model processes."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from shared.research_io import atomic_json, file_lock

DEFAULTS = {"simple": (120, 60), "standard": (300, 120), "deep": (900, 240)}
# A granted retrieval batch cannot have produced pack progress until its results
# return and the model rewrites the pack (observed search latency up to ~32s in
# the 2026-10-04 run). Judging stall on raw elapsed-since-progress at PreToolUse
# time punished exactly those in-flight batches: run-14 round 1 had two of three
# parallel WebSearches refused `no_useful_progress` 60s after the last pack
# write while their results were still returning. The allowance is a fixed
# discount per evaluation, not a per-call reset — continuous futile searching
# still reaches the stall line, just one batch later.
STALL_TURNAROUND_SECONDS = 30


def read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


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
        if not state:
            state = {"started_at": now, "last_progress_at": now, "task_sha256": task_sha, "seen": []}
        if retrieval and "retrieval_started_at" not in state:
            state["retrieval_started_at"] = now
            state["last_progress_at"] = now
        report = read(work / "research-pack-validation.json")
        pack = work / "research-pack.json"
        current = pack.is_file() and report.get("research_pack_sha256") == hashlib.sha256(pack.read_bytes()).hexdigest()
        current = current and report.get("task", {}).get("sha256") == task_sha and report.get("ok") is True
        useful = set()
        if current:
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
                        evidence_path = Path(binding.get("text_path", ""))
                        evidence_path = evidence_path if evidence_path.is_absolute() else work / evidence_path
                        try:
                            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != binding.get("text_sha256"):
                                continue
                        except OSError:
                            continue
                        # Paraphrases, report rewrites and unrelated readable pages
                        # are not progress. A task claim must gain validated support.
                        token = [claim["id"], claim["status"], binding.get("text_sha256")]
                        useful.add(json.dumps(token, ensure_ascii=False))
        if useful - set(state["seen"]):
            state["last_progress_at"] = now
            state["seen"] = sorted(set(state["seen"]) | useful)
        budget, stall = DEFAULTS.get(task.get("budget"), DEFAULTS["standard"])
        budget = task.get("time_budget_seconds", budget)
        stall = task.get("stall_timeout_seconds", stall)
        reason = state.get("reason", "")
        if state.get("task_sha256") != task_sha:
            reason = "task_changed"
        if not reason:
            if current and report.get("delivery_status") in {"ready", "partial"}:
                reason = "sufficient_evidence"
            elif now - state["started_at"] >= budget:
                reason = "time_budget_exhausted"
            elif "retrieval_started_at" in state and (now - STALL_TURNAROUND_SECONDS) - state["last_progress_at"] >= stall:
                reason = "no_useful_progress"
        state.update(state="stop_requested" if reason else "active", reason=reason,
                     elapsed_seconds=round(now - state["started_at"], 3),
                     idle_seconds=round(now - state["last_progress_at"], 3))
        atomic_json(path, state)
        return state
