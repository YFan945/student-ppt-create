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

    def test_prepare_carries_case_visual_style_content_and_fact_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            case = {'id': 'rich', 'topic': 't', 'image': False, 'visual_style': 'Ocean Tech', 'quality_level': 'rigorous',
                    'pages': [{'title': '封面', 'fact': 'f1', 'exact': ['e1'], 'kind': 'cover',
                               'content': ['c1', 'c2'], 'fact_bindings': [{'id': 'b1', 'label': '样本', 'value': '100'}],
                               'visual': {'type': 'photo', 'purpose': 'Show the actual mechanism'}},
                              {'title': '机制', 'fact': 'f2', 'exact': ['e2']}]}
            spec_path = benchmark.prepare(case, directory, 'auto')
            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            self.assertEqual(spec['meta']['visual_style'], 'Ocean Tech')
            self.assertEqual(spec['meta']['quality_level'], 'rigorous')
            self.assertEqual(spec['meta']['slide_count'], 2)
            self.assertEqual(spec['meta']['duration_min'], 2)
            first, second = spec['slides']
            self.assertEqual(first['kind'], 'cover')
            self.assertEqual(first['content'], ['c1', 'c2'])
            self.assertEqual(first['semantic_requirements']['fact_bindings'][0]['label'], '样本')
            self.assertEqual(first['visual'], {'type': 'photo', 'purpose': 'Show the actual mechanism'})
            self.assertNotIn('layout', first)
            self.assertEqual(second['kind'], 'content')
            self.assertEqual(second['content'], ['f2'])
            self.assertEqual(second['semantic_requirements']['fact_bindings'], [])
            self.assertEqual(second['visual']['type'], 'auto')

    def test_observer_preserves_first_stable_qa_candidate(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            work = directory / 'outputs/.pptx-work/comparison-fixture-auto'
            work.mkdir(parents=True)
            deck = work / 'benchmark.pptx'
            page = work / 'render/slide-1.png'
            page.parent.mkdir()
            deck.write_bytes(b'deck-bytes')
            page.write_bytes(b'page-bytes')
            manifest = {'state': 'qa',
                        'build': {'pptx': {'path': str(deck), 'sha256': benchmark.sha(deck)}},
                        'render': {'pages': [{'path': str(page), 'sha256': benchmark.sha(page)}]}}
            (work / 'build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            stop = threading.Event()
            benchmark.observe_first_candidate(directory, stop)
            snapshot = json.loads((directory / 'first-observed-candidate/snapshot.json').read_text(encoding='utf-8'))
            self.assertEqual(snapshot['kind'], 'first-stable-observed-candidate')
            self.assertTrue(snapshot['not_guaranteed_first_draft'])
            self.assertEqual(len(snapshot['artifacts']), 2)
            for item in snapshot['artifacts']:
                self.assertEqual(benchmark.sha(Path(item['path'])), item['sha256'])
            self.assertTrue(deck.is_file())
            self.assertEqual(json.loads((work / 'build-manifest.json').read_text(encoding='utf-8'))['state'], 'qa')

    def test_observer_rejects_manifest_whose_hashes_do_not_match(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            work = directory / 'outputs/.pptx-work/comparison-fixture-auto'
            work.mkdir(parents=True)
            deck = work / 'benchmark.pptx'
            deck.write_bytes(b'changed-after-manifest')
            manifest = {'state': 'qa',
                        'build': {'pptx': {'path': str(deck), 'sha256': '0' * 64}},
                        'render': {'pages': [{'path': str(deck), 'sha256': '0' * 64}]}}
            (work / 'build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            stop = threading.Event()
            observer = threading.Thread(target=benchmark.observe_first_candidate, args=(directory, stop), daemon=True)
            observer.start()
            stop.set()
            observer.join(timeout=5)
            self.assertFalse((directory / 'first-observed-candidate/snapshot.json').exists())
