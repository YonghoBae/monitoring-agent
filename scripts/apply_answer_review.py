"""Apply explicit reviewer annotations; reject missing fields and non-verbatim quotes."""
import hashlib,json,math,re
from pathlib import Path

def validate_normalization(item):
    normalization=item.get('normalization')
    if not normalization:return
    factors={('GiB','GB'):2**30/1e9,('MiB','GB'):2**20/1e9,('bytes','GB'):1e-9}
    factor=factors[(normalization['from'],normalization['to'])]
    known_bytes={'container_memory_rss','node_filesystem_avail_bytes','node_memory_MemAvailable_bytes'}
    metric=normalization.get('metric')
    assert normalization['from'] in item['quote'] or (normalization['from']=='bytes' and metric in known_bytes and metric in item['quote'])
    numbers=re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?',item['quote'])
    assert any(float(n)==normalization['value'] for n in numbers)
    assert math.isclose(item['value'],normalization['value']*factor,rel_tol=1e-12,abs_tol=1e-12)

def apply(run, annotations):
    run=Path(run);path=run/'answer-review.json';review=json.loads(path.read_text())
    entries={(r['id'],r['arm'],r['rep']):r for r in review['rows']}
    answers={(r['id'],r['arm'],r['rep']):r for r in map(json.loads,(run/'results.jsonl').read_text().splitlines())}
    for annotation in annotations:
        key=(annotation['id'],annotation['arm'],annotation.get('rep',0));entry=entries[key];answer=answers[key]['answer']
        assert entry['answer_sha256']==hashlib.sha256(answer.encode()).hexdigest()
        for field,value in annotation.get('fields',{}).items():
            assert field in entry['fields']
            assert value['value'] is None or (value['quote'] and value['quote'] in answer),(key,field,'invalid quote')
            validate_normalization(value)
            entry['fields'][field]=dict(value,method='unanswered_after_review' if value['value'] is None else 'quote_backed_prose_review')
        assert all(v['method']!='pending_prose_review' for v in entry['fields'].values()),(key,'fields still pending')
        for claim in annotation.get('unsupported_claims',[]):assert claim['quote'] in answer and claim['quote'] and claim['reason']
        observations={o['id']:o for o in answers[key]['trace']['observations']}
        for field,evidence in annotation.get('evidence_overrides',{}).items():
            assert field in entry['fields'] and evidence['reason']
            assert all(i in observations for i in evidence.get('observation_ids',[]))
            if evidence['supported']:assert evidence['observation_ids']
        entry['evidence_overrides']=annotation.get('evidence_overrides',{})
        entry['unsupported_claims']=annotation.get('unsupported_claims',[]);entry['causal_claims_reviewed']=True
    path.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
    return {'updated':len(annotations),'reviewed':sum(r['causal_claims_reviewed'] for r in review['rows']),'total':len(review['rows'])}
