"""Contract tests for the v0.8 gate exit codes.

The review flagged that the gate exit codes had no test coverage, and that the
gates were fail-open by default (a missing ``--strict`` silently returned 0).
Gates are now fail-closed by default: a non-ok report exits 2 unless ``--lenient``
is explicitly passed. These tests lock that contract in.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "skills" / "sp-deck" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import art_direction_check  # noqa: E402
import composition_candidate_check  # noqa: E402
import pptx_visual_generation_gate_v08 as visual_gate  # noqa: E402

NON_OK = {"ok": False, "issues": [{"severity": "blocker", "detail": "contract-test"}]}


class GateExitCodeTests(unittest.TestCase):
    @staticmethod
    def _exit(module, argv):
        with mock.patch.object(sys, "argv", ["gate", *argv]):
            return module.main()

    def test_art_direction_fail_closed(self) -> None:
        with mock.patch.object(art_direction_check, "load_structured", return_value={}), \
                mock.patch.object(art_direction_check, "validate_art_direction", return_value=NON_OK):
            tmp = Path(tempfile.gettempdir()) / "art-direction-contract.json"
            self.assertEqual(2, self._exit(art_direction_check, [str(tmp)]))
            self.assertEqual(0, self._exit(art_direction_check, [str(tmp), "--lenient"]))

    def test_composition_fail_closed(self) -> None:
        with mock.patch.object(composition_candidate_check, "load_structured", return_value={}), \
                mock.patch.object(composition_candidate_check, "validate_candidates", return_value=NON_OK):
            tmp = Path(tempfile.gettempdir()) / "composition-contract.json"
            self.assertEqual(2, self._exit(composition_candidate_check, [str(tmp)]))
            self.assertEqual(0, self._exit(composition_candidate_check, [str(tmp), "--lenient"]))

    def test_visual_generation_fail_closed(self) -> None:
        with mock.patch.object(visual_gate, "validate_visual_generation", return_value=NON_OK):
            with tempfile.TemporaryDirectory() as d:
                paths = [str(Path(d) / name) for name in ("spec", "art", "ev")]
                base = ["--slide-spec", paths[0], "--art-direction", paths[1], "--evidence-dir", paths[2]]
                self.assertEqual(2, self._exit(visual_gate, base))
                self.assertEqual(0, self._exit(visual_gate, [*base, "--lenient"]))


if __name__ == "__main__":
    unittest.main()
