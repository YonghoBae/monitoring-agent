"""Development-only retrieval ablations. Holdout selection is handled separately."""
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

import eval_real_vector_retrieval as ev
from vector_model_candidates import Candidate, profile, BASE, TASK


def dataset():
    manifest = json.loads((BASE / 'development-manifest.json').read_text())
    for name, sha in manifest['file_sha256'].items():
        assert ev.sha(BASE / 'cache' / name) == sha
    docs = json.loads((BASE / 'cache/development-documents.json').read_text())
    queries = json.loads((BASE / 'cache/development-queries.json').read_text())
    return docs, queries


def summary(rows):
    groups = []
    for group in sorted({r['group'] for r in rows}):
        selected = [r for r in rows if r['group'] == group]
        groups.append({'group': group, 'queries': len(selected), **{k: float(np.mean([r[k] for r in selected])) for k in ev.metrics([], {'g'})}})
    by = {g['group']: g for g in groups}
    selection = .5 * by['recent_en']['nDCG@10'] + .5 * by['historical_ko']['nDCG@10'] if 'recent_en' in by and 'historical_ko' in by else None
    return {'groups': groups, 'development_selection_score': selection}


def finish(name, docs, queries, rankings, runtime):
    output = BASE / 'runs' / name
    output.mkdir(parents=True, exist_ok=True)
    rows, scored = [], []
    gold = {q['id']: set(q['gold']) for q in queries}
    ids = {d['_id'] for d in docs}
    assert set(rankings) == set(gold)
    with gzip.open(output / 'rankings.jsonl.gz', 'wt') as f:
        for q in queries:
            order = rankings[q['id']]
            assert len(order) == len(set(order)) == 100 and set(order) <= ids and q['source_id'] not in order
            row = {'query_id': q['id'], 'group': q['group'], **ev.metrics(order, gold[q['id']])}
            rows.append(row)
            f.write(json.dumps({'query_id': q['id'], 'document_ids': order}) + '\n')
            scored.extend(ir_measures.ScoredDoc(q['id'], d, 100 - i) for i, d in enumerate(order))
    qrels = [ir_measures.Qrel(q, d, 1) for q, ds in gold.items() for d in ds]
    measures = {nDCG@10: 'nDCG@10', R@5: 'Recall@5', R@10: 'Recall@10', R@100: 'Recall@100', RR@10: 'MRR@10', Success@1: 'Hit@1', Success@5: 'Hit@5'}
    by = {r['query_id']: r for r in rows}
    checked = 0
    for result in ir_measures.iter_calc(list(measures), qrels, scored):
        assert abs(by[result.query_id][measures[result.measure]] - result.value) < 1e-12
        checked += 1
    ev.save(output / 'per-query-metrics.json', rows)
    aggregate = summary(rows)
    ev.save(output / 'summary.json', aggregate)
    ev.save(output / 'manifest.json', {'completed_at': ev.now(), 'name': name, 'candidate_count': len(docs), 'query_count': len(queries),
                                      'protocol_sha256': ev.sha(BASE / 'protocol.json'), 'dataset_manifest_sha256': ev.sha(BASE / 'development-manifest.json'),
                                      'runner_sha256': ev.sha(Path(__file__)), 'adapter_sha256': ev.sha(Path(__file__).with_name('vector_model_candidates.py')),
                                      'independent_metrics_checked': checked, 'paid_api_calls': 0, **runtime})
    print(json.dumps({'completed': name, **aggregate}), flush=True)


