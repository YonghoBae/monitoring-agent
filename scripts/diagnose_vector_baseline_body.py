#!/usr/bin/env python3
"""Same-input MiniLM control, added transparently after the Qwen body probe."""
import argparse
import time
import numpy as np
import eval_real_vector_retrieval as ev
from diagnose_vector_retrieval import OLD, clean_query, inputs, measure, save, sha


def main(url):
    docs, dev, en, ko, _ = inputs()
    tags = ev.api(url, '/api/tags')
    assert any(x['name'] == ev.MODEL and x['digest'] == ev.DIGEST for x in tags['models'])
    byid = {d['_id']:d for d in docs}
    started = time.monotonic()
    a = np.load(OLD/'cache/full/baseline-head.npy')
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    for condition in ['title', 'body']:
        texts = [q['text'] if condition == 'title' else clean_query(q['text']+'\n'+byid[q['source_id']]['text']) for q in en]
        vectors = []
        for offset in range(0,len(texts),16):
            result = ev.api(url, '/api/embed', {'model':ev.MODEL, 'input':texts[offset:offset+16], 'truncate':True,'keep_alive':'10m'})
            vectors.extend(result['embeddings'])
        v = np.asarray(vectors,dtype=np.float32)
        v /= np.linalg.norm(v,axis=1,keepdims=True)
        assert v.shape == (len(en),384) and np.isfinite(v).all()
        if condition == 'title':
            previous = a[len(docs)+len(dev):len(docs)+len(dev)+len(en)]
            assert np.min(np.sum(v*previous,axis=1)) > .9999
        measure('minilm-'+condition+'-fresh',en,(a[:len(docs)]@q for q in v),[d['_id'] for d in docs])
    save('baseline-body-execution.json', {'model':ev.MODEL,'model_digest':ev.DIGEST,'native_context':256,
         'elapsed_seconds':time.monotonic()-started,'paid_api_calls':0,
         'scope':'Same input text as Qwen body256; different tokenizers can retain different character spans. Added after Qwen probe results; not a newly held-out model comparison.'})


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--ollama-url',default='http://localhost:11434')
    main(parser.parse_args().ollama_url)
