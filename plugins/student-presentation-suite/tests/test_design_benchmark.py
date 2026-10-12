"""Live benchmark resumes preserve authorization and cumulative cost evidence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import design_benchmark as benchmark


class LiveBenchmarkTests(unittest.TestCase):
    def test_cumulative_resumed_session_cost_is_not_counted_twice(self):
        attempts = [{'session_id': 'main', 'total_cost_usd': 1}, {'session_id': 'main', 'total_cost_usd': 6}, {'session_id': 'main', 'total_cost_usd': 8}, {'session_id': 'critic', 'total_cost_usd': 2}]
        result = benchmark.cli_cost_summary(attempts)
        self.assertEqual(result['reported_cost_usd'], 10)
        attempts.append({'session_id': 'interrupted', 'total_cost_usd': None})
        result = benchmark.cli_cost_summary(attempts)
        self.assertIsNone(result['reported_cost_usd'])
        self.assertEqual(result['known_cli_estimates_usd'], 10)
        self.assertIsNone(result['actual_provider_cost_usd'])

    def test_stage_resume_does_not_replay_intake_with_yaml_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            work = directory / 'outputs/.pptx-work/comparison-fixture-guided'
            work.mkdir(parents=True)
            (work / 'build-manifest.json').write_text(json.dumps({'state': 'incomplete', 'design_freedom': 'guided', 'build': {'repair_count': 1}}), encoding='utf-8')
            (work / 'production-summary.yaml').write_text('topic: fixture', encoding='utf-8')
            (directory / 'session-id.txt').write_text('saved-session', encoding='utf-8')
            with patch.object(benchmark.live, 'find_claude', return_value='native-claude'), patch.object(benchmark.live, 'run_turn') as turn, patch.object(benchmark, 'continue_live', return_value=[]), patch.object(benchmark, 'collect_evidence', return_value={}):
                result = benchmark.live_case({'id': 'fixture'}, directory, 'guided', True, True)
            turn.assert_not_called()
            self.assertEqual(result['state'], 'incomplete')
            self.assertEqual(result['repair_count'], 1)
