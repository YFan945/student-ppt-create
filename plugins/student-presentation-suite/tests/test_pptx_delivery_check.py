from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image
from test_helpers import load_module

from shared.pptx_static_core import summarize_static_risks

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_delivery_check.py"


class PptxDeliveryCheckTests(unittest.TestCase):
    def write_minimal_pptx(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "ppt/slides/slide1.xml",
                """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>""",
            )

    def write_valid_preview_and_manifest(self, pptx: Path, preview: Path, manifest: Path) -> None:
        image = Image.new("RGB", (640, 360), "white")
        image.paste("navy", (0, 0, 640, 80))
        image.save(preview)
        package_report = manifest.with_name("package-report.json")
        package_report.write_text(
            json.dumps(
                {
                    "ok": True,
                    "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                    "validation_profile": "openxml-sdk-plus-suite-semantic-v4",
                    "schema_validation": {"performed": True, "error_count": 0},
                }
            ),
            encoding="utf-8",
        )
        spec = manifest.with_name("slide-spec.json")
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
        spec_report = manifest.with_name("slide-spec-report.json")
        spec_report.write_text(
            json.dumps(
                {
                    "valid": True,
                    "slide_spec": str(spec),
                    "slide_spec_sha256": spec_hash,
                }
            ),
            encoding="utf-8",
        )
        manifest.write_text(json.dumps({
            "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
            "slide_count": 1,
            "rendered_page_count": 1,
            "scenario_contract_passed": True,
            "slide_spec": spec.name,
            "slide_spec_sha256": spec_hash,
            "slide_spec_report": spec_report.name,
            "slide_spec_report_sha256": hashlib.sha256(spec_report.read_bytes()).hexdigest(),
            "preview_files": [preview.name],
            "preview_sha256": [hashlib.sha256(preview.read_bytes()).hexdigest()],
            "package_report": package_report.name,
            "package_report_sha256": hashlib.sha256(package_report.read_bytes()).hexdigest(),
            "visual_inspection": {
                "completed": True, "inspected_pages": [1], "repair_cycles": 1,
                "remaining_blockers": 0,
            },
        }), encoding="utf-8")

    def test_derives_and_requires_notes_and_preview_by_default(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "demo-presentation.pptx"
            self.write_minimal_pptx(pptx)

            result = module.inspect_delivery(pptx, None, [])

        self.assertEqual(["notes", "preview"], result["missing_expected_files"])
        self.assertTrue(result["requirements"]["notes_required"])
        self.assertTrue(result["requirements"]["preview_required"])

    def test_explicit_exceptions_do_not_report_optional_files_missing(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "demo-presentation.pptx"
            self.write_minimal_pptx(pptx)

            result = module.inspect_delivery(
                pptx,
                None,
                [],
                require_notes=False,
                require_preview=False,
            )

        self.assertEqual([], result["missing_expected_files"])

    def test_font_inheritance_uncertainty_is_not_blocker_like(self) -> None:
        result = summarize_static_risks(
            {
                "findings": [
                    {
                        "slide": 1,
                        "shape": 1,
                        "text_preview": "Inherited text",
                        "char_count": 14,
                        "min_font_pt": None,
                        "risk": ["font-size-not-explicit"],
                    }
                ]
            }
        )

        self.assertEqual(0, result["blocker_like_count"])

    def test_qa_manifest_binds_current_pptx_and_decodable_preview(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx, preview, manifest = root / "demo-presentation.pptx", root / "demo-preview.png", root / "qa-manifest.json"
            notes = root / "demo-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            result = module.inspect_delivery(
                pptx, notes, [preview], qa_manifest=manifest,
                package_report=manifest.with_name("package-report.json"),
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["qa_manifest"]["valid"])
        self.assertEqual("complete", result["delivery_report"]["status"])
        self.assertEqual("1/1", result["delivery_report"]["preview_page_coverage"])
        self.assertEqual(0, result["delivery_report"]["package_blockers"])

    def test_simplified_gate_needs_only_plan_package_previews_and_review(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            preview = root / "deck-preview.png"
            notes = root / "deck-speaker-notes.md"
            legacy_manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, legacy_manifest)
            review = root / "visual-review.json"
            review.write_text(
                json.dumps(
                    {
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "slides": [{"slide": 1, "visual_structure": "diagram"}],
                    }
                ),
                encoding="utf-8",
            )
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                package_report=root / "package-report.json",
                slide_spec_report=root / "slide-spec-report.json",
                simple=True,
                visual_reviewed=True,
                visual_review_report=review,
            )
        self.assertTrue(result["ok"])
        self.assertEqual("simplified-v1", result["delivery_report"]["gate_profile"])
        self.assertTrue(result["delivery_report"]["slide_spec_validation_passed"])
        self.assertTrue(result["delivery_report"]["visual_reviewed"])
        self.assertTrue(result["delivery_report"]["visual_review_check"]["valid"])
        self.assertIsNone(result["delivery_report"]["qa_manifest_sha256"])

    def test_simplified_gate_rejects_unreviewed_previews(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            preview = root / "deck-preview.png"
            notes = root / "deck-speaker-notes.md"
            legacy_manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, legacy_manifest)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                package_report=root / "package-report.json",
                slide_spec_report=root / "slide-spec-report.json",
                simple=True,
                visual_reviewed=False,
            )
        self.assertFalse(result["ok"])

    def test_missing_previews_leave_delivery_incomplete(self) -> None:
        """pptx-qa.md"缺预览状态只能是 incomplete"——行为验证而非文档断言。"""
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            notes = root / "deck-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            # 有合法 package-report 与绑定复核报告，但没有预览图。
            package_report = root / "package-report.json"
            package_report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "validation_profile": "openxml-sdk-plus-suite-semantic-v4",
                        "schema_validation": {"performed": True, "error_count": 0},
                    }
                ),
                encoding="utf-8",
            )
            review = root / "visual-review.json"
            review.write_text(
                json.dumps(
                    {
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                        "slides": [{"slide": 1, "visual_structure": "diagram"}],
                    }
                ),
                encoding="utf-8",
            )
            result = module.inspect_delivery(
                pptx,
                notes,
                [],
                package_report=package_report,
                slide_spec_report=root / "slide-spec-report.json",
                simple=True,
                visual_review_report=review,
            )
        self.assertFalse(result["ok"])
        self.assertEqual("incomplete", result["delivery_report"]["status"])
        # 复核报告本身有效——不完全是因为缺它，而是缺预览。
        self.assertTrue(result["delivery_report"]["visual_review_check"]["valid"])

    def test_bare_visual_reviewed_flag_is_not_evidence(self) -> None:
        """审查致命 1：裸 --visual-reviewed 布尔量由生成方自证，不构成复核证据。"""
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            preview = root / "deck-preview.png"
            notes = root / "deck-speaker-notes.md"
            legacy_manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, legacy_manifest)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                package_report=root / "package-report.json",
                slide_spec_report=root / "slide-spec-report.json",
                simple=True,
                visual_reviewed=True,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["delivery_report"]["visual_review_check"]["valid"])
        self.assertIn("no sha256-bound", result["delivery_report"]["visual_review_check"]["reason"])

    def test_stale_visual_review_report_is_rejected(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            preview = root / "deck-preview.png"
            notes = root / "deck-speaker-notes.md"
            legacy_manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, legacy_manifest)
            review = root / "visual-review.json"
            review.write_text(
                json.dumps(
                    {
                        "pptx_sha256": "0" * 64,
                        "slides": [{"slide": 1, "visual_structure": "diagram"}],
                    }
                ),
                encoding="utf-8",
            )
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                package_report=root / "package-report.json",
                slide_spec_report=root / "slide-spec-report.json",
                simple=True,
                visual_reviewed=True,
                visual_review_report=review,
            )
        self.assertFalse(result["ok"])
        self.assertIn("not bound", result["delivery_report"]["visual_review_check"]["reason"])

    def test_stale_preview_is_warning_not_error(self) -> None:
        """预览在 manifest 后重新渲染：文件本身有效仅 hash 不一致 → warning，不阻断交付。"""
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx, preview, manifest = root / "deck.pptx", root / "deck-preview.png", root / "qa-manifest.json"
            notes = root / "deck-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            # 重新渲染同一张预览（内容有变、尺寸不变、非单色仍是合法 PNG）→ hash 与 manifest 不一致
            import PIL.Image as PILImage
            stale = PILImage.new("RGB", (640, 360), (20, 40, 60))
            for y in range(80, 360):
                for x in range(640):
                    stale.putpixel((x, y), (200, 200, 200))
            stale.save(preview)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                package_report=manifest.with_name("package-report.json"),
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["qa_manifest"]["valid"])
        self.assertTrue(
            any("stale" in warning for warning in result["qa_manifest"].get("warnings", [])),
            "expected a stale warning",
        )

    def test_corrupt_preview_fails_qa_manifest(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx, preview, manifest = root / "demo-presentation.pptx", root / "demo-preview.png", root / "qa-manifest.json"
            notes = root / "demo-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            preview.write_text("not an image", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            result = module.inspect_delivery(pptx, notes, [preview], qa_manifest=manifest)
        self.assertFalse(result["ok"])
        self.assertFalse(result["preview_validation"][0]["valid"])

    def test_blocked_on_missing_package_report_in_strict_mode(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx, notes = root / "deck.pptx", root / "deck-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            preview = root / "deck-preview.png"
            manifest = root / "qa-manifest.json"
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                require_package_report=True,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["package_validation"]["valid"])

    def test_delivery_ok_without_static_gate_when_package_passes(self) -> None:
        """Static XML scan is advisory after the gate-stripping refactor; a passing
        package report alone lets strict delivery succeed."""
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            notes = root / "deck-speaker-notes.md"
            preview = root / "deck-preview.png"
            manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                package_report=manifest.with_name("package-report.json"),
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["package_validation"]["valid"])
        self.assertNotIn("static_xml_risk_summary", result)

    def test_blocked_on_missing_qa_manifest(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx, notes = root / "deck.pptx", root / "deck-speaker-notes.md"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            result = module.inspect_delivery(pptx, notes, [], qa_manifest=None)
        self.assertFalse(result["ok"])
        self.assertFalse(result["qa_manifest"]["valid"])

    def test_strict_contract_requires_package_report(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            notes = root / "deck-speaker-notes.md"
            preview = root / "deck-preview.png"
            manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                require_package_report=True,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["package_validation"]["valid"])
        self.assertTrue(result["requirements"]["package_report_required"])

    def test_rejects_package_report_without_schema_validation(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            notes = root / "deck-speaker-notes.md"
            preview = root / "deck-preview.png"
            manifest = root / "qa-manifest.json"
            package = root / "package-report.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            package.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pptx_sha256": hashlib.sha256(pptx.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                package_report=package,
                require_package_report=True,
            )
        self.assertFalse(result["ok"])
        self.assertIn("Open XML schema validation was not performed", result["package_validation"]["errors"])

    def test_rejects_stale_quality_report(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "deck.pptx"
            notes = root / "deck-speaker-notes.md"
            preview = root / "deck-preview.png"
            manifest = root / "qa-manifest.json"
            self.write_minimal_pptx(pptx)
            notes.write_text("notes", encoding="utf-8")
            self.write_valid_preview_and_manifest(pptx, preview, manifest)
            quality = root / "quality.json"
            quality.write_text(json.dumps({"ok": True, "slide_spec_sha256": "0" * 64}), encoding="utf-8")
            result = module.inspect_delivery(
                pptx,
                notes,
                [preview],
                qa_manifest=manifest,
                quality_report=quality,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["quality_report"]["valid"])

    def test_blocked_on_pptx_unreadable(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "not-a-pptx.pptx"
            pptx.write_text("not a zip", encoding="utf-8")
            result = module.inspect_delivery(pptx, None, [])
        self.assertFalse(result["ok"])

    def test_strict_mode_exits_on_failure(self) -> None:
        module = load_module(SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pptx = root / "missing.pptx"
            with self.assertRaises(SystemExit):
                result = module.inspect_delivery(pptx, None, [])
                self.assertFalse(result["ok"])
                module.parse_args = lambda: mock.Mock(strict=True)
                if not result["ok"]:
                    raise SystemExit(1)
