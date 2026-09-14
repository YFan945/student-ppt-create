"""Research Pack -> Evidence Ledger / compiled Slide Spec contract."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
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
VALIDATOR = ROOT / "scripts" / "validate_research_pack.py"
GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"


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

    def write_validation(self, pack_path: Path, name: str = "research-pack-validation.json") -> Path:
        path = self.tmp / name
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(pack_path), "--output", str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return path

    def compiled(self, pack: dict, spec: dict | None = None, *, with_validation: bool = False) -> tuple[dict, dict | None]:
        pack_path = self.write_pack(pack)
        out = self.tmp / "evidence-map.json"
        argv = [str(pack_path), "--output", str(out)]
        if with_validation:
            validation = self.write_validation(pack_path)
            argv += ["--validation-report", str(validation)]
        compiled_spec = None
        if spec is not None:
            spec_path = self.tmp / "slide-spec-draft.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            compiled_path = self.tmp / "slide-spec-compiled.json"
            argv += [
                "--slide-spec", str(spec_path),
                "--compiled-slide-spec", str(compiled_path),
            ]
            compiled_spec = compiled_path
        code, _ = self.invoke(argv)
        self.assertEqual(0, code)
        report = json.loads(out.read_text(encoding="utf-8"))
        spec_value = json.loads(compiled_spec.read_text(encoding="utf-8")) if compiled_spec else None
        return report, spec_value

    def test_allocation_is_findings_then_data_points_then_quotes(self) -> None:
        pack = base_pack()
        pack["quotes"] = [{"id": "Q01", "text": "直接引语", "source_id": "S01"}]
        report, _ = self.compiled(pack)
        self.assertEqual({"F01": "E01", "D01": "E02", "Q01": "E03"}, report["ref_map"])
        self.assertEqual(["E01", "E02", "E03"], [e["id"] for e in report["evidence_ledger"]])

    def test_entire_semantic_map_is_stable_across_runs(self) -> None:
        first, _ = self.compiled(base_pack())
        second, _ = self.compiled(base_pack())
        self.assertEqual(first["semantic_sha256"], second["semantic_sha256"])
        self.assertEqual(first["ref_map"], second["ref_map"])
        self.assertEqual(first["evidence_ledger"], second["evidence_ledger"])

    def test_ledger_preserves_all_sources_and_selects_primary(self) -> None:
        report, _ = self.compiled(base_pack())
        entry = report["evidence_ledger"][0]
        self.assertEqual(["S01", "S02"], entry["source_ids"])
        self.assertEqual("S02", entry["primary_source_id"])
        self.assertEqual("arXiv:2601.00001", entry["locator"])

    def test_quote_becomes_evidence(self) -> None:
        pack = base_pack()
        pack["quotes"] = [{"id": "Q01", "text": "Hallucination remains a deployment risk.", "source_id": "S01"}]
        report, _ = self.compiled(pack)
        quote_entry = report["evidence_ledger"][2]
        self.assertEqual("E03", quote_entry["id"])
        self.assertEqual(["S01"], quote_entry["source_ids"])
        self.assertEqual("high", quote_entry["confidence"])

    def test_compiled_spec_rewrites_refs_and_ledger(self) -> None:
        draft = {
            "slides": [
                {"id": 5, "evidence_refs": ["F01", "D01"]},
                {"id": 6, "evidence_refs": ["D01"]},
            ]
        }
        report, compiled = self.compiled(base_pack(), draft)
        self.assertIsNotNone(compiled)
        assert compiled is not None
        self.assertEqual(["E01", "E02"], compiled["slides"][0]["evidence_refs"])
        self.assertEqual(["E02"], compiled["slides"][1]["evidence_refs"])
        by_id = {entry["id"]: entry["used_on_slides"] for entry in compiled["evidence_ledger"]}
        self.assertEqual([5], by_id["E01"])
        self.assertEqual([5, 6], by_id["E02"])
        self.assertEqual(compiled["evidence_ledger"], report["evidence_ledger"])

    def test_compiled_spec_also_accepts_allocated_ids(self) -> None:
        draft = {"slides": [{"id": 3, "evidence_refs": ["E02"]}]}
        _, compiled = self.compiled(base_pack(), draft)
        assert compiled is not None
        self.assertEqual(["E02"], compiled["slides"][0]["evidence_refs"])

    def test_an_unresolvable_reference_blocks_compilation(self) -> None:
        draft = {"slides": [{"id": 2, "evidence_refs": ["F99"]}]}
        pack_path = self.write_pack(base_pack())
        draft_path = self.tmp / "draft.json"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        out = self.tmp / "evidence-map.json"
        code, stdout = self.invoke([str(pack_path), "--slide-spec", str(draft_path), "--output", str(out)])
        self.assertEqual(2, code)
        self.assertIn("F99", stdout)
        self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["unresolved_refs"])

    def test_refuses_to_compile_an_invalid_pack(self) -> None:
        pack = base_pack()
        pack["findings"][0]["source_ids"] = ["S99"]
        pack_path = self.write_pack(pack)
        code, _ = self.invoke([str(pack_path), "--output", str(self.tmp / "m.json")])
        self.assertEqual(2, code)
        self.assertFalse((self.tmp / "m.json").exists())

    def test_validation_report_must_match_exact_pack(self) -> None:
        pack_path = self.write_pack(base_pack())
        validation = self.write_validation(pack_path)
        changed = base_pack()
        changed["topic"] = "另一个主题"
        pack_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        code, _ = self.invoke(
            [
                str(pack_path),
                "--validation-report", str(validation),
                "--output", str(self.tmp / "m.json"),
            ]
        )
        self.assertEqual(2, code)

    def test_provenance_records_pack_validation_and_compiled_spec_hashes(self) -> None:
        draft = {"slides": [{"id": 1, "evidence_refs": ["F01"]}]}
        report, _ = self.compiled(base_pack(), draft, with_validation=True)
        provenance = report["provenance"]
        for field in (
            "research_pack_sha256",
            "research_validation_sha256",
            "draft_slide_spec_sha256",
            "compiled_slide_spec_sha256",
        ):
            self.assertRegex(provenance[field], r"^[0-9a-f]{64}$")

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
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.pack = self.tmp / "research-pack.json"
        self.pack.write_text(json.dumps(base_pack(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.research_validation = self.tmp / "research-pack-validation.json"
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.pack), "--output", str(self.research_validation)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        self.draft = self.tmp / "slide-spec-draft.json"
        self.draft.write_text(
            json.dumps({"schema_version": "2.0", "slides": [{"id": 1, "evidence_refs": ["F01"]}]}),
            encoding="utf-8",
        )
        self.spec = self.tmp / "slide-spec-compiled.json"
        self.evidence_map = self.tmp / "evidence-map.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.pack),
                "--validation-report", str(self.research_validation),
                "--slide-spec", str(self.draft),
                "--compiled-slide-spec", str(self.spec),
                "--output", str(self.evidence_map),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        digest = hashlib.sha256(self.spec.read_bytes()).hexdigest()
        self.spec_validation = self.tmp / "slide-spec-validation.json"
        self.spec_validation.write_text(
            json.dumps({"valid": True, "slide_spec_sha256": digest}),
            encoding="utf-8",
        )
        self.lock = self.tmp / "lock.json"

    def guard(self, *args: str) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(GUARD), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode, result.stdout + result.stderr

    def research_args(self) -> list[str]:
        return [
            "--research-pack", str(self.pack),
            "--research-validation", str(self.research_validation),
            "--evidence-map", str(self.evidence_map),
        ]

    def freeze(self, *extra: str) -> tuple[int, str]:
        return self.guard(
            "freeze",
            "--slide-spec", str(self.spec),
            "--validation-report", str(self.spec_validation),
            "--lock-file", str(self.lock),
            *extra,
        )

    def check_ok(self) -> tuple[bool, list[str]]:
        code, output = self.guard("check", "--lock-file", str(self.lock))
        payload = json.loads(output)
        self.assertEqual(0 if payload["ok"] else 2, code)
        return payload["ok"], payload["errors"]

    def test_freeze_without_research_stays_backward_compatible(self) -> None:
        code, output = self.freeze()
        self.assertEqual(0, code, output)
        self.assertNotIn("research", json.loads(self.lock.read_text(encoding="utf-8")))

    def test_freeze_binds_a_verified_research_chain(self) -> None:
        code, output = self.freeze(*self.research_args())
        self.assertEqual(0, code, output)
        bound = json.loads(self.lock.read_text(encoding="utf-8"))["research"]
        self.assertEqual(["evidence_map", "research_pack", "research_validation"], sorted(bound))
        self.assertRegex(bound["evidence_map"]["semantic_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(self.check_ok()[0])

    def test_partial_research_chain_refuses_to_freeze(self) -> None:
        code, output = self.freeze("--research-pack", str(self.pack))
        self.assertNotEqual(0, code)
        self.assertIn("Research Gate is atomic", output)
        self.assertFalse(self.lock.exists())

    def test_mismatched_validation_refuses_to_freeze(self) -> None:
        payload = json.loads(self.research_validation.read_text(encoding="utf-8"))
        payload["research_pack_sha256"] = "0" * 64
        self.research_validation.write_text(json.dumps(payload), encoding="utf-8")
        code, output = self.freeze(*self.research_args())
        self.assertNotEqual(0, code)
        self.assertIn("another pack", output)

    def test_mismatched_compiled_spec_refuses_to_freeze(self) -> None:
        payload = json.loads(self.evidence_map.read_text(encoding="utf-8"))
        payload["provenance"]["compiled_slide_spec_sha256"] = "0" * 64
        self.evidence_map.write_text(json.dumps(payload), encoding="utf-8")
        code, output = self.freeze(*self.research_args())
        self.assertNotEqual(0, code)
        self.assertIn("not compiled for the Slide Spec", output)

    def test_editing_a_bound_artifact_after_freeze_is_detected(self) -> None:
        code, output = self.freeze(*self.research_args())
        self.assertEqual(0, code, output)
        self.pack.write_text(json.dumps({"topic": "被改过"}), encoding="utf-8")
        ok, errors = self.check_ok()
        self.assertFalse(ok)
        self.assertTrue(any("research_pack" in line for line in errors), errors)

    def test_research_backed_revision_cannot_silently_drop_research(self) -> None:
        code, output = self.freeze(*self.research_args())
        self.assertEqual(0, code, output)
        code, output = self.guard(
            "revise",
            "--slide-spec", str(self.spec),
            "--validation-report", str(self.spec_validation),
            "--lock-file", str(self.lock),
            "--reason", "test",
        )
        self.assertNotEqual(0, code)
        self.assertIn("research-backed", output)


class EvidenceMapSchemaTests(unittest.TestCase):
    """Evidence Map 是 Presentation Compiler 的中间表示，形状必须被强制。"""

    SCRIPT = ROOT / "scripts" / "research_pack_to_evidence.py"
    SCHEMA = ROOT / "references" / "evidence-map.schema.json"

    def setUp(self) -> None:
        self.module = load_module(self.SCRIPT)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def compile_map(self, pack: dict) -> dict:
        path = self.tmp / "research-pack.json"
        path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "evidence-map.json"
        code = self.module.main([str(path), "--output", str(out)])
        self.assertEqual(0, code)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_the_schema_file_exists_and_is_valid_json_schema(self) -> None:
        self.assertTrue(self.SCHEMA.is_file(), "evidence-map.schema.json is missing")
        schema = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual("1.0", schema["properties"]["schema_version"]["const"])
        jsonschema = __import__("jsonschema")
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_compiler_output_satisfies_the_schema(self) -> None:
        report = self.compile_map(base_pack())
        self.assertEqual([], self.module.schema_issues(report), "compiler produced a schema-invalid map")

    def test_schema_rejects_a_map_missing_provenance(self) -> None:
        report = self.compile_map(base_pack())
        del report["provenance"]
        self.assertTrue(self.module.schema_issues(report))

    def test_schema_rejects_a_ledger_entry_without_source_ids(self) -> None:
        """多源关系丢了就是丢了，不能靠 additionalProperties 兜过去。"""
        report = self.compile_map(base_pack())
        del report["evidence_ledger"][0]["source_ids"]
        self.assertTrue(self.module.schema_issues(report))

    def test_schema_rejects_a_foreign_schema_version(self) -> None:
        report = self.compile_map(base_pack())
        report["schema_version"] = "0.9"
        self.assertTrue(self.module.schema_issues(report))

    def test_semantic_hash_ignores_the_working_directory(self) -> None:
        """相同内容在不同目录下语义哈希必须一致——审计路径不进哈希。"""
        report_a = self.compiled_via_subdir("a")
        report_b = self.compiled_via_subdir("b")
        self.assertEqual(report_a["semantic_sha256"], report_b["semantic_sha256"])
        self.assertNotEqual(report_a["provenance"]["research_pack"], report_b["provenance"]["research_pack"])

    def compiled_via_subdir(self, name: str) -> dict:
        sub = self.tmp / name
        sub.mkdir()
        path = sub / "research-pack.json"
        path.write_text(json.dumps(base_pack(), ensure_ascii=False), encoding="utf-8")
        out = sub / "evidence-map.json"
        self.assertEqual(0, self.module.main([str(path), "--output", str(out)]))
        return json.loads(out.read_text(encoding="utf-8"))


class ResearchPipelineEndToEndTests(unittest.TestCase):
    """Pack → Validation → Compile → Freeze 的整链回归。

    组件测试能证明每个脚本自己是对的，证明不了它们串起来是对的——这一条补那个缺口。
    它仍然不是 Live E2E（不经过真实模型与联网），但把「编译产物能否真的被冻结」这一环
    从"没测过"变成"每次 CI 都测"。
    """

    GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"
    COMPILER = ROOT / "scripts" / "research_pack_to_evidence.py"
    VALIDATOR = ROOT / "scripts" / "validate_research_pack.py"

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.pack = self.tmp / "research-pack.json"
        self.pack.write_text(json.dumps(base_pack(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.draft = self.tmp / "draft-spec.json"
        self.draft.write_text(
            json.dumps(
                {"schema_version": "2.0", "slides": [{"id": 5, "evidence_refs": ["F01", "D01"]}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.validation = self.tmp / "research-pack-validation.json"
        self.compiled = self.tmp / "compiled-spec.json"
        self.evidence_map = self.tmp / "evidence-map.json"
        self.spec_validation = self.tmp / "spec-validation.json"
        self.lock = self.tmp / "lock.json"

    def run_script(self, *args: str) -> tuple[int, str, str]:
        import subprocess

        result = subprocess.run(
            [sys.executable, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode, result.stdout, result.stderr

    def sha(self, path: Path) -> str:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_the_whole_chain_runs_and_freezes(self) -> None:
        # 1) validate the pack, producing a report bound to the pack hash
        code, _, err = self.run_script(str(self.VALIDATOR), str(self.pack), "--output", str(self.validation))
        self.assertEqual(0, code, err)
        self.assertEqual(self.sha(self.pack), json.loads(self.validation.read_text(encoding="utf-8"))["research_pack_sha256"])

        # 2) compile the draft spec into a compiled spec + evidence map
        code, _, err = self.run_script(
            str(self.COMPILER),
            str(self.pack),
            "--validation-report", str(self.validation),
            "--slide-spec", str(self.draft),
            "--compiled-slide-spec", str(self.compiled),
            "--output", str(self.evidence_map),
        )
        self.assertEqual(0, code, err)

        compiled = json.loads(self.compiled.read_text(encoding="utf-8"))
        slide = compiled["slides"][0]
        self.assertEqual(["E01", "E02"], slide["evidence_refs"], "F/D refs were not rewritten to E ids")
        ledger_ids = [entry["id"] for entry in compiled["evidence_ledger"]]
        self.assertEqual(["E01", "E02"], ledger_ids)
        self.assertEqual([5], compiled["evidence_ledger"][0]["used_on_slides"])

        # 3) freeze, binding the full provenance chain
        self.spec_validation.write_text(
            json.dumps({"valid": True, "slide_spec_sha256": self.sha(self.compiled)}), encoding="utf-8"
        )
        code, _, err = self.run_script(
            str(self.GUARD), "freeze",
            "--slide-spec", str(self.compiled),
            "--validation-report", str(self.spec_validation),
            "--lock-file", str(self.lock),
            "--research-pack", str(self.pack),
            "--research-validation", str(self.validation),
            "--evidence-map", str(self.evidence_map),
        )
        self.assertEqual(0, code, err)

        lock = json.loads(self.lock.read_text(encoding="utf-8"))
        self.assertEqual(
            ["evidence_map", "research_pack", "research_validation"],
            sorted(lock["research"]),
        )
        code, stdout, _ = self.run_script(str(self.GUARD), "check", "--lock-file", str(self.lock))
        self.assertEqual(0, code)
        self.assertTrue(json.loads(stdout)["ok"])

    def test_editing_the_pack_after_freeze_breaks_the_chain(self) -> None:
        self.test_the_whole_chain_runs_and_freezes()
        self.pack.write_text(json.dumps({"topic": "被改动过"}, ensure_ascii=False), encoding="utf-8")
        code, stdout, _ = self.run_script(str(self.GUARD), "check", "--lock-file", str(self.lock))
        self.assertEqual(2, code)
        errors = json.loads(stdout)["errors"]
        self.assertTrue(any("research_pack" in line for line in errors), errors)

    def test_a_compiled_spec_referencing_an_unknown_pack_id_blocks(self) -> None:
        """draft 里写了不存在的 F99，编译器必须拒绝而不是产出半个 spec。"""
        self.draft.write_text(
            json.dumps({"schema_version": "2.0", "slides": [{"id": 1, "evidence_refs": ["F99"]}]}),
            encoding="utf-8",
        )
        self.run_script(str(self.VALIDATOR), str(self.pack), "--output", str(self.validation))
        code, _, _ = self.run_script(
            str(self.COMPILER),
            str(self.pack),
            "--validation-report", str(self.validation),
            "--slide-spec", str(self.draft),
            "--compiled-slide-spec", str(self.compiled),
            "--output", str(self.evidence_map),
        )
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
