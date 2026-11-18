#!/usr/bin/env python3
"""Post-test cause probes; never changes the locked v3 benchmark or deployment.

Full-corpus query ablations and gold-injected, fixed-candidate document probes
have deliberately separate outputs. The latter are not retrieval accuracy.
"""
import argparse
from collections import Counter
import datetime as dt
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
import numpy as np
import ir_measures
from ir_measures import nDCG, Success
import eval_real_vector_retrieval as ev

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'eval/vector-v3-improvement'
OUT = ROOT / 'eval/vector-v4-diagnosis'


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, obj):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def source(did):
    return did.split(':', 1)[0] if ':' in did else 'unix'


def inputs():
    docs = read(OLD / 'holdout-extension/cache/documents.json')
    dev = read(OLD / 'cache/development-queries.json')
    en = read(OLD / 'holdout-extension/cache/queries.json')
    ko = read(OLD / 'holdout-extension/korean-control.json')['queries']
    ranks = {}
    for method in ['baseline', 'bm25', 'selected_encoder', 'selected_pipeline']:
        with gzip.open(OLD / 'final' / (method + '-rankings.jsonl.gz'), 'rt') as f:
            ranks[method] = {x['query_id']: x['document_ids'] for x in map(json.loads, f)}
    return docs, dev, en, ko, ranks


def clean_query(text):
    # Remove ALL site-question URLs, not only gold URLs. Preserve other content.
    return re.sub(r'https?://(?:[\w.-]+\.)?(?:stackexchange\.com|askubuntu\.com|serverfault\.com|superuser\.com)/questions/\S+', '[question link removed]', text)


def prepare():
    docs, dev, en, ko, ranks = inputs()
    byid = {d['_id']: d for d in docs}
    selected = sorted(en, key=lambda q: hashlib.sha256(('v4-document-probe:' + q['id']).encode()).hexdigest())[:32]
    candidates = {q['id']: sorted(set(q['gold']).union(*(set(ranks[m][q['id']][:3]) for m in ranks)) - {q['source_id']}) for q in selected}
    diagnostic = read(OLD / 'final/error-analysis.json')['queries']
    review = []
    # Sampling by failure class uses old outcomes only; no new probe outcomes.
    for category in ['candidate_miss', 'ranking_miss', 'correct_first']:
        eligible = [q for q in en if diagnostic[q['id']]['diagnosis'] == category] if isinstance(diagnostic, dict) else []
        if not eligible:
            for q in en:
                order = ranks['selected_encoder'][q['id']][:50]
                status = 'candidate_miss' if not set(order) & set(q['gold']) else ('correct_first' if ranks['selected_pipeline'][q['id']][0] in q['gold'] else 'ranking_miss')
                if status == category:
                    eligible.append(q)
        review.extend({'id': q['id'], 'category': category} for q in sorted(eligible, key=lambda q: hashlib.sha256(('v4-review:' + q['id']).encode()).hexdigest())[:4])
    plan = {
        'frozen_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'purpose': 'Post-test diagnosis of competing causes, not a new unbiased model ranking or production recommendation.',
        'hypotheses': {
            'implementation': 'Check full vector SHA, shape/norm, stored ranking replay; independently re-encode frozen query texts and sampled documents.',
            'query_information': 'Same full corpus and Qwen document vectors: title256 vs title+source-body256 vs same body512. Remove all site-question URLs, report residual gold-ID mentions. No target answer text is added.',
            'instruction': 'Same frozen title and document vectors; Qwen with original query instruction vs no query instruction. Diagnostic only.',
            'lexical_fields': 'Full corpus BM25 2x2: title-only vs title+body query, title-only vs title+body documents. No stemming or query generation added.',
            'document_truncation': '32 English query IDs selected by hash, gold + top3 from each of four original methods, identical candidate sets. Compare cached head256, recomputed head256, title256, head512 and all overlapping token chunks. Gold injection makes this a representation discrimination probe, NOT full retrieval.',
            'label_and_task': 'Review four hash-selected cases in each original failure class, including successes; preserve gold labels and scores. Review is by the same agent and is not independent adjudication.',
            'candidate_competition': 'For each query describe best gold rank and source of candidates above it; source labels are analysis metadata, not a validated production filter.',
        },
        'controls': {'document_probe_queries': [q['id'] for q in selected], 'document_probe_candidates': candidates, 'review_sample': review,
                     'chunk_tokens': 256, 'chunk_overlap': 64, 'query_max_length': 256, 'document_long_length': 512,
                     'no_paid_apis': True, 'no_production_changes': True, 'no_v3_relabeling_or_retuning': True},
        'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [
            OLD / 'holdout-extension/cache/documents.json', OLD / 'holdout-extension/cache/queries.json',
            OLD / 'final/summary.json', OLD / 'final-selection-lock.json',
            OLD / 'cache/full/qwen-head.npy', OLD / 'cache/full/baseline-head.npy',
            ROOT / 'scripts/vector_model_candidates.py', Path(__file__)]},
    }
    path = OUT / 'plan.json'
    if path.exists():
        old = read(path)
        assert old['input_sha256'] == plan['input_sha256'] and old['controls'] == plan['controls']
    else:
        save('plan.json', plan)
    print(json.dumps({'stage': 'prepared', 'english_queries': len(en), 'probe_queries': len(selected),
                      'probe_documents': len(set().union(*map(set, candidates.values()))), 'review_cases': len(review)}), flush=True)