def cached_embed(alias, texts, queries, suffix='head', tail=False):
    settings = profile(alias)['selected']
    if settings is None:
        raise RuntimeError('Candidate failed both precision probes: ' + alias)
    cache = BASE / 'cache' / alias
    cache.mkdir(exist_ok=True)
    state_path = cache / (suffix + '-state.json')
    path = cache / (suffix + '.npy')
    inputs = texts + [q['text'] for q in queries]
    fingerprint = hashlib.sha256(json.dumps({'inputs': inputs, 'settings': settings, 'tail': tail, 'task': TASK,
                                            'encoding_contract': 'v3-1-titlebody-max256-tail224-preserve-prefix',
                                            'model_sources_sha256': ev.sha(BASE / 'model-sources.json')}, ensure_ascii=False).encode()).hexdigest()
    state = json.loads(state_path.read_text()) if state_path.exists() else {'input_sha256': fingerprint, 'completed': 0, 'total': len(inputs), 'batches': []}
    assert state['input_sha256'] == fingerprint
    if state['completed'] == len(inputs):
        return np.load(path), state
    model = Candidate(alias, settings['precision'])
    batch_size = settings['batch_size']
    vectors = None
    try:
        for kind, start, end in [('document', 0, len(texts)), ('query', len(texts), len(inputs))]:
            for offset in range(max(start, state['completed']), end, batch_size):
                then = time.monotonic()
                batch = inputs[offset:min(offset + batch_size, end)]
                if tail and kind == 'document':
                    # Preserve required model prefixes: select the tail content before the adapter adds them.
                    batch = [model.tokenizer.decode(model.tokenizer.encode(t, add_special_tokens=False)[-224:], skip_special_tokens=True) for t in batch]
                array = model.embed(batch, query=kind == 'query')
                if vectors is None:
                    vectors = np.lib.format.open_memmap(path, mode='r+' if path.exists() else 'w+', dtype=np.float32, shape=(len(inputs), array.shape[1]))
                vectors[offset:offset + len(array)] = array
                vectors.flush()
                state['completed'] = offset + len(array)
                state['batches'].append({'offset': offset, 'count': len(array), 'kind': kind, 'seconds': time.monotonic() - then})
                ev.save(state_path, state)
                if offset == start or state['completed'] % 512 == 0:
                    print(json.dumps({'embedding': alias, 'variant': suffix, 'completed': state['completed'], 'total': len(inputs)}), flush=True)
        state['finished_at'] = ev.now()
        state['peak_allocated_mib'] = torch.cuda.max_memory_allocated() / 1024**2
        ev.save(state_path, state)
    finally:
        model.close()
    return np.load(path), state


def load_ranks(name):
    with gzip.open(BASE / 'runs' / name / 'rankings.jsonl.gz', 'rt') as f:
        return {r['query_id']: r['document_ids'] for r in map(json.loads, f)}


def dense(alias, tail=False):
    name = alias + ('-headtail' if tail else '-dense')
    if (BASE / 'runs' / name / 'summary.json').exists():
        return
    docs, queries = dataset()
    texts = [d['title'] + '\n' + d['text'] for d in docs]
    if alias == 'baseline':
        dv, qv = np.load(BASE / 'cache/baseline-documents.npy'), np.load(BASE / 'cache/baseline-queries.npy')
        state = {'reused_original_vectors': True}
    else:
        all_vectors, state = cached_embed(alias, texts, queries)
        dv, qv = all_vectors[:len(docs)], all_vectors[len(docs):]
    dv = np.ascontiguousarray(dv / np.linalg.norm(dv, axis=1, keepdims=True))
    qv = qv / np.linalg.norm(qv, axis=1, keepdims=True)
    tv = None
    if tail:
        arr, tail_state = cached_embed(alias, texts, queries, suffix='tail', tail=True)
        tv = np.ascontiguousarray(arr[:len(docs)] / np.linalg.norm(arr[:len(docs)], axis=1, keepdims=True))
        state = {'head': state, 'tail': tail_state}
    ids = [d['_id'] for d in docs]
    pos = {i: j for j, i in enumerate(ids)}
    rankings, timings = {}, []
    for i, q in enumerate(queries):
        start = time.monotonic()
        scores = dv @ qv[i]
        if tv is not None:
            scores = np.maximum(scores, tv @ qv[i])
        if q['source_id'] in pos:
            scores[pos[q['source_id']]] = -np.inf
        rankings[q['id']] = [ids[j] for j in ev.ranked(scores)]
        timings.append(time.monotonic() - start)
    finish(name, docs, queries, rankings, {'embedding_state': state, 'query_embedding_latency_included': False,
                                          'search_p50_seconds': float(np.median(timings)), 'search_p95_seconds': float(np.quantile(timings, .95)),
                                          'tail_probe': tail})


