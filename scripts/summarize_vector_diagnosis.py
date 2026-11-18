#!/usr/bin/env python3
"""CPU-only replay of post-test diagnostic rankings and paired effects."""
import json
import re
from pathlib import Path
import numpy as np
import ir_measures
from ir_measures import nDCG, Success
from diagnose_vector_retrieval import inputs, OUT, read, save
from retrieval_uncertainty import relevance_clusters, paired_cluster_interval


def summarize():
    docs, dev, en, ko, _ = inputs()
    byid = {d['_id']:d for d in docs}
    qmap = {q['id']:q for q in en}
    methods = {}
    checks = 0
    for p in sorted(OUT.glob('*.json')):
        d = read(p)
        if not isinstance(d,dict) or not {'name','rows','summary','queries'} <= d.keys():
            continue
        assert len(d['rows']) == len(en)
        for r in d['rows']:
            q = qmap[r['query_id']]
            order = r['top100']
            assert len(order)==len(set(order))==100 and q['source_id'] not in order
            qr = [ir_measures.Qrel(q['id'],g,1) for g in q['gold']]
            run = [ir_measures.ScoredDoc(q['id'],doc,float(100-i)) for i,doc in enumerate(order)]
            ext = ir_measures.calc_aggregate([nDCG@10,Success@1,Success@5],qr,run)
            for key, metric in [('nDCG@10',nDCG@10),('Hit@1',Success@1),('Hit@5',Success@5)]:
                assert abs(r['metrics'][key]-ext[metric])<1e-9
                checks+=1
        for k,v in d['summary'].items():
            assert abs(v-np.mean([r['metrics'][k] for r in d['rows']]))<1e-9
        methods[d['name']] = d
    comparisons = [
        ('qwen-body256','qwen-title-cached'),('qwen-body512','qwen-body256'),
        ('qwen-title-no-instruction','qwen-title-cached'),('minilm-body-fresh','minilm-title-fresh'),
        ('qwen-body256','minilm-body-fresh'),('qwen-body512','minilm-body-fresh'),
        ('bm25-title_body-body','bm25-title_body-title'),('bm25-title-title','bm25-title_body-title'),
        ('minilm-pool5000','minilm-title-fresh'),('qwen-pool5000','qwen-title-cached'),
    ]
    clusters = relevance_clusters(en)
    effects = []
    for a,b in comparisons:
        if a not in methods or b not in methods:
            continue
        aa = {r['query_id']:r['metrics'] for r in methods[a]['rows']}
        bb = {r['query_id']:r['metrics'] for r in methods[b]['rows']}
        deltas = {q:aa[q]['nDCG@10']-bb[q]['nDCG@10'] for q in aa}
        effects.append({'comparison':a+' minus '+b,**paired_cluster_interval(deltas,clusters),
              'ndcg_improved_queries':sum(v>1e-9 for v in deltas.values()),
              'ndcg_worsened_queries':sum(v< -1e-9 for v in deltas.values()),
              'hit5_gains':sum(aa[q]['Hit@5']>bb[q]['Hit@5'] for q in aa),
              'hit5_losses':sum(aa[q]['Hit@5']<bb[q]['Hit@5'] for q in aa)})
    # Conservative sensitivity only: matching an error-message gold title is not
    # proof of leakage; ordinary diagnostic error text may legitimately match.
    flags = []
    for q in en:
        text = byid[q['source_id']]['text']
        titles = [g for g in q['gold'] if byid[g]['title'].casefold() in text.casefold()]
        if titles:
            flags.append({'query_id':q['id'],'gold_title_matches':titles})
    excluded = {q['query_id'] for q in flags}
    sensitivity = {}
    for name,d in methods.items():
        kept = [r for r in d['rows'] if r['query_id'] not in excluded]
        sensitivity[name] = {'queries':len(kept),'ndcg10':float(np.mean([r['metrics']['nDCG@10'] for r in kept])),
                             'hit5':sum(int(r['metrics']['Hit@5']) for r in kept)}
    summary = {'scope':'Post-test explanatory comparisons. CIs are descriptive paired cluster intervals, not confirmatory tests or independent model ranking. No correction for multiple exploratory comparisons.',
       'methods':{name:{'queries':d['queries'],**d['summary'],'hit5_count':sum(int(r['metrics']['Hit@5']) for r in d['rows'])} for name,d in methods.items()},
       'effects':effects,'query_body_exact_gold_title_flags':flags,
       'sensitivity_excluding_title_matches':sensitivity,
       'sensitivity_scope':'Exclude four exact target-title matches, including a common apt error message. This is a conservative sensitivity, not an accusation of leakage; revisions and answer clues are not comprehensively ruled out.',
       'independent_metric_checks':checks,'paid_api_calls':0}
    save('summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k in ['methods','effects','independent_metric_checks']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    summarize()
