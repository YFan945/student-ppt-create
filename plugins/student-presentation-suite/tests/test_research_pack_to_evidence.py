"""Research Pack → Evidence Ledger 的确定性编译。

在这一步存在之前，F03 → E07 → Slide 05 这条链是模型读 pack 后手写 ledger 拼出来的——
等于把 Research Pack 刚消灭掉的自由发挥又放回了最后一步。这里把分配规则钉死：
findings 按 id 排序、再 data_points 按 id 排序，依次得到 E01、E02……，两次运行必须
产出完全相同的 ledger。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_helpers import load_module  # noqa: E402
from test_validate_research_pack import base_pack  # noqa: E402

SCRIPT = ROOT / "scripts" / "research_pack_to_evidence.py"


class ResearchPackToEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_pack(self, pack: dict, name: str = "research-pack.json") -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def invoke(self, argv: list[str]) -> tuple[int, str]:
        module = load_module(SCRIPT)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = module.main(argv)
        return code, buffer.getvalue()

    def compiled(self, pack: dict, spec: dict | None = None) -> dict:
        pack_path = self.write_pack(pack)
        out = self.tmp / "evidence-map.json"
        argv = [str(pack_path), "--output", str(out)]
        if spec is not None:
            spec_path = self.tmp / "slide-spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            argv += ["--slide-spec", str(spec_path)]
        code, _ = self.invoke(argv)
        self.assertEqual(0, code)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_allocation_is_findings_then_data_points_by_id(self) -> None:
        report = self.compiled(base_pack())
        self.assertEqual({"F01": "E01", "D01": "E02"}, report["ref_map"])
        self.assertEqual(["E01", "E02"], [e["id"] for e in report["evidence_ledger"]])

    def test_allocation_is_stable_across_runs(self) -> None:
        first = self.compiled(base_pack())
        second = self.compiled(base_pack())
        self.assertEqual(first["evidence_ledger"], second["evidence_ledger"])

    def test_ledger_entries_match_the_slide_spec_shape(self) -> None:
        report = self.compiled(base_pack())
        entry = report["evidence_ledger"][0]
        for field in ("id", "title", "source_type", "locator", "confidence", "used_on_slides"):
            self.assertIn(field, entry)
        self.assertEqual("paper", entry["source_type"])
        self.assertEqual("high", entry["confidence"])
        # 具体 locator 由"最强来源胜出"那一条测试负责，这里只确认形状。
        self.assertTrue(entry["locator"])

    def test_a_finding_cites_its_strongest_source(self) -> None:
        pack = base_pack()
        # S02 is tier S and must win over S01 (tier A).
        report = self.compiled(pack)
        self.assertEqual("arXiv:2601.00001", report["evidence_ledger"][0]["locator"])

    def test_source_index_keeps_tier_and_locator(self) -> None:
        report = self.compiled(base_pack())
        self.assertEqual("A", report["source_index"]["S01"]["tier"])
        self.assertEqual("arXiv:2601.00001", report["source_index"]["S02"]["locator"])

    def test_used_on_slides_resolves_pack_ids(self) -> None:
        spec = {"slides": [{"id": 5, "evidence_refs": ["F01", "D01"]}, {"id": 6, "evidence_refs": ["D01"]}]}
        report = self.compiled(base_pack(), spec)
        by_id = {e["id"]: e["used_on_slides"] for e in report["evidence_ledger"]}
        self.assertEqual([5], by_id["E01"])
        self.assertEqual([5, 6], by_id["E02"])

    def test_used_on_slides_also_accepts_allocated_ids(self) -> None:
        spec = {"slides": [{"id": 3, "evidence_refs": ["E02"]}]}
        report = self.compiled(base_pack(), spec)
        by_id = {e["id"]: e["used_on_slides"] for e in report["evidence_ledger"]}
        self.assertEqual([3], by_id["E02"])
        self.assertEqual([], by_id["E01"])

    def test_an_unresolvable_reference_blocks_compilation(self) -> None:
        spec = {"slides": [{"id": 2, "evidence_refs": ["F99"]}]}
        pack_path = self.write_pack(base_pack())
        spec_path = self.tmp / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        out = self.tmp / "evidence-map.json"
        code, stdout = self.invoke([str(pack_path), "--slide-spec", str(spec_path), "--output", str(out)])
        self.assertEqual(2, code)
        self.assertIn("F99", stdout)
        self.assertIn("unresolved_refs", json.loads(out.read_text(encoding="utf-8")))

    def test_refuses_to_compile_an_invalid_pack(self) -> None:
        pack = base_pack()
        pack["findings"][0]["source_ids"] = ["S99"]
        pack_path = self.write_pack(pack)
        code, _ = self.invoke([str(pack_path), "--output", str(self.tmp / "m.json")])
        self.assertEqual(2, code)
        self.assertFalse((self.tmp / "m.json").exists())

    def test_provenance_records_the_hashes_a_freeze_can_bind(self) -> None:
        spec = {"slides": [{"id": 1, "evidence_refs": ["F01"]}]}
        report = self.compiled(base_pack(), spec)
        provenance = report["provenance"]
        for field in ("research_pack_sha256", "slide_spec_sha256"):
            self.assertRegex(provenance[field], r"^[0-9a-f]{64}$")
        self.assertTrue(provenance["validation_ok"])

    def test_cli_prints_one_line_when_ok(self) -> None:
        pack_path = self.write_pack(base_pack())
        code, stdout = self.invoke([str(pack_path), "--output", str(self.tmp / "m.json")])
        self.assertEqual(0, code)
        self.assertEqual(1, len(stdout.splitlines()))
        self.assertTrue(stdout.startswith("research_pack_to_evidence: ok"))

    def test_missing_pack_exits_two(self) -> None:
        code, _ = self.invoke([str(self.tmp / "absent.json")])
        self.assertEqual(2, code)


class ResearchGateBindingTests(unittest.TestCase):
    """Freeze 必须把 Research Gate 的产物一起绑住。

    否则 pack 可以在 freeze 之后被改，而没人发现这份 deck 引用的证据已经没人校验过。
    """

    GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        import hashlib

        self.spec = self.tmp / "slide-spec.yaml"
        self.spec.write_text("schema_version: '2.0'\nslides: []\n", encoding="utf-8")
        digest = hashlib.sha256(self.spec.read_bytes()).hexdigest()
        self.report = self.tmp / "report.json"
        self.report.write_text(json.dumps({"valid": True, "slide_spec_sha256": digest}), encoding="utf-8")
        self.lock = self.tmp / "lock.json"
        self.pack = self.tmp / "research-pack.json"
        self.pack.write_text(json.dumps(base_pack(), ensure_ascii=False), encoding="utf-8")
        self.evidence_map = self.tmp / "evidence-map.json"
        self.evidence_map.write_text(json.dumps({"evidence_ledger": []}), encoding="utf-8")

    def guard(self, *args: str) -> tuple[int, str]:
        import subprocess

        result = subprocess.run(
            [sys.executable, str(self.GUARD), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode, result.stdout

    def freeze(self, *extra: str) -> tuple[int, str]:
        return self.guard(
            "freeze",
            "--slide-spec", str(self.spec),
            "--validation-report", str(self.report),
            "--lock-file", str(self.lock),
            *extra,
        )

    def check_ok(self) -> tuple[bool, list[str]]:
        _, stdout = self.guard("check", "--lock-file", str(self.lock))
        payload = json.loads(stdout)
        return payload["ok"], payload["errors"]

    def test_freeze_without_research_stays_backward_compatible(self) -> None:
        code, _ = self.freeze()
        self.assertEqual(0, code)
        self.assertNotIn("research", json.loads(self.lock.read_text(encoding="utf-8")))

    def test_freeze_binds_the_research_artifacts(self) -> None:
        code, _ = self.freeze(
            "--research-pack", str(self.pack),
            "--research-validation", str(self.report),
            "--evidence-map", str(self.evidence_map),
        )
        self.assertEqual(0, code)
        bound = json.loads(self.lock.read_text(encoding="utf-8"))["research"]
        self.assertEqual(
            ["evidence_map", "research_pack", "research_validation"],
            sorted(bound),
        )
        self.assertRegex(bound["research_pack"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(self.check_ok()[0])

    def test_editing_a_bound_artifact_after_freeze_is_detected(self) -> None:
        self.freeze("--research-pack", str(self.pack))
        self.assertTrue(self.check_ok()[0])
        self.pack.write_text(json.dumps({"topic": "被改过"}), encoding="utf-8")
        ok, errors = self.check_ok()
        self.assertFalse(ok)
        self.assertTrue(any("research_pack" in line for line in errors), errors)

    def test_a_missing_research_artifact_refuses_to_freeze(self) -> None:
        code, _ = self.freeze("--research-pack", str(self.tmp / "absent.json"))
        self.assertEqual(1, code)
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