def bm25():
    if (BASE / 'runs/bm25/summary.json').exists():
        return
    docs, queries = dataset()
    model = ev.BM25([d['title'] + '\n' + d['text'] for d in docs])
    ids = [d['_id'] for d in docs]
    pos = {i: j for j, i in enumerate(ids)}
    ranks = {}
    for q in queries:
        scores = model.scores(q['text'])
        if q['source_id'] in pos:
            scores[pos[q['source_id']]] = -np.inf
        ranks[q['id']] = [ids[j] for j in ev.ranked(scores)]
    finish('bm25', docs, queries, ranks, {'implementation': 'unchanged v2 formula'})


def rerank(alias, source, depth=50, union=False):
    name = source + '--' + alias + '--' + ('union' if union else 'dense') + str(depth)
    if (BASE / 'runs' / name / 'summary.json').exists():
        return
    docs, queries = dataset()
    texts = {d['_id']: d['title'] + '\n' + d['text'] for d in docs}
    original = load_ranks(source)
    lexical = load_ranks('bm25') if union else None
    settings = profile(alias)['selected']
    if settings is None:
        raise RuntimeError('Reranker failed smoke tests')
    checkpoint = BASE / 'cache' / (name + '.json')
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {'rankings': {}, 'query_seconds': []}
    model = Candidate(alias, settings['precision'])
    try:
        for q in queries:
            if q['id'] in state['rankings']:
                continue
            candidates = original[q['id']][:depth]
            if union:
                candidates = list(dict.fromkeys(original[q['id']][:depth // 2] + lexical[q['id']][:depth // 2]))
            start = time.monotonic()
            scores = []
            for offset in range(0, len(candidates), settings['batch_size']):
                part = candidates[offset:offset + settings['batch_size']]
                scores.extend(model.rerank([q['text']] * len(part), [texts[d] for d in part]).tolist())
            order = sorted(zip(candidates, scores), key=lambda pair: (-pair[1], pair[0]))
            ranked = [d for d, score in order]
            ranked += [d for d in original[q['id']] if d not in set(ranked)]
            state['rankings'][q['id']] = ranked[:100]
            state['query_seconds'].append({'query_id': q['id'], 'seconds': time.monotonic() - start, 'candidate_count': len(candidates)})
            ev.save(checkpoint, state)
            if len(state['rankings']) % 10 == 0:
                print(json.dumps({'reranker': name, 'completed_queries': len(state['rankings']), 'total_queries': len(queries)}), flush=True)
        peak = torch.cuda.max_memory_allocated() / 1024**2
    finally:
        model.close()
    times = [r['seconds'] for r in state['query_seconds']]
    finish(name, docs, queries, state['rankings'], {'reranker_profile': settings, 'candidate_source': source, 'depth': depth, 'union': union,
                                                    'rerank_p50_seconds': float(np.median(times)), 'rerank_p95_seconds': float(np.quantile(times, .95)),
                                                    'rerank_total_seconds': sum(times), 'peak_allocated_mib': peak,
                                                    'query_embedding_latency_included': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['dense', 'bm25', 'rerank'])
    parser.add_argument('--model', default='baseline')
    parser.add_argument('--source', default='baseline-dense')
    parser.add_argument('--depth', type=int, default=50)
    parser.add_argument('--tail', action='store_true')
    parser.add_argument('--union', action='store_true')
    args = parser.parse_args()
    if args.mode == 'dense':
        dense(args.model, args.tail)
    elif args.mode == 'bm25':
        bm25()
    else:
        rerank(args.model, args.source, args.depth, args.union)
