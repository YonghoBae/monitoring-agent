"""Prepare fixed completed rows for independent AI review, without arm or judge labels."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,required=True);ap.add_argument('--count',type=int,required=True);ap.add_argument('--batch',required=True);args=ap.parse_args()
    base=ROOT/'eval/v5';campaign=base/'comparison-2';frozen=campaign/'frozen-inputs'
    scenes={s['id']:s for s in read(frozen/'eval/v5/dataset.json')['scenarios']};gold=read(frozen/'eval/v5/gold.json')
    candidates=sorted((ROOT/'build/eval').glob('comparison-*'),key=lambda p:int(p.name.split('-')[-1]),reverse=True)
    source=next(p for p in candidates if (p/'dataset.json').exists() and (p/'dataset.json').read_bytes()==(frozen/'eval/v5/dataset.json').read_bytes())
    rows=[json.loads(s) for s in (source/'results.jsonl').read_text().splitlines()]
    if len(rows)<args.start+args.count:raise ValueError('Batch not yet complete')
    out=base/'independent-answer-review';out.mkdir(exist_ok=True)
    packet=[];mapping=[]
    for row in rows[args.start:args.start+args.count]:
        ident='sample-'+hashlib.sha256((row['id']+'|'+row['arm']+'|'+str(row['rep'])).encode()).hexdigest()[:12]
        scene=scenes[row['id']]
        payload={'question':scene['question']+'\nRequested fields: '+json.dumps(scene['answer_fields'],ensure_ascii=False),
                 'answer':row['answer'],'reference':gold[row['id']]['reference'],'observations':row['trace']['observations']}
        packet.append({'id':ident,'payload':payload})
        mapping.append({'id':ident,'case':row['id'],'arm':row['arm'],'rep':row['rep'],'source':str(source)})
    target=out/(args.batch+'.json')
    if target.exists():raise ValueError('Do not overwrite review packet')
    target.write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
    (out/(args.batch+'-mapping-private.json')).write_text(json.dumps(mapping,indent=2)+'\n')
    print('Prepared',len(packet),'arm-blinded answers:',target)
if __name__=='__main__':main()
