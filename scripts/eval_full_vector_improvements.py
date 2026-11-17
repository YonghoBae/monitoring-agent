"""One locked full-corpus comparison, with untouched recent source queries.

Embedding checkpoints are local. Published artifacts contain IDs, ranks, metrics
and provenance only. No optimization is performed using final scores.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import numpy as np
import ir_measures
from ir_measures import nDCG, R, RR, Success
import torch

import eval_real_vector_retrieval as old
from eval_cached_vector_reranker import CachedReranker
from vector_model_candidates import BASE, Candidate, TASK, profile
from retrieval_uncertainty import relevance_clusters, paired_cluster_interval


def inputs():
    lock = json.loads((BASE / 'final-selection-lock.json').read_text())
    hold = BASE / 'holdout-extension'
    assert old.sha(hold / 'dataset-manifest.json') == lock['holdout_manifest_sha256']
    assert old.sha(hold / 'korean-control.json') == lock['korean_control_sha256']
    assert old.sha(BASE / 'protocol.json') == lock['protocol_sha256']
    assert old.sha(BASE / 'development-amendments.json') == lock['amendments_sha256']
    assert old.sha(BASE / 'model-sources.json') == lock['model_sources_sha256']
    manifest = json.loads((hold / 'dataset-manifest.json').read_text())
    for name, digest in manifest['file_sha256'].items():
        assert old.sha(hold / 'cache' / name) == digest
    docs = json.loads((hold / 'cache/documents.json').read_text())
    dev = json.loads((BASE / 'cache/development-queries.json').read_text())
    held = json.loads((hold / 'cache/queries.json').read_text())
    ko = json.loads((hold / 'korean-control.json').read_text())['queries']
    queries = dev + held + ko
    assert len({q['id'] for q in queries}) == len(queries)
    assert len({d['_id'] for d in docs}) == len(docs)
    assert [d['_id'] for d in docs] == sorted(d['_id'] for d in docs), 'Tie ordering requires sorted document IDs'
    assert {d for q in queries for d in q['gold']} <= {d['_id'] for d in docs}
    selected_manifest = json.loads((BASE / 'runs' / lock['embedding_source'] / 'manifest.json').read_text())
    assert selected_manifest['adapter_sha256'] == old.sha(Path(__file__).with_name('vector_model_candidates.py'))
    return lock, docs, queries


def encode(alias, url=None, tail=False):
    lock, docs, queries = inputs()
    cache = BASE / 'cache/full'
    cache.mkdir(exist_ok=True)
    label = alias + ('-tail' if tail else '-head')
    path = cache / (label + '.npy')
    state_path = cache / (label + '-state.json')
    text = [d['title'] + '\n' + d['text'] for d in docs] + [q['text'] for q in queries]
    identity = hashlib.sha256(json.dumps({'texts': text, 'alias': alias, 'tail': tail, 'task': TASK,
                                          'sources': old.sha(BASE / 'model-sources.json'),
                                          'adapter': old.sha(Path(__file__).with_name('vector_model_candidates.py')),
                                          'contract': 'full-v3-1'}, ensure_ascii=False).encode()).hexdigest()
    if state_path.exists():
        state = json.loads(state_path.read_text())
        assert state['input_sha256'] == identity
        if state.get('complete'):
            assert old.sha(path) == state['embeddings_sha256']
            return path
    reuse = {}
    dev_docs = json.loads((BASE / 'cache/development-documents.json').read_text())
    dev_qs = json.loads((BASE / 'cache/development-queries.json').read_text())
    if alias == 'baseline':
        assert not tail
        legacy_docs, legacy_qs, _, _ = old.load_data()
        legacy = np.load(old.BASE / 'cache/embeddings.npy')
        reuse.update({'d:' + d['_id']: legacy[i] for i, d in enumerate(legacy_docs)})
        targets = json.loads((old.BASE / 'recent-control/cache/target-questions.json').read_text())
        changes = np.load(old.BASE / 'recent-control/cache/embeddings.npy')
        reuse.update({'d:' + qid: changes[i] for i, qid in enumerate(sorted(targets))})
        dev_vectors = np.load(BASE / 'cache/baseline-queries.npy')
        reuse.update({'q:' + q['id']: dev_vectors[i] for i, q in enumerate(dev_qs)})
        dimension = 384
    else:
        name = 'tail' if tail else 'head'
        local = BASE / 'cache' / alias / (name + '.npy')
        if local.exists():
            old_vectors = np.load(local)
            reuse.update({'d:' + d['_id']: old_vectors[i] for i, d in enumerate(dev_docs)})
            reuse.update({'q:' + q['id']: old_vectors[len(dev_docs) + i] for i, q in enumerate(dev_qs)})
            dimension = old_vectors.shape[1]
        else:
            dimension = 384 if alias.startswith('e5') else 1024
    ids = ['d:' + d['_id'] for d in docs] + ['q:' + q['id'] for q in queries]
    pending = [i for i, key in enumerate(ids) if key not in reuse]
    if not state_path.exists():
        array = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32, shape=(len(text), dimension))
        for i, key in enumerate(ids):
            if key in reuse:
                array[i] = reuse[key]
        array.flush()
        state = {'input_sha256': identity, 'total_inputs': len(text), 'reused_inputs': len(text) - len(pending), 'pending_inputs': len(pending),
                 'completed_pending': 0, 'batches': [], 'started_at': old.now(), 'alias': alias, 'tail': tail, 'paid_api_calls': 0}
        old.save(state_path, state)
    array = np.lib.format.open_memmap(path, mode='r+')
    model = None
    if alias == 'baseline':
        tags = old.api(url, '/api/tags')
        assert any(m['name'] == old.MODEL and m['digest'] == old.DIGEST for m in tags['models'])
        batch_size = 32
    else:
        underlying = 'e5' if alias == 'e5-symmetric' else alias
        settings = profile(underlying)['selected']
        torch.cuda.reset_peak_memory_stats()
        model = Candidate(underlying, settings['precision'])
        batch_size = settings['batch_size']
        state['profile'] = settings
    # Pending indices are sorted, so document/query batches are kept separate.
    cursor = state['completed_pending']
    try:
        while cursor < len(pending):
            first = pending[cursor]
            query = first >= len(docs)
            positions = []
            for i in pending[cursor:cursor + batch_size]:
                if (i >= len(docs)) != query:
                    break
                positions.append(i)
            batch = [text[i] for i in positions]
            start = time.monotonic()
            if model is None:
                result = old.api(url, '/api/embed', {'model': old.MODEL, 'input': batch, 'truncate': True, 'keep_alive': '10m'})
                vectors = np.asarray(result['embeddings'], dtype=np.float32)
            else:
                if tail and not query:
                    batch = [model.tokenizer.decode(model.tokenizer.encode(s, add_special_tokens=False)[-224:], skip_special_tokens=True) for s in batch]
                vectors = model.embed(batch, query=query or alias == 'e5-symmetric')
            assert vectors.shape == (len(positions), dimension) and np.isfinite(vectors).all()
            assert (np.linalg.norm(vectors, axis=1) > 0).all()
            array[positions] = vectors
            cursor += len(positions)
            state['completed_pending'] = cursor
            state['batches'].append({'count': len(positions), 'query': query, 'seconds': time.monotonic() - start})
            if cursor % 128 < batch_size or cursor == len(pending):
                array.flush()
                old.save(state_path, state)
            if cursor % 1024 < batch_size or cursor == len(pending):
                print(json.dumps({'full_encoding': label, 'completed_new': cursor, 'total_new': len(pending), 'seconds': round(sum(x['seconds'] for x in state['batches']), 1)}), flush=True)
        array.flush()
        state.update({'complete': True, 'finished_at': old.now(), 'embeddings_sha256': old.sha(path)})
        if model is not None:
            state['peak_allocated_mib'] = torch.cuda.max_memory_allocated() / 1024**2
        old.save(state_path, state)
    finally:
        if model is not None:
            model.close()
    return path


def summarize(rows, queries):
    names = sorted({r['method'] for r in rows})
    result, differences = [], []
    groups = sorted({r['group'] for r in rows}) + ['holdout_en', 'holdout_ko']
    clusters = relevance_clusters(queries)
    for group in groups:
        def selected(r):
            if group == 'holdout_en':
                return r['split'] == 'holdout' and r['group'].endswith('_en')
            if group == 'holdout_ko':
                return r['split'] == 'holdout' and r['group'].endswith('_ko')
            return r['group'] == group
        all_rows = [r for r in rows if selected(r)]
        if not all_rows:
            continue
        for method in names:
            part = [r for r in all_rows if r['method'] == method]
            result.append({'group': group, 'method': method, 'queries': len(part), **{k: float(np.mean([r[k] for r in part])) for k in old.metrics([], {'g'})}})
        baseline = {r['query_id']: r['nDCG@10'] for r in all_rows if r['method'] == 'baseline'}
        for method in ['selected_encoder', 'selected_pipeline']:
            values = {r['query_id']: r['nDCG@10'] for r in all_rows if r['method'] == method}
            ids = sorted(baseline)
            delta = np.array([values[q] - baseline[q] for q in ids])
            interval = paired_cluster_interval(dict(zip(ids, delta)), clusters)
            differences.append({'group': group, 'comparison': method + ' - baseline', 'queries': len(ids), 'mean_ndcg10_difference': float(delta.mean()),
                                'ci95': interval['ci95'], 'relevance_clusters': interval['clusters'], 'small_cluster_count': interval['small_cluster_count'],
                                'positive_queries': int((delta > 0).sum()), 'negative_queries': int((delta < 0).sum())})
    return {'groups': result, 'paired_bootstrap': differences, 'note': 'English and translated Korean strata reported separately; do not treat their shared source questions as independent observations in a combined significance claim.'}


def score_final():
    lock, docs, queries = inputs()
    out = BASE / 'final'
    assert not (out / 'summary.json').exists(), 'Final scores already exist; do not retune or overwrite'
    out.mkdir(exist_ok=True)
    ids = [d['_id'] for d in docs]
    positions = {i: j for j, i in enumerate(ids)}
    text = {d['_id']: d['title'] + '\n' + d['text'] for d in docs}
    cache = BASE / 'cache/full'
    base_vectors = np.load(cache / 'baseline-head.npy')
    base_vectors /= np.linalg.norm(base_vectors, axis=1, keepdims=True)
    chosen_vectors = np.load(cache / (lock['encoder'] + '-head.npy'))
    chosen_vectors /= np.linalg.norm(chosen_vectors, axis=1, keepdims=True)
    tail_vectors = None
    if lock['tail']:
        tail_vectors = np.load(cache / (lock['encoder'] + '-tail.npy'))[:len(docs)]
        tail_vectors /= np.linalg.norm(tail_vectors, axis=1, keepdims=True)
    bm25 = old.BM25(list(text.values()))
    rankings = {m: {} for m in ['baseline', 'bm25', 'selected_encoder', 'selected_pipeline']}
    for i, q in enumerate(queries):
        scores = {'baseline': base_vectors[:len(docs)] @ base_vectors[len(docs) + i],
                  'selected_encoder': chosen_vectors[:len(docs)] @ chosen_vectors[len(docs) + i], 'bm25': bm25.scores(q['text'])}
        if tail_vectors is not None:
            scores['selected_encoder'] = np.maximum(scores['selected_encoder'], tail_vectors @ chosen_vectors[len(docs) + i])
        for method, values in scores.items():
            if q['source_id'] in positions:
                values[positions[q['source_id']]] = -np.inf
            rankings[method][q['id']] = [ids[j] for j in old.ranked(values)]
    runtime = []
    fresh_latency = []
    if lock['reranker']:
        progress_path = cache / 'final-rerank-progress.json'
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {'rankings': {}, 'runtime': []}
        torch.cuda.reset_peak_memory_stats()
        reranker = CachedReranker(lock['reranker'])
        def candidates_for(q):
            depth = lock['candidate_depth']
            original = rankings['selected_encoder'][q['id']]
            if lock['candidate_mode'] == 'union':
                return list(dict.fromkeys(original[:depth // 2] + rankings['bm25'][q['id']][:depth // 2]))
            return original[:depth]
        try:
            for q in queries:
                if q['id'] in progress['rankings']:
                    continue
                candidates = candidates_for(q)
                values, timing = reranker.score(q['text'], [text[d] for d in candidates])
                order = [d for d, value in sorted(zip(candidates, values), key=lambda x: (-x[1], x[0]))]
                used = set(order)
                order.extend(d for d in rankings['selected_encoder'][q['id']] if d not in used)
                progress['rankings'][q['id']] = order[:100]
                progress['runtime'].append({'query_id': q['id'], **timing})
                old.save(progress_path, progress)
                if len(progress['rankings']) % 10 == 0:
                    print('FINAL reranked', len(progress['rankings']), '/', len(queries), flush=True)
            rankings['selected_pipeline'] = progress['rankings']
            runtime = progress['runtime']
            # Measure actual fresh reranking, not cache-hit times. Selection is ID-only.
            probe = sorted([q for q in queries if q['group'] not in ['recent_en', 'historical_en', 'historical_ko']],
                           key=lambda q: hashlib.sha256(('v3-latency:' + q['id']).encode()).hexdigest())[:20]
            for q in probe:
                candidates = candidates_for(q)
                _, timing = reranker.score(q['text'], [text[d] for d in candidates], use_cache=False)
                fresh_latency.append({'query_id': q['id'], **timing})
            peak = torch.cuda.max_memory_allocated() / 1024**2
        finally:
            reranker.close()
    else:
        rankings['selected_pipeline'] = rankings['selected_encoder']
        peak = None
    rows, external = [], {}
    gold = {q['id']: set(q['gold']) for q in queries}
    for method, mapping in rankings.items():
        external[method] = []
        with gzip.open(out / (method + '-rankings.jsonl.gz'), 'wt') as f:
            for q in queries:
                order = mapping[q['id']]
                assert len(order) == len(set(order)) == 100 and q['source_id'] not in order and set(order) <= set(ids)
                row = {'method': method, 'query_id': q['id'], 'group': q['group'],
                       'split': 'development' if q['group'] in ['recent_en', 'historical_en', 'historical_ko'] else 'holdout', **old.metrics(order, gold[q['id']])}
                rows.append(row)
                f.write(json.dumps({'query_id': q['id'], 'document_ids': order}) + '\n')
                external[method].extend(ir_measures.ScoredDoc(q['id'], d, 100 - i) for i, d in enumerate(order))
    qrels = [ir_measures.Qrel(q, d, 1) for q, ds in gold.items() for d in ds]
    measures = {nDCG@10: 'nDCG@10', R@5: 'Recall@5', R@10: 'Recall@10', R@100: 'Recall@100', RR@10: 'MRR@10', Success@1: 'Hit@1', Success@5: 'Hit@5'}
    lookup = {(r['method'], r['query_id']): r for r in rows}
    checked = 0
    for method, run in external.items():
        for result in ir_measures.iter_calc(list(measures), qrels, run):
            assert abs(result.value - lookup[(method, result.query_id)][measures[result.measure]]) < 1e-12
            checked += 1
    old.save(out / 'per-query-metrics.json', rows)
    old.save(out / 'numeric-dataset.json', {'candidate_ids': ids, 'queries': [{k: v for k, v in q.items() if k != 'text'} for q in queries]})
    old.save(out / 'runtime.json', {'inference': runtime, 'fresh_latency_probe': fresh_latency, 'reranker_peak_allocated_mib': peak,
             'fresh_rerank_p50_seconds': float(np.median([x['new_inference_seconds'] for x in fresh_latency])) if fresh_latency else None,
             'fresh_rerank_p95_seconds': float(np.quantile([x['new_inference_seconds'] for x in fresh_latency], .95)) if fresh_latency else None,
             'scope': 'Loaded reranker, query+candidate scoring only. Excludes model loading, query embedding, database, answer LLM and simultaneous GPU residency.'})
    old.save(out / 'verification.json', {'status': 'pass', 'checked_at': old.now(), 'independent_per_query_metrics': checked,
                                        'ranking_rows': len(rows), 'self_retrieval_excluded': True, 'selection_lock_sha256': old.sha(BASE / 'final-selection-lock.json')})
    old.save(out / 'manifest.json', {'finished_at': old.now(), 'candidate_count': len(docs), 'queries': len(queries),
               'selection_lock_sha256': old.sha(BASE / 'final-selection-lock.json'), 'runner_sha256': old.sha(Path(__file__)),
               'adapter_sha256': old.sha(Path(__file__).with_name('vector_model_candidates.py')), 'paid_api_calls': 0,
               'component_sha256': {name: old.sha(Path(__file__).with_name(name)) for name in [
                   'eval_full_vector_improvements.py', 'eval_cached_vector_reranker.py', 'vector_model_candidates.py',
                   'eval_real_vector_retrieval.py', 'retrieval_uncertainty.py']},
               'embedding_states': {p.name: json.loads(p.read_text()) for p in sorted(cache.glob('*-state.json'))}})
    aggregate = summarize(rows, queries)
    old.save(out / 'summary.json', aggregate)
    print(json.dumps({'FINAL COMPLETE': True, 'candidate_count': len(docs), 'checked_metrics': checked, 'groups': aggregate['groups']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama-url', default='http://localhost:11434')
    args = parser.parse_args()
    lock, _, _ = inputs()
    assert not (BASE / 'final/summary.json').exists(), 'Completed final results must not be overwritten'
    encode('baseline', args.ollama_url)
    if lock['encoder'] != 'baseline':
        encode(lock['encoder'])
    if lock['tail']:
        encode(lock['encoder'], tail=True)
    score_final()
