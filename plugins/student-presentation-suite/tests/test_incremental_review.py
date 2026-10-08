"""0.27.0 builder/critic round-trip reduction — regression pins.

Incremental review: after a repair only the changed pages are re-reviewed;
unchanged pages carry their prior verdicts (bound by render PNG hashes). Plus
rigorous short decks use the same two-page look as standard.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import test_ppt_pipeline as pipeline_tests
from test_helpers import load_module
from test_ppt_pipeline import PipelineTestCase, minimal_pdf_bytes, pp

ROOT = Path(__file__).resolve().parents[1]

dispatch = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "pipeline" / "dispatch.py")
tiers = load_module(ROOT / "shared" / "quality_tiers.py")


class IncrementalScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.review = self.work / "visual-review.json"
        self.pages = [
            {"path": str(self.work / "render" / "s1.png"), "sha256": "a" * 64},
            {"path": str(self.work / "render" / "s2.png"), "sha256": "b" * 64},
        ]
        self.manifest = {"render": {"pages": self.pages}}

    def test_subset_change_yields_incremental_scope(self):
        self.review.write_text(json.dumps({
            "pptx_sha256": "old",
            "page_sha256": {"1": "a" * 64, "2": "old" * 16},
        }), encoding="utf-8")
        scope = dispatch._incremental_review_scope(self.work, self.manifest)
        self.assertEqual([2], scope["changed_slides"])
        self.assertEqual([1], scope["unchanged_slides"])
        self.assertEqual(str(self.review.resolve()), scope["prior_review"])

    def test_full_change_yields_none(self):
        self.review.write_text(json.dumps({
            "page_sha256": {"1": "x" * 64, "2": "y" * 64},
        }), encoding="utf-8")
        self.assertIsNone(dispatch._incremental_review_scope(self.work, self.manifest))

    def test_no_prior_review_or_no_page_map_yields_none(self):
        self.assertIsNone(dispatch._incremental_review_scope(self.work, self.manifest))
        self.review.write_text(json.dumps({"pptx_sha256": "old"}), encoding="utf-8")
        self.assertIsNone(dispatch._incremental_review_scope(self.work, self.manifest))


class IncrementalQaReceiptTests(PipelineTestCase):
    """The receipt only has to cover the contact sheet + changed pages when a
    valid review-scope.json is present; without it the full-page rule holds."""

    def setUp(self):
        super().setUp()
        self.files = self.write_inputs()
        self.plan(self.files)
        pp.main(["build", "--work-dir", str(self.work), "--entry", str(self.entry())])
        from PIL import Image
        manifest = self.manifest()
        pages = []
        for index in (1, 2):
            page = self.work / "render" / f"slide-{index}.png"
            page.parent.mkdir(exist_ok=True)
            Image.new("RGB", (640, 360), "white").save(page)
            pages.append(pp.bind(page))
        contact = self.work / "contact-sheet.png"
        pp.make_contact_sheet([Path(b["path"]) for b in pages], contact)
        pdf = self.work / "render" / "slide.pdf"
        pdf.write_bytes(minimal_pdf_bytes(2))
        manifest["render"] = {
            "pptx_sha256": pp.sha256_file(self.work / "deck.pptx"),
            "pages": pages,
            "contact_sheet": pp.bind(contact),
            "pdf": pp.bind(pdf),
            "page_count": 2,
        }
        pp.save_manifest(self.work, manifest)
        self.page_bindings = pages
        self.contact = contact
        self.review_path = self.files["visual_review"]
        scores = dict.fromkeys(("hierarchy", "focal_point", "composition", "visual_interest", "whitespace"), 8)
        review = {
            "pptx_sha256": manifest["render"]["pptx_sha256"],
            "contact_sheet_sha256": pp.sha256_file(contact),
            "page_sha256": {str(i): b["sha256"] for i, b in enumerate(pages, 1)},
            "slides": [
                {"slide": index, "visual_structure": "cover", "issues": [], "scores": dict(scores)}
                for index in (1, 2)
            ],
        }
        self.review_path.write_text(json.dumps(review), encoding="utf-8")
        self.prior_sha = pp.sha256_file(self.review_path)

    def _receipt(self, reads):
        receipt = {
            "agent": "student-presentation-suite:visual-critic",
            "agent_id": "test-child",
            "spawn_verified": True,
            "work_id": self.work.name,
            "artifact": pp.bind(self.review_path),
            "reads": reads,
        }
        (self.work / "critic-execution.json").write_text(json.dumps(receipt), encoding="utf-8")

    def _scope(self, changed):
        scope = {
            "changed_slides": changed,
            "unchanged_slides": [i for i in (1, 2) if i not in changed],
            "prior_review": str(self.review_path.resolve()),
            "prior_review_sha256": self.prior_sha,
        }
        (self.work / "review-scope.json").write_text(json.dumps(scope), encoding="utf-8")
        return scope

    def test_scope_limits_required_reads_to_changed_pages(self):
        # Page 1 is unchanged: the incremental critic read the prior review, the
        # contact sheet and page 2 only — and QA still accepts the report.
        self._scope(changed=[2])
        self._receipt({
            str(self.review_path.resolve()): self.prior_sha,
            str(self.contact.resolve()): pp.sha256_file(self.contact),
            str(self.page_bindings[1]["path"]): self.page_bindings[1]["sha256"],
        })
        runner = pipeline_tests.FakeRunner(self.work)
        pp._core._runner = runner
        argv = ["qa", "--work-dir", str(self.work), "--visual-review", str(self.review_path)]
        self.assertEqual(0, pp.main(argv))

    def test_without_scope_the_full_page_rule_holds(self):
        self._scope(changed=[2])
        self._receipt({
            str(self.review_path.resolve()): self.prior_sha,
            str(self.contact.resolve()): pp.sha256_file(self.contact),
            str(self.page_bindings[1]["path"]): self.page_bindings[1]["sha256"],
        })
        (self.work / "review-scope.json").unlink()
        runner = pipeline_tests.FakeRunner(self.work)
        pp._core._runner = runner
        argv = ["qa", "--work-dir", str(self.work), "--visual-review", str(self.review_path)]
        self.assertEqual(2, pp.main(argv))


class RigorousShortDeckCalibrationTests(unittest.TestCase):
    def test_rigorous_skips_calibration_at_or_below_the_page_line(self):
        self.assertTrue(tiers.calibration_enabled("rigorous", 8))
        self.assertTrue(tiers.uses_preview_pair("rigorous", 8))
        self.assertTrue(tiers.calibration_enabled("rigorous", 9))
        self.assertTrue(tiers.calibration_enabled("rigorous", None))
        self.assertTrue(tiers.calibration_enabled("standard", 8))


if __name__ == "__main__":
    unittest.main()
