"""Six fixed holdout requests through a sequential, memory-bounded local path.

Diagnostic only, after final evaluation. No deployment or parameter tuning.
Includes GPU model load/unload, query encoding, in-memory exact search, reranking.
Excludes corpus/index loading, a real database/API, and the answer LLM.
"""
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

import eval_real_vector_retrieval as ev
from eval_full_vector_improvements import inputs
from vector_model_candidates import BASE, Candidate, profile


def main():
    lock, docs, queries = inputs()
    assert (BASE / 'final/summary.json').exists(), 'This diagnostic must follow the locked final evaluation'
    output = BASE / 'final/sequential-runtime-probe.json'
    assert not output.exists(), 'Preserve the first diagnostic'
    if lock['encoder'] == 'baseline' or lock['tail'] or not lock['reranker']:
        ev.save(output, {'status': 'not_applicable', 'reason': 'This optional probe implements a new head-only encoder plus reranker.'})
        return
    encoder = 'e5' if lock['encoder'] == 'e5-symmetric' else lock['encoder']
    encoder_profile = profile(encoder)['selected']
    reranker_profile = profile(lock['reranker'])['selected']
    ids = [d['_id'] for d in docs]
    positions = {d: i for i, d in enumerate(ids)}
    text = {d['_id']: d['title'] + '\n' + d['text'] for d in docs}
    vectors = np.load(BASE / 'cache/full' / (lock['encoder'] + '-head.npy'))[:len(docs)]
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    bm25 = ev.BM25(list(text.values())) if lock['candidate_mode'] == 'union' else None
    with gzip.open(BASE / 'final/selected_pipeline-rankings.jsonl.gz', 'rt') as f:
        expected = {r['query_id']: r['document_ids'][:10] for r in map(json.loads, f)}
    held = [q for q in queries if q['group'] not in ['recent_en', 'historical_en', 'historical_ko']]
    chosen = []
    for suffix in ['_en', '_ko']:
        chosen += sorted([q for q in held if q['group'].endswith(suffix)],
                         key=lambda q: hashlib.sha256(('v3-sequential:' + q['id']).encode()).hexdigest())[:3]
    rows = []
    for q in chosen:
        torch.cuda.reset_peak_memory_stats()
        times = {}
        beginning = previous = time.monotonic()
        model = Candidate(encoder, encoder_profile['precision'])
        times['encoder_load_seconds'] = time.monotonic() - previous
        previous = time.monotonic()
        try:
            query_vector = model.embed([q['text']], query=True)[0]
        finally:
            model.close()
        times['query_encoding_and_unload_seconds'] = time.monotonic() - previous
        previous = time.monotonic()
        scores = vectors @ query_vector
        if q['source_id'] in positions:
            scores[positions[q['source_id']]] = -np.inf
        original = [ids[i] for i in ev.ranked(scores)]
        depth = lock['candidate_depth']
        if bm25 is not None:
            lexical = bm25.scores(q['text'])
            if q['source_id'] in positions:
                lexical[positions[q['source_id']]] = -np.inf
            lexical_ids = [ids[i] for i in ev.ranked(lexical)]
            candidates = list(dict.fromkeys(original[:depth // 2] + lexical_ids[:depth // 2]))
        else:
            candidates = original[:depth]
        times['in_memory_candidate_search_seconds'] = time.monotonic() - previous
        previous = time.monotonic()
        model = Candidate(lock['reranker'], reranker_profile['precision'])
        times['reranker_load_seconds'] = time.monotonic() - previous
        previous = time.monotonic()
        values = []
        try:
            for start in range(0, len(candidates), reranker_profile['batch_size']):
                batch = candidates[start:start + reranker_profile['batch_size']]
                values.extend(model.rerank([q['text']] * len(batch), [text[d] for d in batch]).tolist())
        finally:
            model.close()
        order = [d for d, value in sorted(zip(candidates, values), key=lambda pair: (-pair[1], pair[0]))]
        used = set(order)
        order.extend(d for d in original if d not in used)
        times['fresh_reranking_and_unload_seconds'] = time.monotonic() - previous
        rows.append({'query_id': q['id'], 'candidate_count': len(candidates), 'seconds': time.monotonic() - beginning,
                     'stages': times, 'peak_allocated_mib': torch.cuda.max_memory_allocated() / 1024**2,
                     'top10_matches_frozen_result': order[:10] == expected[q['id']],
                     'observed_top10': order[:10], 'expected_top10': expected[q['id']]})
        print(json.dumps({k: v for k, v in rows[-1].items() if k not in ['observed_top10', 'expected_top10']}), flush=True)
    ev.save(output, {'status': 'complete', 'queries': len(rows), 'rows': rows,
                    'median_seconds': float(np.median([r['seconds'] for r in rows])),
                    'range_seconds': [min(r['seconds'] for r in rows), max(r['seconds'] for r in rows)],
                    'matching_top10_orders': sum(r['top10_matches_frozen_result'] for r in rows),
                    'selection_lock_sha256': ev.sha(BASE / 'final-selection-lock.json'),
                    'runner_sha256': ev.sha(Path(__file__)), 'paid_api_calls': 0,
                    'scope': 'Six ID-hash-selected requests, 3 English and 3 translated Korean. Sequential GPU loading with warm filesystem caches; full-corpus in-memory search. No server, database request, answer LLM, concurrent load or production SLA measurement. Too few observations for a reliable p95.'})


if __name__ == '__main__':
    main()