def measure(name, qs, scores, ids):
    lookup = {did: i for i, did in enumerate(ids)}
    rows = []
    for q, values in zip(qs, scores):
        values = np.asarray(values).copy()
        if q['source_id'] in lookup:
            values[lookup[q['source_id']]] = -np.inf
        order = [ids[i] for i in ev.ranked(values)]
        m = ev.metrics(order, set(q['gold']))
        qrels = [ir_measures.Qrel(q['id'], d, 1) for d in q['gold']]
        run = [ir_measures.ScoredDoc(q['id'], d, float(len(order)-i)) for i, d in enumerate(order)]
        external = ir_measures.calc_aggregate([nDCG@10, Success@1, Success@5], qrels, run)
        for key, metric in [('nDCG@10', nDCG@10), ('Hit@1', Success@1), ('Hit@5', Success@5)]:
            assert abs(m[key] - external[metric]) < 1e-9
        rows.append({'query_id': q['id'], 'group': q['group'], 'metrics': m, 'top100': order})
    summary = {k: float(np.mean([r['metrics'][k] for r in rows])) for k in rows[0]['metrics']}
    result = {'name': name, 'queries': len(qs), 'summary': summary, 'rows': rows}
    save(name + '.json', result)
    print(json.dumps({'stage': name, 'queries': len(qs), **summary}), flush=True)
    return result


