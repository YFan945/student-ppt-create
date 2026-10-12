"""New-task constraints follow data validity and actual occupied geometry."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.design_tokens import resolve_design_tokens, validate_custom_style  # noqa: E402
from shared.slide_spec_contract import validate_spec_data  # noqa: E402


def spec():
    return {"schema_version": "2.1", "research_scope": "C",
            "meta": {"topic": "设计约束回归", "language": "Chinese", "format": "individual",
                     "duration_min": 1, "slide_count": 1, "design_freedom": "auto", "quality_level": "fast"},
            "slides": [{"id": 1, "title": "关系说明", "content": ["合成教学内容"],
                        "timing_sec": 60, "owner": "speaker",
                        "semantic_requirements": {"must_convey": [{"id": "core", "text": "解释关系"}],
                                                  "must_show_exact": []}}]}


def custom_style():
    return {"style_character": "自由多色教学图解",
            "palette": {"canvas": "FFFFFF", "surface": "F5F5F5", "primary_text": "111111",
                        "secondary_text": "555555", "primary_accent": "2563EB",
                        "secondary_accent": "93C5FD", "category_teal": "087F8C",
                        "category_gold": "F4CB42"}}


class PlanningConstraintTests(unittest.TestCase):
    def test_two_stage_timeline_five_item_matrix_and_two_step_cycle_pass(self):
        cases = [("timeline", {"stages": ["准备", "实施"]}),
                 ("matrix", {"items": [str(i) for i in range(5)]}),
                 ("cycle", {"steps": ["执行", "反馈"]})]
        for kind, details in cases:
            with self.subTest(kind=kind):
                data = spec()
                data["slides"][0]["visual"] = {"type": kind, "purpose": "合成关系图", "details": details}
                data["slides"][0]["supporting_points"] = [f"支撑材料{i}" for i in range(9)]
                self.assertEqual(validate_spec_data(data), [])
                data["slides"][0]["visual"]["details"] = {next(iter(details)): []}
                self.assertTrue(validate_spec_data(data), "empty structured data must still fail")

    def test_legacy_component_requirements_remain_supported(self):
        data = spec()
        data.pop("schema_version")
        data["meta"].pop("design_freedom")
        data["slides"][0]["visual"] = {"type": "timeline", "purpose": "legacy", "details": {"stages": ["a", "b"]}}
        self.assertTrue(any("at least 3" in item["message"] for item in validate_spec_data(data)))

    def test_requested_caps_are_positive_integers_without_artificial_ranges(self):
        for cap in (1, 5, 300, 1000):
            data = spec()
            data["meta"].update(max_words_per_slide=cap, max_chinese_chars_per_slide=cap)
            self.assertEqual(validate_spec_data(data), [])
        for bad in (0, -1, 2.5):
            data["meta"]["max_words_per_slide"] = bad
            self.assertTrue(validate_spec_data(data))
        schema = json.loads((ROOT / "references/presentation-brief.schema.json").read_text())
        validator = Draft202012Validator(schema["properties"]["controls"])
        controls = {"visual_text_ratio": "balanced", "speaker_notes": True, "key_lines": False,
                    "citations": "classroom", "versioning": False, "max_words_per_slide": 5,
                    "max_chinese_chars_per_slide": 300}
        self.assertEqual(list(validator.iter_errors(controls)), [])

    def test_single_point_chart_passes_but_bad_data_and_missing_sources_fail(self):
        data = spec()
        details = {"measure": "合成值", "unit": "项", "scope": "教学样例", "source": "合成数据",
                   "takeaway": "单个观察", "series": [{"name": "观察", "labels": ["A"], "values": [3]}]}
        data["slides"][0]["visual"] = {"type": "chart", "purpose": "教学图表", "details": details}
        self.assertEqual(validate_spec_data(data), [])
        for bad in (["invalid"], [], [3, 4]):
            details["series"][0]["values"] = bad
            self.assertTrue(validate_spec_data(data))
        details["series"][0]["values"] = [3]
        details.pop("source")
        self.assertTrue(validate_spec_data(data))


class CustomStyleTests(unittest.TestCase):
    def test_minimal_custom_style_and_semantic_colors_resolve(self):
        custom = custom_style()
        self.assertEqual(validate_custom_style(custom), [])
        data = spec()
        data["meta"].update(visual_style="Other", visual_style_custom=custom)
        self.assertEqual(validate_spec_data(data), [])
        tokens = resolve_design_tokens("Other", custom)
        self.assertEqual(tokens["palette"]["category_gold"], "F4CB42")
        self.assertIn("category_gold", tokens["dark_palette"])
        custom["backgrounds"] = {"content": "白底分组"}
        self.assertEqual(validate_custom_style(custom), [])
        self.assertEqual(validate_spec_data(data), [])

    def test_invalid_optional_choices_and_unreadable_core_colors_still_fail(self):
        for field, value in [("backgrounds", "invalid"), ("svg_reference", {"name": "missing-usage"})]:
            custom = custom_style()
            custom[field] = value
            self.assertTrue(validate_custom_style(custom))
        custom = custom_style()
        custom["palette"]["category_gold"] = "not-a-color"
        self.assertTrue(validate_custom_style(custom))
        custom = custom_style()
        custom["palette"]["primary_text"] = "FFFFFF"
        self.assertTrue(validate_custom_style(custom))

    def test_explicit_dark_category_color_is_not_discarded(self):
        custom = custom_style()
        dark = resolve_design_tokens("Other", custom)["dark_palette"]
        custom["dark_palette"] = {**dark, "category_gold": "FFE880"}
        self.assertEqual(validate_custom_style(custom), [])
        self.assertEqual(resolve_design_tokens("Other", custom)["dark_palette"]["category_gold"], "FFE880")


class OccupiedGeometryTests(unittest.TestCase):
    def test_empty_box_overlap_passes_but_ink_overlap_and_invalid_geometry_fail(self):
        code = r"""
const {SlideElementRegistry:R}=require('./scripts/pptx-element-registry.js');
function run(mode) {
 const r=new R({capture:true,designPreferencesAdvisory:true});
 const a={x:.5,y:.5,w:5,h:1,fontSize:18,lineGeometry:[{text:'左文',x:.5,y:.5,w:.5,h:.2}]};
 const b={x:3,y:.5,w:2,h:1,fontSize:18,lineGeometry:[{text:'右文',x:3,y:.5,w:.5,h:.2}]};
 if(mode==='ink')b.lineGeometry[0].x=.6;
 if(mode==='unmeasured'){delete a.lineGeometry;delete b.lineGeometry;}
 if(mode==='invalid')b.lineGeometry[0].x=NaN;
 if(mode==='zero')b.lineGeometry[0].w=0;
 r.text(1,'左文',a);r.text(1,'右文',b);
 return r.analyzeDeck();
}
process.stdout.write(JSON.stringify(Object.fromEntries(['empty','ink','unmeasured','invalid','zero'].map(k=>[k,run(k)]))));
"""
        result = subprocess.run(["node", "-e", code], cwd=ROOT, text=True, capture_output=True, check=True)
        reports = json.loads(result.stdout)
        self.assertTrue(reports["empty"]["ok"])
        for kind in ("ink", "unmeasured", "invalid", "zero"):
            self.assertIn("text_overlap", [item["code"] for item in reports[kind]["errors"]])


if __name__ == "__main__":
    unittest.main()
