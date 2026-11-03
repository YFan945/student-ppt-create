"""Portable built-in references must work without the owner's source drives."""
from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation
from pptx.util import Inches, Pt

from shared import bundled_templates as bundled
from shared.hashing import file_sha256
from shared.template_library import search_catalog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_template_references import extract  # noqa: E402


class BundledTemplateTests(unittest.TestCase):
    def test_suggestions_match_page_content_without_optional_visual_type(self):
        def entry(key, name, count):
            return {"id": key, "name": name, "path": f"builtin:{key}", "slide_count": count,
                    "slides": [{"slide": n, "text": "能源成本统计" if key == "energy" else "普通数据",
                                "roles": ["data"], "pictures": 0, "tables": int(n > 1)}
                               for n in range(1, count + 1)]}
        catalog = {"templates": [entry("generic", "A", 40), entry("energy", "Z", 4)]}
        spec = {"meta": {"topic": "能源"}, "slides": [
            {"id": 1, "kind": "cover", "title": "能源"},
            {"id": 2, "title": "成本统计"}, {"id": 3, "title": "能源数据"}]}
        with patch.object(bundled, "load_catalog", return_value=catalog):
            result = bundled.suggestions(spec)
        cover, first, second = result["by_slide"]
        self.assertTrue(all(c["page_kind"] == "cover" for c in cover["candidates"]))
        self.assertEqual(first["candidates"][0]["source_id"], "energy")
        self.assertTrue(all(c["slide"] > 1 for c in first["candidates"] + second["candidates"]))
        self.assertGreater(len({c["slide"] for c in result["candidates"] if c["source_id"] == "energy"}), 1)

    def fixture(self, root: Path) -> None:
        (root / "layouts").mkdir(parents=True)
        (root / "previews").mkdir()
        preview = root / "previews/page.jpg"
        preview.write_bytes(b"reference-preview-fixture")
        page = {"slide": 1, "text": "研究机制", "roles": ["process"], "pictures": 1, "tables": 0,
                "objects": [{"kind": "sp", "position_in": {"off": {"x": 1, "y": 2}},
                             "text": {"replace_example_text": True, "paragraphs": []}}],
                "inherits": ["master-example"]}
        recipe = root / "layouts/test.json.gz"
        with gzip.open(recipe, "wt", encoding="utf-8") as stream:
            json.dump({"slides": [page], "inherited_components": {"master-example": {"objects": []}}}, stream)
        catalog = {"kind": "bundled-design-references", "templates": [{
            "id": "test", "name": "机制参考", "path": "builtin:test", "slide_count": 1,
            "preview": "previews/page.jpg", "preview_sha256": file_sha256(preview),
            "recipe": "layouts/test.json.gz", "recipe_sha256": file_sha256(recipe),
            "slides": [{key: value for key, value in page.items() if key not in {"objects", "inherits"}}]}]}
        (root / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

    def test_relocated_bundle_search_and_recipe_need_no_original_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            source, relocated = Path(directory) / "old", Path(directory) / "new-install"
            self.fixture(source)
            shutil.copytree(source, relocated)
            # Make the original location unavailable without deleting user data.
            source.rename(Path(directory) / "unavailable-original")
            with patch.object(bundled, "BUNDLED_ROOT", relocated):
                catalog = bundled.load_catalog()
                matches = search_catalog(catalog, "机制", "process")
                self.assertTrue(matches)
                self.assertTrue(Path(matches[0]["preview"]).is_relative_to(relocated))
                page = bundled.reference("builtin:test", 1)
                self.assertEqual(page["slides"][0]["objects"][0]["position_in"]["off"]["x"], 1)
                self.assertIn("master-example", page["inherited_components"])
                self.assertTrue(bundled.validate_bundle()["ok"])

    def test_missing_assets_checksums_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            self.fixture(root)
            with patch.object(bundled, "BUNDLED_ROOT", root):
                (root / "previews/page.jpg").write_bytes(b"changed")
                self.assertFalse(bundled.validate_bundle()["ok"])
                with self.assertRaisesRegex(ValueError, "outside"):
                    bundled.asset_path("../outside.jpg")
                with self.assertRaisesRegex(ValueError, "out of range"):
                    bundled.reference("test", 2)

    def test_real_pack_is_offline_portable_and_contains_the_featured_template(self):
        self.assertTrue(bundled.validate_bundle()["ok"])
        raw = bundled.catalog_path().read_text(encoding="utf-8")
        self.assertNotIn("D:/", raw)
        self.assertNotIn("D:\\", raw)
        data = bundled.reference("award-blue", 7)
        self.assertEqual(data["slide_count"], 33)
        self.assertTrue(data["slides"][0]["objects"])
        self.assertTrue(Path(data["slides"][0]["preview"]).is_file())
        self.assertTrue(data["inherited_components"])
        self.assertFalse(any(p.suffix.lower() in {".pptx", ".ppt", ".ttf", ".otf"} for p in bundled.BUNDLED_ROOT.rglob("*")))

    def test_default_cli_search_does_not_require_a_directory_or_catalog(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/template_library.py"),
                                 "search", "--role", "data", "--limit", "2"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        data = json.loads(result.stdout)
        self.assertTrue(data["matches"])
        self.assertTrue(data["matches"][0]["path"].startswith("builtin:"))
        self.assertTrue(Path(data["matches"][0]["preview"]).is_file())

    def test_extract_records_editable_geometry_styles_and_inheritance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.pptx"
            prs = Presentation()
            page = prs.slides.add_slide(prs.slide_layouts[6])
            shape = page.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
            run = shape.text_frame.paragraphs[0].add_run()
            run.text, run.font.size = "每页200字以内是示例内容", Pt(18)
            prs.save(path)
            entry, recipe = extract(path, "fixture")
            self.assertEqual(entry["path"], "builtin:fixture")
            obj = recipe["slides"][0]["objects"][0]
            self.assertEqual(obj["position_in"]["off"], {"x": 1.0, "y": 2.0})
            self.assertTrue(obj["text"]["replace_example_text"])
            self.assertEqual(obj["text"]["paragraphs"][0]["runs"][0]["font_size_pt"], 18)
            self.assertTrue(recipe["inherited_components"])
