from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "scripts" / "slide_spec_to_pptx_brief.py"
DELIVERY_DIR = ROOT / "skills" / "sp-deck" / "scripts"
DELIVERY = DELIVERY_DIR / "pptx_delivery_check.py"
DELIVERY_V08 = DELIVERY_DIR / "pptx_delivery_check_v08.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_delivery():
    if str(DELIVERY_DIR) not in sys.path:
        sys.path.insert(0, str(DELIVERY_DIR))
    return sys.modules.get("pptx_delivery_check") or load_module("pptx_delivery_check", DELIVERY)


def load_v08():
    if str(DELIVERY_DIR) not in sys.path:
        sys.path.insert(0, str(DELIVERY_DIR))
    if "pptx_delivery_check" not in sys.modules:
        load_module("pptx_delivery_check", DELIVERY)
    return sys.modules.get("pptx_delivery_check_v08") or load_module(
        "pptx_delivery_check_v08", DELIVERY_V08
    )


def minimal_spec(meta: dict) -> dict:
    return {
        "meta": {"topic": "Deliverable scope", "visual_style": "Modern Minimal", **meta},
        "slides": [
            {
                "id": 1,
                "title": "One slide",
                "layout": "hero",
                "content": {"bullets": ["Point"]},
                "timing_sec": 60,
                "owner": "A",
            }
        ],
    }


class RequiredDeliverablesTests(unittest.TestCase):
    """The confirmed set must never be padded with defaults."""

    def test_missing_deliverables_default_to_pptx_only(self) -> None:
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        self.assertEqual(["pptx"], bridge.required_deliverables({}))

    def test_pptx_only_choice_is_preserved(self) -> None:
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        self.assertEqual(["pptx"], bridge.required_deliverables({"deliverables": ["pptx"]}))

    def test_legacy_export_formats_is_the_fallback(self) -> None:
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        self.assertEqual(
            ["pptx", "speaker-notes"],
            bridge.required_deliverables({"export_formats": ["pptx", "speaker-notes"]}),
        )

    def test_brief_omits_notes_line_when_not_selected(self) -> None:
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        brief = bridge.build_brief(minimal_spec({"deliverables": ["pptx"]}), Path("input.yaml"))
        self.assertNotIn("- Notes:", brief)
        self.assertIn("Required deliverables:\n  - pptx", brief)

    def test_brief_lists_notes_line_when_selected(self) -> None:
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        brief = bridge.build_brief(
            minimal_spec({"deliverables": ["pptx", "speaker-notes"]}), Path("input.yaml")
        )
        self.assertIn("- Notes:", brief)
        self.assertIn("  - speaker-notes", brief)


class DeliveryRequirementTests(unittest.TestCase):
    """Notes/preview are owed artifacts only when the user asked for them."""

    def test_pptx_only_owes_neither_notes_nor_preview(self) -> None:
        delivery = load_delivery()
        self.assertEqual((False, False), delivery.resolve_requirements(["pptx"]))

    def test_speaker_notes_owes_notes_only(self) -> None:
        delivery = load_delivery()
        self.assertEqual((True, False), delivery.resolve_requirements(["pptx", "speaker-notes"]))

    def test_preview_and_contact_sheet_owe_preview(self) -> None:
        delivery = load_delivery()
        for name in ("preview", "contact-sheet"):
            with self.subTest(deliverable=name):
                self.assertEqual((False, True), delivery.resolve_requirements(["pptx", name]))

    def test_unspecified_deliverables_keep_the_historical_default(self) -> None:
        delivery = load_delivery()
        self.assertEqual((True, True), delivery.resolve_requirements(None))

    def test_explicit_allow_missing_flags_still_win(self) -> None:
        delivery = load_delivery()
        self.assertEqual(
            (False, True),
            delivery.resolve_requirements(
                ["pptx", "speaker-notes", "preview"], allow_missing_notes=True
            ),
        )
        self.assertEqual(
            (True, False),
            delivery.resolve_requirements(
                ["pptx", "speaker-notes", "preview"], allow_missing_preview=True
            ),
        )

    def test_parse_deliverables_tolerates_spacing_and_blanks(self) -> None:
        delivery = load_delivery()
        self.assertEqual(["pptx", "speaker-notes"], delivery.parse_deliverables(" pptx , speaker-notes ,"))
        self.assertIsNone(delivery.parse_deliverables(None))


class DeliverableScopeIntegrationTests(unittest.TestCase):
    def write_pptx(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ppt/slides/slide1.xml", "<p:sld/>")

    def test_missing_notes_is_not_a_delivery_gap_when_not_owed(self) -> None:
        delivery = load_delivery()
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            self.write_pptx(pptx)
            owed = delivery.inspect_delivery(pptx, None, [], require_notes=False, require_preview=False)
            self.assertNotIn("notes", owed["missing_expected_files"])
            self.assertNotIn("preview", owed["missing_expected_files"])
            forced = delivery.inspect_delivery(pptx, None, [], require_notes=True, require_preview=True)
            self.assertIn("notes", forced["missing_expected_files"])
            self.assertIn("preview", forced["missing_expected_files"])

    def test_deliverables_are_read_from_the_slide_spec(self) -> None:
        v08 = load_v08()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_json = root / "slide-spec.json"
            spec_json.write_text(json.dumps({"meta": {"deliverables": ["pptx"]}}), encoding="utf-8")
            self.assertEqual(["pptx"], v08.deliverables_from_spec(spec_json))

            legacy = root / "slide-spec.yaml"
            try:
                import yaml  # noqa: F401
            except ImportError:  # pragma: no cover - optional dependency
                self.skipTest("PyYAML is not installed")
            legacy.write_text("meta:\n  export_formats:\n    - pptx\n    - speaker-notes\n", encoding="utf-8")
            self.assertEqual(["pptx", "speaker-notes"], v08.deliverables_from_spec(legacy))

    def test_unreadable_spec_falls_back_to_no_deliverables(self) -> None:
        v08 = load_v08()
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.yaml"
            self.assertIsNone(v08.deliverables_from_spec(missing))


if __name__ == "__main__":
    unittest.main()
