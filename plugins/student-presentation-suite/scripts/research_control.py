"""Inspect research stop state or explicitly resume it from the main session."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        if args.resume:
            resume(args.work_dir, args.reason)
        print(json.dumps(status(args.work_dir), ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"research_control: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
