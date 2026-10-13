"""Transient Windows sharing failures do not lose an atomic checkpoint."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import research_io


class AtomicJsonTests(unittest.TestCase):
    def test_transient_windows_sharing_error_retries_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            path.write_text('{"old":true}', encoding='utf-8')
            real_replace = research_io.os.replace
            error = PermissionError('briefly held destination')
            error.winerror = 32
            attempts = []

            def replace(source, destination):
                attempts.append(source)
                if len(attempts) == 1:
                    self.assertEqual(json.loads(path.read_text()), {'old': True})
                    raise error
                real_replace(source, destination)

            with patch.object(research_io.os, 'replace', side_effect=replace), patch.object(research_io.time, 'sleep'):
                research_io.atomic_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'new': True})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_permanent_denial_is_not_swallowed_or_rewritten_non_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            path.write_text('{"old":true}', encoding='utf-8')
            error = PermissionError('permanent denial')
            error.winerror = 5
            with patch.object(research_io.os, 'replace', side_effect=error) as replace, patch.object(research_io.time, 'sleep'):
                with self.assertRaises(PermissionError):
                    research_io.atomic_json(path, {'new': True})
            self.assertEqual(replace.call_count, 5)
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])
