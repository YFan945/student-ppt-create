"""README flow tables are generated from the contract — drift is a test failure."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import render_pipeline_tables as tables  # noqa: E402


class ReadmeGeneratedTableTests(unittest.TestCase):
    def test_generated_blocks_match_both_readmes(self) -> None:
        contract = tables.load_contract()
        for lang, path in tables.READMES.items():
            with self.subTest(lang=lang):
                block = tables.render_block(contract, lang)
                text = path.read_text(encoding="utf-8")
                self.assertIn(block, text, f"{path.name} flow table drifted — run scripts/render_pipeline_tables.py")

    def test_check_mode_passes_on_the_current_tree(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "render_pipeline_tables.py"), "--check"],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_both_languages_carry_the_same_machine_numbers(self) -> None:
        contract = tables.load_contract()
        en = tables.render_block(contract, "en")
        zh = tables.render_block(contract, "zh")
        for token in (
            f"| {contract['max_repairs']} |",
            f"| {contract['max_repairs_hard_cap']} |",
            f"| {contract['max_pre_qa_rebuilds']} |",
            "`fast`",
            "`standard`",
            "`rigorous`",
        ):
            self.assertIn(token, en)
            self.assertIn(token, zh)
        for stage in contract["qa_order"]:
            self.assertIn(f"`{stage}`", en)
            self.assertIn(f"`{stage}`", zh)

    def test_stale_hand_written_claims_are_gone(self) -> None:
        zh = tables.READMES["zh"].read_text(encoding="utf-8")
        en = tables.READMES["en"].read_text(encoding="utf-8")
        self.assertNotIn("默认流程只有三道门禁", zh)
        self.assertNotIn("最多允许一次", zh)
        self.assertNotIn("three gates", en)
        self.assertNotIn("At most one repair loop", en)


if __name__ == "__main__":
    unittest.main()
