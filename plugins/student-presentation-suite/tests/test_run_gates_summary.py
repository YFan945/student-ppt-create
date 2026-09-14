"""run_gates.py 的"一次运行、只回显问题项"契约。

这套门禁存在的理由是成本：v0.8 的 Art Direction / composition / 探索证据三个门禁
原本各打印一整份 JSON 报告，一次**通过**的运行也会产生数千 token 的上下文，却
不含任何信息。这里把"通过即一行、失败只列问题项、报告落盘"钉成回归契约。
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_helpers import load_module  # noqa: E402

RUN_GATES = load_module(ROOT / "skills" / "sp-deck" / "scripts" / "run_gates.py")
GOLDEN = ROOT / "examples" / "golden-sample"
MAX_SUMMARY_LINES = 15


class RunGatesSummaryTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = RUN_GATES.main(argv)
        return code, buffer.getvalue()

    def golden_args(self, out: Path) -> list[str]:
        return [
            "--art-direction",
            str(GOLDEN / "art-direction.yaml"),
            "--slide-spec",
            str(GOLDEN / "slide-spec.yaml"),
            "--evidence-dir",
            str(GOLDEN / "composition"),
            "--output",
            str(out),
        ]

    def test_passing_run_prints_exactly_one_line_and_writes_the_report(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            code, stdout = self.invoke(self.golden_args(out))

            self.assertEqual(0, code)
            self.assertEqual(1, len(stdout.splitlines()), stdout)
            self.assertLess(len(stdout.encode("utf-8")), 400)

            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(0, report["counts"]["blockers"])
            self.assertIn("art_direction", report["gates"])
            self.assertIn("visual_generation", report["gates"])

    def test_blocking_run_lists_only_problems_and_exits_two(self) -> None:
        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "art-direction-broken.yaml"
            data = RUN_GATES.art_check.load_structured(GOLDEN / "art-direction.yaml")
            del data["color_system"]
            data["typography"]["body_pt"] = 30
            broken.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

            out = Path(tmp) / "gates-report.json"
            argv = self.golden_args(out)
            argv[argv.index(str(GOLDEN / "art-direction.yaml"))] = str(broken)
            code, stdout = self.invoke(argv)

            self.assertEqual(2, code)
            lines = stdout.splitlines()
            self.assertLessEqual(len(lines), MAX_SUMMARY_LINES)
            self.assertTrue(lines[0].startswith("run_gates: blocked"), lines[0])
            for line in lines[1:]:
                self.assertTrue(
                    line.startswith("  [critical]") or line.startswith("  [major]") or line.startswith("  …"),
                    f"非问题项混入了回显: {line!r}",
                )

    def test_art_direction_blocker_is_reported_once_not_twice(self) -> None:
        """visual-generation 门禁内部会重跑 Art Direction 校验，不能重复计数。"""
        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "art-direction-broken.yaml"
            data = RUN_GATES.art_check.load_structured(GOLDEN / "art-direction.yaml")
            del data["color_system"]
            broken.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

            out = Path(tmp) / "gates-report.json"
            argv = self.golden_args(out)
            argv[argv.index(str(GOLDEN / "art-direction.yaml"))] = str(broken)
            self.invoke(argv)

            report = json.loads(out.read_text(encoding="utf-8"))
            codes = [item["code"] for item in report["problems"]]
            self.assertEqual(len(codes), len(set(codes)), codes)
            self.assertEqual(0, report["counts"]["critical"])
            self.assertNotIn("visual-generation", {item["gate"] for item in report["problems"]})

    def test_candidates_only_mode_reports_the_composition_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            code, stdout = self.invoke(
                [
                    "--art-direction",
                    str(GOLDEN / "art-direction.yaml"),
                    "--candidates",
                    str(GOLDEN / "composition" / "composition-candidates-1.json"),
                    str(GOLDEN / "composition" / "composition-candidates-9.json"),
                    "--output",
                    str(out),
                ]
            )
            self.assertEqual(0, code)
            self.assertEqual(1, len(stdout.splitlines()), stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("composition", report["gates"])
            self.assertNotIn("visual_generation", report["gates"])
            self.assertEqual(2, len(report["gates"]["composition"]["files"]))

    def test_missing_evidence_is_blocking_and_capping_keeps_output_small(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            code, stdout = self.invoke(
                [
                    "--art-direction",
                    str(GOLDEN / "art-direction.yaml"),
                    "--slide-spec",
                    str(GOLDEN / "slide-spec.yaml"),
                    "--evidence-dir",
                    str(Path(tmp) / "empty"),
                    "--output",
                    str(out),
                    "--max-items",
                    "2",
                ]
            )
            self.assertEqual(2, code)
            lines = stdout.splitlines()
            # 1 行汇总 + 2 行问题 + 1 行省略提示
            self.assertEqual(4, len(lines), stdout)
            self.assertTrue(lines[-1].startswith("  …"), lines[-1])
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertGreater(report["counts"]["blockers"], len(lines) - 2)

    def test_json_mode_emits_the_full_report(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            argv = self.golden_args(out) + ["--json"]
            code, stdout = self.invoke(argv)
            self.assertEqual(0, code)
            report = json.loads(stdout)
            self.assertTrue(report["ok"])
            self.assertIn("problems", report)

    def test_qa_mode_accepts_a_pptx_without_art_direction(self) -> None:
        """QA-only runs have no Art Direction; the front-end gate must not be forced."""
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            code, stdout = self.invoke(
                ["--pptx", str(Path(tmp) / "absent.pptx"), "--output", str(out)]
            )
            self.assertEqual(2, code)
            self.assertNotIn("nothing to check", stdout)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("art_direction", report["gates"])

    def test_qa_mode_survives_a_missing_pptx_and_still_reports(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "gates-report.json"
            code, _ = self.invoke(
                ["--pptx", str(Path(tmp) / "absent.pptx"), "--output", str(out)]
            )
            self.assertEqual(2, code)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("rendered", report["gates"])
            self.assertTrue(any(p["gate"] == "rendered" for p in report["problems"]))

    def test_qa_mode_merges_actual_content_when_spec_is_given(self) -> None:
        with TemporaryDirectory() as tmp:
            spec = Path(tmp) / "slide-spec.yaml"
            spec.write_text("schema_version: '2.0'\nslides: []\n", encoding="utf-8")
            out = Path(tmp) / "gates-report.json"
            self.invoke(
                [
                    "--pptx", str(Path(tmp) / "absent.pptx"),
                    "--slide-spec", str(spec),
                    "--output", str(out),
                ]
            )
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("actual-content", report["gates"])

    def test_missing_argument_combination_is_refused(self) -> None:
        code, stdout = self.invoke(["--art-direction", str(GOLDEN / "art-direction.yaml")])
        self.assertEqual(2, code)
        self.assertEqual("", stdout)

        code, stdout = self.invoke(
            [
                "--art-direction",
                str(GOLDEN / "art-direction.yaml"),
                "--evidence-dir",
                str(GOLDEN / "composition"),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("", stdout)


if __name__ == "__main__":
    unittest.main()
