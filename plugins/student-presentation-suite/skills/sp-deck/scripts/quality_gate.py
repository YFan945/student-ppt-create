#!/usr/bin/env python3
"""Compatibility CLI for shared technical validation.

Historical analysis functions remain importable for explicit diagnostics;
the executable route uses shared.validation_cli and has no score/lock gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORES = {"v071": "pptx_quality_gate_v071"}
DEFAULT_CORE = "v071"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, add_help=False
    )
    parser.add_argument(
        "--core",
        choices=sorted(CORES),
        default=DEFAULT_CORE,
        help="deprecated compatibility core (same current policy) (default: %(default)s)",
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
    plugin = str(Path(__file__).resolve().parents[3])
    if plugin not in sys.path:
        sys.path.insert(0, plugin)
    from shared.validation_cli import main as validate_cli
    return validate_cli("quality", forwarded)



if __name__ == "__main__":
    sys.exit(main())
