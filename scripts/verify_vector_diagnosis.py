#!/usr/bin/env python3
"""Verify public diagnostic numbers without raw posts, GPU, models or network."""
import hashlib
import json
from pathlib import Path
import numpy as np
import ir_measures
from ir_measures import nDCG, Success
from retrieval_uncertainty import relevance_clusters, paired_cluster_interval

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'eval/vector-v4-diagnosis'


def read(p):
    return json.loads(p.read_text())


def metrics(q,order,expected):
    qrels=[ir_measures.Qrel(q['id'],g,1) for g in q['gold']]
    run=[ir_measures.ScoredDoc(q['id'],d,float(len(order)-i)) for i,d in enumerate(order)]
    values=ir_measures.calc_aggregate([nDCG@10,Success@1,Success@5],qrels,run)
    for key,m in [('nDCG@10',nDCG@10),('Hit@1',Success@1),('Hit@5',Success@5)]:
        assert abs(values[m]-expected[key])<1e-9
    return 3


def main():
    original=read(ROOT/'eval/vector-v3-improvement/final/numeric-dataset.json')
    queries=[q for q in original['queries'] if q['group'] in ['askubuntu_en','serverfault_en','superuser_en']]
    qmap={q['id']:q for q in queries}
    assert len(qmap)==91
    summary=read(BASE/'summary.json')
    checked=0
    methods={}
    for name,expected in summary['methods'].items():
        value=read(BASE/(name+'.json'))
        assert {r['query_id'] for r in value['rows']}==set(qmap)
        for r in value['rows']:
            q=qmap[r['query_id']];order=r['top100']
            assert len(order)==len(set(order))==100 and q['source_id'] not in order
            assert set(order)<=set(original['candidate_ids'])
            checked+=metrics(q,order,r['metrics'])
        for key,number in value['summary'].items():
            assert abs(number-np.mean([r['metrics'][key] for r in value['rows']]))<1e-9
            assert abs(number-expected[key])<1e-9
        methods[name]={r['query_id']:r['metrics'] for r in value['rows']}
    assert checked==summary['independent_metric_checks']
    clusters=relevance_clusters(queries)
    for e in summary['effects']:
        a,b=e['comparison'].split(' minus ')
        delta={q:methods[a][q]['nDCG@10']-methods[b][q]['nDCG@10'] for q in qmap}
        got=paired_cluster_interval(delta,clusters)
        assert np.allclose(got['ci95'],e['ci95'],atol=1e-12) and abs(got['mean']-e['mean'])<1e-12
    plan=read(BASE/'plan.json')
    probe=read(BASE/'document-probe.json')
    for r in probe['rows']:
        q=qmap[r['query_id']];pool=plan['controls']['document_probe_candidates'][q['id']]
        assert set(r['order'])==set(pool) and set(q['gold'])<=set(pool)
        assert r['order']==sorted(pool,key=lambda d:(-r['scores'][d],d))
        assert r['best_gold_rank']==min(r['order'].index(g)+1 for g in q['gold'])
        checked+=metrics(q,r['order'],r['metrics'])
    for name,expected in probe['summary'].items():
        rows=[r for r in probe['rows'] if r['representation']==name]
        assert len(rows)==32 and sum(r['best_gold_rank']==1 for r in rows)==expected['gold_first']
        assert abs(np.mean([r['metrics']['nDCG@10'] for r in rows])-expected['mean_ndcg10'])<1e-9
    revision=read(BASE/'runner-revision.json')
    for path,key in [(BASE/'runner-initial.py','initial_sha256'),(ROOT/'scripts/diagnose_vector_retrieval.py','current_sha256')]:
        assert hashlib.sha256(path.read_bytes()).hexdigest()==revision[key]
    assert revision['initial_sha256']==plan['input_sha256']['scripts/diagnose_vector_retrieval.py']
    manifest=BASE/'artifact-sha256.json'
    if manifest.exists():
        for name,digest in read(manifest)['files'].items():
            assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    print(json.dumps({'status':'pass','full_corpus_and_pool_methods':len(methods),'queries':91,
         'fixed_document_probe_queries':32,'independent_metrics':checked,'gpu_required':False,'api_calls':0,
         'scope':'Numeric replay and artifact integrity; not independent label adjudication or inference replay.'},indent=2))


if __name__=='__main__':
    main()
