"""Builder Packet: the isolated builder's complete task input (v0.15 Batch 2).

Context projection, not just context isolation: three parallel builders used to
re-read the same frozen inputs (spec, art direction, research pack, QA reports),
paying for three copies of one context. The packet projects exactly one instance's
slice; these tests pin the projection so it stays byte-derived from the sources
the gates judge.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PACKET = ROOT / "skills" / "sp-deck" / "scripts" / "builder_packet.py"
ACTUAL = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_actual_content_check.py"

SPEC = """\
meta:
  citation_style: classroom
slides:
  - id: 1
    title: 封面页
    claim: 交叉点不等于替代时点
    layout: cover
    content: []
    timing_sec: 30
    owner: deck
    slide_copy:
      - 2024 年公用事业级光伏 LCOE 降至 0.044 美元每千瓦时
  - id: 2
    title: 背景页
    claim: 装机结构正在转向
    layout: narrative
    content: []
    timing_sec: 40
    owner: deck
    slide_copy:
      - 85% 的新增装机来自光伏
  - id: 3
    title: 对比页
    claim: 度电成本已交叉
    layout: comparison
    content: []
    timing_sec: 45
    owner: deck
    evidence_refs: [E01]
    slide_copy:
      - 光伏 0.044 美元每千瓦时
  - id: 4
    title: 数据页
    claim: 储能决定替代速度
    layout: chart
    content: []
    timing_sec: 40
    owner: deck
    evidence_refs: [E01]
    slide_copy:
      - 配储比例 10%
evidence_ledger:
  - id: E01
    title: Renewable Power Generation Costs in 2024
    source_ids: [S01]
    locator: irena.org/publications/2025
    date: 2025-06
    used_on_slides: [3, 4]
"""

ART_DIRECTION = """\
style_id: academic-rigorous
palette:
  light: {bg: "#FFFFFF", fg: "#111111", accent: "#0A5C2E"}
  dark: {bg: "#101418", fg: "#F2F2F2", accent: "#6FCF97"}
typography:
  body_min_pt: 22
