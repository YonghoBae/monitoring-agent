"""Development ablation: E5's documented query/query mode for similar-question retrieval."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import eval_real_vector_retrieval as ev
from eval_vector_improvements import dataset, finish
from vector_model_candidates import BASE, Candidate, profile


def main():
    name = 'e5-symmetric-dense'
    if (BASE / 'runs' / name / 'summary.json').exists():
        return
    docs, queries = dataset()
    inputs = [d['title'] + '\n' + d['text'] for d in docs] + [q['text'] for q in queries]
    config = profile('e5')['selected']
    cache = BASE / 'cache/e5-symmetric'
    cache.mkdir(exist_ok=True)
    path = cache / 'head.npy'
    state_path = cache / 'head-state.json'
    fingerprint = hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()
    state = json.loads(state_path.read_text()) if state_path.exists() else {'input_sha256': fingerprint, 'completed': 0, 'total': len(inputs), 'seconds': 0}
    assert state['input_sha256'] == fingerprint
    if state['completed'] < len(inputs):
        model = Candidate('e5', config['precision'])
        vectors = np.lib.format.open_memmap(path, mode='r+' if path.exists() else 'w+', dtype=np.float32, shape=(len(inputs), 384))
        try:
            for offset in range(state['completed'], len(inputs), config['batch_size']):
                start = time.monotonic()
                array = model.embed(inputs[offset:offset + config['batch_size']], query=True)
                vectors[offset:offset + len(array)] = array
                state['completed'] = offset + len(array)
                state['seconds'] += time.monotonic() - start
                if state['completed'] % 128 == 0 or state['completed'] == len(inputs):
                    vectors.flush()
                    ev.save(state_path, state)
                if state['completed'] % 1024 == 0:
                    print('symmetric embedded', state['completed'], flush=True)
        finally:
            model.close()
    vectors = np.load(path)
    assert np.isfinite(vectors).all()
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    dv, qv = vectors[:len(docs)], vectors[len(docs):]
    ids = [d['_id'] for d in docs]
    positions = {i: j for j, i in enumerate(ids)}
    ranks = {}
    for i, q in enumerate(queries):
        scores = dv @ qv[i]
        if q['source_id'] in positions:
            scores[positions[q['source_id']]] = -np.inf
        ranks[q['id']] = [ids[j] for j in ev.ranked(scores)]
    finish(name, docs, queries, ranks, {'variant': 'query: prefix for both question documents and queries; other E5 settings unchanged',
                                       'source': 'https://huggingface.co/intfloat/multilingual-e5-small#faq', 'embedding_state': state,
                                       'variant_runner_sha256': ev.sha(Path(__file__))})


if __name__ == '__main__':
    main()
