"""Regression coverage for user constraints, technical reports and preview freshness."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "scripts", ROOT / "skills" / "sp-deck" / "scripts"):
    sys.path.insert(0, str(directory))

import copy_fit_preflight as copy_fit  # noqa: E402
import direct_production as production  # noqa: E402
from slide_spec_to_pptx_brief import build_brief  # noqa: E402

from shared.presentation_quality import analyze_spec  # noqa: E402


class DensityContractTests(unittest.TestCase):
    def spec(self, *, model=True, cap=None):
        spec = {"meta": {}, "slides": [{"id": 1, "kind": "content", "title": "阶段复盘",
                "claim": "记录、分析与验证共同支撑复盘", "slide_copy": "保留证据与解释。" * 16,
                "note_goal": "说明各类记录", "transition": "讨论下一步", "owner": "speaker", "timing_sec": 60}]}
        if model:
            spec["schema_version"] = "2.1"
        if cap is not None:
            spec["meta"]["max_chinese_chars_per_slide"] = cap
        return spec

    def preflight(self, spec, cap=None):
        return copy_fit.preflight(spec, None, content_w=8.8,
                                  regions=dict(copy_fit.DEFAULT_REGIONS), max_chars=cap)

    def test_uncapped_model_task_keeps_dense_content_without_legacy_cap(self):
        spec = self.spec()
        report = self.preflight(spec)
        self.assertIsNone(report["max_chars"])
        self.assertNotIn("density", [item["field"] for item in report["problems"]])
        self.assertNotIn("slide_copy", [item["field"] for item in report["problems"]])
        findings = analyze_spec(spec)["findings"]
        self.assertFalse(any(item["code"] in {"chinese-density", "word-density"} for item in findings))

    def test_explicit_and_legacy_limits_remain_effective(self):
        for spec, expected in [(self.spec(cap=60), 60), (self.spec(model=False), 80)]:
            with self.subTest(expected=expected):
                report = self.preflight(spec)
                self.assertEqual(report["max_chars"], expected)
                self.assertIn("density", [item["field"] for item in report["problems"]])
                self.assertTrue(any(item["code"] == "chinese-density" for item in analyze_spec(spec)["findings"]))
        self.assertEqual(self.preflight(self.spec(cap=60), 90)["max_chars"], 90)

    def test_brief_accepts_omitted_caps_but_validates_explicit_values(self):
        schema = json.loads((ROOT / "references" / "presentation-brief.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema["properties"]["controls"])
        controls = {"visual_text_ratio": "balanced", "speaker_notes": True, "key_lines": False,
                    "citations": "classroom", "versioning": False}
        self.assertEqual(list(validator.iter_errors(controls)), [])
        self.assertTrue(list(validator.iter_errors({**controls, "max_chinese_chars_per_slide": 0})))

    def test_model_bridge_does_not_restore_minimum_fonts_or_typical_region_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            model = self.spec()
            model["slides"][0]["slide_copy"] *= 8
            model["slides"][0]["content"] = model["slides"][0]["slide_copy"]
            model["meta"]["language"] = "Chinese"
            brief = build_brief(model, output / "spec.json", output)
            self.assertNotIn("must be >= 22pt", brief)
            self.assertNotIn("Never shrink below minimums", brief)
            self.assertIn("no global font floor", brief)
            legacy = self.spec(model=False)
            legacy["slides"][0]["content"] = legacy["slides"][0]["slide_copy"]
            self.assertIn("must be >= 22pt", build_brief(legacy, output / "old.json", output))

    def test_english_word_cap_is_only_implied_for_legacy_work(self):
        spec = self.spec()
        spec["slides"][0]["slide_copy"] = "record evidence and explain limitations " * 10
        self.assertFalse(any(item["code"] == "word-density" for item in analyze_spec(spec)["findings"]))
        spec["meta"]["max_words_per_slide"] = 40
        self.assertTrue(any(item["code"] == "word-density" for item in analyze_spec(spec)["findings"]))


class PreviewFreshnessTests(unittest.TestCase):
    def test_repair_invalidates_cache_and_removes_obsolete_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            pptx = work / "deck.pptx"
            pptx.write_bytes(b"version-one")
            calls = []

            def fake_render(source, output, prefix, fmt, dpi):
                calls.append(source.read_bytes())
                pdf = output / "deck.pdf"
                pdf.write_bytes(source.read_bytes())
                pages = []
                for index in range(2 if source.read_bytes() == b"version-one" else 1):
                    page = output / f"slide-{index + 1}.png"
                    Image.new("RGB", (32, 18), "blue").save(page)
                    pages.append(page)
                return pdf, pages, []

            with patch("shared.pptx_runtime.render.render_pptx", side_effect=fake_render):
                first = production.render(work, {}, pptx)
                self.assertEqual(production.render(work, {"render": first}, pptx), first)
                self.assertEqual(len(calls), 1)
                pptx.write_bytes(b"version-two")
                second = production.render(work, {"render": first}, pptx)
                self.assertEqual(len(second["pages"]), 1)
                self.assertFalse((work / "render" / "slide-2.png").exists())
                self.assertNotEqual(first["pdf"]["sha256"], second["pdf"]["sha256"])
                Path(second["pages"][0]["path"]).write_bytes(b"changed preview")
                production.render(work, {"render": second}, pptx)
                self.assertEqual(len(calls), 3)


class TechnicalReportTests(unittest.TestCase):
    def test_geometry_errors_block_and_advisories_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            pptx = work / "deck.pptx"
            pptx.write_bytes(b"fixture")
            spec = {"schema_version": "2.1", "slides": [{"id": 1}]}
            sidecar = Path(str(pptx) + ".registry-report.json")
            geometry = {"ok": True, "errors": [], "warnings": [{"slide": 1, "code": "content_dead_zone"}],
                        "pptx_sha256": production.file_sha256(pptx)}

            def write_content(args):
                production.write(args.output, {"ok": True, "actual_slide_count": 1})

            with (patch.object(production, "actual_copy"),
                  patch.object(production, "validate_slide_spec", return_value=(spec, [], [])),
                  patch("shared.pptx_runtime.validate_pptx", return_value={"ok": True}),
                  patch("pptx_actual_content_check.run", side_effect=write_content),
                  patch("pptx_actual_content_check.extract_pptx_notes", return_value={})):
                manifest = {"source": None, "slide_spec": {"path": str(work / "spec.json")}}
                production.write(sidecar, geometry)
                report = production.check_artifact(work, manifest, pptx)
                self.assertTrue(report["ok"])
                self.assertFalse(report["check_scope"]["visual_quality_verified"])
                self.assertTrue(report["geometry"]["warnings"])
                geometry.update(ok=False, errors=[{"slide": 1, "code": "text_overlap"}])
                production.write(sidecar, geometry)
                self.assertFalse(production.check_artifact(work, manifest, pptx)["ok"])
                geometry["pptx_sha256"] = "stale"
                production.write(sidecar, geometry)
                with self.assertRaisesRegex(production.ProductionError, "geometry report"):
                    production.check_artifact(work, manifest, pptx)

    def test_missing_page_cannot_pass_delivery(self):
        # All remaining files are current; page coverage must still fail.
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            files = []
            for name in ["deck.pptx", "deck.pdf", "preview.png", "slide-1.png"]:
                path = work / name
                path.write_bytes(name.encode())
                files.append(production.bind(path))
            production.write(work / "production-check.json", {"content": {"actual_slide_count": 2}})
            manifest = {"build": {"pptx": files[0]},
                        "check": {"ok": True, "report": production.bind(work / "production-check.json")},
                        "render": {"pptx_sha256": files[0]["sha256"], "pdf": files[1],
                                   "contact_sheet": files[2], "pages": [files[3]]}}
            with patch.object(production, "work_directory", return_value=work), patch.object(production, "authorized", return_value=manifest):
                with self.assertRaisesRegex(production.ProductionError, "one rendered preview"):
                    production.complete(argparse.Namespace(work_dir=work))


class NativeVisualTests(unittest.TestCase):
    def test_actual_cover_crop_and_default_aspect_use_supported_image_api(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "diagram.png"
            output = Path(directory) / "images.pptx"
            Image.new("RGB", (1200, 400), "teal").save(image)
            code = r"""
