#!/usr/bin/env python3
"""Stable CLI for deck delivery checking, dispatched by generator-core version.

Version history used to live in sibling script names
(`pptx_delivery_check_v07.py`, `_v071.py`, `_v08.py`), which meant every new
core added another top-level tool and every doc had to pick one. Version
belongs in schema and data, not in file names: this entry is the single
external surface, and `--core` selects the implementation. The historical
modules stay importable as internal implementations and their own tests keep
covering them.

    python delivery_check.py [--core {v07,v071,v08}] <original args...>

`--core` defaults to v08 (the current pipeline contract); remaining arguments
are forwarded verbatim to the selected implementation, whose exit code is
returned. This wrapper's own `--help` documents the dispatch surface; the
per-core flags are documented by the inner modules (also reachable directly).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORES = {
    "v07": "pptx_delivery_check_v07",
    "v071": "pptx_delivery_check_v071",
    "v08": "pptx_delivery_check_v08",
}
DEFAULT_CORE = "v08"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--core",
        choices=sorted(CORES),
        default=DEFAULT_CORE,
        help="internal delivery-check implementation to dispatch to (default: %(default)s)",
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
    # The historical mains parse sys.argv directly and return None; rewrite the
    # argv so their usage/prog strings stay truthful, then normalise the result.
    sys.argv = [f"{CORES[known.core]}.py", *forwarded]
    return module.main() or 0


if __name__ == "__main__":
    sys.exit(main())
