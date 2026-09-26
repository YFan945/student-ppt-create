"""Structural-contract gate: layout promises must be realized in the built PPTX.

layout-library.json `requirements` declared what a layout needs since v0.15, and
plan/copy-fit checked the spec side — but the BUILT page was only judged by the
critic. These tests pin the deterministic observables: asset/data zero
realization is critical on every tier; the chart/table instrument promise is
weak-realized when a data page renders text numbers only (fast advisory,
standard+ major); unresolvable layout ids are skipped, never guessed.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pptx_structural_contract_check as gate  # noqa: E402

SPEC = {
    "slides": [
        {"id": 1, "title": "Cover", "layout": "cover-minimal"},
        {"id": 2, "title": "Visual", "layout": "visual-left"},
        {"id": 3, "title": "KPI", "layout": "data-kpi-row"},
        {"id": 4, "title": "Chart", "layout": "data-chart-takeaway"},
        {"id": 5, "title": "Freeform", "layout": "totally-made-up"},
    ]
}

RUN_WITH_DIGITS = "<a:p><a:r><a:t>214 人次</a:t></a:r></a:p>"
RUN_PLAIN = "<a:p><a:r><a:t>标题文字没有数字</a:t></a:r></a:p>"


def write_deck(root: Path, slides: dict[int, str]) -> Path:
    pptx = root / "deck.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        )
        for number, body in slides.items():
            archive.writestr(
                f"ppt/slides/slide{number}.xml",
                f"<p:sld xmlns:p='p' xmlns:a='a'>{body}</p:sld>",
            )
            if "chart" in body:
                archive.writestr(
                    f"ppt/slides/_rels/slide{number}.xml.rels",
                    "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                    '<Relationship Type="x/chart" Target="../charts/chart1.xml"/></Relationships>',
                )
                archive.writestr("ppt/charts/chart1.xml", "<c:chart xmlns:c='c'/>")
    return pptx


def write_spec(root: Path) -> Path:
    path = root / "slide-spec.yaml"
    import yaml

    path.write_text(yaml.safe_dump(SPEC, allow_unicode=True), encoding="utf-8")
    return path


class StructuralContractCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spec = write_spec(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def report(self, slides: dict[int, str], quality: str = "fast") -> dict:
        return gate.check_pptx(write_deck(self.root, slides), self.spec, quality=quality)

    def test_asset_required_with_picture_passes(self) -> None:
        report = self.report({2: "<p:pic/>"})
        self.assertEqual([], [i for i in report["issues"] if i["slide"] == 2])

    def test_asset_required_zero_realization_is_critical_even_fast(self) -> None:
        report = self.report({2: RUN_PLAIN})
        issue = next(i for i in report["issues"] if i["slide"] == 2)
        self.assertEqual("asset_required_missing", issue["code"])
        self.assertEqual("critical", issue["severity"])
        self.assertFalse(report["ok"])

    def test_kpi_numbers_fulfill_data_without_a_chart(self) -> None:
        report = self.report({3: RUN_WITH_DIGITS})
        self.assertEqual([], [i for i in report["issues"] if i["slide"] == 3])

    def test_data_zero_realization_is_critical_even_fast(self) -> None:
        report = self.report({3: RUN_PLAIN})
        issue = next(i for i in report["issues"] if i["slide"] == 3)
        self.assertEqual("data_required_missing", issue["code"])
        self.assertEqual("critical", issue["severity"])

    def test_instrument_promise_with_text_numbers_is_weak(self) -> None:
        report = self.report({4: RUN_WITH_DIGITS})
        issue = next(i for i in report["issues"] if i["slide"] == 4)
        self.assertEqual("data_instrument_missing", issue["code"])
        self.assertEqual("minor", issue["severity"], "fast tier: weak realization is advisory")
        self.assertTrue(report["ok"], "fast tier: weak realization does not block")

    def test_instrument_weak_realization_blocks_outside_fast(self) -> None:
        for quality in ("standard", "rigorous"):
            with self.subTest(quality=quality):
                report = self.report({4: RUN_WITH_DIGITS}, quality=quality)
                issue = next(i for i in report["issues"] if i["slide"] == 4)
                self.assertEqual("major", issue["severity"])
                self.assertFalse(report["ok"])

    def test_chart_instrument_fulfills_the_promise(self) -> None:
        report = self.report({4: RUN_WITH_DIGITS + "chart"})
        self.assertEqual([], [i for i in report["issues"] if i["slide"] == 4])

    def test_unknown_layout_ids_are_skipped_not_guessed(self) -> None:
        report = self.report({5: RUN_PLAIN})
        self.assertEqual([], report["issues"])
        skipped = {item["slide"]: item for item in report["skipped_slides"]}
        self.assertIn(5, skipped)
        self.assertEqual("layout id not in library", skipped[5]["reason"])
        # layouts without any deterministic requirement (cover-minimal) skip too
        self.assertIn(1, skipped)

    def test_absent_slide_parts_are_skipped(self) -> None:
        report = self.report({})
        self.assertEqual([], report["checked_slides"])
        self.assertEqual([], report["issues"])


if __name__ == "__main__":
    unittest.main()