def cpu():
    docs, dev, en, ko, ranks = inputs()
    ids = [d['_id'] for d in docs]
    ix = {d: i for i, d in enumerate(ids)}
    allqs = dev + en + ko
    qi = {q['id']: len(docs)+i for i, q in enumerate(allqs)}
    arrays = {}
    checks = {}
    for alias, method in [('baseline', 'baseline'), ('qwen', 'selected_encoder')]:
        p = OLD / 'cache/full' / (alias + '-head.npy')
        a = np.load(p, mmap_mode='r')
        state = read(p.with_name(alias + '-head-state.json'))
        assert sha(p) == state['embeddings_sha256']
        norms = np.linalg.norm(a, axis=1)
        assert np.isfinite(a).all() and np.allclose(norms, 1, atol=.002)
        normalized = np.asarray(a).copy()
        normalized /= np.linalg.norm(normalized, axis=1, keepdims=True)
        # Match the frozen evaluator's matvec order, avoiding ~1e-7 GEMM ties.
        allscores = (normalized[:len(docs)] @ normalized[qi[q['id']]] for q in en)
        matches = 0
        competition = []
        for q, scores in zip(en, allscores):
            scores[ix[q['source_id']]] = -np.inf
            order = ev.ranked(scores, len(docs))
            assert [ids[i] for i in order[:100]] == ranks[method][q['id']]
            matches += 1
            best = next(i for i, j in enumerate(order) if ids[j] in q['gold'])
            competition.append({'query_id': q['id'], 'best_gold_rank': best+1,
                                'above_gold_by_source': dict(Counter(source(ids[i]) for i in order[:best]))})
        checks[alias] = {'shape': list(a.shape), 'norm_range': [float(norms.min()), float(norms.max())],
                         'stored_top100_matches': matches, 'queries': len(en), 'competition': competition}
    save('cache-audit.json', checks)
    required = {g for q in en for g in q['gold']}
    background = sorted(set(ids)-required,key=lambda d:hashlib.sha256(('v4-distractors:'+d).encode()).hexdigest())
    smallids = sorted(required | set(background[:5000-len(required)]))
    indices = [ix[d] for d in smallids]
    save('pool5000.json', {'scope':'Gold-preserving diagnostic, not a new test set or production accuracy.', 'candidate_ids':smallids})
    for alias,label in [('baseline','minilm'),('qwen','qwen')]:
        array = np.load(OLD/'cache/full'/(alias+'-head.npy'))
        array /= np.linalg.norm(array,axis=1,keepdims=True)
        small = array[indices]
        measure(label+'-pool5000',en,(small@array[qi[q['id']]] for q in en),smallids)
    byid = {d['_id']: d for d in docs}
    body = [clean_query(q['text'] + '\n' + byid[q['source_id']]['text']) for q in en]
    save('query-input-audit.json', {'scope': 'Source question body can include edits or answer hints; not proven contemporaneous incident input.',
         'queries': [{'query_id': q['id'], 'source_body_characters': len(byid[q['source_id']]['text']),
                      'question_links_removed': body[i] != q['text'] + '\n' + byid[q['source_id']]['text'],
                      'gold_numeric_id_mentions': [g for g in q['gold'] if re.search(r'(?<!\d)' + re.escape(g.split(':')[-1]) + r'(?!\d)', body[i])]} for i,q in enumerate(en)]})
    for field in ['title_body', 'title']:
        model = ev.BM25([d['title'] + '\n' + d['text'] if field == 'title_body' else d['title'] for d in docs])
        for query_field, texts in [('title', [q['text'] for q in en]), ('body', body)]:
            result = measure('bm25-' + field + '-' + query_field, en, (model.scores(t) for t in texts), ids)
            if field == 'title_body' and query_field == 'title':
                assert all(r['top100'] == ranks['bm25'][r['query_id']] for r in result['rows'])
        del model
        gc.collect()


