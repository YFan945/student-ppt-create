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


if __name__ == "__main__":
    unittest.main()
