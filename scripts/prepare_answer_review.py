"""Prepare quote-backed structured extraction and a list of fields needing prose review."""
import argparse,hashlib,json,re
from pathlib import Path
from score_harness_comparison import facts

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);ap.add_argument('--append',action='store_true');args=ap.parse_args()
    path=args.run/'answer-review.json';existing={}
    if path.exists():
        if not args.append:raise RuntimeError('Refusing to overwrite existing review')
        existing={(r['id'],r['arm'],r['rep']):r for r in json.loads(path.read_text())['rows']}
    scenes={s['id']:s for s in json.loads((args.run/'dataset.json').read_text())['scenarios']}
    reviews=[];pending=[]
    for line in (args.run/'results.jsonl').read_text().splitlines():
        row=json.loads(line);identity=(row['id'],row['arm'],row['rep']);digest=hashlib.sha256(row['answer'].encode()).hexdigest()
        if identity in existing:
            entry=existing[identity];assert entry['answer_sha256']==digest;reviews.append(entry)
            pending.extend({'id':row['id'],'arm':row['arm'],'rep':row['rep'],'key':k} for k,v in entry['fields'].items() if v['method']=='pending_prose_review')
            continue
        extracted=facts(row['answer']);fields={}
        for gold in scenes[row['id']]['gold']:
            key=gold['key'];value=extracted.get(key);quote=''
            if value is not None:
                for m in re.finditer('"'+re.escape(key)+'"'+r'\s*:\s*',row['answer']):
                    try:
                        parsed,end=json.JSONDecoder().raw_decode(row['answer'][m.end():])
                        if parsed==value:quote=row['answer'][m.start():m.end()+end]
                    except ValueError:pass
            if not quote:
                value=None;pending.append({'id':row['id'],'arm':row['arm'],'rep':row['rep'],'key':key})
            fields[key]={'value':value,'quote':quote,'method':'structured' if quote else 'pending_prose_review'}
        reviews.append({'id':row['id'],'arm':row['arm'],'rep':row['rep'],'answer_sha256':digest,'fields':fields,'causal_claims_reviewed':False,'unsupported_claims':[]})
    output={'reviewer':'Codex: structured extraction plus explicit quote-backed prose review','human_validated':False,'rows':reviews}
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (args.run/'review-pending.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2)+'\n')
    print('Prepared',len(reviews),'answers;',len(pending),'fields require prose review')
if __name__=='__main__':main()
