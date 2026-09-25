"""Publish-bound completeness: every delivered artifact covers the frozen spec."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "sp-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pipeline.deliverables import (  # noqa: E402
    RefusedError,
    pdf_page_count,
    verify_deliverable,
)

SPEC = {
    "slides": [
        {"id": 1, "title": "开场"},
        {"id": 2, "title": "方法"},
    ],
    "evidence_ledger": [{"id": "e1"}, {"id": "e2"}],
}


def write_pptx(path: Path, slides: int) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for number in range(1, slides + 1):
            archive.writestr(f"ppt/slides/slide{number}.xml", "<slide/>")


def write_pdf(path: Path, pages: int) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + index} 0 R".encode() for index in range(pages))
        + b"] /Count "
        + str(pages).encode()
        + b" >>",
        *(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>" for _ in range(pages)),
    ]
    out = [b"%PDF-1.4\n"]
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(sum(len(part) for part in out))
        out.append(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = sum(len(part) for part in out)
    out.append(f"xref\n0 {len(objects) + 1}\n".encode())
    out.append(b"0000000000 65535 f \n")
    out.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    path.write_bytes(b"".join(out))


class VerifyDeliverableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pptx_page_count_must_cover_the_spec(self) -> None:
        pptx = self.root / "deck.pptx"
        write_pptx(pptx, 2)
        self.assertEqual({"pages": 2}, verify_deliverable("pptx", pptx, SPEC))
        write_pptx(pptx, 1)
        with self.assertRaisesRegex(RefusedError, "missing slides"):
            verify_deliverable("pptx", pptx, SPEC)

    def test_unreadable_pptx_is_refused(self) -> None:
        pptx = self.root / "deck.pptx"
        pptx.write_bytes(b"PK\x03\x04 not really a zip")
        with self.assertRaisesRegex(RefusedError, "not a readable package"):
            verify_deliverable("pptx", pptx, SPEC)

    def test_pdf_pages_are_counted_and_cross_checked(self) -> None:
        pdf = self.root / "deck.pdf"
        write_pdf(pdf, 2)
        self.assertEqual(2, pdf_page_count(pdf))
        self.assertEqual({"pages": 2}, verify_deliverable("pdf", pdf, SPEC))
        self.assertEqual({"pages": 2}, verify_deliverable("pdf", pdf, SPEC, render_pages=2))
        with self.assertRaisesRegex(RefusedError, "rendered pages"):
            verify_deliverable("pdf", pdf, SPEC, render_pages=3)
        write_pdf(pdf, 1)
        with self.assertRaisesRegex(RefusedError, "planned slides"):
            verify_deliverable("pdf", pdf, SPEC)

    def test_fake_pdf_bytes_are_refused_not_waved_through(self) -> None:
        pdf = self.root / "deck.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        with self.assertRaisesRegex(RefusedError, "cannot determine the page count"):
            pdf_page_count(pdf)
        pdf.write_bytes(b"not a pdf")
        with self.assertRaisesRegex(RefusedError, "not a PDF file"):
            pdf_page_count(pdf)

    def test_full_script_requires_every_page_section(self) -> None:
        script = self.root / "script.md"
        script.write_text(
            "# Full Presentation Script\n\n## Slide 1: 开场\n\n第一页正文。\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RefusedError, "missing sections"):
            verify_deliverable("full-script", script, SPEC)
        script.write_text(
            "# Full Presentation Script\n\n## Slide 1: 开场\n\n第一页正文。\n\n"
            "## Slide 2: 方法\n\n第二页正文。\n",
            encoding="utf-8",
        )
        self.assertEqual({"pages": 2}, verify_deliverable("full-script", script, SPEC))
        script.write_text(
            "# Full Presentation Script\n\n## Slide 1: 开场\n\n第一页正文。\n\n"
            "## Slide 2: 方法\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RefusedError, "empty page section"):
            verify_deliverable("full-script", script, SPEC)

    def test_teleprompter_and_notes_sections_are_counted(self) -> None:
        html = self.root / "deck.html"
        html.write_text('<section data-slide="1"><p>一</p></section>', encoding="utf-8")
        with self.assertRaisesRegex(RefusedError, "missing sections"):
            verify_deliverable("teleprompter", html, SPEC)
        html.write_text(
            '<section data-slide="1"><p>一</p></section>\n'
            '<section data-slide="2"><p>二</p></section>',
            encoding="utf-8",
        )
        self.assertEqual({"pages": 2}, verify_deliverable("teleprompter", html, SPEC))

        notes = self.root / "speaker-notes.md"
        notes.write_text("# 演讲稿\n\n## 第 1 页 · 开场\n\n一。\n", encoding="utf-8")
        with self.assertRaisesRegex(RefusedError, "missing sections"):
            verify_deliverable("speaker-notes", notes, SPEC)
        notes.write_text(
            "# 演讲稿\n\n## 第 1 页 · 开场\n\n一。\n\n## 第 2 页 · 方法\n\n二。\n",
            encoding="utf-8",
        )
        self.assertEqual({"pages": 2}, verify_deliverable("speaker-notes", notes, SPEC))

    def test_references_entries_match_the_ledger(self) -> None:
        refs = self.root / "refs.md"
        refs.write_text("# References\n\n- [e1] A. (2024). T. loc\n", encoding="utf-8")
        with self.assertRaisesRegex(RefusedError, "ledger has 2"):
            verify_deliverable("references", refs, SPEC)
        refs.write_text(
            "# References\n\n- [e1] A. (2024). T. loc\n- [e2] B. (2025). U. loc\n",
            encoding="utf-8",
        )
        self.assertEqual({"entries": 2}, verify_deliverable("references", refs, SPEC))

    def test_training_cards_cover_every_slide(self) -> None:
        cards = self.root / "cards.md"
        cards.write_text(
            "# Presentation Training Cards\n\n## Slide 1: 开场\n\n- Keywords: a\n\n"
            "## Slide 2: 方法\n\n- Keywords: b\n",
            encoding="utf-8",
        )
        self.assertEqual({"pages": 2}, verify_deliverable("training-cards", cards, SPEC))

    def test_non_page_deliverables_only_need_content(self) -> None:
        report = self.root / "quality-report.json"
        report.write_text('{"ok": true}', encoding="utf-8")
        self.assertEqual({}, verify_deliverable("quality-report", report, SPEC))
        empty = self.root / "change-summary.md"
        empty.write_bytes(b"")
        with self.assertRaisesRegex(RefusedError, "missing or empty"):
            verify_deliverable("change-summary", empty, SPEC)

    def test_legacy_specs_without_slides_skip_count_checks(self) -> None:
        pptx = self.root / "deck.pptx"
        write_pptx(pptx, 3)
        self.assertEqual({"pages": 3}, verify_deliverable("pptx", pptx, {}))


if __name__ == "__main__":
    unittest.main()
