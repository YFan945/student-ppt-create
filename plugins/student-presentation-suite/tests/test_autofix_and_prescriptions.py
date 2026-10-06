"""0.26.0 builder/critic round-reduction — regression pins.

Three structural moves: mechanical repair findings (layout swaps) are applied by
the pipeline instead of a builder instance; deterministic failures carry an
executable remedy; calibration is gated deterministically with a single
production-boundary review.
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]

autofix = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "pipeline" / "autofix.py")
cr = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "calibration_review.py")
packet = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "builder_packet.py")

PAGE = (
    "'use strict';\n"
    "/** Slide 1 — demo */\n"
    "const COPY = { title: \"t\", claim: \"c\", keyLine: \"\", slideCopy: [\"a\", \"b\"] };\n"
    "module.exports = {\n"
    "  dark: false,\n"
    "  kind: \"content\",\n"
    "  context: {},\n"
    "  layout: {current},\n"
    "  slots: { title: COPY.title, body: COPY.slideCopy },\n"
    "  params: {{}},\n"
    "  notes: \"n\",\n"
    "};\n"
)


def write_review(path: Path, findings: list[dict]) -> Path:
    path.write_text(json.dumps({
        "review_version": "0.8",
        "pptx_sha256": "x",
        "slides": [{"slide": 1, "visual_structure": "split", "scores": {
            "hierarchy": 7, "focal_point": 7, "composition": 7, "visual_interest": 7, "whitespace": 7,
        }, "issues": findings}],
    }, ensure_ascii=False), encoding="utf-8")
    return path


class ApplyPageFixesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / "pages").mkdir()
        self.page = self.work / "pages" / "p01-demo.js"
        self.page.write_text(PAGE.replace("{current}", "undefined"), encoding="utf-8")
        self.review = self.work / "visual-review.json"

    def _run(self) -> dict:
        completed = subprocess.run(
            ["node", str(ROOT / "scripts" / "apply_page_fixes.js"),
             "--work-dir", str(self.work), "--review", str(self.review)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return json.loads(completed.stdout)

    def test_layout_swap_finding_is_applied_to_the_page_module(self):
        write_review(self.review, [{
            "code": "cramped-composition", "severity": "major",
            "message": "body overflows",
            "element": "body 区域",
            "fix": "换用 'claim-focus' 版式并压缩 body",
            "repair_level": "implementation",
        }])
        report = self._run()
        self.assertEqual(1, report["applied_count"])
        self.assertEqual("claim-focus", report["applied"][0]["to"])
        self.assertIn('layout: "claim-focus"', self.page.read_text(encoding="utf-8"))
        self.assertTrue((self.work / "autofix-report.json").is_file())

    def test_second_pass_is_a_noop_when_layout_already_matches(self):
        write_review(self.review, [{
            "code": "cramped-composition", "severity": "major", "message": "m",
            "element": "e", "fix": "换用 'claim-focus'", "repair_level": "implementation",
        }])
        self._run()
        report = self._run()
        self.assertEqual(0, report["applied_count"])
        self.assertEqual("layout is already claim-focus", report["skipped"][0]["reason"])

    def test_function_form_pages_are_never_patched(self):
        self.page.write_text(
            "module.exports = function (ctx) { /* custom: D9 escape hatch */ };\n",
            encoding="utf-8",
        )
        write_review(self.review, [{
            "code": "cramped-composition", "severity": "major", "message": "m",
            "element": "e", "fix": "换用 'claim-focus'", "repair_level": "implementation",
        }])
        report = self._run()
        self.assertEqual(0, report["applied_count"])
        self.assertIn("not data-patchable", report["skipped"][0]["reason"])


class AutofixRoutingTests(unittest.TestCase):
    """Mixed or creative findings keep the builder; all-mechanical goes to autofix."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / "pages").mkdir()
        (self.work / "pages" / "p01-demo.js").write_text(
            PAGE.replace("{current}", "undefined"), encoding="utf-8"
        )

    def test_all_mechanical_findings_route_to_autofix(self):
        write_review(self.work / "visual-review.json", [{
            "code": "cramped-composition", "severity": "major", "message": "m",
            "element": "e", "fix": "换用 'claim-focus'", "repair_level": "implementation",
        }])
        report = autofix.autofix_pending_repair(self.work)
        self.assertIsNotNone(report)
        self.assertEqual(1, report["applied_count"])

    def test_one_creative_finding_falls_back_to_the_builder(self):
        write_review(self.work / "visual-review.json", [
            {"code": "cramped-composition", "severity": "major", "message": "m",
             "element": "e", "fix": "换用 'claim-focus'", "repair_level": "implementation"},
            {"code": "weak-narrative", "severity": "major", "message": "m",
             "element": "整页", "fix": "重新设计信息层级", "repair_level": "composition"},
        ])
        self.assertIsNone(autofix.autofix_pending_repair(self.work))

    def test_no_review_or_only_minors_never_autofix(self):
        self.assertIsNone(autofix.autofix_pending_repair(self.work))
        write_review(self.work / "visual-review.json", [{
            "code": "cramped-composition", "severity": "minor", "message": "m",
        }])
        self.assertIsNone(autofix.autofix_pending_repair(self.work))


class CheckPageModuleRemedyTests(unittest.TestCase):
    def test_unknown_layout_remedy_lists_valid_ids(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "pages").mkdir()
            (work / "deck.js").write_text(
                "const TOKENS = " + json.dumps({"palette": {"accent": "C8102E", "canvas": "FFFFFF"}, "typography": {}}) + ";\nmodule.exports={};",
                encoding="utf-8",
            )
            (work / "pages" / "p01-x.js").write_text(
                "module.exports = { dark:false, kind:'content', layout:'kpi-band', "
                "slots:{ body:['a','b','c'] }, params:{}, notes:'n' };",
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["node", str(ROOT / "scripts" / "check_page_module.js"),
                 "--work-dir", str(work), "--pages", "pages/p01-x.js"],
                capture_output=True, text=True,
            )
            report = json.loads(proc.stdout)
        finding = next(f for f in report["findings"] if f["kind"] == "throw")
        self.assertIn("remedy", finding)
        self.assertIn("claim-focus", finding["remedy"][0])
        self.assertIn("kpi-band", finding["remedy"][0])


class CalibrationDeterministicGateTests(unittest.TestCase):
    def test_green_calibration_without_a_review_file(self):
        from test_style_contract import StyleContractTests

        fixture = StyleContractTests()
        fixture.setUp()
        fixture.green_calibration([1])
        (fixture.work / "calibration" / "calibration-visual-review.json").unlink()
        try:
            result = cr.calibration_review(fixture.work)
            self.assertTrue(result["ok"], result["reason"])
            self.assertFalse(result["review_advisory"]["present"])
        finally:
            fixture.doCleanups()

    def test_packet_carries_the_declarative_page_example(self):
        example = packet.DECLARATIVE_PAGE_EXAMPLE
        self.assertIn("exports", example)
        self.assertIn("L.renderDeclaredPage", example["notes_lines"][0])
        self.assertIn('packet["example_page"]', (ROOT / "skills" / "sp-deck" / "scripts" / "builder_packet.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
