#!/usr/bin/env python3
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = root / 'data'
required = [
    data/'annotation_sample_100.jsonl', data/'trajectory_review.schema.json',
    data/'assignments/A.jsonl', data/'assignments/B.jsonl',
    data/'outputs/canonical_runs.jsonl',
    data/'outputs/checkpoint_replay/checkpoint_analysis_summary.json',
]
for path in required:
    assert path.exists(), f'missing: {path}'
def rows(path): return [json.loads(x) for x in path.read_text().splitlines() if x]
all_rows, a_rows, b_rows = rows(required[0]), rows(required[2]), rows(required[3])
all_ids={x['annotation_id'] for x in all_rows}; a_ids={x['annotation_id'] for x in a_rows}; b_ids={x['annotation_id'] for x in b_rows}
assert len(all_rows)==100 and len(all_ids)==100
assert len(a_rows)==50 and len(b_rows)==50
assert not (a_ids & b_ids) and (a_ids | b_ids)==all_ids
assert '/root/' not in required[0].read_text()
print('bundle ok: 100 samples = A(50) + B(50), no overlap, no /root absolute paths')
