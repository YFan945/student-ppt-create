from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
calibration = load_module(ROOT / "skills/sp-deck/scripts/calibration_preview.py")


class CalibrationPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        (self.work / "pages").mkdir()

    def write_page(self, number: int, *, scaffold: bool = False) -> Path:
        path = self.work / "pages" / f"p{number:02d}-test.js"
        marker = f"/* {calibration.SCAFFOLD_MARKER} */\n" if scaffold else ""
        path.write_text(
            "'use strict';\n"
            + marker
            + f"module.exports = function(ctx) {{ ctx.slide.addText('S{number}', {{x:1,y:1,w:2,h:1}}); }};\n",
            encoding="utf-8",
        )
        return path

    def test_high_leverage_selection_is_unique_and_capped_at_three(self) -> None:
        art = self.work / "art-direction.yaml"
        art.write_text(
            "high_leverage_slides:\n"
            "  - slide: 1\n"
            "  - slide: 4\n"
            "  - slide: 4\n"
            "  - slide: 7\n"
            "  - slide: 9\n",
            encoding="utf-8",
        )
        self.assertEqual([1, 4, 7], calibration.high_leverage_slides(art))

    def test_selected_calibration_pages_must_be_implemented(self) -> None:
        self.write_page(1)
        self.write_page(4, scaffold=True)
        with self.assertRaisesRegex(ValueError, "still scaffold stubs"):
            calibration.require_implemented_pages(self.work, [1, 4])

        page4 = self.write_page(4)
        self.assertEqual(
            [self.work / "pages/p01-test.js", page4],
            calibration.require_implemented_pages(self.work, [1, 4]),
        )

    def test_temporary_deck_contains_only_selected_pages_and_original_ids(self) -> None:
        page1 = self.write_page(1)
        page7 = self.write_page(7)
        target = self.work / "calibration-deck.js"
        calibration.write_calibration_deck(target, [(1, page1.resolve()), (7, page7.resolve())])
        text = target.read_text(encoding="utf-8")
        self.assertIn("n: 1", text)
        self.assertIn("n: 7", text)
        self.assertIn(str(page1.resolve()).replace("\\", "\\\\"), text.replace("\\\\", "\\\\"))
        self.assertNotIn("p04-", text)

    def test_manifest_shape_binds_page_and_render_hashes(self) -> None:
        page1 = self.write_page(1)
        page4 = self.write_page(4)

        original = calibration.run_checked

        def fake_run(argv: list[str], label: str) -> None:
            if label == "calibration build":
                output = Path(argv[argv.index("--output") + 1])
                output.write_bytes(b"pptx")
            elif label == "calibration render":
                out_dir = Path(argv[argv.index("--output-dir") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "calibration-1.png").write_bytes(b"one")
                (out_dir / "calibration-2.png").write_bytes(b"two")

        calibration.run_checked = fake_run
        try:
            result = calibration.build_preview(self.work, [1, 4])
        finally:
            calibration.run_checked = original

        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual([1, 4], manifest["slides"])
        self.assertEqual(2, len(manifest["render"]))
        self.assertEqual(calibration.sha256_file(page1), manifest["pages"][0]["sha256"])
        self.assertEqual(calibration.sha256_file(page4), manifest["pages"][1]["sha256"])
        self.assertTrue(manifest["pptx"]["sha256"])


if __name__ == "__main__":
    unittest.main()
