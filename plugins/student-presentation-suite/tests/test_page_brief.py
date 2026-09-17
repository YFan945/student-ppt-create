from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
PAGE_BRIEF = ROOT / "skills" / "sp-deck" / "scripts" / "page_brief.py"
ACTUAL = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_actual_content_check.py"

SPEC = """\
meta:
  citation_style: classroom
slides:
  - id: 1
    title: 光伏与风电的总成本曲线已经交叉
    claim: 交叉点不等于替代时点
    layout: cover
    content: []
    timing_sec: 30
    owner: deck
    slide_copy:
      - 2024 年公用事业级光伏 LCOE 降至 0.044 美元每千瓦时
  - id: 7
    title: 储能缺口决定替代速度
    claim: 储能时长从 4 小时走到 10 小时，度电成本才追平
    layout: chart
    content: []
    timing_sec: 40
    owner: deck
    evidence_refs: [E02]
    slide_copy:
      - 85% 的新增装机来自光伏
      - 配储比例 10%
evidence_ledger:
  - id: E02
    title: Renewable Power Generation Costs in 2024
    source_ids: [S01, S04]
    locator: irena.org/publications/2025
    date: 2025-06
    used_on_slides: [7]
"""

CHINESE_TITLE = "《“十五五”碳达峰行动方案》解读"


class PageBriefTests(unittest.TestCase):
    """`page_brief.py` replaces the builder's hand-rolled `node -e` extractors.

    2026-09-18 transcript analysis: a repair round ran 19-46 inline scripts to pull
    these same fields out of qa-quality.json / research-pack.json / build-manifest.json,
    plus 11 re-reads of slide-spec-compiled.yaml. The brief must therefore be
    byte-identical to what the gates judge, or the builder is being told the wrong thing.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "carbon-pv-wind"
        (self.work / "pages").mkdir(parents=True)
        self.brief = load_module(PAGE_BRIEF)
        self.actual = load_module(ACTUAL)
        (self.work / "slide-spec-compiled.yaml").write_text(SPEC, encoding="utf-8")
        (self.work / "research-pack.json").write_text(
            json.dumps(
                {
                    "sources": [
                        {"id": "S01", "title": "Renewable Power Generation Costs in 2024", "publisher": "IRENA", "year": 2025},
                        {"id": "S04", "title": CHINESE_TITLE, "publisher": "国务院", "year": 2026},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (self.work / "pipeline-qa.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "failed_stages": ["actual_content", "quality", "delivery"],
                    "blockers_by_gate": {
                        "actual_content": ["missing_key_claim"],
                        "quality": ["speaker_notes_missing"],
                    },
                    "derived_problems": ["delivery_incomplete"],
                    "problems": [
                        {"gate": "actual_content", "severity": "major", "code": "missing_key_claim", "message": "claim missing", "slide": 7},
                        {"gate": "actual_content", "severity": "major", "code": "missing_key_claim", "message": "claim missing", "slide": 1},
                        {"gate": "quality", "severity": "major", "code": "missing_final_reference", "message": "refs missing"},
                        {"gate": "delivery", "severity": "major", "code": "delivery_incomplete", "message": "upstream failed", "derived": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.work / "build-manifest.json").write_text(
            json.dumps({"state": "producing", "manifest_version": "2.0"}), encoding="utf-8"
        )
        (self.work / "art-direction.yaml").write_text("high_leverage_slides: [1, 7]\n", encoding="utf-8")
        (self.work / "pages" / "p01-cover.js").write_text("// stub", encoding="utf-8")
        (self.work / "pages" / "p07-s07.js").write_text("// stub", encoding="utf-8")

    def test_slide_requirements_are_identical_to_what_the_readback_gate_judges(self) -> None:
        """The builder must be handed the same bytes the gate will compare against."""
        brief = self.brief.build_brief(self.work, 7)
        spec = self.brief.load_structured(self.work / "slide-spec-compiled.yaml")
        planned = spec["slides"][1]
        self.assertEqual(self.actual.planned_requirements(planned), brief["on_screen"])
        self.assertEqual(
            ["10", "10%", "4", "85%"],
            brief["on_screen"]["numbers"],
        )

    def test_sources_come_byte_exact_from_the_research_pack(self) -> None:
        """2026-09-17 live: hand-typed source titles drifted at character level and the
        final-reference gate rejected 6 refs. The rail must carry the pack's bytes."""
        brief = self.brief.build_brief(self.work, 7)
        self.assertEqual(["S01", "S04"], [item["id"] for item in brief["sources"]])
        self.assertEqual(CHINESE_TITLE, brief["sources"][1]["title"])

    def test_blockers_are_split_per_slide_deck_level_and_derived(self) -> None:
        brief = self.brief.build_brief(self.work, 7)
        self.assertEqual(["missing_key_claim"], [item["code"] for item in brief["blockers"]])
        self.assertEqual(["missing_final_reference"], [item["code"] for item in brief["deck_blockers"]])
        self.assertEqual(["delivery_incomplete"], brief["deck"]["derived_problems"])
        self.assertNotIn(
            "delivery_incomplete",
            [item["code"] for item in brief["deck_blockers"]],
            "a derived failure must not be handed to the builder as its own task",
        )
        self.assertEqual("pages/p07-s07.js", brief["page_module"])
        self.assertTrue(brief["high_leverage"])

    def test_deck_brief_covers_every_slide_once(self) -> None:
        """initial mode reads the whole deck in one call instead of 11 spec re-reads."""
        brief = self.brief.build_brief(self.work, None)
        self.assertEqual([1, 7], [item["slide"] for item in brief["slides"]])
        self.assertEqual("pages/p01-cover.js", brief["slides"][0]["page_module"])
        self.assertEqual([1, 7], brief["high_leverage_slides"])
        self.assertEqual(["missing_key_claim"], [item["code"] for item in brief["slides"][1]["blockers"]])

    def test_unknown_slide_is_an_error_not_an_empty_brief(self) -> None:
        with self.assertRaises(SystemExit):
            self.brief.build_brief(self.work, 99)

    def test_missing_spec_is_an_error(self) -> None:
        (self.work / "slide-spec-compiled.yaml").unlink()
        with self.assertRaises(SystemExit):
            self.brief.build_brief(self.work, None)


if __name__ == "__main__":
    unittest.main()
