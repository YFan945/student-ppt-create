"""Composition-candidates schema/template/validator consistency.

The 2026-09-26 e2e run lost two repair-free minutes to field-shape guessing
(`zones` written as an array, `slide_id` omitted) because the candidate file
had a validator and a gate but no shape contract. This file pins the triangle:

1. the emitted `--emit-template` skeleton validates against
   references/composition-candidates.schema.json;
2. the skeleton passes composition_candidate_check.validate_candidates up to
   the one thing a skeleton cannot know (real reference-library ids);
3. every field the checker/gate consumes exists in the schema, so a validator
   rename cannot silently orphan the shape contract (and vice versa).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills" / "sp-deck" / "scripts" / "composition_candidate_check.py"
SCHEMA = ROOT / "references" / "composition-candidates.schema.json"

# Fields composition_candidate_check.py / pptx_visual_generation_gate_v08.py
# actually read (issue codes key off these); keep in sync with both.
VALIDATOR_FIELDS = {
    "slide_id", "high_leverage", "candidates", "selected_id", "selection_reason",
    "id", "silhouette", "rationale", "focal_share", "title_pt", "body_pt",
    "reference_ids", "zones", "exception_justification",
}


def emit_template(slide_id: int) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--emit-template", str(slide_id), "--json"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AssertionError(f"--emit-template failed: {proc.stderr[:300]}")
    return json.loads(proc.stdout)


class CompositionCandidateSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        from jsonschema import Draft202012Validator

        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_emitted_template_matches_schema(self) -> None:
        template = emit_template(3)
        errors = sorted(self.validator.iter_errors(template), key=lambda e: list(e.path))
        self.assertEqual(
            [], [f"{list(e.path)}: {e.message}" for e in errors],
        )

    def test_template_slide_id_follows_the_argument(self) -> None:
        self.assertEqual(7, emit_template(7)["slide_id"])

    def test_template_zone_shapes_match_the_e2e_failure_modes(self) -> None:
        template = emit_template(2)
        self.assertTrue(template["high_leverage"])
        self.assertGreaterEqual(len(template["candidates"]), 2)
        for candidate in template["candidates"]:
            self.assertIsInstance(candidate["zones"], dict, "zones must be an object, not an array")
            for zone in candidate["zones"].values():
                self.assertEqual(4, len(zone))
                x, y, w, h = zone
                self.assertGreater(w, 0)
                self.assertGreater(h, 0)
                self.assertLessEqual(x + w, 1.000001)
                self.assertLessEqual(y + h, 1.000001)

    def test_template_passes_the_checker_up_to_real_reference_ids(self) -> None:
        sys.path.insert(0, str(CHECKER.parent))
        try:
            import composition_candidate_check as checker
        finally:
            sys.path.remove(str(CHECKER.parent))
        report = checker.validate_candidates(emit_template(4), high_score=True)
        self.assertEqual(
            [], [i for i in report["issues"] if i["severity"] in checker.BLOCKING],
        )

    def test_schema_covers_every_validator_consumed_field(self) -> None:
        root_properties = set(self.schema["properties"])
        candidate_properties = set(self.schema["$defs"]["candidate"]["properties"])
        covered = root_properties | candidate_properties
        missing = sorted(VALIDATOR_FIELDS - covered)
        self.assertEqual([], missing)

    def test_template_fields_do_not_drift_from_schema(self) -> None:
        template = emit_template(5)
        covered = set(self.schema["properties"]) | set(self.schema["$defs"]["candidate"]["properties"])
        stray = (
            set(template)
            | {key for candidate in template["candidates"] for key in candidate}
        ) - covered
        self.assertEqual([], sorted(stray))


if __name__ == "__main__":
    unittest.main()
