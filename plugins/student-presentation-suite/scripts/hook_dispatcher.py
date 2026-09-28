#!/usr/bin/env python3
"""Single PreToolUse entrypoint that routes one hook event to every guard.

hooks.json registers one dispatcher process per event; routing happens
in-process. Spawning one interpreter per (event, guard) pair made every
non-pipeline tool call pay 4-5 python startups (~0.4-0.5s on Bash) for guards
that immediately exit 0 outside pipeline scope — the blocking boundary was
scoped (v0.19.1), the execution boundary was not. One dispatcher spawn keeps
that overhead at a single startup while preserving each guard's own output,
exit code and short-circuit semantics (first refusal wins, as with parallel
hooks where any deny blocks).

The route table mirrors the former per-script matchers exactly; changing a
route must land here AND in tests/test_hook_responsibilities.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import builder_guard  # noqa: E402
import cost_guard  # noqa: E402
import hook_health  # noqa: E402
import production_entry_guard  # noqa: E402
import runtime_evidence  # noqa: E402

# tool_name -> guards, in execution order. hook_health arms first so a receipt
# exists even when a later guard refuses the same call (parallel-hook parity:
# every registered hook used to run regardless of the others' verdicts).
ROUTES = {
    "Bash": (hook_health, production_entry_guard, builder_guard, cost_guard),
    "Read": (builder_guard, cost_guard),
    "Grep": (cost_guard,),
    "Write": (builder_guard, runtime_evidence),
    "Edit": (builder_guard, runtime_evidence),
    "PowerShell": (builder_guard,),
    "Skill": (runtime_evidence,),
    "WebSearch": (runtime_evidence,),
    "WebFetch": (runtime_evidence,),
    "Agent": (runtime_evidence,),
    "SendMessage": (runtime_evidence,),
}


def dispatch(event: dict) -> int:
    name = str(event.get("tool_name") or event.get("tool") or "")
    for guard in ROUTES.get(name, ()):
        try:
            code = guard.handle(event)
        except Exception as exc:  # a broken guard must not crash the others either
            label = getattr(guard, "__name__", type(guard).__name__)
            print(f"hook_dispatcher: {label} failed: {exc}", file=sys.stderr)
            continue
        if code:
            return code
    return 0


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    return dispatch(event)


if __name__ == "__main__":
    sys.exit(main())
