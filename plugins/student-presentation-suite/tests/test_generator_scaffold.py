from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "skills" / "sp-deck" / "scripts" / "generator_scaffold.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScaffoldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scaffold = load_module("generator_scaffold_contract_test", SCAFFOLD)

    def test_deck_inlines_resolved_tokens_and_binds_background(self) -> None:
        """The stub must model the correct calls: tokens flow to pages, no raw hex."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps({
                    "meta": {"visual_style": "Data Driven"},
                    "slides": [{"id": 1, "title": "封面", "kind": "cover"}],
                }),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            deck = (work / "deck.js").read_text(encoding="utf-8")
            self.assertIn("const TOKENS = ", deck)
            self.assertIn("H.applyTokens(pptx, TOKENS, 'chinese')", deck)
            self.assertIn("H.color(TOKENS, 'canvas')", deck)
            self.assertIn("tokens: TOKENS", deck)
            self.assertNotIn("canvas: 'FFFFFF' }}", deck)
            start = deck.index("const TOKENS = ") + len("const TOKENS = ")
            tokens = json.loads(deck[start:deck.index(";\n", start)])
            self.assertIn("palette", tokens)

    def test_page_stub_demonstrates_fitted_text_notes_and_alt_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps({"slides": [{"id": 1, "title": "封面", "kind": "cover"}]}),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            stub = next((work / "pages").glob("p*.js")).read_text(encoding="utf-8")
            self.assertIn("H.addFittedText(", stub)
            self.assertIn("'title')", stub)
            self.assertIn("slide.addNotes", stub)
            self.assertIn("altText", stub)
            self.assertNotIn("slide.addText(COPY.title", stub)

    def test_page_stub_carries_the_on_screen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps({"slides": [{"id": 1, "title": "封面", "kind": "cover"}]}),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            stub = (work / "pages" / "p01-cover.js").read_text(encoding="utf-8")
            self.assertIn("ON-SCREEN REQUIRED", stub)
            self.assertIn("actual-content", stub)
            self.assertIn("planned_numbers_missing", stub)

    def test_closing_page_gets_a_byte_exact_source_rail_from_the_pack(self) -> None:
        """2026-09-17 live: hand-typed titles drifted at character level and the
        final-reference gate rejected 6 refs; the rail is injected by code, not typing."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            pack = {
                "sources": [
                    {
                        "id": "S01",
                        "title": "Renewable Power Generation Costs in 2024",
                        "publisher": "IRENA",
                        "year": 2025,
                    },
                    {
                        "id": "S02",
                        "title": "《“十五五”碳达峰行动方案》解读",
                        "publisher": "国务院",
                        "year": 2026,
                    },
                ]
            }
            (work / "research-pack.json").write_text(
                json.dumps(pack, ensure_ascii=False), encoding="utf-8"
            )
            spec = work / "spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "slides": [
                            {"id": 1, "title": "封面", "kind": "cover"},
                            {"id": 2, "title": "结论", "kind": "closing"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            closing = (work / "pages" / "p02-closing.js").read_text(encoding="utf-8")
            self.assertIn("Renewable Power Generation Costs in 2024", closing)
            self.assertIn("《“十五五”碳达峰行动方案》解读", closing)
            self.assertIn("never retype them", closing)
            cover = (work / "pages" / "p01-cover.js").read_text(encoding="utf-8")
            self.assertNotIn("sources:", cover)

    def test_last_slide_without_closing_kind_still_carries_the_rail(self) -> None:
        """The final-reference gate matches against the last page's reference area."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "research-pack.json").write_text(
                json.dumps({"sources": [{"id": "S01", "title": "Only Source", "year": 2026}]}),
                encoding="utf-8",
            )
            spec = work / "spec.json"
            spec.write_text(
                json.dumps(
                    {"slides": [{"id": 1, "title": "结论", "role": "conclusion"}]}
                ),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            last = (work / "pages" / "p01-s01.js").read_text(encoding="utf-8")
            self.assertIn("Only Source", last)

    def test_page_stub_injects_this_pages_verbatim_requirements(self) -> None:
        """2026-09-18: the stub only said "this page needs its numbers" without saying
        which, so the builder re-read slide-spec-compiled.yaml 11 times in one round."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "slides": [
                            {
                                "id": 7,
                                "title": "储能缺口决定替代速度",
                                "claim": "储能时长从 4 小时走到 10 小时，度电成本才追平",
                                "slide_copy": ["85% 的新增装机来自光伏"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.scaffold.scaffold_generator(work, spec)
            stub = (work / "pages" / "p07-s07.js").read_text(encoding="utf-8")
            self.assertIn("claim:   储能时长从 4 小时走到 10 小时，度电成本才追平", stub)
            self.assertIn("numbers: 10 · 4 · 85%", stub)
            self.assertIn("copy:    85% 的新增装机来自光伏", stub)

    def test_spec_text_cannot_close_the_stub_comment(self) -> None:
        """A spec title or claim containing */ must not truncate a comment and turn the
        rest of the text into code (the doc comment is still a comment)."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            spec = work / "spec.json"
            spec.write_text(
                json.dumps(
                    {"slides": [{"id": 1, "title": "a */ b", "claim": "c */ d"}]}
                ),
                encoding="utf-8",
            )
            result = self.scaffold.scaffold_generator(work, spec)
            stub = (work / "pages" / result["pages"][0]).read_text(encoding="utf-8")
            self.assertIn("a * / b", stub)
            self.assertIn("c * / d", stub)
            head, _, _ = stub.partition("\nmodule.exports")
            self.assertEqual(
                head.count("/*"),
                head.count("*/"),
                "every comment opened in the header must close exactly once",
            )


if __name__ == "__main__":
    unittest.main()