high_leverage_slides: [1, 3, 4]
"""


class BuilderPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "demo"
        (self.work / "pages").mkdir(parents=True)
        self.packet = load_module(BUILDER_PACKET)
        self.actual = load_module(ACTUAL)
        (self.work / "slide-spec-compiled.yaml").write_text(SPEC, encoding="utf-8")
        (self.work / "art-direction.yaml").write_text(ART_DIRECTION, encoding="utf-8")
        (self.work / "research-pack.json").write_text(
            json.dumps(
                {"sources": [{"id": "S01", "title": "Renewable Power Generation Costs in 2024",
                              "publisher": "IRENA", "year": 2025}]}
            ),
            encoding="utf-8",
        )
        for number in range(1, 5):
            (self.work / "pages" / f"p0{number}-s0{number}.js").write_text(
                "// student-presentation-suite-scaffold stub\n", encoding="utf-8"
            )

    # --- calibration ---------------------------------------------------------

    def test_calibration_defaults_to_high_leverage_slides(self) -> None:
        self.assertEqual([1, 3, 4], self.packet.default_calibration_slides(self.work))

    def test_calibration_packet_projects_style_and_requirements(self) -> None:
        path, packet = self.packet.write_packet(self.work, "calibration", [1, 4])
        self.assertTrue(path.is_file())
        self.assertEqual("calibration", packet["mode"])
        self.assertEqual([1, 4], packet["assigned_slides"])
        self.assertEqual("speaker-notes.md", packet["speaker_notes_target"])
        self.assertEqual("academic-rigorous", packet["art_direction"]["style_id"])
        slide4 = next(item for item in packet["slides"] if item.get("id") == 4)
        self.assertEqual(self.actual.planned_requirements(
            {"id": 4, "title": "数据页", "claim": "储能决定替代速度", "layout": "chart",
             "content": [], "slide_copy": ["配储比例 10%"]}
        )["numbers"], slide4["requirements"]["numbers"])
        self.assertEqual(["S01"], [s["id"] for s in slide4["sources"]])
        self.assertIn("pages/p04-s04.js", packet["allowed_files"])
        self.assertIn("build", packet["forbidden_actions"])
        self.assertIn("render", packet["forbidden_actions"])

    # --- initial -------------------------------------------------------------

    def test_initial_single_packet_covers_remaining_scaffold_slides(self) -> None:
        path, packet = self.packet.write_packet(self.work, "initial")
        self.assertEqual([1, 2, 3, 4], packet["assigned_slides"])
        self.assertTrue(all(item["page_module"] for item in packet["slides"]))
        self.assertIn("speaker-notes.md", packet["allowed_files"])

    def test_initial_shard_packets_are_disjoint_with_own_notes_targets(self) -> None:
        descriptors = self.packet.prepare_packets(self.work, "initial")
        self.assertGreaterEqual(len(descriptors), 2, "four pages should shard")
        seen: list[int] = []
        notes: list[str] = []
        for descriptor in descriptors:
            packet = json.loads(Path(descriptor["packet"]).read_text(encoding="utf-8"))
            self.assertEqual(packet["shard"], descriptor["shard"])
            seen.extend(packet["assigned_slides"])
            notes.append(packet["speaker_notes_target"])
        self.assertEqual(sorted(seen), [1, 2, 3, 4], "shards must cover every page exactly once")
        self.assertEqual(len(set(notes)), len(notes), "shards must not share a notes fragment")

    # --- repair --------------------------------------------------------------

    def prepare_qa(self) -> None:
        (self.work / "pipeline-qa.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "failed_stages": ["quality"],
                    "blockers_by_gate": {"quality": ["speaker_notes_missing"]},
                    "problems": [
                        {"gate": "quality", "severity": "major", "code": "overflow",
                         "message": "title overflow", "slide": 3},
                        {"gate": "quality", "severity": "major", "code": "overflow",
                         "message": "claim clipped", "slide": 4},
                        {"gate": "delivery", "severity": "major", "code": "missing_final_reference",
                         "message": "refs missing"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.work / "visual-score-history.json").write_text(
            json.dumps({"3": {"average": 7.2, "best": 7.8}, "4": {"average": 6.9, "best": 6.9}}),
            encoding="utf-8",
        )

    def test_repair_packet_projects_blockers_history_and_deck_level_findings(self) -> None:
        self.prepare_qa()
        path, packet = self.packet.write_packet(
            self.work, "repair", [3, 4], None, ["pipeline-qa.json"]
        )
        self.assertEqual("repair", packet["mode"])
        self.assertEqual([str((self.work / "pipeline-qa.json").resolve())], packet["reports"])
        slide3 = next(item for item in packet["slides"] if item.get("id") == 3)
        self.assertEqual(["overflow"], [b["code"] for b in slide3["blockers"]])
        self.assertEqual({"average": 7.2, "best": 7.8}, slide3["must_not_regress"])
        self.assertEqual(
            ["missing_final_reference"], [b["code"] for b in packet["deck_blockers"]],
            "deck-level blockers must be visible without reading the report",
        )

    def test_repair_blockers_coming_from_reports_beat_state_projections(self) -> None:
        """Without reports the packet falls back to deck state; with reports it uses
        them — the two sources must not be silently mixed."""
        self.prepare_qa()
        path, packet = self.packet.write_packet(self.work, "repair", [3], None, ["pipeline-qa.json"])
        slide3 = packet["slides"][0]
        self.assertEqual(["overflow"], [b["code"] for b in slide3["blockers"]])

    # --- errors --------------------------------------------------------------

    def test_unknown_slide_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            self.packet.build_packet(self.work, "initial", [9])

    def test_unknown_mode_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            self.packet.build_packet(self.work, "design", [1])

    def test_repair_without_slides_or_reports_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            self.packet.build_packet(self.work, "repair")

    # --- CLI -----------------------------------------------------------------

    def test_cli_writes_packet_and_prints_descriptor(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.packet.main(
                ["--work-dir", str(self.work), "--mode", "calibration", "--slides", "1", "4", "--json"]
            )
        self.assertEqual(0, code)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(Path(payload["packet"]).is_file())
        self.assertEqual([1, 4], payload["slides"])

    def test_cli_reports_whether_an_override_keeps_coverage(self) -> None:
        """2026-09-20: overriding the calibration default is allowed, but the
        cost of the swap must be on the record, not in the session's head."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.packet.main(
                ["--work-dir", str(self.work), "--mode", "calibration", "--slides", "1", "4", "--json"]
            )
        self.assertEqual(0, code)
        coverage = json.loads(buffer.getvalue())["coverage"]
        self.assertEqual([1, 3, 4], coverage["default"])
        self.assertEqual([1, 4], coverage["candidate"])
        self.assertEqual({"default": 3, "candidate": 2}, coverage["archetype_count"])
        self.assertFalse(coverage["keeps_coverage"])
        self.assertIn("rejected", coverage["verdict"])

    def test_coverage_is_printed_as_one_line_without_json(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.packet.main(["--work-dir", str(self.work), "--mode", "calibration", "--slides", "1", "4"])
        self.assertIn("calibration coverage:", buffer.getvalue())

    def test_empty_initial_set_yields_no_packets(self) -> None:
        (self.work / "pages" / "p01-s01.js").write_text(
            "// implemented — no scaffold marker\nexport default {};\n", encoding="utf-8"
        )
        for number in range(1, 5):
            (self.work / "pages" / f"p0{number}-s0{number}.js").write_text(
                "// implemented — no scaffold marker\nexport default {};\n", encoding="utf-8"
            )
        self.assertEqual([], self.packet.prepare_packets(self.work, "initial"))


if __name__ == "__main__":
    unittest.main()
