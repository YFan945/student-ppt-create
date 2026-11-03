"""Real local repairs preserve unrelated facts, references and atomicity."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

import test_research_evidence as fixtures

from shared.research_updates import apply_updates, update_current


class PackUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TextEvidenceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.pack = self.fixture.pack
        self.path = self.fixture.work / "research-pack.json"
        self.path.write_text(json.dumps(self.pack), encoding="utf-8")
        (self.fixture.fetched / "fetch-text-report.json").write_text(json.dumps(self.fixture.report), encoding="utf-8")
        self.update = self.fixture.work / "update.json"

    def save(self, update):
        self.update.write_text(json.dumps(update), encoding="utf-8")

    def test_cli_updates_one_field_without_rebuilding_or_searching(self):
        self.save({"upsert": {"findings": [{"id": "F01", "notes": "仅限报告样本"}]}})
        before = copy.deepcopy(self.pack)
        with patch.object(fixtures.validator, "validate", wraps=fixtures.validator.validate) as validate:
            self.assertEqual(0, fixtures.validator.main([str(self.path), "--patch", str(self.update)]))
        self.assertEqual(validate.call_count, 1)
        result = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result["findings"][0].pop("notes"), "仅限报告样本")
        before["findings"][0].pop("notes", None)
        self.assertEqual(result, before)
        self.assertFalse(update_current(self.path, self.update, fixtures.validator)["changed"])

    def test_invalid_reference_update_preserves_original_bytes(self):
        before = self.path.read_bytes()
        self.save({"remove": {"sources": ["S01"]}})
        with self.assertRaisesRegex(ValueError, "original Pack preserved"):
            update_current(self.path, self.update, fixtures.validator)
        self.assertEqual(self.path.read_bytes(), before)

    def test_removing_candidate_cleans_only_ancillary_links(self):
        original = copy.deepcopy(self.pack)
        original["data_points"].append({"id": "D99", "source_ids": ["S01"]})
        original["evidence"].append({"entity_id": "D99", "source_id": "S01"})
        original["visual_candidates"][0]["data_point_ids"] = ["D01", "D99"]
        result = apply_updates(original, {"remove": {"data_points": ["D99"]}})
        self.assertEqual(result["data_points"], self.pack["data_points"])
        self.assertEqual(result["evidence"], self.pack["evidence"])
        self.assertEqual(result["visual_candidates"][0]["data_point_ids"], ["D01"])
        self.assertEqual(result["must_verify"], self.pack["must_verify"])

    def test_duplicate_updates_and_wrong_shapes_are_rejected(self):
        for update in ({"upsert": {"findings": [{"id": "F01"}, {"id": "F01"}]}},
                       {"upsert": {"findings": [{"id": None}]}},
                       {"upsert": {"sources": []}, "unexpected": True}):
            with self.assertRaises(ValueError):
                apply_updates(self.pack, update)

    def test_null_removes_only_requested_field(self):
        result = apply_updates(self.pack, {"upsert": {"data_points": [{"id": "D01", "source_value": None}]}})
        self.assertNotIn("source_value", result["data_points"][0])
        self.assertEqual(result["sources"], self.pack["sources"])
