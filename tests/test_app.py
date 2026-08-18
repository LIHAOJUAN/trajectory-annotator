import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as ui


class AnnotationUITest(unittest.TestCase):
    def setUp(self):
        self.client = ui.app.test_client()

    def test_health(self):
        data = self.client.get('/health').get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['sample_count'], 100)

    def test_items_and_detail(self):
        items = self.client.get('/api/items?replay=yes').get_json()['items']
        self.assertGreater(len(items), 0)
        detail = self.client.get('/api/items/' + items[0]['annotation_id']).get_json()
        self.assertIn('sample', detail)
        self.assertIsNotNone(detail['replay_instance'])

    def test_bundled_data_has_no_server_absolute_paths(self):
        text = (ui.DATA_DIR / 'annotation_sample_100.jsonl').read_text()
        self.assertNotIn('/root/', text)
        first = json.loads(text.splitlines()[0])
        self.assertIn('run_relpath', first)

    def test_tool_statistics_shape(self):
        aid = ui.repo.samples[0]['annotation_id']
        stats = ui.repo.tool_statistics(aid)
        self.assertIn('available', stats)
        if stats['available']:
            self.assertEqual(stats['total'], sum(x['total'] for x in stats['rounds']))
            self.assertEqual(stats['total'], stats['worker_total'] + stats['evaluator_total'] + stats['other_total'])

    def test_primary_suggestion_uses_legal_trajectory_label(self):
        sample = ui.repo.samples[0]
        suggestion = ui.repo.primary_suggestion(sample)
        allowed = set(ui.repo.schema['properties']['trajectory_verdict']['enum'])
        self.assertIn(suggestion['value'], allowed)
        self.assertIn('reason', suggestion)

    def test_round_summary_shape_when_trajectory_is_mounted(self):
        aid = ui.repo.samples[0]['annotation_id']
        summary = ui.repo.trajectory_round_summary(aid)
        self.assertIn('available', summary)
        if summary['available']:
            self.assertGreater(len(summary['rounds']), 0)
            first = summary['rounds'][0]
            self.assertIn('worker', first)
            self.assertIn('evaluator', first)
            self.assertEqual(first['worker']['tool_count'], len(first['worker']['tools']))

    def test_simple_review_save(self):
        aid = ui.repo.samples[0]['annotation_id']
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / 'reviews.jsonl'
            lock = Path(td) / 'reviews.jsonl.lock'
            with patch.object(ui, 'REVIEW_STORE_PATH', store), patch.object(ui, 'REVIEW_LOCK_PATH', lock):
                res = self.client.post('/api/reviews/' + aid, json={
                    'annotator': 'reviewer',
                    'trajectory_verdict': 'Uncertain',
                    'notes': 'test',
                })
                self.assertEqual(res.status_code, 200, res.get_json())
                row = json.loads(store.read_text().strip())
                self.assertEqual(row['trajectory_verdict'], 'Uncertain')
                self.assertIn('machine_suggestion', row)



if __name__ == '__main__':
    unittest.main()
