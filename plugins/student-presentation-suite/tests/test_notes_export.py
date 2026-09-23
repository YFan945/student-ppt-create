"""Regression tests for readable notes exported from the PPTX artifact."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "sp-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pipeline.deliverables import export_speaker_notes  # noqa: E402


class NotesExportTests(unittest.TestCase):
    def test_calibration_notes_survive_and_all_pages_are_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "spec.json"
            spec.write_text(json.dumps({"slides": [
                {"id": number, "title": f"标题 {number}"} for number in range(1, 5)
            ]}), encoding="utf-8")
            pptx = root / "deck.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                for number in range(1, 5):
                    archive.writestr(f"ppt/slides/slide{number}.xml", "<slide/>")
                    archive.writestr(
                        f"ppt/slides/_rels/slide{number}.xml.rels",
                        '<Relationships><Relationship Type="x/notesSlide" '
                        f'Target="../notesSlides/notesSlide{number}.xml"/></Relationships>',
                    )
                    archive.writestr(
                        f"ppt/notesSlides/notesSlide{number}.xml",
                        '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                        '<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
                        f'<p:txBody><a:p><a:r><a:t>讲稿 {number}</a:t></a:r></a:p></p:txBody></p:sp>'
                        '<p:sp><p:nvSpPr><p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
                        f'<p:txBody><a:p><a:r><a:t>{number}</a:t></a:r></a:p></p:txBody></p:sp>'
                        '</p:notes>',
                    )
            target = root / "speaker-notes.md"
            target.write_text("## 4 标题\n旧讲稿", encoding="utf-8")
            export_speaker_notes(pptx, spec, target)
            body = target.read_text(encoding="utf-8")
            self.assertEqual(4, body.count("## 第 "))
            self.assertLess(body.index("## 第 1 页"), body.index("## 第 4 页"))
            self.assertIn("讲稿 1", body)
            self.assertNotIn("旧讲稿", body)
            self.assertNotIn("讲稿 1\n1", body)


if __name__ == "__main__":
    unittest.main()
