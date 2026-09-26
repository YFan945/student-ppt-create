from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline.core import (  # noqa: E402
    GATE_HISTORY_NAME,
    MAX_REPAIRS,
    MAX_REPAIRS_HARD_CAP,
)


def repair_budget(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Base budget + rounds granted this run, read from the manifest.

    The budget used to be a bare constant, so a run that ran out of rounds had nowhere to
    record a decision except the installed plugin's contract file. Grants live in the
    manifest instead: they survive the plugin being reinstalled, they travel with the work
    id, and they are auditable next to the QA rounds that justified them.
    """
    grants = []
    for entry in ((manifest or {}).get("build") or {}).get("repair_budget_grants") or []:
        if isinstance(entry, dict):
            grants.append(entry)
    granted = sum(int(entry.get("rounds") or 0) for entry in grants)
    return {
        "base": MAX_REPAIRS,
        "granted": granted,
        "effective": MAX_REPAIRS + granted,
        "hard_cap": MAX_REPAIRS_HARD_CAP,
        "grants": grants,
    }


def gate_regressions(
    work_dir: Path,
    reports: dict[str, Any],
    *,
    blockers: int = 0,
    failed: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A gate that passed on the previous build and fails now means the change broke it.

    2026-09-17 live: repair round 6 broke `actual_content`, which had passed since build 3.
    Nothing compared gate status across rounds, so the breakage surfaced only as another
    blocker pile, the budget was already spent, and the round had effectively undone its own
    predecessor. Naming the regression at the moment it appears is what makes "repair"
    converge instead of oscillate.

    Returns the problems to add plus the history to persist (round counter per gate).
    """
    path = work_dir / GATE_HISTORY_NAME
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}

    problems: list[dict[str, Any]] = []
    history: dict[str, Any] = {}
    for name, data in reports.items():
        ok = bool(data.get("ok"))
        entry = previous.get(name) if isinstance(previous.get(name), dict) else {}
        history[name] = {"ok": ok, "round": int(entry.get("round") or 0) + 1}
        if entry.get("ok") is True and not ok:
            problems.append(
                {
                    "gate": "pipeline",
                    "severity": "major",
                    "code": "gate_regression",
                    "message": (
                        f"`{name}` passed on the previous build and fails now: the last change "
                        "broke a gate that was already working. Restore it before anything else."
                    ),
                }
            )
    # Gates that did not run this round keep their last state: otherwise a hard stop would
    # silently erase the record of a gate that had been passing.
    for name, entry in previous.items():
        if name.startswith("_"):
            continue
        history.setdefault(name, entry)
    rounds = [item for item in (previous.get("_rounds") or []) if isinstance(item, dict)]
    rounds.append({"round": len(rounds) + 1, "blockers": int(blockers), "failed": list(failed or [])})
    history["_rounds"] = rounds[-8:]
    return problems, history


def repair_convergence(work_dir: Path) -> dict[str, Any] | None:
    """Whether the repair rounds are converging, read from the QA round history.

    2026-09-17 live: the budget was a fixed count of rounds while the blocker count barely
    moved, so the run ended in a user prompt — "repair budget exhausted, 23 majors left, what
    now?" — and the granted rounds included one that only undid its predecessor. Publishing
    the trend lets the main session decide from numbers instead of asking the user to guess,
    and gives it an explicit stop condition when a round made things worse.
    """
    path = work_dir / GATE_HISTORY_NAME
    if not path.is_file():
        return None
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(history, dict):
        return None
    rounds = [item for item in (history.get("_rounds") or []) if isinstance(item, dict)]
    if len(rounds) < 2:
        return None
    previous = int(rounds[-2].get("blockers") or 0)
    current = int(rounds[-1].get("blockers") or 0)
    if current < previous:
        trend = "improving"
        advice = "the blocker count is coming down; another round is justified"
    elif current == previous:
        trend = "flat"
        advice = (
            "the last round removed no blockers net: change the approach or deliver incomplete — "
            "repeating it with more budget is not a repair strategy"
        )
    else:
        trend = "worse"
        advice = (
            "the last round ADDED blockers: recover the regression first; granting more rounds "
            "on the same approach only moves the cost"
        )
    result: dict[str, Any] = {
        "rounds": rounds,
        "previous_blockers": previous,
        "current_blockers": current,
        "trend": trend,
        "advice": advice,
    }
    # D3 (informational): pages touched per round. Two consecutive rounds naming
    # the same pages while the trend is not "improving" is the signature of work
    # that keeps polishing the same spots instead of clearing the blocker set.
    pages_by_round = [sorted(item.get("pages") or []) for item in rounds]
    result["pages_touched_by_round"] = pages_by_round
    if (
        trend != "improving"
        and len(pages_by_round) >= 2
        and pages_by_round[-1]
        and pages_by_round[-1] == pages_by_round[-2]
    ):
        result["advice"] += (
            f" Rounds {rounds[-1].get('round')} and {rounds[-2].get('round')} name exactly the "
            f"same pages ({pages_by_round[-1]}): the approach is not moving those pages — "
            "change it or deliver incomplete."
        )

    # A blocker group that is byte-identical in two consecutive rounds while everything else
    # moved is evidence about the GATE, not about the pages. 2026-09-18 live: 16
    # `missing_final_reference` blockers were identical in all four QA rounds (the gate matched
    # each evidence entry's claim text against a bibliography that lists sources), so `complete`
    # was unreachable by construction. The trend stayed "improving" — 48/34/23/17 — and the run
    # spent the whole repair budget plus 5.4M tokens of forensics on a fixed offset, then asked
    # the user a question it could have answered itself. Naming the group converts that into a
    # reading the main session can act on: exclude it, repair the rest, and say so in the
    # delivery note.
    previous_codes = {str(k): int(v) for k, v in (rounds[-2].get("codes") or {}).items()}
    current_codes = {str(k): int(v) for k, v in (rounds[-1].get("codes") or {}).items()}
    frozen = {code: count for code, count in current_codes.items() if previous_codes.get(code) == count}
    frozen_total = sum(frozen.values())
    if previous_codes and frozen_total >= max(3, int(0.2 * current)):
        result["suspect_gate_defect"] = {
            "codes": dict(sorted(frozen.items())),
            "blockers": frozen_total,
            "share_of_current": round(frozen_total / current, 3) if current else None,
            "advice": (
                "these blockers are identical in two consecutive rounds while the rest of the "
                "list moved: repair rounds cannot change them, so they are a gate-side candidate "
                "rather than page work. Check them against the artifact once — if the deck already "
                "satisfies the stated contract, the check is wrong. Either way stop spending repair "
                "rounds on this group: exclude it, repair the remaining blockers, and record it as a "
                "known gate limitation in the delivery note. Do not ask the user to choose a "
                "delivery strategy for it — the data already answers what to do."
            ),
        }
    return result


