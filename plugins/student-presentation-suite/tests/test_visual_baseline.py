"""Perceptual-hash visual baseline: record/compare semantics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from shared.pptx_runtime import compare_baseline, record_baseline


def _solid_png(path: Path, color: tuple[int, int, int], size: int = 64) -> None:
    Image.new("RGB", (size, size), color).save(path)


def _split_png(path: Path, a: tuple[int, int, int], b: tuple[int, int, int], vertical: bool = False) -> None:
    """两半分割图案（aHash 对纯色图退化，必须用有结构的图）。"""
    size = 64
    img = Image.new("RGB", (size, size))
    half = size // 2
    for y in range(size):
        for x in range(size):
            pick_a = (x < half) if not vertical else (y < half)
            img.putpixel((x, y), a if pick_a else b)
    img.save(path)


class VisualBaselineTests(unittest.TestCase):
    def test_identical_renders_pass_and_changed_pixels_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            render_a = tmp_path / "a"
            render_a.mkdir()
            _split_png(render_a / "page-1.png", (240, 240, 240), (30, 30, 60))
            _split_png(render_a / "page-2.png", (20, 20, 20), (230, 230, 230), vertical=True)
            baseline = tmp_path / "baseline.json"

            payload = record_baseline(render_a, baseline)
            self.assertEqual(2, payload["pages"])

            report = compare_baseline(render_a, baseline)
            self.assertTrue(report["ok"], report["changed"])

            # 同尺寸、不同内容的渲染必须被标记（视觉回归防线）
            render_b = tmp_path / "b"
            render_b.mkdir()
            _split_png(render_b / "page-1.png", (240, 240, 240), (30, 30, 60))
            _split_png(render_b / "page-2.png", (20, 20, 20), (230, 230, 230))  # 方向反转
            report_b = compare_baseline(render_b, baseline)
            self.assertFalse(report_b["ok"])
            changed_pages = {entry["page"] for entry in report_b["changed"]}
            self.assertIn("page-2.png", changed_pages)

    def test_missing_page_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            render = tmp_path / "render"
            render.mkdir()
            _solid_png(render / "page-1.png", (128, 128, 128))
            _solid_png(render / "page-2.png", (128, 128, 128))
            baseline = tmp_path / "baseline.json"
            record_baseline(render, baseline)
            (render / "page-2.png").unlink()
            report = compare_baseline(render, baseline)
            self.assertFalse(report["ok"])
            self.assertIn("page-2.png", report["missing"])


if __name__ == "__main__":
    unittest.main()
