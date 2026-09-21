"""Tests for deliverables dependency binding and source_speaker_notes tracking."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "skills" / "sp-deck" / "scripts" / "pipeline" / "deliverables.py"

# Add the pipeline directory to sys.path
PIPELINE_DIR = DELIVERABLES.parent
if str(PIPELINE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR.parent))

# Load the deliverables module
_SPEC = importlib.util.spec_from_file_location("deliverables", DELIVERABLES)
assert _SPEC is not None and _SPEC.loader is not None
deliverables = importlib.util.module_from_spec(_SPEC)
sys.modules["deliverables"] = deliverables
_SPEC.loader.exec_module(deliverables)


class TestDeliverablesBinding(unittest.TestCase):
    """Test deliverables_are_current and deliverable_bindings functions."""

    def _make_binding(self, path: Path) -> dict:
        """Create a file binding with sha256."""
        content = path.read_bytes()
        return {
            "path": str(path),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def test_deliverables_are_current_with_source_speaker_notes(self) -> None:
        """Test that source_speaker_notes binding is checked when present."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create test files
            pptx = tmp_path / "test.pptx"
            pptx.write_bytes(b"fake pptx content")
            spec = tmp_path / "spec.yaml"
            spec.write_text("meta:\n  deliverables: [pptx, full-script]")
            notes = tmp_path / "speaker-notes.md"
            notes.write_text("## 1 - Opening\n\nTest notes.\n")
            report = tmp_path / "deliverables-report.json"
            report.write_text("{}")

            # Create output file
            output_script = tmp_path / "test-full-script.md"
            output_script.write_text("# Full Script\n\nTest script.\n")

            # Create manifest with source_speaker_notes binding
            # Note: requested should only include PREPARED_DELIVERABLES (not pptx)
            manifest = {
                "inputs": {
                    "slide_spec": {"path": str(spec)},
                },
                "deliverables": {
                    "requested": ["full-script"],
                    "source_pptx": self._make_binding(pptx),
                    "source_slide_spec": self._make_binding(spec),
                    "source_speaker_notes": self._make_binding(notes),
                    "outputs": {
                        "full-script": self._make_binding(output_script),
                    },
                    "report": self._make_binding(report),
                },
            }

            # Should be current when all bindings match
            self.assertTrue(deliverables.deliverables_are_current(manifest))

            # Modify speaker notes
            notes.write_text("## 1 - Opening\n\nUpdated notes.\n")

            # Should not be current after speaker notes change
            self.assertFalse(deliverables.deliverables_are_current(manifest))

    def test_deliverables_are_current_without_source_speaker_notes(self) -> None:
        """Test that missing source_speaker_notes binding does not break check."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create test files
            pptx = tmp_path / "test.pptx"
            pptx.write_bytes(b"fake pptx content")
            spec = tmp_path / "spec.yaml"
            spec.write_text("meta:\n  deliverables: [pptx, speaker-notes]")
            report = tmp_path / "deliverables-report.json"
            report.write_text("{}")

            # Create output file
            output_notes = tmp_path / "test-speaker-notes.md"
            output_notes.write_text("# Speaker Notes\n\nTest notes.\n")

            # Create manifest without source_speaker_notes binding
            # Note: requested should only include PREPARED_DELIVERABLES (not pptx)
            manifest = {
                "inputs": {
                    "slide_spec": {"path": str(spec)},
                },
                "deliverables": {
                    "requested": ["speaker-notes"],
                    "source_pptx": self._make_binding(pptx),
                    "source_slide_spec": self._make_binding(spec),
                    "outputs": {
                        "speaker-notes": self._make_binding(output_notes),
                    },
                    "report": self._make_binding(report),
                },
            }

            # Should be current even without source_speaker_notes
            self.assertTrue(deliverables.deliverables_are_current(manifest))

    def test_deliverable_bindings_includes_source_speaker_notes(self) -> None:
        """Test that deliverable_bindings returns source_speaker_notes when present."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            notes = tmp_path / "speaker-notes.md"
            notes.write_text("## 1 - Opening\n\nTest notes.\n")

            value = {
                "source_pptx": {"path": "/fake/pptx"},
                "source_slide_spec": {"path": "/fake/spec"},
                "source_speaker_notes": self._make_binding(notes),
                "report": {"path": "/fake/report"},
                "outputs": {
                    "full-script": {"path": "/fake/script"},
                },
            }

            bindings = deliverables.deliverable_bindings(value)
            self.assertEqual(len(bindings), 5)  # 4 named + 1 output

            # Check that source_speaker_notes is included
            notes_bindings = [b for b in bindings if b.get("path") == str(notes)]
            self.assertEqual(len(notes_bindings), 1)

    def test_deliverable_bindings_excludes_missing_source_speaker_notes(self) -> None:
        """Test that deliverable_bindings does not include source_speaker_notes when absent."""
        value = {
            "source_pptx": {"path": "/fake/pptx"},
            "source_slide_spec": {"path": "/fake/spec"},
            "report": {"path": "/fake/report"},
            "outputs": {},
        }

        bindings = deliverables.deliverable_bindings(value)
        self.assertEqual(len(bindings), 3)  # 3 named only

        # Check that no source_speaker_notes binding exists
        notes_bindings = [b for b in bindings if "speaker" in str(b.get("path", "")).lower()]
        self.assertEqual(len(notes_bindings), 0)

    def test_source_speaker_notes_only_added_when_needed(self) -> None:
        """Test that source_speaker_notes is only added for full-script/teleprompter."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create test files
            pptx = tmp_path / "test.pptx"
            pptx.write_bytes(b"fake pptx content")
            spec = tmp_path / "spec.yaml"
            spec.write_text("meta:\n  deliverables: [pptx, speaker-notes]")
            notes = tmp_path / "speaker-notes.md"
            notes.write_text("## 1 - Opening\n\nTest notes.\n")
            report = tmp_path / "deliverables-report.json"
            report.write_text("{}")

            # Create output file
            output_notes = tmp_path / "test-speaker-notes.md"
            output_notes.write_text("# Speaker Notes\n\nTest notes.\n")

            # Create manifest
            # Note: requested should only include PREPARED_DELIVERABLES (not pptx)
            manifest = {
                "inputs": {
                    "slide_spec": {"path": str(spec)},
                },
                "deliverables": {
                    "requested": ["speaker-notes"],
                    "source_pptx": self._make_binding(pptx),
                    "source_slide_spec": self._make_binding(spec),
                    "outputs": {
                        "speaker-notes": self._make_binding(output_notes),
                    },
                    "report": self._make_binding(report),
                },
            }

            # When only speaker-notes is requested (not full-script/teleprompter),
            # source_speaker_notes should not be required
            self.assertTrue(deliverables.deliverables_are_current(manifest))


if __name__ == "__main__":
    unittest.main()
