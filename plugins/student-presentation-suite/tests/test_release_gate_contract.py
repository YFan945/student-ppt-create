"""The release gate runs its own suite (2026-10-11).

v0.28.1 was published with two failing tests: no release gate ran the unit
suite, so "run the tests" was an AGENTS.md instruction the operator had to
remember. `check_plugin_release.py` now executes the suite as its last stage.
These tests pin the parsing seam (which is testable without recursively running
the suite inside the suite) and the wiring that would otherwise quietly vanish.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_plugin_release.py"

_SPEC = importlib.util.spec_from_file_location("check_plugin_release", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)

GREEN = """\
ppt_pipeline: built deck.pptx
Ran 1363 tests in 93.330s

OK (skipped=1)
"""

RED = """\
Ran 1362 tests in 90.100s

FAILED (failures=2, skipped=1)
"""


class TestSummaryParsingTests(unittest.TestCase):
    def test_reads_a_green_run(self) -> None:
        report = check.parse_test_summary(GREEN, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(1363, report["tests_run"])
        self.assertEqual("OK (skipped=1)", report["summary"])

    def test_reads_a_red_run(self) -> None:
        report = check.parse_test_summary(RED, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(1362, report["tests_run"])
        self.assertEqual("FAILED (failures=2, skipped=1)", report["summary"])

    def test_a_lookalike_ok_printed_by_a_test_is_not_the_verdict(self) -> None:
        output = "OK\nsome narration\nRan 4 tests in 0.100s\n\nFAILED (failures=1)\n"
        report = check.parse_test_summary(output, 1)
        self.assertEqual("FAILED (failures=1)", report["summary"])

    def test_unparsable_output_still_reports_the_exit_code(self) -> None:
        report = check.parse_test_summary("boom", 3)
        self.assertFalse(report["ok"])
        self.assertIsNone(report["tests_run"])
        self.assertEqual("exit 3", report["summary"])


class ReleaseGateWiringTests(unittest.TestCase):
    def test_the_suite_stage_is_wired_into_the_gate(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("tests = check_test_suite(errors)", source)
        self.assertIn('"tests": tests', source)

    def test_a_red_run_fails_the_gate(self) -> None:
        report = check.parse_test_summary(RED, 1)
        self.assertEqual(
            "单元测试套件未通过: FAILED (failures=2, skipped=1)",
            check.test_suite_error(report),
        )

    def test_a_green_run_raises_no_error(self) -> None:
        report = check.parse_test_summary(GREEN, 0)
        self.assertIsNone(check.test_suite_error(report))

    def test_timeout_is_a_positive_budget(self) -> None:
        self.assertIsInstance(check.TEST_SUITE_TIMEOUT_SECONDS, int)
        self.assertGreater(check.TEST_SUITE_TIMEOUT_SECONDS, 0)


if __name__ == "__main__":
    unittest.main()
