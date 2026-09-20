"""plan must bind the validation report to the spec it actually freezes.

2026-09-20 live run: `plan` compiles the source spec into
`slide-spec-compiled.yaml` and then freezes *that* file, while the report the
session produced describes the source spec. The guard refuses with
"stale or belongs to another spec", the session only then discovers the compiled
file by listing the directory, and plan has to run a second time. Three
round-trips spent discovering a file the pipeline itself created.

Plan owns the compiled spec, so plan owns its report: it re-validates against
whatever spec is about to be frozen instead of demanding that the caller guess.
Re-validation is not a bypass — a spec that fails validation still refuses.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_SPEC = importlib.util.spec_from_file_location("pipeline.plan", SCRIPTS / "pipeline" / "plan.py")
plan = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("pipeline.plan", plan)
_SPEC.loader.exec_module(plan)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Completed:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class PlanSpecAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        self.spec = self.work / "slide-spec-compiled.yaml"
        self.spec.write_text("slides: []\n", encoding="utf-8")
        self.report = self.work / "slide-spec-validation.json"

    def _write_report(self, path: Path, spec: Path, *, valid: bool = True) -> None:
        path.write_text(
            json.dumps({"valid": valid, "slide_spec_sha256": sha256_of(spec)}),
            encoding="utf-8",
        )

    def test_a_report_that_describes_the_frozen_spec_is_used_as_is(self) -> None:
        self._write_report(self.report, self.spec)
        with patch.object(plan.core, "_runner") as runner:
            chosen, regenerated = plan.aligned_validation_report(self.work, self.spec, self.report)
        self.assertEqual(self.report, chosen)
        self.assertFalse(regenerated)
        runner.assert_not_called()

    def test_a_report_describing_a_different_spec_is_revalidated(self) -> None:
        """The chicken-and-egg: the compiled spec did not exist when the report was made."""
        source = self.work / "slide-spec.yaml"
        source.write_text("slides: []  # source, pre-compile\n", encoding="utf-8")
        self._write_report(self.report, source)

        def fake_runner(argv: list[str]) -> Completed:
            position = argv.index("--output")
            self._write_report(Path(argv[position + 1]), Path(argv[position - 1]))
            return Completed(0)

        with patch.object(plan.core, "_runner", side_effect=fake_runner) as runner:
            chosen, regenerated = plan.aligned_validation_report(self.work, self.spec, self.report)

        self.assertTrue(regenerated)
        self.assertEqual(self.work / "slide-spec-report.json", chosen)
        self.assertTrue(chosen.is_file())
        regenerated_report = json.loads(chosen.read_text(encoding="utf-8"))
        self.assertEqual(sha256_of(self.spec), regenerated_report["slide_spec_sha256"])
        # The validator must be pointed at the frozen spec, not the source one.
        self.assertIn(str(self.spec), runner.call_args[0][0])

    def test_a_spec_that_does_not_validate_still_refuses(self) -> None:
        """Auto re-validation is not a bypass — the freeze must still fail."""
        self._write_report(self.report, self.spec, valid=False)
        with patch.object(plan.core, "_runner", return_value=Completed(2)):
            with self.assertRaises(plan.RefusedError):
                plan.aligned_validation_report(self.work, self.spec, self.report)

    def test_a_missing_report_is_revalidated_instead_of_refused(self) -> None:
        def fake_runner(argv: list[str]) -> Completed:
            out = Path(argv[argv.index("--output") + 1])
            self._write_report(out, self.spec)
            return Completed(0)

        with patch.object(plan.core, "_runner", side_effect=fake_runner):
            chosen, regenerated = plan.aligned_validation_report(self.work, self.spec, self.report)
        self.assertTrue(regenerated)
        self.assertEqual(self.work / "slide-spec-report.json", chosen)


if __name__ == "__main__":
    unittest.main()
