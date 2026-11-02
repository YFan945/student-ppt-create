"""Batch QA emits one summary, with optional bounded failure details."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "skills/sp-deck/scripts"):
    sys.path.insert(0, str(directory))
import run_gates


class RunGatesSummaryTests(unittest.TestCase):
    def invoke(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_gates.main(args)
        return code, out.getvalue()

    def test_success_prints_one_line_and_does_not_chain_old_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "qa.json"
            with patch("shared.validation_cli.validate_artifact", return_value={"ok": True, "issues": []}) as validate:
                code, text = self.invoke(["--pptx", "deck.pptx", "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(len(text.splitlines()), 1)
            validate.assert_called_once()
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["ok"])

    def test_failure_details_are_bounded_and_cannot_be_bypassed_with_lenient(self):
        report = {"ok": False, "issues": [{"code": "missing_fact", "message": str(i)} for i in range(20)]}
        with patch("shared.validation_cli.validate_artifact", return_value=report):
            code, text = self.invoke(["--pptx", "deck.pptx", "--max-items", "3", "--lenient"])
        self.assertEqual(code, 2)
        self.assertEqual(len(text.splitlines()), 4)
        self.assertIn("missing_fact", text)

    def test_json_mode_emits_current_report(self):
        with patch("shared.validation_cli.validate_artifact", return_value={"ok": True, "issues": []}):
            code, text = self.invoke(["--pptx", "deck.pptx", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(text)["ok"])
        self.assertFalse(json.loads(text)["visual_quality_verified"])

    def test_planning_does_not_require_art_direction_wireframes_or_scores(self):
        with patch("shared.validation_cli.validate_slide_spec", return_value=({}, [], "")):
            code, text = self.invoke(["--slide-spec", "spec.yaml", "--evidence-dir", "missing", "--json"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(text)["artifact_checked"])

    def test_missing_input_returns_a_specific_failure(self):
        code, text = self.invoke(["--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["issues"][0]["code"], "input_missing")

    def test_missing_pptx_is_reported_without_traceback(self):
        code, text = self.invoke(["--pptx", "does-not-exist.pptx", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["issues"][0]["code"], "pptx_missing")