def gpu():
    from vector_model_candidates import Candidate, TASK
    import torch
    docs, dev, en, ko, ranks = inputs()
    ids = [d['_id'] for d in docs]
    ix = {d: i for i,d in enumerate(ids)}
    byid = {d['_id']: d for d in docs}
    qi = {q['id']: len(docs)+i for i,q in enumerate(dev+en+ko)}
    cached = np.load(OLD / 'cache/full/qwen-head.npy', mmap_mode='r')
    plan = read(OUT / 'plan.json')
    model = Candidate('qwen', 'float32')
    started = time.monotonic()
    def encode(texts, query=False, max_length=256):
        out = []
        for offset in range(0, len(texts), 2):
            out.extend(model.embed(texts[offset:offset+2], query=query, max_length=max_length))
            if offset % 256 == 0:
                print(json.dumps({'stage': 'encoding', 'items_done': offset+len(texts[offset:offset+2]), 'total': len(texts), 'max_length': max_length}), flush=True)
        return np.asarray(out)
    try:
        title = [q['text'] for q in en]
        body = [clean_query(q['text'] + '\n' + byid[q['source_id']]['text']) for q in en]
        titlevec = encode(title, query=True)
        oldq = np.asarray(cached[[qi[q['id']] for q in en]])
        similarities = np.sum(titlevec * oldq, axis=1)
        assert similarities.min() > .9999
        save('fresh-encoding-check.json', {'queries': len(en), 'minimum_cosine_with_cache': float(similarities.min()),
              'max_abs_difference': float(np.max(np.abs(titlevec-oldq))), 'model': 'qwen', 'precision': 'float32'})
        for name, vectors in [('qwen-title-cached', oldq), ('qwen-title-fresh', titlevec),
                              ('qwen-body256', encode(body, query=True)),
                              ('qwen-body512', encode(body, query=True, max_length=512)),
                              ('qwen-title-no-instruction', encode(title, query=False))]:
            measure(name, en, vectors @ np.asarray(cached[:len(docs)]).T, ids)
        counts = [{'query_id': q['id'], 'title_query_tokens': len(model.tokenizer.encode('Instruct: '+TASK+'\nQuery: '+q['text'])),
                   'body_query_tokens': len(model.tokenizer.encode('Instruct: '+TASK+'\nQuery: '+b)),
                   'gold_document_tokens': {g: len(model.tokenizer.encode(byid[g]['title']+'\n'+byid[g]['text'])) for g in q['gold']}} for q,b in zip(en,body)]
        save('token-coverage.json', counts)
        probes = plan['controls']['document_probe_candidates']
        dids = sorted(set().union(*map(set, probes.values())))
        di = {d:i for i,d in enumerate(dids)}
        texts = [byid[d]['title']+'\n'+byid[d]['text'] for d in dids]
        representations = {'cached_head256': np.asarray(cached[[ix[d] for d in dids]]),
                           'fresh_head256': encode(texts), 'title256': encode([byid[d]['title'] for d in dids]),
                           'head512': encode(texts, max_length=512)}
        chunk_ids, chunks = [], []
        for d,t in zip(dids,texts):
            tokens = model.tokenizer.encode(t, add_special_tokens=False)
            for start in range(0, len(tokens), 192):
                chunk_ids.append(d)
                chunks.append(model.tokenizer.decode(tokens[start:start+256], skip_special_tokens=True))
                if start+256 >= len(tokens):
                    break
        print(json.dumps({'stage': 'full-chunks', 'documents': len(dids), 'chunks': len(chunks)}), flush=True)
        chunkvec = encode(chunks)
        records = []
        enmap = {q['id']:q for q in en}
        for qid, pool in probes.items():
            q = enmap[qid]
            qvec = oldq[[x['id'] for x in en].index(qid)]
            variants = {}
            for name, vec in representations.items():
                variants[name] = {d: float(vec[di[d]] @ qvec) for d in pool}
            variants['all_chunks_max'] = {d: -1.0 for d in pool}
            for d,s in zip(chunk_ids,chunkvec @ qvec):
                if d in variants['all_chunks_max']:
                    variants['all_chunks_max'][d] = max(variants['all_chunks_max'][d],float(s))
            for name,scores in variants.items():
                order = sorted(pool,key=lambda d:(-scores[d],d))
                positives = [scores[d] for d in q['gold']]
                negatives = [scores[d] for d in pool if d not in q['gold']]
                records.append({'query_id': qid,'representation':name,'candidate_count':len(pool),
                    'best_gold_rank':min(order.index(g)+1 for g in q['gold']),
                    'gold_margin':max(positives)-max(negatives), 'order':order,'scores':scores,
                    'metrics':ev.metrics(order,set(q['gold']))})
        save('document-probe.json', {'scope':'Post-test gold-injected fixed candidate discrimination; NOT full-corpus retrieval accuracy. All chunks use max score; more chunks can also increase false positives.',
             'queries':len(probes),'documents':len(dids),'chunks':len(chunks),'rows':records,
             'summary':{name:{'gold_first':sum(x['best_gold_rank']==1 for x in records if x['representation']==name),
                  'mean_gold_margin':float(np.mean([x['gold_margin'] for x in records if x['representation']==name])),
                  'mean_ndcg10':float(np.mean([x['metrics']['nDCG@10'] for x in records if x['representation']==name]))} for name in list(representations)+['all_chunks_max']}})
        save('gpu-execution.json', {'status':'complete','elapsed_seconds':time.monotonic()-started,
             'peak_allocated_mib':torch.cuda.max_memory_allocated()/1024**2,'paid_api_calls':0,
             'runner_sha256':sha(Path(__file__))})
    finally:
        model.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage',choices=['prepare','cpu','gpu'])
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare()
    else:
        plan = read(OUT / 'plan.json')
        for name,digest in plan['input_sha256'].items():
            if name == str(Path(__file__).resolve().relative_to(ROOT)) and sha(ROOT/name) != digest:
                revision = read(OUT/'runner-revision.json')
                assert sha(OUT/'runner-initial.py') == digest == revision['initial_sha256']
                assert sha(ROOT/name) == revision['current_sha256']
            else:
                assert sha(ROOT/name)==digest, name
        globals()[args.stage]()
