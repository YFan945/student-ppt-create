"""Focused regressions for the hardened research evidence pipeline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
VALIDATE_RESEARCH = ROOT / "scripts" / "validate_research_pack.py"
COMPILE = ROOT / "scripts" / "research_pack_to_evidence.py"
VALIDATE_SPEC = ROOT / "scripts" / "validate_slide_spec.py"
GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_validate_research_pack import base_pack  # noqa: E402


class ResearchHardeningRegressionTests(unittest.TestCase):
    def run_python(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_compiled_slide_spec_passes_the_real_slide_spec_validator(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            pack = tmp / "research-pack.json"
            validation = tmp / "research-pack-validation.json"
            draft = tmp / "slide-spec-draft.json"
            compiled = tmp / "slide-spec-compiled.json"
            evidence_map = tmp / "evidence-map.json"
            spec_report = tmp / "slide-spec-validation.json"

            pack.write_text(json.dumps(base_pack(), ensure_ascii=False, indent=2), encoding="utf-8")
            research_result = self.run_python(
                VALIDATE_RESEARCH,
                str(pack),
                "--output",
                str(validation),
            )
            self.assertEqual(0, research_result.returncode, research_result.stdout + research_result.stderr)

            draft.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "slides": [
                            {
                                "id": 1,
                                "title": "对象幻觉仍是关键风险",
                                "layout": "content",
                                "content": "对象幻觉与基准幻觉率",
                                "evidence_refs": ["F01", "D01"],
                                "timing_sec": 45,
                                "owner": "Individual",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            compile_result = self.run_python(
                COMPILE,
                str(pack),
                "--validation-report",
                str(validation),
                "--slide-spec",
                str(draft),
                "--compiled-slide-spec",
                str(compiled),
                "--output",
                str(evidence_map),
            )
            self.assertEqual(0, compile_result.returncode, compile_result.stdout + compile_result.stderr)

            spec_result = self.run_python(
                VALIDATE_SPEC,
                str(compiled),
                "--output",
                str(spec_report),
                "--json",
            )
            self.assertEqual(0, spec_result.returncode, spec_result.stdout + spec_result.stderr)
            report = json.loads(spec_report.read_text(encoding="utf-8"))
            self.assertTrue(report["valid"], report["errors"])

            spec = json.loads(compiled.read_text(encoding="utf-8"))
            self.assertEqual(["E01", "E02"], spec["slides"][0]["evidence_refs"])
            self.assertEqual([1], spec["evidence_ledger"][0]["used_on_slides"])
            self.assertEqual(["S01", "S02"], spec["evidence_ledger"][0]["source_ids"])

    def test_legacy_v10_lock_remains_readable_after_upgrade(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            spec = tmp / "slide-spec.json"
            validation = tmp / "slide-spec-validation.json"
            lock = tmp / "slide-spec-lock.json"

            spec.write_text(
                json.dumps(
                    {
                        "slides": [
                            {
                                "id": 1,
                                "title": "Legacy",
                                "layout": "content",
                                "content": "legacy",
                                "timing_sec": 30,
                                "owner": "Individual",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            spec_hash = hashlib.sha256(spec.read_bytes()).hexdigest()
            validation.write_text(
                json.dumps({"valid": True, "slide_spec_sha256": spec_hash}),
                encoding="utf-8",
            )
            validation_hash = hashlib.sha256(validation.read_bytes()).hexdigest()
            lock.write_text(
                json.dumps(
                    {
                        "lock_version": "1.0",
                        "status": "frozen",
                        "revision": 1,
                        "reason": "legacy",
                        "parent_slide_spec_sha256": None,
                        "slide_spec": str(spec.resolve()),
                        "slide_spec_sha256": spec_hash,
                        "validation_report": str(validation.resolve()),
                        "validation_report_sha256": validation_hash,
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_python(GUARD, "check", "--lock-file", str(lock), "--json")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["errors"])


if __name__ == "__main__":
    unittest.main()
