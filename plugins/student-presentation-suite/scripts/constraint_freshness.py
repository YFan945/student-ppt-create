#!/usr/bin/env python3
"""Report how far python-constraints.txt pins drift from PyPI latest.

dependabot's pip group is disabled for this repo (v0.16.8): the constraints
file is a cross-platform frozen pin set that independent transitive bumps kept
breaking. Staleness is therefore a manual discipline, and this script turns it
into a monthly report (the dep-freshness workflow) instead of silent drift.

The report is informational: a pin older than latest is not automatically
wrong — magika/mpmath/numpy/onnxruntime stay frozen until their parent
constraints move, and a regen must cover py3.11/3.12 on linux and windows.
Exit code is always 0; the workflow greps the DRIFT line.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s#]+)")


def pins(path: Path) -> list[tuple[str, str]]:
    """Ordered unique (package, pin) pairs from a constraints file."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN_RE.match(line.strip())
        if not match or match.group(1).lower() in seen:
            continue
        seen.add(match.group(1).lower())
        found.append((match.group(1), match.group(2)))
    return found


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def build_report(path: Path, fetch=fetch_json) -> str:
    rows: list[tuple[str, str, str, str]] = []
    drifted = 0
    for package, pinned in pins(path):
        payload = fetch(f"https://pypi.org/pypi/{package}/json")
        latest = str(payload.get("version") or "?")
        requires = str((payload.get("info") or {}).get("requires_python") or "?")
        if latest != pinned:
            drifted += 1
        rows.append((package, pinned, latest, requires))
    lines = [
        "| package | pinned | pypi latest | latest requires_python |",
        "| --- | --- | --- | --- |",
    ]
    for package, pinned, latest, requires in rows:
        lines.append(f"| {package} | {pinned} | {latest} | {requires} |")
    lines.append("")
    lines.append(f"DRIFT: {drifted}/{len(rows)} pins differ from PyPI latest.")
    lines.append(
        "A pin older than latest is not automatically wrong: check whether the "
        "parent constraint still forces the older pin (magika/mpmath/numpy/"
        "onnxruntime are deliberately frozen, see CHANGELOG 0.16.4-0.16.6) and "
        "regenerate with py3.11/3.12 coverage on linux and windows."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("constraints", type=Path, help="path to python-constraints.txt")
    args = parser.parse_args()
    print(build_report(args.constraints))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
