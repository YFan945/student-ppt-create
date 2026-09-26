from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
freshness = load_module(ROOT / "scripts" / "constraint_freshness.py")

PYPI = {
    "numpy": {"version": "2.5.3", "info": {"requires_python": ">=3.12"}},
    "idna": {"version": "3.20", "info": {"requires_python": ">=3.9"}},
    "magika": {"version": "1.0.3", "info": {"requires_python": ">=3.9"}},
}


def fake_fetch(url: str) -> dict:
    package = url.rstrip("/json").rsplit("/", 1)[-1]
    return PYPI[package]


class ConstraintFreshnessTests(unittest.TestCase):
    def test_report_counts_drift_and_fresh_pins(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "python-constraints.txt"
            path.write_text(
                "# header comment\nnumpy==2.4.6\nidna==3.20\n", encoding="utf-8"
            )
            report = freshness.build_report(path, fetch=fake_fetch)
        self.assertIn("| numpy | 2.4.6 | 2.5.3 | >=3.12 |", report)
        self.assertIn("| idna | 3.20 | 3.20 | >=3.9 |", report)
        self.assertIn("DRIFT: 1/2", report)

    def test_duplicate_pins_and_comments_are_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "python-constraints.txt"
            path.write_text(
                "idna==3.20\n# magika==0.6.3 (frozen)\nMAGIKA==0.6.3\n",
                encoding="utf-8",
            )
            pairs = freshness.pins(path)
        self.assertEqual([("idna", "3.20"), ("MAGIKA", "0.6.3")], pairs)

    def test_missing_metadata_degrades_to_placeholder(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "python-constraints.txt"
            path.write_text("idna==3.20\n", encoding="utf-8")
            report = freshness.build_report(path, fetch=lambda _url: {})
        self.assertIn("| idna | 3.20 | ? | ? |", report)


if __name__ == "__main__":
    unittest.main()
