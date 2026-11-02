"""All compatibility core names use the same current technical policy."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "skills/sp-deck/scripts"):
    sys.path.insert(0, str(directory))
import delivery_check
import quality_gate


class DispatchTestCase(unittest.TestCase):
    def test_every_compatibility_core_uses_current_policy(self):
        for entry, kind in ((delivery_check, "delivery"), (quality_gate, "quality")):
            for core in [None, *entry.CORES]:
                with self.subTest(kind=kind, core=core), patch("shared.validation_cli.main", return_value=0) as check:
                    forwarded = ["--pptx", "deck.pptx", "--strict"]
                    self.assertEqual(entry.main((["--core", core] if core else []) + forwarded), 0)
                    check.assert_called_once_with(kind, forwarded)

    def test_invalid_core_is_usage_error(self):
        for entry in (delivery_check, quality_gate):
            for args in (["--core"], ["--core", "v99"]):
                with patch("shared.validation_cli.main") as check:
                    self.assertEqual(entry.main(args), 2)
                    check.assert_not_called()
