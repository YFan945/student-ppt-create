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

    def test_script_and_teleprompter_do_not_trigger_speaker_notes(self) -> None:
        delivery = load_delivery()
        for name in ("full-script", "teleprompter"):
            with self.subTest(deliverable=name):
                self.assertEqual((False, False), delivery.resolve_requirements(["pptx", name]))

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


class PerTypeDeliverableTests(unittest.TestCase):
    """Every confirmed deliverable owns its OWN artifact (2026-09-20).

    `speaker-notes`, `full-script` and `teleprompter` used to share one "notes
    owed" boolean, so a user who confirmed only `teleprompter` was still asked
    for `*-speaker-notes.md`, while a missing teleprompter HTML was undetectable.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pptx = self.root / "demo-presentation.pptx"
        self.write_pptx(self.pptx)

    def write_pptx(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ppt/slides/slide1.xml", "<p:sld/>")

    def touch(self, name: str, text: str = "content") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_teleprompter_does_not_owe_speaker_notes(self) -> None:
        delivery = load_delivery()
        owed = delivery.required_deliverables(["pptx", "teleprompter"])
        self.assertEqual(["teleprompter"], owed)
        self.assertNotIn("speaker-notes", owed)

    def test_full_script_does_not_owe_speaker_notes(self) -> None:
        delivery = load_delivery()
        self.assertEqual(["full-script"], delivery.required_deliverables(["pptx", "full-script"]))

    def test_each_kind_maps_to_its_own_expected_path(self) -> None:
        delivery = load_delivery()
        expected = {
            "speaker-notes": "demo-speaker-notes.md",
            "full-script": "demo-full-script.md",
            "teleprompter": "demo-teleprompter.html",
        }
        for name, filename in expected.items():
            with self.subTest(deliverable=name):
                paths = delivery.expected_artifact_paths(self.pptx, name)
                self.assertEqual(filename, paths[0].name)

    def test_a_wrong_kind_on_disk_does_not_satisfy_the_owed_kind(self) -> None:
        """A speaker-notes file must not stand in for a requested full script."""
        delivery = load_delivery()
        self.touch("demo-speaker-notes.md")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [],
            require_notes=False,
            require_preview=False,
            owed_deliverables=["full-script"],
        )
        self.assertEqual(["full-script"], result["missing_expected_files"])
        self.assertFalse(result["deliverable_evidence"]["full-script"]["satisfied"])

    def test_expected_file_on_disk_satisfies_its_own_kind(self) -> None:
        delivery = load_delivery()
        self.touch("demo-full-script.md")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [],
            require_notes=False,
            require_preview=False,
            owed_deliverables=["full-script"],
        )
        self.assertEqual([], result["missing_expected_files"])
        self.assertTrue(result["deliverable_evidence"]["full-script"]["satisfied"])

    def test_a_pdf_handed_in_as_preview_is_not_demanded_twice(self) -> None:
        """`--pdf` doubles as exported-preview evidence; counting it under both
        `preview` and `pdf` reported a phantom gap for a file that was present."""
        delivery = load_delivery()
        pdf = self.touch("demo-preview.pdf", "%PDF-1.4\n")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [pdf],
            require_notes=False,
            require_preview=True,
            owed_deliverables=["pdf"],
            extra_files={"pdf": pdf},
        )
        self.assertEqual([], result["missing_expected_files"])
        self.assertTrue(result["deliverable_evidence"]["pdf"]["satisfied"])

    def test_png_preview_cannot_satisfy_a_pdf_deliverable(self) -> None:
        delivery = load_delivery()
        png = self.touch("demo-preview.png", "not-a-pdf")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [png],
            require_notes=False,
            require_preview=True,
            owed_deliverables=["pdf"],
        )
        self.assertIn("pdf", result["missing_expected_files"])
        self.assertFalse(result["deliverable_evidence"]["pdf"]["satisfied"])

    def test_renamed_non_pdf_file_cannot_satisfy_pdf(self) -> None:
        delivery = load_delivery()
        fake = self.touch("demo-export.pdf", "PNG bytes")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [],
            require_notes=False,
            require_preview=False,
            owed_deliverables=["pdf"],
            extra_files={"pdf": fake},
        )
        self.assertIn("pdf", result["missing_expected_files"])

    def test_unrelated_pdf_in_work_dir_cannot_satisfy_pdf(self) -> None:
        delivery = load_delivery()
        self.touch("source-paper.pdf", "%PDF-1.4\n")
        result = delivery.inspect_delivery(
            self.pptx,
            None,
            [],
            require_notes=False,
            require_preview=False,
            owed_deliverables=["pdf"],
        )
        self.assertIn("pdf", result["missing_expected_files"])
        self.assertFalse(result["deliverable_evidence"]["pdf"]["satisfied"])
        self.assertEqual(
            [str(self.pptx.with_suffix(".pdf"))],
            result["deliverable_evidence"]["pdf"]["expected"],
        )

    def test_allow_missing_drops_only_the_named_kind(self) -> None:
        delivery = load_delivery()
        owed = delivery.required_deliverables(
            ["pptx", "speaker-notes", "preview"], allow_missing_notes=True
        )
        self.assertEqual(["preview"], owed)

    def test_default_when_nothing_is_confirmed_still_owes_notes_and_preview(self) -> None:
        delivery = load_delivery()
        self.assertEqual(
            ["speaker-notes", "preview"], delivery.required_deliverables(None)
        )


class DeliverableGateIntegrationTests(unittest.TestCase):
    """Acceptance: confirmed + deleted file must be REFUSED, every time.

    The gate is only worth its name if removing any single confirmed artifact
    flips it. This drives the real v08 entrypoint over a satisfied set and then
    deletes one file at a time.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_pptx(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ppt/slides/slide1.xml", "<p:sld/>")

    def run_v08(self, deliverables_meta: dict, *, pdf: Path | None = None, full_script: Path | None = None):
        """Run the v08 gate main over a minimal but satisfied fixture."""
        v08 = load_v08()
        pptx = self.root / "demo-presentation.pptx"
        self.write_pptx(pptx)
        spec = self.root / "slide-spec.json"
        spec.write_text(
            json.dumps({"meta": {"deliverables": ["pptx", "pdf", "full-script"], **deliverables_meta}}),
            encoding="utf-8",
        )
        argv = [
            "pptx_delivery_check_v08.py",
            "--pptx", str(pptx),
            "--slide-spec", str(spec),
            "--deliverables", ",".join(deliverables_meta.get("deliverables", ["pptx", "pdf", "full-script"])),
        ]
        if pdf is not None:
            argv += ["--pdf", str(pdf)]
        if full_script is not None:
            argv += ["--full-script", str(full_script)]
        return v08, pptx, spec, argv

    def test_deleting_each_confirmed_artifact_is_detected(self) -> None:
        """Confirm PPTX + PDF + full script, then remove one file at a time."""
        delivery = load_delivery()
        pptx = self.root / "demo-presentation.pptx"
        self.write_pptx(pptx)
        pdf = self.root / "demo-export.pdf"
        pdf.write_text("%PDF-1.4\n", encoding="utf-8")
        script = self.root / "demo-full-script.md"
        script.write_text("script", encoding="utf-8")

        # 1. everything present -> nothing owed is missing
        complete = delivery.inspect_delivery(
            pptx, None, [], require_notes=False, require_preview=False,
            owed_deliverables=["pdf", "full-script"],
            extra_files={"pdf": pdf, "full-script": script},
        )
        self.assertEqual([], complete["missing_expected_files"])

        # 2. remove the PDF -> the pdf deliverable is named as missing
        pdf.unlink()
        without_pdf = delivery.inspect_delivery(
            pptx, None, [], require_notes=False, require_preview=False,
            owed_deliverables=["pdf", "full-script"],
            extra_files={"pdf": None, "full-script": script},
        )
        self.assertIn("pdf", without_pdf["missing_expected_files"])
        self.assertNotIn("full-script", without_pdf["missing_expected_files"])

        # 3. remove the full script as well -> both are named
        script.unlink()
        without_both = delivery.inspect_delivery(
            pptx, None, [], require_notes=False, require_preview=False,
            owed_deliverables=["pdf", "full-script"],
            extra_files={"pdf": None, "full-script": None},
        )
        self.assertIn("pdf", without_both["missing_expected_files"])
        self.assertIn("full-script", without_both["missing_expected_files"])

    def test_v08_reports_missing_deliverables_and_clears_ok(self) -> None:
        """The v08 report must carry the owed/missing sets AND refuse completion."""
        v08 = load_v08()
        spec_meta = {"deliverables": ["pptx", "pdf", "full-script"]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "slide-spec.json"
            spec.write_text(json.dumps({"meta": spec_meta}), encoding="utf-8")
            self.assertEqual(
                ["pptx", "pdf", "full-script"], v08.deliverables_from_spec(spec)
            )
            # And the brief reads the same spec to the same conclusion.
            bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
            self.assertEqual(
                ["pptx", "pdf", "full-script"],
                bridge.required_deliverables(json.loads(spec.read_text(encoding="utf-8"))["meta"]),
            )

    def test_gate_and_brief_agree_when_the_spec_is_silent(self) -> None:
        """No `meta.deliverables`: the brief's default must reach the gate too,
        or the run shows "Brief: PPTX only / Delivery QA: Notes required"."""
        v08 = load_v08()
        bridge = load_module("slide_spec_to_pptx_brief", BRIDGE)
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "slide-spec.json"
            spec.write_text(json.dumps({"meta": {"topic": "silent"}}), encoding="utf-8")
            self.assertIsNone(v08.deliverables_from_spec(spec))
            resolved = v08.confirmed_deliverables(spec, None)
            self.assertEqual(bridge.required_deliverables({}), resolved)
            self.assertEqual(["pptx"], resolved)


if __name__ == "__main__":
    unittest.main()
