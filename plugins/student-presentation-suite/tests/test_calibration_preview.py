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
        spec = self.work / "slide-spec.json"
        art = self.work / "art-direction.yaml"
        spec.write_text('{"slides": []}\n', encoding="utf-8")
        art.write_text('style_seed: "Data Driven"\n', encoding="utf-8")
        (self.work / "build-manifest.json").write_text(
            json.dumps(
                {
                    "inputs": {
                        "slide_spec": {
                            "path": str(spec.resolve()),
                            "sha256": calibration.sha256_file(spec),
                        },
                        "art_direction": {
                            "path": str(art.resolve()),
                            "sha256": calibration.sha256_file(art),
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

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
        calibration.write_calibration_deck(
            target,
            [(1, page1.resolve()), (7, page7.resolve())],
            calibration.calibration_tokens_json(self.work),
        )
        text = target.read_text(encoding="utf-8")
        self.assertIn("n: 1", text)
        self.assertIn("n: 7", text)
        self.assertIn(str(page1.resolve()).replace("\\", "\\\\"), text.replace("\\\\", "\\\\"))
        self.assertNotIn("p04-", text)

    def test_successful_preview_counts_one_calibration_round(self) -> None:
        """一次成功预览 = 一轮，计数归 preview 本身：手动直跑也要烧预算
        （2026-09-28 live：绕过 advance 直跑 4 次不记账，校准超限到第 4 轮复核）。"""
        self.write_page(1)
        original_run, original_palette = calibration.run_checked, calibration.pptx_palette_check.check_pptx

        def fake_run(argv: list[str], label: str) -> None:
            if label == "calibration build":
                output = Path(argv[argv.index("--output") + 1])
                output.write_bytes(b"pptx")
            elif label == "calibration render":
                out_dir = Path(argv[argv.index("--output-dir") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "calibration-1.png").write_bytes(b"one")

        calibration.run_checked = fake_run
        calibration.pptx_palette_check.check_pptx = lambda *_: {"ok": True, "issues": []}
        try:
            from unittest.mock import patch

            for attempt, expected_rounds in enumerate((1, 1, 2)):
                if attempt == 2:
                    with (self.work / "pages" / "p01-test.js").open("a", encoding="utf-8") as stream:
                        stream.write("\n// changed source dependency\n")
                argv = ["calibration_preview.py", "--work-dir", str(self.work), "--slides", "1", "--json"]
                with patch.object(__import__("sys"), "argv", argv):
                    self.assertEqual(0, calibration.main())
                manifest = json.loads((self.work / "build-manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(expected_rounds, manifest["calibration"]["rounds"])
        finally:
            calibration.run_checked = original_run
            calibration.pptx_palette_check.check_pptx = original_palette

    def test_preview_harness_carries_the_production_page_ctx_contract(self) -> None:
        """Scaffold pages read ctx.tokens — the harness must inject it like deck.js does.

        2026-09-28 live: the harness passed no tokens and applied an empty palette,
        so every scaffold page crashed in paletteMode (reading dark_palette of
        undefined) and calibration could never render.
        """
        page1 = self.write_page(1)
        target = self.work / "calibration-deck.js"
        tokens_json = calibration.calibration_tokens_json(self.work)
        calibration.write_calibration_deck(target, [(1, page1.resolve())], tokens_json)
        text = target.read_text(encoding="utf-8")
        self.assertIn(f"const TOKENS = {tokens_json};", text)
        self.assertIn("H.applyTokens(pptx, TOKENS, 'chinese');", text)
        self.assertIn("tokens: TOKENS", text)
        self.assertIn("slideNumber: item.n", text)
        self.assertIn("layoutReport", text)
        self.assertNotIn("H.applyTokens(pptx, {}, 'chinese')", text)

    def test_preview_tokens_resolve_through_the_production_resolver(self) -> None:
        """Preview colors are production colors: one resolver, not a second derivation."""
        import generator_scaffold

        art = self.work / "art-direction.yaml"
        expected = generator_scaffold.inline_tokens_json({"slides": []}, art)
        self.assertEqual(expected, calibration.calibration_tokens_json(self.work))
        self.assertIn("dark_palette", json.loads(expected))

    def test_preview_tokens_find_the_yaml_specs_the_pipeline_uses(self) -> None:
        """实际工作区是 slide-spec*.yaml：spec 找不到时 token 会退化成白盘兜底。"""
        (self.work / "slide-spec.json").unlink()
        (self.work / "art-direction.yaml").unlink()
        (self.work / "slide-spec-compiled.yaml").write_text(
            'meta:\n  visual_style: "Data Driven"\nslides: []\n', encoding="utf-8"
        )
        tokens = json.loads(calibration.calibration_tokens_json(self.work))
        self.assertIn("dark_palette", tokens)
        self.assertNotEqual("FFFFFF", tokens["palette"]["canvas"])

    def test_manifest_shape_binds_page_and_render_hashes(self) -> None:
        page1 = self.write_page(1)
        page4 = self.write_page(4)

        original = calibration.run_checked
        original_palette = calibration.pptx_palette_check.check_pptx

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
        calibration.pptx_palette_check.check_pptx = lambda *_: {"ok": True, "issues": []}
        try:
            result = calibration.build_preview(self.work, [1, 4])
        finally:
            calibration.run_checked = original
            calibration.pptx_palette_check.check_pptx = original_palette

        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual([1, 4], manifest["slides"])
        self.assertEqual(2, len(manifest["render"]))
        self.assertEqual(calibration.sha256_file(page1), manifest["pages"][0]["sha256"])
        self.assertEqual(calibration.sha256_file(page4), manifest["pages"][1]["sha256"])
        self.assertTrue(manifest["pptx"]["sha256"])

    def test_rerun_after_a_calibration_fix_round_is_not_blocked_by_its_own_output(self) -> None:
        """run_with_pptxgenjs.js refuses to overwrite; the helper clears its own preview first.

        2026-09-17 live: the resume path ("respawn the builder for the calibration pages,
        then rerun calibration_preview.py") failed at exit 2 because the previous
        calibration.pptx was still there, and the round went to deleting it by hand.
        """
        self.write_page(1)
        self.write_page(4)
        stale = self.work / "calibration" / "calibration.pptx"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"previous preview")

        original = calibration.run_checked
        original_palette = calibration.pptx_palette_check.check_pptx

        def fake_run(argv: list[str], label: str) -> None:
            if label == "calibration build":
                output = Path(argv[argv.index("--output") + 1])
                if output.exists():
                    raise RuntimeError("calibration build failed (exit 2): Refusing to overwrite existing output")
                output.write_bytes(b"pptx")
            elif label == "calibration render":
                out_dir = Path(argv[argv.index("--output-dir") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                for number in (1, 4):
                    (out_dir / f"calibration-{number}.png").write_bytes(b"img")

        calibration.run_checked = fake_run
        calibration.pptx_palette_check.check_pptx = lambda *_: {"ok": True, "issues": []}
        try:
            result = calibration.build_preview(self.work, [1, 4])
        finally:
            calibration.run_checked = original
            calibration.pptx_palette_check.check_pptx = original_palette
        self.assertTrue(Path(result["manifest"]).is_file())
        self.assertEqual(b"pptx", stale.read_bytes())


if __name__ == "__main__":
    unittest.main()
