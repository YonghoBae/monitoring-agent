"""Serial GPU development selection; freezes one final pipeline before holdout use."""
import json
from pathlib import Path
import subprocess
import sys

import eval_real_vector_retrieval as ev
from vector_model_candidates import BASE


def execute(script, arguments):
    result = subprocess.run(['rtk', 'proxy', sys.executable, 'scripts/' + script, *arguments])
    path = BASE / 'stage-execution.json'
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append({'finished_at': ev.now(), 'script': script, 'arguments': arguments, 'exit_code': result.returncode})
    ev.save(path, rows)
    if result.returncode:
        print('STAGE FAILED; preserved and continuing other candidates:', script, arguments, flush=True)
    return result.returncode == 0


def score(name):
    path = BASE / 'runs' / name / 'summary.json'
    return json.loads(path.read_text())['development_selection_score'] if path.exists() else -1


def index_estimate(name):
    if name == 'baseline-dense':
        return 30.0  # Most vectors already exist; new source records need embedding.
    m = json.loads((BASE / 'runs' / name / 'manifest.json').read_text())
    state = m['embedding_state']
    def seconds_per_doc(s):
        if 'batches' in s:
            rows = [b for b in s['batches'] if b['kind'] == 'document']
            return sum(b['seconds'] for b in rows) / sum(b['count'] for b in rows)
        return s['seconds'] / s['total']
    per_doc = seconds_per_doc(state['head']) + seconds_per_doc(state['tail']) if 'head' in state else seconds_per_doc(state)
    count = json.loads((BASE / 'holdout-extension/dataset-manifest.json').read_text())['candidate_count'] - 5000
    return per_doc * count


def main():
    assert not (BASE / 'final').exists(), 'Holdout already evaluated; no further automatic tuning'
    assert all((BASE / 'runs' / n / 'manifest.json').exists() for n in ['baseline-dense', 'bm25', 'e5-dense', 'bge-dense', 'qwen-dense'])
    execute('eval_e5_symmetric.py', [])
    natives = ['e5-dense', 'bge-dense', 'qwen-dense']
    native = max(natives, key=score)
    execute('eval_vector_improvements.py', ['dense', '--model', native.removesuffix('-dense'), '--tail'])
    embeddings = ['baseline-dense', *natives, 'e5-symmetric-dense', native.removesuffix('-dense') + '-headtail']
    rows = []
    for name in embeddings:
        if score(name) < 0:
            continue
        estimate = index_estimate(name)
        rows.append({'name': name, 'development_score': score(name), 'estimated_remaining_full_index_seconds': estimate, 'within_frozen_resource_budget': estimate <= 10800})
    eligible = [r for r in rows if r['within_frozen_resource_budget']]
    best = max(eligible, key=lambda r: (r['development_score'], -r['estimated_remaining_full_index_seconds']))['name']
    ev.save(BASE / 'embedding-selection.json', {'selected_at': ev.now(), 'candidates': rows, 'selected': best,
                                               'scope': 'Development-only choice; all large/small-pool scores retained; full-index timing is a projection, not query latency.'})
    print('SELECTED EMBEDDING', best, flush=True)
    reranked = []
    for model in ['bge-reranker', 'qwen-reranker']:
        for source in dict.fromkeys(['baseline-dense', best]):
            if execute('eval_cached_vector_reranker.py', ['--model', model, '--source', source, '--depth', '20']):
                reranked.append(source + '--' + model + '--dense20')
    assert reranked, 'No reranker completed; inspect failures before proceeding'
    leading = max(reranked, key=score)
    source, reranker, _ = leading.split('--')
    expanded = source + '--' + reranker + '--dense50'
    union = source + '--' + reranker + '--union50'
    execute('eval_cached_vector_reranker.py', ['--model', reranker, '--source', source, '--depth', '50'])
    execute('eval_cached_vector_reranker.py', ['--model', reranker, '--source', source, '--depth', '50', '--union'])
    candidates = ['baseline-dense', best, *reranked, expanded, union]
    selected = max(candidates, key=score)
    parts = selected.split('--')
    source = parts[0]
    mode = parts[2] if len(parts) > 1 else 'none'
    lock = {'locked_at': ev.now(), 'selected_development_run': selected, 'embedding_source': source,
            'encoder': source.removesuffix('-dense').removesuffix('-headtail'), 'tail': source.endswith('-headtail'),
            'reranker': parts[1] if len(parts) > 1 else None, 'candidate_mode': 'union' if mode.startswith('union') else 'dense',
            'candidate_depth': int(mode.removeprefix('union').removeprefix('dense')) if mode != 'none' else None,
            'development_selection_score': score(selected), 'candidate_scores': {n: score(n) for n in candidates if score(n) >= 0},
            'holdout_scores_seen': False, 'holdout_manifest_sha256': ev.sha(BASE / 'holdout-extension/dataset-manifest.json'),
            'korean_control_sha256': ev.sha(BASE / 'holdout-extension/korean-control.json'),
            'protocol_sha256': ev.sha(BASE / 'protocol.json'), 'amendments_sha256': ev.sha(BASE / 'development-amendments.json'),
            'model_sources_sha256': ev.sha(BASE / 'model-sources.json'),
            'final_comparisons': ['baseline dense', 'BM25', 'selected encoder dense', 'selected pipeline'],
            'final_rule': 'Evaluate once, report regressions and uncertainty; do not choose a different pipeline using final scores.'}
    ev.save(BASE / 'final-selection-lock.json', lock)
    print('FINAL PIPELINE LOCKED', json.dumps(lock), flush=True)


if __name__ == '__main__':
    main()
