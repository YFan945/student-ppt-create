"""Inspect research stop state, resume it, or re-bind the task — from the main session."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validate_research_task import validate_task  # noqa: E402

from shared.research_control import read, status  # noqa: E402
from shared.research_io import atomic_json, file_lock  # noqa: E402

REBIND_MIN_REASON = 24


def resume(work: Path, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A concrete new-input/environment-change reason is required")
    task_path = work / "research-task.json"
    errors = validate_task(read(task_path), task_path)
    if errors:
        raise ValueError("; ".join(errors))
    with file_lock(work / ".research-control.lock"):
        path = work / "research-control.json"
        state = read(path)
        now = time.time()
        state.setdefault("resumes", []).append({"at": now, "reason": reason.strip(), "previous_reason": state.get("reason")})
        state.update(started_at=now, last_progress_at=now, reason="", state="active",
                     task_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest())
        state.setdefault("seen", [])
        state.pop("retrieval_started_at", None)
        atomic_json(path, state)


def rebind(work: Path, reason: str) -> None:
    """Re-bind research-task-binding.json to the CURRENT task bytes.

    The task is frozen at dispatch, but the documented close-out path — the spec
    no longer asserts an unresolved dimension, so its claim is demoted from core
    to supporting — requires converging the declared task AFTER the researcher
    returned. With no supported rebind there was no legal route from "task
    changed" back to a validating pack: the binding is hook-owned (model writes
    refused), respawning is refused while a pack exists, and re-running the task
    validator does not refresh the frozen hash. Run-14 live: the main session
    hand-renamed the binding to `.superseded-<sha>.json` — guard surgery without
    audit. This command performs the same move as a first-class, audited action:
    the stale binding is archived under its old hash, the current task bytes are
    bound, and the decision lands in research-control history.
    """
    if len(reason.strip()) < REBIND_MIN_REASON:
        raise ValueError(
            f"rebind requires a concrete reason (>= {REBIND_MIN_REASON} chars) naming the scope change"
        )
    task_path = work / "research-task.json"
    errors = validate_task(read(task_path), task_path)
    if errors:
        raise ValueError("; ".join(errors))
    binding_path = work / "research-task-binding.json"
    if not binding_path.is_file():
        raise ValueError("no research-task-binding.json to rebind (task was never spawned)")
    new_sha = hashlib.sha256(task_path.read_bytes()).hexdigest()
    with file_lock(work / ".research-control.lock"):
        frozen = json.loads(binding_path.read_text(encoding="utf-8"))
        old_sha = str(frozen.get("sha256") or "")
        if old_sha == new_sha:
            print(json.dumps({"ok": True, "rebound": False, "sha256": new_sha,
                              "note": "binding already matches the current task bytes"}, ensure_ascii=False))
            return
        archive = binding_path.with_name(f"research-task-binding.superseded-{old_sha[:8]}.json")
        if not archive.exists():
            archive.write_text(binding_path.read_text(encoding="utf-8"), encoding="utf-8")
        atomic_json(binding_path, {
            "path": str(task_path.resolve()),
            "session_id": frozen.get("session_id"),
            "sha256": new_sha,
            "rebound_from": old_sha,
            "rebound_at": time.time(),
            "reason": reason.strip(),
        })
        path = work / "research-control.json"
        state = read(path)
        now = time.time()
        state.setdefault("rebinds", []).append({
            "at": now, "from": old_sha, "to": new_sha, "reason": reason.strip(),
        })
        state["task_sha256"] = new_sha
        atomic_json(path, state)
        print(json.dumps({"ok": True, "rebound": True, "from": old_sha, "to": new_sha,
                          "archived": str(archive)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rebind", action="store_true",
                        help="bind research-task-binding.json to the current research-task.json bytes "
                             "(sanctioned scope convergence; requires --reason)")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        if args.resume and args.rebind:
            raise ValueError("--resume and --rebind are mutually exclusive")
        if args.resume:
            resume(args.work_dir, args.reason)
        elif args.rebind:
            rebind(args.work_dir, args.reason)
        print(json.dumps(status(args.work_dir), ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"research_control: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
