"""Descriptive execution diagnostics; never reads answer text or raw backend trace."""
import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def describe(rows):
    result = {}
    for arm in ('pi_plus', 'compact_plus'):
        selected = [r for r in rows if r['arm'] == arm]
        if not selected:
            raise ValueError('Both arms required')
        lengths = []; elapsed = []; first = Counter(); tools = Counter(); duplicates = 0
        for row in selected:
            trace = row['trace']
            if trace.get('kind') != 'delivered_tool_results' or trace.get('captureSupported') is not True:
                raise ValueError('Exact delivered-tool trace required')
            observations = trace['observations']; lengths.append(len(observations))
            elapsed.append(row['elapsedMs'] / 1000)
            first[observations[0]['tool'] if observations else '(none)'] += 1
            tools.update(o['tool'] for o in observations)
            requests = [(o['tool'], o['input']) for o in observations]
            duplicates += len(requests) - len(set(requests))
        result[arm] = {'n': len(selected), 'median_elapsed_seconds': statistics.median(elapsed),
            'median_delivered_tool_results': statistics.median(lengths),
            'total_delivered_tool_results': sum(lengths),
            'first_tool_counts': dict(first.most_common()), 'delivered_tool_counts': dict(tools.most_common()),
            'repeated_identical_tool_inputs': duplicates,
            'runner_errors': sum(bool(r['error']) for r in selected)}
    return {'arms': result,
        'interpretation': 'Descriptive only. Delivered results include cache deliveries; repeated inputs do not prove repeated backend execution. Elapsed time includes harness overhead. No equal inference-token claim.',
        'answer_text_inspected': False, 'raw_backend_trace_used': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.campaign/'manifest.json').read_text())
    if manifest.get('status') != 'completed':
        raise ValueError('Completed campaign required')
    path = args.campaign/'raw-comparison/results.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) != manifest['answers']:
        raise ValueError('Result count differs from campaign manifest')
    result = describe(rows)
    result['results_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    destination = args.campaign/'workflow-diagnostics.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
