#!/usr/bin/env python3
"""Stable CLI for the deck quality gate, dispatched by generator-core version.

Same contract as `delivery_check.py`: one external surface, `--core` selects
the internal implementation, historical modules stay importable but are no
longer exposed as sibling CLIs.

    python quality_gate.py [--core {v071}] <original args...>

`--core` currently only has v071 (the only quality-gate implementation); the
default is pinned explicitly so adding a future core never silently changes
behaviour for existing calls. This wrapper's own `--help` documents the
dispatch surface; the per-core flags are documented by the inner modules
(also reachable directly).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORES = {"v071": "pptx_quality_gate_v071"}
DEFAULT_CORE = "v071"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--core",
        choices=sorted(CORES),
        default=DEFAULT_CORE,
        help="internal quality-gate implementation to dispatch to (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        known, forwarded = build_parser().parse_known_args(args)
    except SystemExit as exc:  # argparse: 0 = help was printed, else usage error
        if exc.code in (0, None):
            raise
        return 2
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    module = importlib.import_module(CORES[known.core])
    sys.argv = [f"{CORES[known.core]}.py", *forwarded]
    return module.main() or 0


if __name__ == "__main__":
    sys.exit(main())
