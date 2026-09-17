from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "pptx_tool.py"
NODE_WRAPPER = ROOT / "scripts" / "run_with_pptxgenjs.js"


def write_minimal_package(path: Path, slide_xml: str = "<slide/>") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("ppt/slides/slide1.xml", slide_xml)


class PptxToolTests(unittest.TestCase):
    def run_tool(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-B", str(TOOL), *args],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_help_runs_from_unrelated_space_path_without_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pptx tool cwd ") as tmp:
            result = self.run_tool("--help", cwd=Path(tmp))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("qa-manifest", result.stdout)

    def test_inspect_text_uses_ooxml_fallback_without_markitdown(self) -> None:
        module = load_module(TOOL)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "minimal.pptx"
            output = Path(tmp) / "text.md"
            write_minimal_package(pptx)
            stream = io.StringIO()
            with mock.patch.object(module.shutil, "which", return_value=None), redirect_stdout(stream):
                returncode = module.command_inspect(
                    SimpleNamespace(input=pptx, text_output=output)
                )
            payload = json.loads(stream.getvalue())
            self.assertEqual(0, returncode)
            self.assertEqual("suite-ooxml-fallback", payload["text_extraction"])
            self.assertTrue(output.is_file())

    def test_ooxml_text_fallback_does_not_truncate_long_slide_text(self) -> None:
        module = load_module(TOOL)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "long.pptx"
            output = Path(tmp) / "text.md"
            long_text = "前" * 700 + "TAIL-MARKER"
            write_minimal_package(
                pptx,
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{long_text}</a:t>"
                "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
            )
            with mock.patch.object(module.shutil, "which", return_value=None), redirect_stdout(
                io.StringIO()
            ):
                returncode = module.command_inspect(
                    SimpleNamespace(input=pptx, text_output=output)
                )
            self.assertEqual(0, returncode)
            extracted = output.read_text(encoding="utf-8")
            self.assertIn("TAIL-MARKER", extracted)
            self.assertGreater(len(extracted), 700)

    def test_shared_geometry_keeps_title_content_and_footer_disjoint(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        script = (
            f"const H=require({json.dumps(str(ROOT / 'scripts' / 'pptx-helpers.js'))});"
            "const t={geometry:{safe_margin_pct:7,title_zone_pct:15,footer_zone_pct:5,"
            "spacing_scale_pt:[6,12,18,24,36,48]}};"
            "const a=H.safeArea(10,5.625,t);const f=H.footerArea(10,5.625,t);"
            "const cells=H.gridLayout(a,3,2,{columnGap:0.2,rowGap:0.2});"
            "process.stdout.write(JSON.stringify({a,f,cells}));"
        )
        result = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        title = payload["a"]["titleBox"]
        self.assertLessEqual(title["y"] + title["h"], payload["a"]["y"])
        self.assertLessEqual(payload["a"]["y"] + payload["a"]["h"], payload["f"]["y"])
        self.assertLessEqual(payload["f"]["y"] + payload["f"]["h"], 5.625)
        self.assertEqual(6, len(payload["cells"]))
        self.assertLessEqual(
            payload["cells"][-1]["x"] + payload["cells"][-1]["w"],
            payload["a"]["x"] + payload["a"]["w"],
        )

    def test_inspect_unpack_and_pack_use_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source deck.pptx"
            unpacked = root / "work dir"
            output = root / "candidate deck.pptx"
            write_minimal_package(source)
            source_bytes = source.read_bytes()

            inspected = self.run_tool("inspect", str(source), cwd=root)
            self.assertEqual(0, inspected.returncode, inspected.stderr)
            self.assertEqual(1, json.loads(inspected.stdout)["slide_count"])

            unpack = self.run_tool("unpack", str(source), "--output", str(unpacked), cwd=root)
            self.assertEqual(0, unpack.returncode, unpack.stderr)
            self.assertTrue((unpacked / "ppt" / "slides" / "slide1.xml").is_file())

            pack = self.run_tool("pack", str(unpacked), "--output", str(output), cwd=root)
            self.assertEqual(0, pack.returncode, pack.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual(source_bytes, source.read_bytes(), "source must remain unchanged")
            second = root / "candidate deck second.pptx"
            repack = self.run_tool("pack", str(unpacked), "--output", str(second), cwd=root)
            self.assertEqual(0, repack.returncode, repack.stderr)
            self.assertEqual(output.read_bytes(), second.read_bytes())

    def test_package_add_slide_requires_separate_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pptx"
            write_minimal_package(source)
            result = self.run_tool("add-slide", str(source), "slide1.xml")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--output is required", result.stderr + result.stdout)

    def test_cjk_fonts_requires_separate_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pptx"
            write_minimal_package(source)
            missing = self.run_tool("cjk-fonts", str(source), "--map", "Cambria=SimHei")
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("--output", missing.stderr + missing.stdout)
            same = self.run_tool(
                "cjk-fonts", str(source), "--output", str(source), "--map", "Cambria=SimHei"
            )
            self.assertNotEqual(0, same.returncode)
            self.assertIn("overwrite", same.stderr + same.stdout)
            output = Path(tmp) / "cjk.pptx"
            ok = self.run_tool(
                "cjk-fonts", str(source), "--output", str(output), "--map", "Cambria=SimHei"
            )
            self.assertEqual(0, ok.returncode, ok.stderr + ok.stdout)
            self.assertTrue(output.is_file())
            self.assertTrue(source.is_file())

    def test_unpack_rejects_zip_slip_and_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "unsafe.pptx"
            output = root / "unpacked"
            escaped = root / "escaped.xml"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("safe.xml", "safe")
                archive.writestr("../escaped.xml", "unsafe")
            result = self.run_tool("unpack", str(source), "--output", str(output))
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())
            self.assertFalse(escaped.exists())

    def test_pack_rejects_output_inside_unpacked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unpacked = root / "unpacked"
            unpacked.mkdir()
            (unpacked / "part.xml").write_text("<part/>", encoding="utf-8")
            result = self.run_tool(
                "pack", str(unpacked), "--output", str(unpacked / "deck.pptx")
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("outside", result.stderr + result.stdout)

    def test_slide_relationship_copy_deep_clones_mutable_dependencies(self) -> None:
        from shared.pptx_runtime.edit import _copy_slide_relationships

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ppt" / "slides" / "_rels" / "slide1.xml.rels"
            source.parent.mkdir(parents=True)
            source.write_text(
                '<?xml version="1.0"?><Relationships '
                'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
                'Target="../slideLayouts/slideLayout1.xml"/>'
                '<Relationship Id="rId2" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" '
                'Target="../charts/chart1.xml"/>'
                '</Relationships>',
                encoding="utf-8",
            )
            chart = root / "ppt" / "charts" / "chart1.xml"
            chart.parent.mkdir(parents=True)
            chart.write_text("<chart/>", encoding="utf-8")
            chart_rels = root / "ppt" / "charts" / "_rels" / "chart1.xml.rels"
            chart_rels.parent.mkdir(parents=True)
            chart_rels.write_text(
                '<?xml version="1.0"?><Relationships '
                'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" '
                'Target="../embeddings/workbook1.xlsx"/>'
                '</Relationships>',
                encoding="utf-8",
            )
            embedding = root / "ppt" / "embeddings" / "workbook1.xlsx"
            embedding.parent.mkdir(parents=True)
            embedding.write_bytes(b"workbook")
            (root / "[Content_Types].xml").write_text(
                '<?xml version="1.0"?><Types '
                'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>'
                '<Override PartName="/ppt/charts/chart1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
                '</Types>',
                encoding="utf-8",
            )
            _copy_slide_relationships(
                root,
                "ppt/slides/slide1.xml",
                "ppt/slides/slide2.xml",
            )
            output = root / "ppt" / "slides" / "_rels" / "slide2.xml.rels"
            copied = output.read_text(encoding="utf-8")
            self.assertIn("slideLayout", copied)
            self.assertIn("../charts/chart2.xml", copied)
            self.assertTrue((root / "ppt" / "charts" / "chart2.xml").is_file())
            cloned_chart_rels = (
                root / "ppt" / "charts" / "_rels" / "chart2.xml.rels"
            ).read_text(encoding="utf-8")
            self.assertIn("../embeddings/workbook2.xlsx", cloned_chart_rels)
            self.assertEqual(
                b"workbook",
                (root / "ppt" / "embeddings" / "workbook2.xlsx").read_bytes(),
            )
            self.assertIn(
                "/ppt/charts/chart2.xml",
                (root / "[Content_Types].xml").read_text(encoding="utf-8"),
            )

    def test_validator_reports_shared_live_theme_and_unresolved_relationship_id(self) -> None:
        from shared.pptx_runtime.validate import _validate_unpacked

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parts = {
                "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>',
                "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
                "ppt/presentation.xml": '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldMasterIdLst/><p:notesMasterIdLst/><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
                "ppt/_rels/presentation.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>',
                "ppt/slides/slide1.xml": '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:graphicFrame r:id="rId404"/></p:spTree></p:cSld></p:sld>',
                "ppt/slideMasters/slideMaster1.xml": '<p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
                "ppt/slideMasters/_rels/slideMaster1.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>',
                "ppt/notesMasters/notesMaster1.xml": '<p:notesMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
                "ppt/notesMasters/_rels/notesMaster1.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>',
                "ppt/theme/theme1.xml": '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="test"/>',
            }
            for name, content in parts.items():
                path = root / Path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            findings = _validate_unpacked(root)
            codes = {finding.code for finding in findings}
        self.assertIn("shared-master-theme", codes)
        self.assertIn("relationship-id-unresolved", codes)

    def test_thumbnail_metadata_preserves_order_and_hidden_state(self) -> None:
        from shared.pptx_runtime.thumbnail import slide_metadata

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hidden.pptx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "ppt/presentation.xml",
                    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
                    '<p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
                )
                archive.writestr(
                    "ppt/_rels/presentation.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="slides/slide1.xml"/>'
                    '<Relationship Id="rId2" Target="slides/slide2.xml"/>'
                    '</Relationships>',
                )
                archive.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
                )
                archive.writestr(
                    "ppt/slides/slide2.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" show="0"/>',
                )
            metadata = slide_metadata(source)
        self.assertEqual(["slide2.xml", "slide1.xml"], [item["name"] for item in metadata])
        self.assertEqual([True, False], [item["hidden"] for item in metadata])
        self.assertEqual([1, 2], [item["index"] for item in metadata])
        self.assertEqual(["256", "257"], [item["slide_id"] for item in metadata])
        self.assertTrue(all("text_preview" in item for item in metadata))

    def test_thumbnail_grids_paginate_and_keep_hidden_placeholder(self) -> None:
        from PIL import Image

        from shared.pptx_runtime.thumbnail import create_thumbnail_grids

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "hidden.pptx"
            rendered = []
            for index in range(2):
                page = root / f"rendered-{index}.png"
                Image.new("RGB", (160, 90), (index * 80, 120, 180)).save(page)
                rendered.append(page)
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "ppt/presentation.xml",
                    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<p:sldIdLst><p:sldId id="256" r:id="rId1"/>'
                    '<p:sldId id="257" r:id="rId2"/><p:sldId id="258" r:id="rId3"/>'
                    '</p:sldIdLst></p:presentation>',
                )
                archive.writestr(
                    "ppt/_rels/presentation.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="slides/slide1.xml"/>'
                    '<Relationship Id="rId2" Target="slides/slide2.xml"/>'
                    '<Relationship Id="rId3" Target="slides/slide3.xml"/>'
                    '</Relationships>',
                )
                for number in range(1, 4):
                    hidden = ' show="0"' if number == 2 else ""
                    archive.writestr(
                        f"ppt/slides/slide{number}.xml",
                        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
                        f"{hidden}/>",
                    )
            with mock.patch(
                "shared.pptx_runtime.thumbnail.render_pptx",
                return_value=(root / "deck.pdf", rendered, []),
            ):
                result = create_thumbnail_grids(source, root / "contact", cols=1, rows=1)
            outputs = result["outputs"]
            self.assertEqual(3, len(outputs))
            self.assertTrue(all(path.is_file() for path in outputs))
            self.assertEqual("contact.jpg", outputs[0].name)
            self.assertEqual("contact-3.jpg", outputs[2].name)
            self.assertTrue(result["slides"][1]["hidden"])
            self.assertEqual(1, result["metadata_version"])

    def test_validate_reaches_validator_instead_of_import_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "invalid-but-readable.pptx"
            write_minimal_package(source)
            result = self.run_tool("validate", str(source), "--json")
        self.assertNotIn("ImportError", result.stderr)
        self.assertNotIn("No module named 'helpers'", result.stderr)

    def test_inspect_reports_invalid_zip_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "broken.pptx"
            source.write_text("not a package", encoding="utf-8")
            result = self.run_tool("inspect", str(source))
        self.assertEqual(1, result.returncode)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertNotIn("Traceback", result.stderr)

    def test_qa_manifest_binds_final_pptx_and_all_previews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "deck.pptx"
            preview = root / "slide-1.png"
            output = root / "qa.json"
            package_report = root / "deck-package-report.json"
            content_report = root / "content-qa.json"
            visual_report = root / "visual-inspection.json"
            asset_manifest = root / "asset-manifest.json"
            asset_report = root / "asset-report.json"
            write_minimal_package(source)
            preview.write_bytes(b"preview")
            package_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pptx_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "validation_profile": "openxml-sdk-plus-suite-semantic-v4",
                        "schema_validation": {"performed": True, "error_count": 0},
                    }
                ),
                encoding="utf-8",
            )
            spec = root / "spec.json"
            spec_report = root / "spec-report.json"
            spec.write_text(
                json.dumps(
                    {
                        "slides": [
                            {
                                "id": 1,
                                "title": "Test",
                                "layout": "hero",
                                "content": {"bullets": ["Test"]},
                                "timing_sec": 30,
                                "owner": "Tester",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            spec_hash = hashlib.sha256(spec.read_bytes()).hexdigest()
            spec_report.write_text(
                json.dumps({"valid": True, "slide_spec_sha256": spec_hash}),
                encoding="utf-8",
            )
            pptx_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            content_report.write_text(
                json.dumps({"ok": True, "report_type": "content-qa-v1", "pptx_sha256": pptx_hash, "blocker_count": 0}),
                encoding="utf-8",
            )
            visual_report.write_text(
                json.dumps({
                    "ok": True,
                    "report_type": "visual-inspection-v1",
                    "pptx_sha256": pptx_hash,
                    "checked_page_count": 1,
                    "repair_cycle": 0,
                    "blocker_count": 0,
                    "pages": [{"slide": 1, "preview_sha256": hashlib.sha256(preview.read_bytes()).hexdigest()}],
                }),
                encoding="utf-8",
            )
            asset_manifest.write_text(json.dumps({"deck": str(source), "assets": []}), encoding="utf-8")
            asset_report.write_text(
                json.dumps({"ok": True, "manifest_sha256": hashlib.sha256(asset_manifest.read_bytes()).hexdigest()}),
                encoding="utf-8",
            )
            result = self.run_tool(
                "qa-manifest",
                "--pptx",
                str(source),
                "--preview",
                str(preview),
                "--output",
                str(output),
                "--no-repair-needed-reason",
                "No visual defect was found.",
                "--slide-spec-report",
                str(spec_report),
                "--slide-spec",
                str(spec),
                "--package-report",
                str(package_report),
                "--content-qa",
                str(content_report),
                "--visual-inspection",
                str(visual_report),
                "--asset-manifest",
                str(asset_manifest),
                "--asset-manifest-report",
                str(asset_report),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["rendered_page_count"])
        self.assertEqual([1], payload["visual_inspection"]["inspected_pages"])
        self.assertTrue(payload["scenario_contract_passed"])
        self.assertEqual(spec_hash, payload["slide_spec_sha256"])
        self.assertEqual(str(package_report), payload["package_report"])

    def test_asset_manifest_rejects_missing_alt_text_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "asset-manifest.json"
            report = root / "asset-report.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "assets": [
                            {
                                "slide": 1,
                                "purpose": "evidence",
                                "source": "generated",
                                "permission": "suite-owned",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_tool(
                "validate-asset-manifest",
                str(manifest),
                "--output",
                str(report),
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(payload["ok"])

    def test_visual_inspection_rejects_unchecked_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            preview = root / "slide-1.png"
            findings = root / "findings.json"
            report = root / "visual-inspection.json"
            write_minimal_package(pptx)
            preview.write_bytes(b"preview")
            findings.write_text(
                json.dumps(
                    {
                        "pages": [
                            {
                                "slide": 1,
                                "checked": False,
                                "blockers": [],
                                "warnings": [],
                                "notes": "not inspected",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_tool(
                "visual-inspection",
                "--pptx",
                str(pptx),
                "--preview",
                str(preview),
                "--findings",
                str(findings),
                "--output",
                str(report),
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("was not explicitly checked", result.stderr)
        self.assertFalse(report.exists())

    def test_real_package_edit_preserves_source_and_validates_against_original(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        probe = subprocess.run(
            ["node", str(NODE_WRAPPER), "--probe"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if probe.returncode:
            self.skipTest("pptxgenjs runtime is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "deck.js"
            source = root / "source.pptx"
            edited = root / "edited.pptx"
            reordered = root / "reordered.pptx"
            deleted = root / "deleted.pptx"
            script.write_text(
                "const pptxgen=require('pptxgenjs');"
                "const pptx=new pptxgen();"
                "const s=pptx.addSlide();s.addText('Source',{x:1,y:1,w:4,h:1,fontSize:24});"
                "pptx.writeFile({fileName:process.argv[2]});",
                encoding="utf-8",
            )
            generated = subprocess.run(
                ["node", str(NODE_WRAPPER), "--output", str(source), str(script)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            source_bytes = source.read_bytes()
            added = self.run_tool(
                "add-slide",
                str(source),
                "slide1.xml",
                "--output",
                str(edited),
            )
            self.assertEqual(0, added.returncode, added.stderr)
            self.assertEqual(source_bytes, source.read_bytes())
            self.assertEqual(2, json.loads(self.run_tool("inspect", str(edited)).stdout)["slide_count"])
            validated = self.run_tool(
                "validate", str(edited), "--original", str(source), "--json"
            )
            self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)
            validation_payload = json.loads(validated.stdout)
            self.assertTrue(validation_payload["schema_validation"]["performed"])
            self.assertEqual(
                "DocumentFormat.OpenXml",
                validation_payload["schema_validation"]["engine"],
            )
            self.assertEqual(1000, validation_payload["schema_validation"]["max_errors"])
            self.assertFalse(validation_payload["schema_validation"]["truncated"])
            reordered_result = self.run_tool(
                "reorder-slides",
                str(edited),
                "slide2.xml",
                "slide1.xml",
                "--output",
                str(reordered),
            )
            self.assertEqual(0, reordered_result.returncode, reordered_result.stderr)
            deleted_result = self.run_tool(
                "delete-slide",
                str(reordered),
                "slide1.xml",
                "--output",
                str(deleted),
            )
            self.assertEqual(0, deleted_result.returncode, deleted_result.stderr)
            self.assertEqual(source_bytes, source.read_bytes())
            self.assertEqual(
                1,
                json.loads(self.run_tool("inspect", str(deleted)).stdout)["slide_count"],
            )
            validated_deleted = self.run_tool(
                "validate", str(deleted), "--original", str(source), "--json"
            )
            self.assertEqual(
                0,
                validated_deleted.returncode,
                validated_deleted.stdout + validated_deleted.stderr,
            )

    def test_wrapper_refuses_existing_output(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "deck.js"
            output = root / "existing.pptx"
            script.write_text("throw new Error('must not execute');", encoding="utf-8")
            output.write_bytes(b"preserve-me")
            result = subprocess.run(
                ["node", str(NODE_WRAPPER), "--output", str(output), str(script)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            preserved = output.read_bytes()
        self.assertEqual(2, result.returncode)
        self.assertIn("Refusing to overwrite", result.stderr)
        self.assertEqual(b"preserve-me", preserved)

    def test_wrapper_publishes_deck_without_static_gate(self) -> None:
        """The wrapper no longer runs a generation-time static gate; it normalizes
        and atomically publishes the deck, leaving overflow to QA visual checks."""
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        probe = subprocess.run(
            ["node", str(NODE_WRAPPER), "--probe"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode:
            self.skipTest("pptxgenjs runtime is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "overlap.js"
            output = root / "overlap.pptx"
            script.write_text(
                "const pptxgen=require('pptxgenjs');const pptx=new pptxgen();"
                "const s=pptx.addSlide();"
                "s.addText('Title',{x:0.7,y:0.4,w:8.6,h:0.8,fontSize:30});"
                "s.addText('Card',{x:0.7,y:0.9,w:4,h:1.2,fontSize:24});"
                "pptx.writeFile({fileName:process.argv[2]});",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(NODE_WRAPPER), "--output", str(output), str(script)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            published = output.exists()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(published)
        self.assertFalse((output.parent / "overlap-static-report.json").exists())

    def test_real_pptxgenjs_chart_passes_custom_chart_validation(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        probe = subprocess.run(
            ["node", str(NODE_WRAPPER), "--probe"],
            check=False,
            capture_output=True,
            text=True,
        )
        if probe.returncode:
            self.skipTest("pptxgenjs runtime is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "chart.js"
            output = root / "chart.pptx"
            script.write_text(
                "const pptxgen=require('pptxgenjs');const pptx=new pptxgen();"
                "const slide=pptx.addSlide();"
                "slide.addChart(pptx.ChartType.bar,[{name:'Series 1',"
                "labels:['A','B','C'],values:[10,null,30]}],"
                "{x:0.5,y:0.5,w:8,h:4,showTitle:true,title:'Sample chart'});"
                "pptx.writeFile({fileName:process.argv[2]});",
                encoding="utf-8",
            )
            generated = subprocess.run(
                ["node", str(NODE_WRAPPER), "--output", str(output), str(script)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            # The wrapper no longer emits a static report; package validation is the gate.
            self.assertFalse((root / "chart-static-report.json").exists())
            validated = self.run_tool("validate", str(output), "--json")
            payload = json.loads(validated.stdout)
        self.assertTrue(payload["ok"], payload["findings"])
        chart_errors = [
            finding
            for finding in payload["findings"]
            if finding["severity"] == "error" and finding["code"].startswith("chart-")
        ]
        self.assertEqual([], chart_errors)

    def test_openxml_schema_validator_rejects_unknown_presentation_element(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "deck.js"
            source = root / "source.pptx"
            damaged = root / "damaged.pptx"
            unpacked = root / "unpacked"
            script.write_text(
                "const pptxgen=require('pptxgenjs');const pptx=new pptxgen();"
                "pptx.addSlide();pptx.writeFile({fileName:process.argv[2]});",
                encoding="utf-8",
            )
            generated = subprocess.run(
                ["node", str(NODE_WRAPPER), "--output", str(source), str(script)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(unpacked)
            presentation = unpacked / "ppt" / "presentation.xml"
            xml = presentation.read_text(encoding="utf-8")
            xml = xml.replace("</p:presentation>", "<p:bogus/></p:presentation>")
            presentation.write_text(xml, encoding="utf-8")
            with zipfile.ZipFile(damaged, "w", zipfile.ZIP_DEFLATED) as archive:
                for part in unpacked.rglob("*"):
                    if part.is_file():
                        archive.write(part, part.relative_to(unpacked).as_posix())
            validated = self.run_tool("validate", str(damaged), "--json")
            payload = json.loads(validated.stdout)
        self.assertNotEqual(0, validated.returncode)
        self.assertTrue(payload["schema_validation"]["performed"])
        self.assertTrue(
            any(finding["code"].startswith("openxml-") for finding in payload["findings"])
        )


if __name__ == "__main__":
    unittest.main()
