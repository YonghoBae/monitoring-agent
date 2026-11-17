"""Deterministic requested-field accuracy plus reached evidence. Not a prose-quality judge."""
import argparse,collections,json,math,re
from pathlib import Path

def facts(answer):
    candidates=re.findall(r'```(?:json)?\s*(.*?)```',answer,re.S)
    candidates.append(answer)
    for text in reversed(candidates):
        try:
            data=json.loads(text.strip());value=data.get('facts')
            if isinstance(value,dict):return value
        except (ValueError,AttributeError):pass
    return {}

def score(row,scene):
    extracted=facts(row['answer']);observations=row['trace']['observations'];checks=[]
    for gold in scene['gold']:
        actual=extracted.get(gold['key']);expected=gold['value']
        if isinstance(expected,(int,float)):
            correct=isinstance(actual,(int,float)) and not isinstance(actual,bool) and math.isfinite(actual) and abs(actual-expected)<=gold['tolerance']
        else:correct=actual==expected
        # Evidence must have been reached successfully, not only named by the model.
        statuses={'ok','unavailable'} if expected=='unknown' else {'ok'}
        def reached_target(target):
            pattern=r'(?<![a-zA-Z0-9_:])'+re.escape(target)+r'(?![a-zA-Z0-9_:])'
            return any(o.get('status') in statuses and (o.get('source')==target or re.search(pattern,o.get('target',''))) and o.get('data') not in [None,[],{}] for o in observations)
        matches=[reached_target(t) for t in gold['evidence_targets']]
        reached=all(matches) if gold.get('evidence_all') else any(matches)
        checks.append({'key':gold['key'],'correct_value':correct,'reached_related_evidence':reached,'grounded_field':correct and reached})
    return {'id':row['id'],'arm':row['arm'],'rep':row['rep'],'error':row['error'],'checks':checks,'score':100*sum(c['grounded_field'] for c in checks)/len(checks),'schema_valid':bool(extracted),'empty_observations':not observations,'elapsedMs':row['elapsedMs']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    scenes={s['id']:s for s in json.loads((args.run/'dataset.json').read_text())['scenarios']}
    rows=[json.loads(l) for l in (args.run/'results.jsonl').read_text().splitlines()];scored=[score(r,scenes[r['id']]) for r in rows]
    groups=collections.defaultdict(list)
    for row in scored:groups[row['arm']].append(row)
    summary={arm:{'n':len(rs),'requested_field_score':sum(r['score'] for r in rs)/len(rs),'schema_valid':sum(r['schema_valid'] for r in rs),'empty_observations':sum(r['empty_observations'] for r in rs),'errors':sum(bool(r['error']) for r in rs),'mean_elapsed_ms':sum(r['elapsedMs'] for r in rs)/len(rs)} for arm,rs in groups.items()}
    report={'scope':'requested-field exact/numeric correctness with successful related observation; not root-cause prose validation or overall production accuracy','independent_human_validated':False,'summary':summary,'rows':scored}
    (args.run/'scores.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
