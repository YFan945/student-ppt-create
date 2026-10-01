from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_helpers import load_module

runtime = load_module(Path(__file__).resolve().parents[1] / "scripts/runtime_evidence.py")

excerpt = load_module(Path(__file__).resolve().parents[1] / "scripts/research_excerpt.py")


class ExcerptTests(unittest.TestCase):
    def test_metadata_helper_is_allowed_but_appended_body_dump_is_not(self):
        helper = Path(__file__).resolve().parents[1] / "scripts/research_excerpt.py"
        command = f'python "{helper.as_posix()}" --text "research/fetched/page.txt" --start "a" --end "b" --pack pack.json --entity-id F01 --source-id S01 ; echo "EXIT=$?"'
        self.assertFalse(runtime.dumps_fetched_body(command))
        relative = f'cd "{helper.parent.parent.as_posix()}" && python scripts/research_excerpt.py --text "research/fetched/page.txt" --start "a" --end "b" 2>&1 | head -20'
        self.assertFalse(runtime.dumps_fetched_body(relative))
        self.assertTrue(runtime.dumps_fetched_body(relative.replace("head -20", "cat")))
        self.assertTrue(runtime.dumps_fetched_body(command + ' ; cat research/fetched/page.txt'))
        self.assertTrue(runtime.dumps_fetched_body(command + ' ; python -c "print(open(\"research/fetched/page.txt\").read())"'))

    def test_exact_newlines_survive_and_oversized_dynamic_spans_are_refused(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "research/source.txt"
            path.parent.mkdir()
            path.write_bytes("prefix 起点\n中间\n终点 suffix".encode())
            result = excerpt.extract(path, "起点", "终点")
            self.assertEqual("起点\n中间\n终点", result["excerpt"])
            with self.assertRaises(ValueError):
                excerpt.extract(path, "起点", "终点", 2)
            with self.assertRaises(ValueError):
                excerpt.extract(path, "missing", "终点")
            with self.assertRaises(ValueError):
                excerpt.extract(path, "起点", "终点", 2001)


if __name__ == "__main__":
    unittest.main()
