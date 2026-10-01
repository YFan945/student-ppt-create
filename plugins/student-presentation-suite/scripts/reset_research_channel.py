#!/usr/bin/env python3
"""Main-session recovery after a documented search-provider/environment change."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime_evidence  # noqa: E402

from shared.research_io import atomic_json  # noqa: E402
from shared.retrieval_trail import search_channel_closed  # noqa: E402


def reset(project: Path, session_id: str | None, agent_id: str | None, reason: str) -> Path:
    if not reason.strip():
        raise ValueError("A concrete environment-change reason is required")
    guard = project.resolve() / "outputs/.pptx-work/.guard"
    if session_id and agent_id:
        key = re.sub(r"[^A-Za-z0-9_-]", "_", session_id + "-" + agent_id)
        path = guard / f"search-channel-{key}.json"
    elif session_id or agent_id:
        raise ValueError("Provide both session-id and agent-id, or omit both")
    else:
        candidates = [p for p in guard.glob("search-channel-*.json")
                      if time.time() - p.stat().st_mtime < runtime_evidence.pipeline_context.RESEARCH_ACTIVE_TTL_SECONDS
                      and search_channel_closed(json.loads(p.read_text(encoding="utf-8")).get("executions", []))]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one active paused channel; specify both IDs to select it")
        path = candidates[0]
        key = path.stem.removeprefix("search-channel-")
    with runtime_evidence.event_lock({}, project_override=project.resolve(), key_override=key):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["executions"].append({"event": "channel_reset", "reason": reason.strip(), "at": time.time()})
        atomic_json(path, data)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--agent-id")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        path = reset(args.project, args.session_id, args.agent_id, args.reason)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"reset_research_channel: {exc}\n")
    print(f"reset_research_channel: ready for recovery probe — {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