const P=require('pptxgenjs'), H=require('./scripts/pptx-helpers.js');
const R=require('./scripts/pptx-page-runtime.js');
const {SlideElementRegistry}=require('./scripts/pptx-element-registry.js');
const pptx=new P();pptx.layout='LAYOUT_WIDE';
const slide=pptx.addSlide(), asset={path:IMAGE,width:1200,height:400};
H.addPlannedImage(slide,asset,{x:.5,y:.5,w:2,h:2},pptx);
H.addPlannedImage(slide,{...asset,crop_suggestion:'cover'},{x:3,y:.5,w:2,h:2},pptx);
H.addPlannedImage(slide,{...asset,crop:{x:0,y:0,w:.5,h:1}},{x:5.5,y:.5,w:2,h:2},pptx);
const registry=new SlideElementRegistry();
const ctx={pptx,slide,n:1,H,registry,presentationCopy:[],tokens:{model_led:true,palette:{canvas:'FFFFFF',primary_text:'111111'}}};
const mod=c=>H.addPlannedImage(c.slide,{...asset,crop_suggestion:'cover'},{x:8,y:.5,w:2,h:2},c.pptx);
mod.presentation_copy={headline:'',visual_labels:[]};mod.notes='合成图片接口测试';
R.renderPage(ctx,mod);
const geometry=registry.analyzeDeck();
pptx.writeFile({fileName:OUTPUT}).then(()=>process.stdout.write(JSON.stringify(geometry)));
""".replace("IMAGE", json.dumps(str(image))).replace("OUTPUT", json.dumps(str(output)))
            result = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(result.stdout)["ok"])
            with zipfile.ZipFile(output) as package:
                root = ET.fromstring(package.read("ppt/slides/slide1.xml"))
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                  "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
            pictures = root.findall(".//p:pic", ns)
            extents = [pic.find("p:spPr/a:xfrm/a:ext", ns) for pic in pictures]
            self.assertAlmostEqual(int(extents[0].get("cx")) / int(extents[0].get("cy")), 3, places=5)
            self.assertEqual(extents[1].get("cx"), extents[1].get("cy"))
            centered = pictures[1].find("p:blipFill/a:srcRect", ns)
            self.assertEqual(centered.get("l"), centered.get("r"))
            self.assertEqual(int(centered.get("l")), 33333)
            cropped = pictures[2].find("p:blipFill/a:srcRect", ns)
            self.assertLess(int(cropped.get("l")), int(cropped.get("r")))

    def test_model_indentation_has_no_design_warning_but_overlap_is_blocking(self):
        code = r"""
const {SlideElementRegistry:R}=require('./scripts/pptx-element-registry.js');
const r=new R({designPreferencesAdvisory:true});
r.text(1,'标题',{x:.5,y:.5,w:4,h:.5,fontSize:18});
r.text(1,'缩进说明',{x:.65,y:1.5,w:4,h:.5,fontSize:18});
const before=r.analyzeDeck();
r.text(1,'真正重叠',{x:.5,y:.5,w:4,h:.5,fontSize:18});
const after=r.analyzeDeck();
const legacy=new R();
legacy.text(1,'标题',{x:.5,y:.5,w:4,h:.5,fontSize:18});
legacy.text(1,'缩进说明',{x:.65,y:1.5,w:4,h:.5,fontSize:18});
process.stdout.write(JSON.stringify({before,after,legacy:legacy.analyzeDeck()}));
"""
        result = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertTrue(report["before"]["ok"])
        self.assertNotIn("near_miss_alignment", [item["code"] for item in report["before"]["warnings"]])
        self.assertIn("text_overlap", [item["code"] for item in report["after"]["errors"]])
        self.assertFalse(report["legacy"]["ok"])


if __name__ == "__main__":
    unittest.main()
