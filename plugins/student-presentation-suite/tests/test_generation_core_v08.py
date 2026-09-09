from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"
REF_SELECT = SKILL_SCRIPTS / "visual_reference_select.py"
ART_CHECK = SKILL_SCRIPTS / "art_direction_check.py"
CANDIDATE_CHECK = SKILL_SCRIPTS / "composition_candidate_check.py"
VISUAL_GATE = SKILL_SCRIPTS / "pptx_visual_generation_gate_v08.py"
REFERENCE_LIBRARY = ROOT / "skills" / "sp-deck" / "references" / "visual-reference-library.json"
WIREFRAME = ROOT / "scripts" / "composition_wireframe.js"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenerationCoreV08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selector = load_module("visual_reference_select_v08_test", REF_SELECT)
        cls.art = load_module("art_direction_check_v08_test", ART_CHECK)
        cls.candidates = load_module("composition_candidate_check_v08_test", CANDIDATE_CHECK)
        cls.visual_gate = load_module("pptx_visual_generation_gate_v08_test", VISUAL_GATE)
        cls.library = cls.selector.load_library(REFERENCE_LIBRARY)
        cls.reference_ids = cls.candidates.load_reference_ids(REFERENCE_LIBRARY)

    def test_reference_retrieval_prefers_matching_strategy_and_distinct_silhouettes(self) -> None:
        selected = self.selector.select_references(
            self.library,
            role="prove",
            grammar="academic-research",
            visual_strategy="chart",
            density="medium",
            tags=["evidence", "result"],
            count=3,
        )
        self.assertEqual(3, len(selected))
        self.assertEqual(3, len({item["silhouette"] for item in selected}))
        self.assertIn("data-big-number-proof", {item["id"] for item in selected})
        self.assertTrue(any("visual-strategy" in item["match_reasons"] for item in selected))

    def test_reference_retrieval_penalizes_recent_duplicate(self) -> None:
        baseline = self.selector.select_references(
            self.library,
            role="cover",
            grammar="coursework",
            visual_strategy="mixed",
            count=1,
        )[0]
        repeated = self.selector.select_references(
            self.library,
            role="cover",
            grammar="coursework",
            visual_strategy="mixed",
            history_ids=[baseline["id"]],
            history_silhouettes=[baseline["silhouette"]],
            count=1,
        )[0]
        self.assertNotEqual(baseline["id"], repeated["id"])

    def good_art_direction(self, high_slides=(1, 2, 5)):
        return {
            "version": "0.8",
            "concept": "Evidence-first editorial classroom deck with decisive visual hierarchy",
            "color_system": {
                "dominant_role": "canvas",
                "dominant_share_pct": 65,
                "contrast_mode": "dark-light-sandwich",
                "accent_usage": "key evidence only",
            },
            "typography": {
                "personality": "editorial",
                "cover_title_pt": 52,
                "slide_title_pt": 34,
                "key_statement_pt": 30,
                "body_pt": 19,
                "caption_pt": 10,
            },
            "imagery": {
                "strategy": "evidence-first",
                "crop_language": "half-bleed and edge crop",
                "treatment": "natural color",
            },
            "icon_language": {"usage": "semantic accent", "style": "line", "max_per_slide": 3},
            "chart_grammar": {"default": "native chart", "takeaway": "one highlighted series"},
            "component_language": {"cards": "exception", "borders": "hairline", "shadows": "none"},
            "motif": {"name": "evidence rail", "description": "source annotation treatment"},
            "background_rhythm": [
                {"role": "cover", "mode": "dark"},
                {"role": "content", "mode": "light"},
                {"role": "closing", "mode": "dark"},
            ],
            "asset_plan": {
                "hero_visuals": 1,
                "evidence_visuals": 2,
                "diagrams": 1,
                "native_charts": 1,
                "typography_led": 1,
            },
            "high_leverage_slides": [
                {"slide": slide, "reason": f"Slide {slide} carries a decisive visual/narrative moment"}
                for slide in high_slides
            ],
        }

    def test_art_direction_passes_concrete_positive_priors(self) -> None:
        result = self.art.validate_art_direction(self.good_art_direction(), high_score=True)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual([1, 2, 5], result["high_leverage_slides"])

    def test_art_direction_blocks_weak_type_hierarchy(self) -> None:
        data = self.good_art_direction()
        data["typography"]["slide_title_pt"] = 24
        data["typography"]["body_pt"] = 22
        result = self.art.validate_art_direction(data, high_score=True)
        self.assertFalse(result["ok"])
        self.assertIn("weak_type_hierarchy", {item["code"] for item in result["issues"]})

    def test_art_direction_blocks_missing_high_leverage_plan(self) -> None:
        data = self.good_art_direction()
        data["high_leverage_slides"] = []
        result = self.art.validate_art_direction(data, high_score=True)
        self.assertFalse(result["ok"])
        self.assertIn("high_leverage_count_invalid", {item["code"] for item in result["issues"]})

    def good_candidate_set(self, slide_id=5):
        return {
            "version": "0.8",
            "slide_id": slide_id,
            "high_leverage": True,
            "candidates": [
                {
                    "id": "A",
                    "visual_strategy": "chart",
                    "silhouette": "big-number-chart",
                    "reference_ids": ["data-big-number-proof"],
                    "dominant_element": "key_number",
                    "focal_share": 0.48,
                    "title_pt": 34,
                    "body_pt": 19,
                    "zones": {
                        "title": [0.06, 0.06, 0.72, 0.1],
                        "focus": [0.07, 0.24, 0.3, 0.3],
                        "visual": [0.43, 0.22, 0.5, 0.55],
                    },
                    "rationale": "Lead with the result number, then use the chart as proof for the stated claim.",
                },
                {
                    "id": "B",
                    "visual_strategy": "chart",
                    "silhouette": "figure-caption",
                    "reference_ids": ["data-figure-caption"],
                    "dominant_element": "figure",
                    "focal_share": 0.65,
                    "title_pt": 34,
                    "body_pt": 19,
                    "zones": {
                        "title": [0.05, 0.05, 0.72, 0.1],
                        "visual": [0.06, 0.2, 0.68, 0.61],
                        "body": [0.78, 0.23, 0.17, 0.42],
                    },
                    "rationale": "Let the research figure dominate and reserve a narrow rail for one interpretation.",
                },
            ],
            "selected_id": "A",
            "selection_reason": "Candidate A makes the quantitative takeaway visible before the chart and best fits the evidence-first art direction.",
        }

    def test_high_leverage_candidates_pass_when_distinct_and_referenced(self) -> None:
        result = self.candidates.validate_candidates(
            self.good_candidate_set(),
            known_reference_ids=self.reference_ids,
            high_score=True,
        )
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(2, len(result["distinct_silhouettes"]))

    def test_high_leverage_candidates_block_fake_single_option(self) -> None:
        data = self.good_candidate_set()
        data["candidates"] = data["candidates"][:1]
        result = self.candidates.validate_candidates(data, known_reference_ids=self.reference_ids, high_score=True)
        self.assertFalse(result["ok"])
        self.assertIn("candidate_count_low", {item["code"] for item in result["issues"]})

    def test_high_leverage_candidates_block_duplicate_silhouette(self) -> None:
        data = self.good_candidate_set()
        data["candidates"][1]["silhouette"] = data["candidates"][0]["silhouette"]
        result = self.candidates.validate_candidates(data, known_reference_ids=self.reference_ids, high_score=True)
        self.assertFalse(result["ok"])
        self.assertIn("candidate_silhouettes_not_distinct", {item["code"] for item in result["issues"]})

    def test_high_leverage_candidates_block_out_of_bounds_zone(self) -> None:
        data = self.good_candidate_set()
        data["candidates"][0]["zones"]["visual"] = [0.8, 0.2, 0.4, 0.5]
        result = self.candidates.validate_candidates(data, known_reference_ids=self.reference_ids, high_score=True)
        self.assertFalse(result["ok"])
        self.assertIn("zone_out_of_bounds", {item["code"] for item in result["issues"]})

    def test_wireframe_renderer_probe(self) -> None:
        completed = subprocess.run(
            ["node", str(WIREFRAME), "--probe"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual("0.8", payload["version"])

    def render_wireframe(self, candidate_file: Path, output: Path) -> None:
        subprocess.run(
            ["node", str(WIREFRAME), "--input", str(candidate_file), "--output", str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_wireframe_renderer_writes_pptx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_file = root / "candidates.json"
            candidate_file.write_text(json.dumps(self.good_candidate_set()), encoding="utf-8")
            output = root / "wireframes.pptx"
            self.render_wireframe(candidate_file, output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)

    def make_reference_selection(self) -> dict:
        ids = {"data-big-number-proof", "data-figure-caption"}
        selected = [item for item in self.library["references"] if item["id"] in ids]
        return {"version": "0.8", "selected": selected}

    def test_visual_generation_gate_binds_high_leverage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "slide-spec.yaml"
            spec.write_text(
                yaml.safe_dump({"slides": [{"id": 1}, {"id": 2}, {"id": 3}]}, sort_keys=False),
                encoding="utf-8",
            )
            art = root / "art-direction.yaml"
            art.write_text(yaml.safe_dump(self.good_art_direction((1, 2, 3)), sort_keys=False), encoding="utf-8")

            for slide in (1, 2, 3):
                (root / f"references-slide-{slide}.json").write_text(
                    json.dumps(self.make_reference_selection()), encoding="utf-8"
                )
                candidate_file = root / f"composition-candidates-{slide}.json"
                candidate_file.write_text(json.dumps(self.good_candidate_set(slide)), encoding="utf-8")
                self.render_wireframe(candidate_file, root / f"wireframes-{slide}.pptx")

            result = self.visual_gate.validate_visual_generation(
                slide_spec=spec,
                art_direction=art,
                evidence_dir=root,
                quality="high-score",
            )
            self.assertTrue(result["ok"], result["issues"])
            self.assertEqual([1, 2, 3], result["high_leverage_slides"])
            self.assertEqual(3, len(result["evidence"]))
            self.assertTrue(all(item.get("wireframe_sha256") for item in result["evidence"]))

    def test_visual_generation_gate_blocks_missing_wireframe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "slide-spec.yaml"
            spec.write_text(yaml.safe_dump({"slides": [{"id": 1}, {"id": 2}, {"id": 3}]}), encoding="utf-8")
            art = root / "art-direction.yaml"
            art.write_text(yaml.safe_dump(self.good_art_direction((1, 2, 3))), encoding="utf-8")
            for slide in (1, 2, 3):
                (root / f"references-slide-{slide}.json").write_text(json.dumps(self.make_reference_selection()), encoding="utf-8")
                candidate_file = root / f"composition-candidates-{slide}.json"
                candidate_file.write_text(json.dumps(self.good_candidate_set(slide)), encoding="utf-8")
                if slide != 2:
                    self.render_wireframe(candidate_file, root / f"wireframes-{slide}.pptx")
            result = self.visual_gate.validate_visual_generation(
                slide_spec=spec,
                art_direction=art,
                evidence_dir=root,
                quality="high-score",
            )
            self.assertFalse(result["ok"])
            self.assertIn("wireframe_missing", {item["code"] for item in result["issues"]})


if __name__ == "__main__":
    unittest.main()
