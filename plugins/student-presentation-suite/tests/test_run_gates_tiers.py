from __future__ import annotations

import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
run_gates = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "run_gates.py")


class RunGatesTierTests(unittest.TestCase):
    """2026-09-26 e2e: SKILL.md passes pipeline-contract tier names to
    run_gates.py, but the CLI only accepted high-score|standard — a fast deck
    could not run the sanctioned gate command at all."""

    def test_contract_tiers_are_accepted_and_normalized(self) -> None:
        self.assertEqual(run_gates.parse_args(["--quality", "fast"]).quality, "standard")
        self.assertEqual(
            run_gates.parse_args(["--quality", "standard"]).quality, "standard"
        )
        self.assertEqual(
            run_gates.parse_args(["--quality", "rigorous"]).quality, "high-score"
        )
        self.assertEqual(
            run_gates.parse_args(["--quality", "high-score"]).quality, "high-score"
        )

    def test_default_tier_is_high_score(self) -> None:
        self.assertEqual(run_gates.parse_args([]).quality, "high-score")


if __name__ == "__main__":
    unittest.main()
