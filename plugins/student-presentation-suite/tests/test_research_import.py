"""Research stop conditions and D-class structured import (no researcher subagent)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "scripts"), str(ROOT / "skills" / "sp-deck" / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import import_user_materials as importer  # noqa: E402
import validate_research_pack as validator  # noqa: E402
from pipeline import core  # noqa: E402


def base_pack(**over) -> dict:
    pack = {
        "version": "1.0",
        "topic": "test",
        "budget": "standard",
        "queries": ["q1"],
        "findings": [],
        "sources": [
            {"id": "S1", "title": "a", "type": "web", "tier": "B", "independence_group": "a"},
            {"id": "S2", "title": "b", "type": "web", "tier": "B", "independence_group": "b"},
        ],
    }
    pack.update(over)
    return pack


class MustVerifyStopConditionTests(unittest.TestCase):
    def test_absent_declaration_is_not_yet_required(self) -> None:
        self.assertEqual([], validator.must_verify_issues(base_pack()))

    def test_three_to_five_claims_with_coverage_pass(self) -> None:
        pack = base_pack(must_verify=[
            {"claim": "c1", "source_ids": ["S1", "S2"]},
            {"claim": "c2", "source_ids": ["S2"]},
            {"claim": "c3", "status": "unresolved"},
        ])
        self.assertEqual([], validator.must_verify_issues(pack))

    def test_out_of_range_claim_count_is_reported(self) -> None:
        pack = base_pack(must_verify=[{"claim": "c1", "source_ids": ["S1"]}])
        codes = {item["code"] for item in validator.must_verify_issues(pack)}
        self.assertIn("must_verify_count", codes)

    def test_uncovered_claim_names_the_stop_condition(self) -> None:
        pack = base_pack(must_verify=[
            {"claim": "c1", "source_ids": ["S1"]},
            {"claim": "c2"},
            {"claim": "c3"},
        ])
        problems = [item for item in validator.must_verify_issues(pack) if item["code"] == "must_verify_uncovered"]
        self.assertEqual(2, len(problems), "claims without source_ids must be covered or unresolved")
        self.assertEqual({"major"}, {item["severity"] for item in problems})

    def test_simple_band_downgrades_to_advisory(self) -> None:
        pack = base_pack(
            budget="simple",
            must_verify=[{"claim": "c1"}],
        )
        problems = validator.must_verify_issues(pack)
        self.assertTrue(problems)
        self.assertEqual({"minor"}, {item["severity"] for item in problems})

    def test_unknown_source_reference_is_reported(self) -> None:
        pack = base_pack(must_verify=[
            {"claim": "c1", "source_ids": ["S1"]},
            {"claim": "c2", "source_ids": ["S1"]},
            {"claim": "c3", "source_ids": ["S9"]},
        ])
        codes = {item["code"] for item in validator.must_verify_issues(pack)}
        self.assertIn("must_verify_unknown_source", codes)


class StructuredImportTests(unittest.TestCase):
    def run_import(self, work: Path, materials: list[Path]) -> dict:
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "import_user_materials.py"),
                *[str(path) for path in materials],
                "--work-dir", str(work), "--json",
            ],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        return json.loads(result.stdout)

    def test_import_builds_a_hash_bound_d_pack_without_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            material = root / "paper.md"
            material.write_text("# my paper\n", encoding="utf-8")
            work = root / "outputs" / ".pptx-work" / "work-01"
            work.mkdir(parents=True)
            payload = self.run_import(work, [material])
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(1, payload["sources"])
            pack = json.loads((work / "research-pack.json").read_text(encoding="utf-8"))
            self.assertEqual([], pack["queries"])
            self.assertEqual("import_user_materials", pack["pack_author"])
            source = pack["sources"][0]
            self.assertEqual("user-file", source["type"])
            self.assertEqual(importer.sha256_file(material), source["sha256"])
            self.assertTrue((work / "research-pack-validation.json").is_file())
            self.assertTrue((work / "research-import.json").is_file())

    def test_missing_material_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "outputs" / ".pptx-work" / "work-01"
            work.mkdir(parents=True)
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "import_user_materials.py"),
                    str(root / "nope.md"), "--work-dir", str(work), "--json",
                ],
                check=False, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(2, result.returncode)


class ImportReceiptTests(unittest.TestCase):
    def test_plan_accepts_the_import_receipt_in_place_of_a_researcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            material = root / "paper.md"
            material.write_text("# my paper\n", encoding="utf-8")
            work = root / "outputs" / ".pptx-work" / "work-01"
            work.mkdir(parents=True)
            pack = importer.build_pack([material], "topic")
            pack_path = work / "research-pack.json"
            pack_path.write_text(json.dumps(pack), encoding="utf-8")
            (work / "research-import.json").write_text(json.dumps({
                "tool": "import_user_materials.py",
                "work_id": work.name,
                "files": [{"path": str(material), "sha256": pack["sources"][0]["sha256"]}],
                "pack": core.bind(pack_path),
            }), encoding="utf-8")
            receipt = core.execution_receipt(work, "research", pack_path)
            self.assertTrue(receipt["imported"])
            self.assertEqual(work.name, receipt["work_id"])

    def test_drifted_material_is_a_hard_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            material = root / "paper.md"
            material.write_text("# my paper\n", encoding="utf-8")
            work = root / "outputs" / ".pptx-work" / "work-01"
            work.mkdir(parents=True)
            pack = importer.build_pack([material], "topic")
            pack_path = work / "research-pack.json"
            pack_path.write_text(json.dumps(pack), encoding="utf-8")
            (work / "research-import.json").write_text(json.dumps({
                "tool": "import_user_materials.py",
                "work_id": work.name,
                "files": [{"path": str(material), "sha256": pack["sources"][0]["sha256"]}],
                "pack": core.bind(pack_path),
            }), encoding="utf-8")
            material.write_text("# edited after import\n", encoding="utf-8")
            with self.assertRaisesRegex(core.RefusedError, "material changed after import"):
                core.execution_receipt(work, "research", pack_path)

    def test_without_an_import_receipt_the_researcher_rule_stays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "outputs" / ".pptx-work" / "work-01"
            work.mkdir(parents=True)
            pack_path = work / "research-pack.json"
            pack_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(core.RefusedError):
                core.execution_receipt(work, "research", pack_path)


if __name__ == "__main__":
    unittest.main()
