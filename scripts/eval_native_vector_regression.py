"""Apply the locked encoder to the existing small Korean synthetic fixture.

Supplementary regression only: 20 authored families, not an independent
real-incident test or evidence of production accuracy. No reranker tuning.
"""
import json
from pathlib import Path
import time

import ir_measures
from ir_measures import nDCG, Success
import numpy as np

import eval_real_vector_retrieval as ev
from vector_model_candidates import BASE, Candidate, profile


def main():
    assert (BASE / 'final/summary.json').exists(), 'Run this appendix after the primary final evaluation'
    destination = BASE / 'native-regression.json'
    assert not destination.exists(), 'Preserve the first regression result'
    lock = json.loads((BASE / 'final-selection-lock.json').read_text())
    plan = json.loads((BASE / 'native-regression-plan.json').read_text())
    fixture = BASE.parent / 'vector-v1/dataset.json'
    old_vectors = BASE.parent / 'vector-v1/runs/initial/embeddings.json'
    assert plan['dataset_sha256'] == ev.sha(fixture)
    assert plan['selection_lock_sha256'] == ev.sha(BASE / 'final-selection-lock.json')
    data = json.loads(fixture.read_text())
    documents = sorted(data['corpus'], key=lambda d: d['id'])
    queries = [q for q in data['queries'] if q['answerable']]
    baseline = json.loads(old_vectors.read_text())
    items = documents + queries
    vectors = {'baseline': np.array([baseline[x['id']] for x in items], dtype=np.float32)}
    alias = lock['encoder']
    if alias == 'baseline' or lock['tail']:
        ev.save(destination, {'status': 'not_applicable', 'reason': 'This appendix implements a new head-only encoder.'})
        return
    underlying = 'e5' if alias == 'e5-symmetric' else alias
    settings = profile(underlying)['selected']
    model = Candidate(underlying, settings['precision'])
    started = time.monotonic()
    encoded = []
    try:
        for collection, query in [(documents, False), (queries, True)]:
            for start in range(0, len(collection), settings['batch_size']):
                batch = collection[start:start + settings['batch_size']]
                encoded.extend(model.embed([x['text'] for x in batch], query=query or alias == 'e5-symmetric'))
    finally:
        model.close()
    vectors['selected_encoder'] = np.array(encoded, dtype=np.float32)
    elapsed = time.monotonic() - started
    for values in vectors.values():
        values /= np.linalg.norm(values, axis=1, keepdims=True)
    lexical = ev.BM25([d['text'] for d in documents])
    rows, ranks = [], []
    measures = {nDCG@10: 'nDCG@10', Success@1: 'Hit@1', Success@5: 'Hit@5'}
    qrels = [ir_measures.Qrel(q['id'], doc, relevance) for q in queries for doc, relevance in data['qrels'][q['id']].items()]
    checked = 0
    for pool in ['all_records', 'resolution_only']:
        eligible = [i for i, d in enumerate(documents) if pool == 'all_records' or d['type'] == 'resolution']
        for method in ['baseline', 'bm25', 'selected_encoder']:
            run, expected = [], {}
            for i, q in enumerate(queries):
                scores = lexical.scores(q['text']) if method == 'bm25' else vectors[method][:len(documents)] @ vectors[method][len(documents) + i]
                order = [documents[j]['id'] for j in sorted(eligible, key=lambda j: (-scores[j], documents[j]['id']))]
                values = ev.metrics(order, set(data['qrels'][q['id']]))
                row = {'query_id': q['id'], 'family': q['family'], 'variant': q['variant'], 'method': method,
                       'pool': pool, 'candidate_count': len(eligible), **{key: values[key] for key in measures.values()}}
                rows.append(row)
                ranks.append({'query_id': q['id'], 'method': method, 'pool': pool, 'document_ids': order})
                expected[q['id']] = row
                run.extend(ir_measures.ScoredDoc(q['id'], doc, len(order) - j) for j, doc in enumerate(order))
            for value in ir_measures.iter_calc(list(measures), qrels, run):
                assert abs(value.value - expected[value.query_id][measures[value.measure]]) < 1e-12
                checked += 1
    summary = []
    for pool in ['all_records', 'resolution_only']:
        for method in ['baseline', 'bm25', 'selected_encoder']:
            for language in ['ko', 'en']:
                part = [r for r in rows if r['pool'] == pool and r['method'] == method and r['variant'].startswith(language + '_')]
                summary.append({'pool': pool, 'method': method, 'query_language': language, 'queries': len(part),
                                **{key: float(np.mean([r[key] for r in part])) for key in measures.values()}})
    ev.save(destination, {'status': 'complete', 'scope': plan['scope'], 'finished_at': ev.now(), 'dataset_sha256': ev.sha(fixture),
                         'baseline_embeddings_sha256': ev.sha(old_vectors), 'selection_lock_sha256': ev.sha(BASE / 'final-selection-lock.json'),
                         'runner_sha256': ev.sha(Path(__file__)), 'adapter_sha256': ev.sha(Path(__file__).with_name('vector_model_candidates.py')),
                         'queries': len(queries), 'synthetic_families': len({q['family'] for q in queries}),
                         'excluded_no_answer_queries': sum(not q['answerable'] for q in data['queries']), 'selected_encoder': alias,
                         'embedding_seconds_excluding_load': elapsed, 'independent_metrics_checked': checked,
                         'paid_api_calls': 0, 'summary': summary, 'per_query_metrics': rows, 'rankings': ranks})
    print(json.dumps({'status': 'complete', 'checked_metrics': checked, 'summary': summary}), flush=True)


if __name__ == '__main__':
    main()
