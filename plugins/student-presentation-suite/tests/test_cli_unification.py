"""Tests for the stable version-dispatched CLIs (P1-4).

External surface must be `delivery_check.py` / `quality_gate.py`; the
v0.7/v0.7.1/v0.8 implementations stay internal. Dispatch is verified with
fake modules so no real PPTX is needed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK_SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


delivery_entry = _load("delivery_check_entry", DECK_SCRIPTS / "delivery_check.py")
quality_entry = _load("quality_gate_entry", DECK_SCRIPTS / "quality_gate.py")


class DispatchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_argv = sys.argv
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in ("pptx_delivery_check_v07", "pptx_delivery_check_v071",
                         "pptx_delivery_check_v08", "pptx_quality_gate_v071")
        }
        self.calls: list[tuple[str, list[str]]] = []

    def tearDown(self) -> None:
        sys.argv = self._saved_argv
        for name, module in self._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def install_fake(self, module_name: str) -> None:
        entry = self

        def recorder() -> int:
            entry.calls.append((module_name, list(sys.argv[1:])))
            return 0

        sys.modules[module_name] = types.SimpleNamespace(main=recorder)

    def test_default_core_is_v08_for_delivery(self) -> None:
        self.install_fake("pptx_delivery_check_v08")
        rc = delivery_entry.main(["--pptx", "deck.pptx", "--output", "r.json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [("pptx_delivery_check_v08", ["--pptx", "deck.pptx", "--output", "r.json"])])

    def test_core_flag_is_extracted_and_forwarded(self) -> None:
        self.install_fake("pptx_delivery_check_v071")
        rc = delivery_entry.main(["--core", "v071", "--strict"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [("pptx_delivery_check_v071", ["--strict"])])

    def test_unknown_core_is_refused_without_import(self) -> None:
        rc = delivery_entry.main(["--core", "v99", "--pptx", "deck.pptx"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [])

    def test_core_without_value_is_refused(self) -> None:
        rc = delivery_entry.main(["--core"])
        self.assertEqual(rc, 2)

    def test_all_declared_delivery_cores_resolve(self) -> None:
        for core, module_name in delivery_entry.CORES.items():
            self.install_fake(module_name)
            rc = delivery_entry.main(["--core", core])
            self.assertEqual(rc, 0)
        self.assertEqual([name for name, _ in self.calls], list(delivery_entry.CORES.values()))

    def test_quality_defaults_to_v071(self) -> None:
        self.install_fake("pptx_quality_gate_v071")
        rc = quality_entry.main(["--pptx", "deck.pptx", "--strict"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [("pptx_quality_gate_v071", ["--pptx", "deck.pptx", "--strict"])])

    def test_quality_unknown_core_is_refused(self) -> None:
        rc = quality_entry.main(["--core", "v08"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
