"""Context projection: what travels in packets/briefs so nothing gets re-read."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (
    str(ROOT / "skills" / "sp-deck" / "scripts"),
    str(ROOT / "skills" / "sp-deck" / "scripts" / "pipeline"),
    str(ROOT / "scripts"),
):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import builder_guard  # noqa: E402
from pipeline import advance  # noqa: E402


class BriefProjectionTests(unittest.TestCase):
    def test_brief_carries_calibrator_and_high_leverage_slots(self) -> None:
        for key in ("calibration", "high_leverage_slides", "builder_shards", "pre_qa"):
            self.assertIn(key, advance.BRIEF_DISPATCH_KEYS)
        self.assertNotIn(
            "review_output",
            advance.BRIEF_DISPATCH_KEYS,
            "dead keys made the main session fetch the full dispatch for nothing",
        )

    def test_brief_drops_the_heavy_prose(self) -> None:
        self.assertNotIn("notes", advance.BRIEF_DISPATCH_KEYS)
        self.assertNotIn("contract", advance.BRIEF_DISPATCH_KEYS)


class NoRereadGapTests(unittest.TestCase):
    def test_contract_list_closes_the_known_gaps(self) -> None:
        contract = json.loads(
            (ROOT / "references" / "agent-behavior-contract.json").read_text(encoding="utf-8")
        )
        files = contract["presentation_builder"]["packet"]["no_reread_files"]
        for fragment in (
            "slide-spec-compiled", "slide-spec.yaml", "art-direction", "research-pack",
            "build-manifest", "pipeline-qa", "pre-qa", "qa-", "visual-review",
            "calibration-style-contract", "page_brief",
        ):
            self.assertIn(fragment, files)

    def test_guard_refuses_the_gap_files(self) -> None:
        for name in (
            "qa-package.json", "qa-rendered.json", "visual-review.json",
            "slide-spec.yaml", "calibration-style-contract.json",
        ):
            self.assertTrue(
                builder_guard._matches_no_reread(Path("/tmp") / name),
                f"{name} must not be re-readable during a packet round",
            )


if __name__ == "__main__":
    unittest.main()
