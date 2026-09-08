from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "scripts" / "pptx-element-registry.js"
ACTUAL_CHECK = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_actual_content_check.py"
DELIVERY_V07 = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_delivery_check_v07.py"
SLIDE_VALIDATION = ROOT / "shared" / "slide_spec_validation.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenerationCoreV07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.actual = load_module("pptx_actual_content_check_v07_test", ACTUAL_CHECK)
        cls.delivery = load_module("pptx_delivery_check_v07_test", DELIVERY_V07)
        cls.slide_validation = load_module("slide_spec_validation_v07_test", SLIDE_VALIDATION)
        cls.node = shutil.which("node")

    def run_registry(self, statements: str) -> dict:
        if not self.node:
            self.skipTest("node is unavailable")
        registry_path = json.dumps(str(REGISTRY))
        script = f"""
const {{ SlideElementRegistry }} = require({registry_path});
const registry = new SlideElementRegistry();
{statements}
console.log(JSON.stringify(registry.analyzeDeck()));
"""
        proc = subprocess.run(
            [self.node, "-e", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        return json.loads(proc.stdout)

    def test_actual_element_registry_accepts_safe_geometry(self) -> None:
        report = self.run_registry(
            "registry.text(1, 'Safe title', {x: 0.8, y: 0.6, w: 4.2, h: 0.7, fontSize: 28});"
            "registry.shape(1, {x: 6.5, y: 1.5, w: 2.0, h: 1.2});"
        )
        self.assertTrue(report["ok"])
        self.assertEqual([], report["errors"])

    def test_actual_element_registry_blocks_out_of_canvas(self) -> None:
        report = self.run_registry(
            "registry.image(1, {x: 12.8, y: 1.0, w: 1.2, h: 1.0});"
        )
        self.assertFalse(report["ok"])
        self.assertIn("out_of_canvas", {item["code"] for item in report["errors"]})

    def test_actual_element_registry_blocks_text_overlap(self) -> None:
        report = self.run_registry(
            "registry.text(1, 'Primary claim', {x: 1.0, y: 1.0, w: 3.0, h: 1.0, fontSize: 24});"
            "registry.shape(1, {x: 1.2, y: 1.1, w: 2.5, h: 0.8});"
        )
        self.assertFalse(report["ok"])
        self.assertIn("text_overlap", {item["code"] for item in report["errors"]})

    def test_actual_element_registry_warns_when_line_crosses_text(self) -> None:
        report = self.run_registry(
            "registry.text(1, 'Body', {x: 1.0, y: 1.0, w: 2.0, h: 1.0, fontSize: 20});"
            "registry.line(1, {x1: 0.5, y1: 1.5, x2: 4.0, y2: 1.5});"
        )
        warning_codes = {item["code"] for item in report["warnings"]}
        self.assertIn("line_crosses_text", warning_codes)

    def test_typography_is_valid_intentional_visual_strategy(self) -> None:
        data = {
            "meta": {
                "quality_level": "high-score",
                "visual_text_ratio": "visual-led",
                "scenario": "coursework",
                "audience_type": "classmates",
                "audience_depth": "peer",
                "structure_mode": "story",
                "slide_count": 1,
            },
            "slides": [
                {
                    "id": 1,
                    "title": "核心判断",
                    "timing_sec": 30,
                    "visual": {
                        "type": "typography",
                        "purpose": "用一句结论建立全页视觉焦点",
                    },
                }
            ],
        }
        errors = self.slide_validation.semantic_errors(data)
        visual_errors = [item for item in errors if ".visual" in item["path"]]
        self.assertEqual([], visual_errors)

    def test_actual_content_check_passes_when_plan_is_present(self) -> None:
        spec = {
            "slides": [
                {
                    "id": 1,
                    "title": "模型表现",
                    "claim": "准确率达到82.7%",
                    "slide_copy": ["核心结果稳定复现"],
                }
            ]
        }
        report = self.actual.check(
            spec,
            ["模型表现\n准确率达到 82.7%\n核心结果稳定复现"],
        )
        self.assertTrue(report["ok"])
        self.assertEqual(0, report["blocker_count"])

    def test_actual_content_check_blocks_missing_title_and_number(self) -> None:
        spec = {
            "slides": [
                {
                    "id": 1,
                    "title": "实验结果",
                    "claim": "准确率达到82.7%",
                }
            ]
        }
        report = self.actual.check(spec, ["实验表现明显提升"])
        codes = {item["code"] for item in report["issues"]}
        self.assertFalse(report["ok"])
        self.assertIn("missing_title", codes)
        self.assertIn("planned_numbers_missing", codes)

    def test_actual_content_check_blocks_slide_count_drift(self) -> None:
        spec = {
            "slides": [
                {"id": 1, "title": "第一页"},
                {"id": 2, "title": "第二页"},
            ]
        }
        report = self.actual.check(spec, ["第一页"])
        self.assertFalse(report["ok"])
        self.assertIn(
            "slide_count_mismatch",
            {item["code"] for item in report["issues"]},
        )

    def test_delivery_rejects_stale_actual_content_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            pptx.write_bytes(b"current-pptx")
            actual_report = root / "actual.json"
            actual_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pptx_sha256": "0" * 64,
                        "slide_count": 1,
                        "blocker_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            result = self.delivery.validate_actual_report(actual_report, pptx, 1)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("does not match the current PPTX" in item for item in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
