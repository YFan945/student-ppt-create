"""copy_fit_preflight.py — 在写生成器之前发现"文案上屏"问题。

第二轮的真实教训：Spec 里写 60–90 字的策划性 claim，而确认的密度上限是 80 字/页；
actual-content 回读要求逐字上屏，于是 30 个 blocker、整文件重写、整条修复链重来。
这件事在 deck.js 存在之前就能用算术算出来——这里把算术钉住。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_helpers import load_module  # noqa: E402

SCRIPT = ROOT / "skills" / "sp-deck" / "scripts" / "copy_fit_preflight.py"
LONG_CLAIM = (
    "光伏的约束在用地面积，它争的是连片的戈壁荒漠与屋顶表面；"
    "风电的约束在机位与空域，它争的是风资源带上的点位，"
    "还要额外承担噪音退避、鸟类碰撞与海域生态三类不同性质的约束"
)
ART = {"typography": {"slide_title_pt": 32, "body_pt": 22}}


class CopyFitPreflightTests(unittest.TestCase):
    @staticmethod
    def _write(tmp: Path, name: str, payload: dict) -> Path:
        path = tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _run(self, spec: dict, *, art: dict | None = ART, argv: list[str] | None = None) -> tuple[int, str, dict]:
        module = load_module(SCRIPT)
        spec_path = self._write(self.tmp, "spec.json", spec)
        out_path = self.tmp / "copy-fit-report.json"
        base = ["--slide-spec", str(spec_path), "--output", str(out_path)]
        if art is not None:
            base += ["--art-direction", str(self._write(self.tmp, "art.json", art))]
        code = module.main(base + (argv or []))
        return code, "", json.loads(out_path.read_text(encoding="utf-8"))

    def test_fitting_copy_passes_and_prints_one_line(self) -> None:
        spec = {"slides": [{"id": 1, "title": "风光互补", "claim": "两者互补而非替代", "content": ["(a) 时间", "(b) 成本"]}]}
        code, _, report = self._run(spec)
        self.assertEqual(0, code)
        self.assertTrue(report["ok"])
        self.assertEqual(0, report["counts"]["major"])

    def test_planning_length_claim_is_blocked_before_generation(self) -> None:
        """这正是第二轮 r2 返工的成因：claim 太长，上屏放不下。"""
        spec = {"slides": [{"id": 1, "title": "标题", "claim": LONG_CLAIM}]}
        code, _, report = self._run(spec)
        self.assertEqual(2, code)
        self.assertFalse(report["ok"])
        self.assertEqual(1, report["counts"]["major"])
        self.assertEqual("claim", report["problems"][0]["field"])

    def test_overlong_title_is_blocked(self) -> None:
        spec = {"slides": [{"id": 1, "title": "一个长到需要折行并且会顶穿标题下划线的页面标题文本"}]}
        code, _, report = self._run(spec)
        self.assertEqual(2, code)
        self.assertEqual("title", report["problems"][0]["field"])

    def test_source_lines_are_excluded_from_the_density_cap(self) -> None:
        base = {"slides": [{"id": 1, "title": "标题", "claim": "主张", "content": ["要点一"]}]}
        with_note = {
            "slides": [
                {
                    "id": 1,
                    "title": "标题",
                    "claim": "主张",
                    "content": ["要点一", "来源：国家能源局 2026-01；国家统计局 2026-02；中电联 2026-02"],
                }
            ]
        }
        _, _, clean = self._run(base, argv=["--max-chars", "20"])
        _, _, noted = self._run(with_note, argv=["--max-chars", "20"])
        self.assertEqual(clean["slides"][0]["on_slide_chars"], noted["slides"][0]["on_slide_chars"])

    def test_density_over_cap_is_minor_not_blocking(self) -> None:
        spec = {"slides": [{"id": 1, "title": "标题", "claim": "主张", "content": ["一" * 60]}]}
        code, _, report = self._run(spec, argv=["--max-chars", "20", "--verbose"])
        self.assertEqual(0, code)
        self.assertEqual(0, report["counts"]["major"])
        self.assertEqual(1, report["counts"]["minor"])

    def test_cjk_is_roughly_twice_as_wide_as_latin(self) -> None:
        module = load_module(SCRIPT)
        # 72pt => 1 em = 1 inch, so 10 CJK chars = 10in and 10 latin chars = 5.8in.
        cjk = module.text_width_in("中" * 10, 72)
        latin = module.text_width_in("a" * 10, 72)
        self.assertAlmostEqual(10.0 * module.CJK_EM, cjk, places=6)
        self.assertAlmostEqual(10.0 * module.LATIN_EM, latin, places=6)
        self.assertGreater(cjk, latin)

    def test_golden_sample_fits(self) -> None:
        """金样例必须仍然通过，否则说明检查过严、会误伤正常规格。"""
        module = load_module(SCRIPT)
        spec = module.load_structured(ROOT / "examples" / "golden-sample" / "slide-spec.yaml")
        report = module.preflight(
            spec,
            None,
            content_w=10.0 - 0.6 * 2,
            regions={"title_w": None, "title_h": 0.72, "claim_w": None, "claim_h": 0.94, "body_w": None, "body_h": 3.04},
            max_chars=80,
        )
        self.assertTrue(report["ok"], report["problems"])


if __name__ == "__main__":
    unittest.main()
