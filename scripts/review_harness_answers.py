"""Score model-assisted, quote-backed field extraction separately from JSON compliance.

The extraction file must contain every answer and every requested field. This is
an auditable semantic review, not an independent human judgement or a new run.
"""
import argparse,collections,hashlib,json
from pathlib import Path
from score_harness_comparison import score
from apply_answer_review import validate_normalization

def exclude_invalid_gold(scene, exclusions):
    excluded=exclusions.get(scene['id'],{})
    assert set(excluded).issubset({g['key'] for g in scene['gold']})
    assert all(isinstance(reason,str) and reason for reason in excluded.values())
    gold=[g for g in scene['gold'] if g['key'] not in excluded]
    assert gold,'Cannot silently remove an entire case'
    return dict(scene,gold=gold),excluded

def validate_evidence_override(value,evidence,observations):
    if not evidence['supported']:return
    assert evidence['observation_ids']
    allowed={'ok','unavailable'} if value=='unknown' else {'ok'}
    absence=evidence.get('scope')=='absence_of_verification'
    if absence:
        assert value in ('no','unknown'),'Absence can support lack of verification, not a positive state'
        allowed.update(['empty','unavailable'])
    for identity in evidence['observation_ids']:
        observation=observations[identity]
        assert observation['status'] in allowed
        assert (absence and observation['status']=='empty') or observation.get('data') not in [None,[],{}]

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);ap.add_argument('review',type=Path);ap.add_argument('--exclusions',type=Path);args=ap.parse_args()
    scenes={s['id']:s for s in json.loads((args.run/'dataset.json').read_text())['scenarios']}
    rows=[json.loads(l) for l in (args.run/'results.jsonl').read_text().splitlines()]
    exclusions={}
    if args.exclusions:
        exclusions=json.loads(args.exclusions.read_text())
        assert exclusions['dataset_sha256']==hashlib.sha256((args.run/'dataset.json').read_bytes()).hexdigest()
        assert set(exclusions['fields']).issubset(scenes)
    review=json.loads(args.review.read_text());assert review['reviewer'] and review['human_validated'] is False
    entries={(r['id'],r['arm'],r['rep']):r for r in review['rows']}
    assert len(entries)==len(rows),'Review must cover all outputs, including failures'
    scored=[]
    for row in rows:
        entry=entries[(row['id'],row['arm'],row['rep'])];fields=entry['fields'];scene=scenes[row['id']]
        assert entry['answer_sha256']==hashlib.sha256(row['answer'].encode()).hexdigest(),'Reviewed answer changed'
        assert entry.get('causal_claims_reviewed') is True,(row['id'],row['arm'],'causal claim review incomplete')
        for claim in entry.get('unsupported_claims',[]):
            assert claim['quote'] and claim['quote'] in row['answer'] and claim['reason'],(row['id'],row['arm'],'invalid unsupported-claim quote')
        assert set(fields)=={g['key'] for g in scene['gold']}
        extracted={}
        for key,item in fields.items():
            assert item.get('method')!='pending_prose_review',(row['id'],row['arm'],key,'review incomplete')
            validate_normalization(item)
            if item['value'] is not None:
                assert item['quote'] and item['quote'] in row['answer'],(row['id'],row['arm'],key,'quote absent from answer')
                extracted[key]=item['value']
            else:assert not item.get('quote'),'Unanswered field must not have a fabricated quote'
        rewritten=dict(row,answer=json.dumps({'facts':extracted},ensure_ascii=False))
        scored_scene,excluded=exclude_invalid_gold(scene,exclusions.get('fields',{}))
        result=score(rewritten,scored_scene);result['strict_evidence_score']=result['score'];result['excluded_fields']=excluded
        result['output_contract_score_after_exclusions']=score(row,scored_scene)['score']
        observations={o['id']:o for o in row['trace']['observations']}
        for check in result['checks']:
            evidence=entry.get('evidence_overrides',{}).get(check['key'])
            if evidence is None:continue
            assert evidence['reason']
            validate_evidence_override(extracted.get(check['key']),evidence,observations)
            check['reached_related_evidence']=evidence['supported'];check['grounded_field']=check['correct_value'] and evidence['supported'];check['evidence_review']=evidence
        result['score']=100*sum(c['grounded_field'] for c in result['checks'])/len(result['checks'])
        result['schema_valid']=score(row,scene)['schema_valid'];result['unsupported_claims']=entry.get('unsupported_claims',[]);scored.append(result)
    groups=collections.defaultdict(list)
    for row in scored:groups[row['arm']].append(row)
    summary={arm:{'n':len(rs),'requested_value_score':sum(100*sum(c['correct_value'] for c in r['checks'])/len(r['checks']) for r in rs)/len(rs),'requested_content_field_score':sum(r['score'] for r in rs)/len(rs),'original_schema_valid':sum(r['schema_valid'] for r in rs),'answers_with_flagged_unsupported_claims':sum(bool(r['unsupported_claims']) for r in rs)} for arm,rs in groups.items()}
    report={'scope':'Quote-backed model-assisted content extraction, deterministic gold, reached-evidence checks and explicit observation-ID-backed semantic evidence overrides; not independent human validation or full-prose causal truth','reviewer':review['reviewer'],'human_validated':False,'gold_exclusions':exclusions,'summary':summary,'rows':scored}
    (args.run/'content-scores.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
