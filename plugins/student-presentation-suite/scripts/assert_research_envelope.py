#!/usr/bin/env python3
"""Assert a Research Pack handoff is the compact envelope, not a prose dump.

Main-flow isolation (CD-5) fails when a teammate pastes findings back. This
checker accepts the 8-line RESEARCH_DONE / RESEARCH_BLOCKED envelope and
rejects extra body text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MAX_LINES = 12
ALLOWED_PREFIXES = (
    "RESEARCH_DONE",
    "RESEARCH_BLOCKED",
    "pack:",
    "validation:",
    "findings:",
    "data_points:",
    "quotes:",
    "unresolved:",
    "status:",
    "reason:",
)


def check_text(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    problems: list[str] = []
    if not lines:
        return ["empty research handoff"]
    if not lines[0].startswith(("RESEARCH_DONE", "RESEARCH_BLOCKED")):
        problems.append("first line must be RESEARCH_DONE or RESEARCH_BLOCKED")
    if len(lines) > MAX_LINES:
        problems.append(f"handoff has {len(lines)} lines; max {MAX_LINES} (CD-5 envelope)")
    for line in lines:
        if not line.startswith(ALLOWED_PREFIXES):
            problems.append(f"extra prose is not allowed: {line[:80]}")
            break
    return problems


def check_main_transcript(text: str) -> list[str]:
    """Main-flow isolation: raw retrieval tools must not appear in the parent chat."""
    problems: list[str] = []
    for marker in ("WebSearch", "WebFetch"):
        if marker in text:
            problems.append(f"main transcript contains {marker} (CD-5)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="file path; default stdin")
    args = parser.parse_args(argv)
    text = Path(args.source).read_text(encoding="utf-8") if args.source else sys.stdin.read()
    problems = check_text(text)
    if problems:
        print("assert_research_envelope: blocked", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 2
    print("assert_research_envelope: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
