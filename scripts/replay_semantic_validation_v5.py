"""Recheck frozen paid responses under stricter structural parser, without paid calls."""
import hashlib,json
from pathlib import Path
from semantic_judge_v5 import SYSTEM,validate
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'eval/v5/semantic-validation-1'
    controls={c['id']:c for c in json.loads((ROOT/'eval/v5/semantic-holdout.json').read_text())['cases']}
    rows=[json.loads(s) for s in (out/'results.jsonl').read_text().splitlines()]
    failures=[]
    for row in rows:
        try:validate(row['result'],controls[row['id']]['payload'])
        except Exception as e:failures.append({'id':row['id'],'rep':row['rep'],'error':str(e)})
    assert hashlib.sha256(SYSTEM.encode()).hexdigest()==json.loads((out/'manifest.json').read_text())['system_sha256']
    result={'method':'offline structural revalidation of every frozen response; no semantic prompt or decisions changed',
            'original_judgments':len(rows),'failures':failures,'passed':not failures,
            'current_judge_sha256':hashlib.sha256((ROOT/'scripts/semantic_judge_v5.py').read_bytes()).hexdigest(),
            'additional_paid_calls':0}
    (out/'structural-amendment.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if failures:raise SystemExit(1)
if __name__=='__main__':main()
