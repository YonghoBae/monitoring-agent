"""Reuse identical query/document scores across development ablations, never labels.

Cache hits are excluded from uncached latency statistics. This avoids paying the
same local inference cost again when testing a different candidate generator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np
import torch

import eval_real_vector_retrieval as ev
from eval_vector_improvements import dataset, finish, load_ranks
from vector_model_candidates import BASE, Candidate, MODELS, TASK, profile


class CachedReranker:
    def __init__(self, alias):
        self.alias = alias
        self.settings = profile(alias)['selected']
        if self.settings is None:
            raise RuntimeError('No successful precision probe for ' + alias)
        self.model = Candidate(alias, self.settings['precision'])
        self.db = sqlite3.connect(BASE / 'cache/reranker-pairs.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS pairs (key TEXT PRIMARY KEY, score REAL NOT NULL)')
        source = next(m for m in json.loads((BASE / 'model-sources.json').read_text()) if m['model_id'] == MODELS[alias])
        self.identity = json.dumps({'model': source['model_id'], 'revision': source['revision'], 'precision': self.settings['precision'],
                                   'task': TASK, 'max_length': 512, 'adapter_sha256': ev.sha(Path(__file__).with_name('vector_model_candidates.py'))}, sort_keys=True)

    def close(self):
        self.db.close()
        self.model.close()

    def score(self, query, documents, use_cache=True):
        keys = [hashlib.sha256(json.dumps([self.identity, query, doc], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest() for doc in documents]
        scores = [None] * len(keys)
        hits = 0
        for i, key in enumerate(keys):
            row = self.db.execute('SELECT score FROM pairs WHERE key=?', (key,)).fetchone() if use_cache else None
            if row is not None:
                scores[i] = row[0]
                hits += 1
        missing = [i for i, value in enumerate(scores) if value is None]
        started = time.monotonic()
        for offset in range(0, len(missing), self.settings['batch_size']):
            positions = missing[offset:offset + self.settings['batch_size']]
            values = self.model.rerank([query] * len(positions), [documents[i] for i in positions])
            for i, value in zip(positions, values):
                scores[i] = float(value)
                self.db.execute('INSERT OR REPLACE INTO pairs VALUES (?,?)', (keys[i], float(value)))
        self.db.commit()
        return scores, {'pairs': len(keys), 'cached_pairs': hits, 'new_pairs': len(missing), 'new_inference_seconds': time.monotonic() - started}


def main(alias, source, depth, union):
    name = source + '--' + alias + '--' + ('union' if union else 'dense') + str(depth)
    if (BASE / 'runs' / name / 'summary.json').exists():
        return
    docs, queries = dataset()
    texts = {d['_id']: d['title'] + '\n' + d['text'] for d in docs}
    original = load_ranks(source)
    lexical = load_ranks('bm25') if union else None
    checkpoint = BASE / 'cache' / (name + '-cached.json')
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {'rankings': {}, 'query_runtime': []}
    model = CachedReranker(alias)
    try:
        for q in queries:
            if q['id'] in state['rankings']:
                continue
            candidates = original[q['id']][:depth]
            if union:
                candidates = list(dict.fromkeys(original[q['id']][:depth // 2] + lexical[q['id']][:depth // 2]))
            values, runtime = model.score(q['text'], [texts[i] for i in candidates])
            order = [i for i, value in sorted(zip(candidates, values), key=lambda x: (-x[1], x[0]))]
            selected = set(order)
            order.extend(i for i in original[q['id']] if i not in selected)
            state['rankings'][q['id']] = order[:100]
            state['query_runtime'].append({'query_id': q['id'], **runtime})
            ev.save(checkpoint, state)
            if len(state['rankings']) % 10 == 0:
                print(json.dumps({'run': name, 'queries_completed': len(state['rankings']), 'queries_total': len(queries),
                                  'new_pairs': sum(x['new_pairs'] for x in state['query_runtime']), 'cached_pairs': sum(x['cached_pairs'] for x in state['query_runtime'])}), flush=True)
        peak = torch.cuda.max_memory_allocated() / 1024**2
    finally:
        model.close()
    fresh = [r['new_inference_seconds'] for r in state['query_runtime'] if r['cached_pairs'] == 0]
    finish(name, docs, queries, state['rankings'], {'variant_runner_sha256': ev.sha(Path(__file__)), 'candidate_source': source,
               'reranker': alias, 'depth': depth, 'union': union, 'query_runtime': state['query_runtime'],
               'new_pairs': sum(x['new_pairs'] for x in state['query_runtime']), 'cached_pairs': sum(x['cached_pairs'] for x in state['query_runtime']),
               'fully_uncached_latency_query_count': len(fresh), 'uncached_rerank_p50_seconds': float(np.median(fresh)) if fresh else None,
               'uncached_rerank_p95_seconds': float(np.quantile(fresh, .95)) if fresh else None, 'peak_allocated_mib': peak,
               'latency_scope': 'Loaded model reranking only; reused scores do not count as fresh inference or represent latency improvement.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--depth', type=int, default=20)
    parser.add_argument('--union', action='store_true')
    args = parser.parse_args()
    main(args.model, args.source, args.depth, args.union)
