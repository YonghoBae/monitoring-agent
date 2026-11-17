"""Public numeric replay. Requires numpy/ir_measures, not Torch, model files or APIs."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import ir_measures
from ir_measures import nDCG, R, RR, Success

from eval_real_vector_retrieval import metrics
from retrieval_uncertainty import relevance_clusters, paired_cluster_interval

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval/vector-v3-improvement'
MEASURES = {nDCG@10: 'nDCG@10', R@5: 'Recall@5', R@10: 'Recall@10', R@100: 'Recall@100',
            RR@10: 'MRR@10', Success@1: 'Hit@1', Success@5: 'Hit@5'}


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(path, dataset, final=False):
    queries = {q['id']: q for q in dataset['queries']}
    assert len(queries) == len(dataset['queries'])
    assert all(q['gold'] and len(q['gold']) == len(set(q['gold'])) and q['source_id'] not in q['gold'] for q in queries.values())
    candidates = set(dataset['candidate_ids'])
    assert len(candidates) == len(dataset['candidate_ids'])
    assert {d for q in queries.values() for d in q['gold']} <= candidates
    rows = read(path / 'per-query-metrics.json')
    expected = {(r.get('method', 'run'), r['query_id']): r for r in rows}
    assert len(expected) == len(rows)
    qrels = [ir_measures.Qrel(q['id'], d, 1) for q in queries.values() for d in q['gold']]
    count = 0
    for ranks_path in sorted(path.glob('*rankings.jsonl.gz')):
        method = ranks_path.name.removesuffix('-rankings.jsonl.gz') if final else 'run'
        run, seen = [], set()
        with gzip.open(ranks_path, 'rt') as f:
            for record in map(json.loads, f):
                qid = record['query_id']
                assert qid in queries and qid not in seen
                seen.add(qid)
                q = queries[qid]
                order = record['document_ids']
                assert len(order) == len(set(order)) == 100 and set(order) <= candidates and q['source_id'] not in order
                row = expected[(method, qid)]
                assert row['group'] == q['group']
                for key, value in metrics(order, set(q['gold'])).items():
                    assert abs(value - row[key]) < 1e-12, (path.name, qid, key)
                run.extend(ir_measures.ScoredDoc(qid, d, 100 - i) for i, d in enumerate(order))
        assert seen == set(queries)
        for result in ir_measures.iter_calc(list(MEASURES), qrels, run):
            assert abs(result.value - expected[(method, result.query_id)][MEASURES[result.measure]]) < 1e-12
            count += 1
    assert count == len(rows) * 7
    summary = read(path / 'summary.json')
    for group in summary['groups']:
        def match(row):
            g = group['group']
            if g in ['holdout_en', 'holdout_ko']:
                return row['split'] == 'holdout' and row['group'].endswith('_en' if g == 'holdout_en' else '_ko')
            return row['group'] == g
        selected = [r for r in rows if match(r) and (not final or r['method'] == group['method'])]
        assert len(selected) == group['queries']
        for key in metrics([], {'g'}):
            assert abs(float(np.mean([r[key] for r in selected])) - group[key]) < 1e-12
    if not final:
        groups = {g['group']: g for g in summary['groups']}
        assert abs(summary['development_selection_score'] - .5 * (groups['recent_en']['nDCG@10'] + groups['historical_ko']['nDCG@10'])) < 1e-12
    else:
        clusters = relevance_clusters(dataset['queries'])
        for comparison in summary['paired_bootstrap']:
            group = comparison['group']
            selected = [r for r in rows if ((r['split'] == 'holdout' and r['group'].endswith('_en' if group == 'holdout_en' else '_ko')) if group in ['holdout_en', 'holdout_ko'] else r['group'] == group)]
            base = {r['query_id']: r['nDCG@10'] for r in selected if r['method'] == 'baseline'}
            method = comparison['comparison'].removesuffix(' - baseline')
            other = {r['query_id']: r['nDCG@10'] for r in selected if r['method'] == method}
            delta = np.array([other[q] - base[q] for q in sorted(base)])
            interval = paired_cluster_interval(dict(zip(sorted(base), delta)), clusters)
            np.testing.assert_allclose(interval['ci95'], comparison['ci95'], atol=1e-12, rtol=0)
            assert interval['clusters'] == comparison['relevance_clusters']
            assert abs(float(delta.mean()) - comparison['mean_ndcg10_difference']) < 1e-12
    return {'run': path.name, 'ranking_rows': len(rows), 'independent_metrics': count}


def verify_native_fixture():
    value = read(BASE / 'native-regression.json')
    if value['status'] != 'complete':
        return {'run': 'native-synthetic-regression-skipped', 'ranking_rows': 0, 'independent_metrics': 0}
    fixture_path = BASE.parent / 'vector-v1/dataset.json'
    assert digest(fixture_path) == value['dataset_sha256']
    assert digest(BASE / 'final-selection-lock.json') == value['selection_lock_sha256']
    assert digest(BASE.parent / 'vector-v1/runs/initial/embeddings.json') == value['baseline_embeddings_sha256']
    fixture = read(fixture_path)
    queries = {q['id']: q for q in fixture['queries'] if q['answerable']}
    expected = {(r['method'], r['pool'], r['query_id']): r for r in value['per_query_metrics']}
    assert len(expected) == len(value['per_query_metrics']) == len(queries) * 6
    selected_measures = {nDCG@10: 'nDCG@10', Success@1: 'Hit@1', Success@5: 'Hit@5'}
    runs, seen = {}, set()
    for row in value['rankings']:
        key = (row['method'], row['pool'], row['query_id'])
        assert key in expected and key not in seen
        seen.add(key)
        candidates = {d['id'] for d in fixture['corpus'] if row['pool'] == 'all_records' or d['type'] == 'resolution'}
        order = row['document_ids']
        assert len(order) == len(set(order)) == len(candidates) and set(order) == candidates
        computed = metrics(order, set(fixture['qrels'][row['query_id']]))
        for name in selected_measures.values():
            assert abs(computed[name] - expected[key][name]) < 1e-12
        runs.setdefault(key[:2], []).extend(ir_measures.ScoredDoc(row['query_id'], d, len(order) - i) for i, d in enumerate(order))
    assert seen == set(expected)
    qrels = [ir_measures.Qrel(q, d, relevance) for q in queries for d, relevance in fixture['qrels'][q].items()]
    checked = 0
    for (method, pool), run in runs.items():
        for result in ir_measures.iter_calc(list(selected_measures), qrels, run):
            assert abs(result.value - expected[(method, pool, result.query_id)][selected_measures[result.measure]]) < 1e-12
            checked += 1
    for summary in value['summary']:
        part = [r for r in expected.values() if r['method'] == summary['method'] and r['pool'] == summary['pool'] and r['variant'].startswith(summary['query_language'] + '_')]
        assert len(part) == summary['queries']
        for name in selected_measures.values():
            assert abs(float(np.mean([r[name] for r in part])) - summary[name]) < 1e-12
    assert checked == value['independent_metrics_checked']
    return {'run': 'native-synthetic-regression', 'ranking_rows': len(seen), 'independent_metrics': checked}


def main(development_only=False, write=False):
    dev = read(BASE / 'development-manifest.json')
    results = []
    for path in sorted((BASE / 'runs').glob('*')):
        if (path / 'summary.json').exists():
            results.append(verify_run(path, dev))
    if not development_only:
        lock = read(BASE / 'final-selection-lock.json')
        assert lock['holdout_scores_seen'] is False
        assert digest(BASE / 'protocol.json') == lock['protocol_sha256']
        assert digest(BASE / 'development-amendments.json') == lock['amendments_sha256']
        assert digest(BASE / 'holdout-extension/dataset-manifest.json') == lock['holdout_manifest_sha256']
        assert digest(BASE / 'holdout-extension/korean-control.json') == lock['korean_control_sha256']
        assert digest(BASE / 'model-sources.json') == lock['model_sources_sha256']
        assert lock['selected_development_run'] in lock['candidate_scores']
        assert abs(lock['development_selection_score'] - max(lock['candidate_scores'].values())) < 1e-12
        for name, value in lock['candidate_scores'].items():
            assert abs(value - read(BASE / 'runs' / name / 'summary.json')['development_selection_score']) < 1e-12
        numeric = read(BASE / 'final/numeric-dataset.json')
        assert len(numeric['candidate_ids']) == read(BASE / 'holdout-extension/dataset-manifest.json')['candidate_count']
        assert numeric['candidate_ids'] == sorted(numeric['candidate_ids'])
        expected_queries = dev['queries'] + read(BASE / 'holdout-extension/dataset-manifest.json')['queries'] + read(BASE / 'holdout-extension/korean-control.json')['queries']
        expected = {q['id']: (q['source_id'], q['group'], sorted(q['gold'])) for q in expected_queries}
        assert {q['id']: (q['source_id'], q['group'], sorted(q['gold'])) for q in numeric['queries']} == expected
        results.append(verify_run(BASE / 'final', numeric, final=True))
        final = read(BASE / 'final/manifest.json')
        assert final['selection_lock_sha256'] == digest(BASE / 'final-selection-lock.json')
        for name, sha256 in final['component_sha256'].items():
            assert digest(Path(__file__).with_name(name)) == sha256, ('implementation changed', name)
        assert dt.datetime.fromisoformat(lock['locked_at']) < dt.datetime.fromisoformat(final['finished_at'])
        if (BASE / 'native-regression.json').exists():
            results.append(verify_native_fixture())
    result = {'status': 'pass', 'development_only': development_only, 'runs': results,
              'ranking_rows': sum(r['ranking_rows'] for r in results), 'independent_metrics': sum(r['independent_metrics'] for r in results),
              'api_calls': 0, 'gpu_required': False, 'models_required': False}
    artifacts = BASE / 'artifact-sha256.json'
    if not development_only and artifacts.exists():
        for name, sha256 in read(artifacts)['files'].items():
            assert digest(BASE.parents[1] / name) == sha256, ('published artifact changed', name)
    if write:
        (BASE / 'numeric-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--development-only', action='store_true')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    main(args.development_only, args.write)
