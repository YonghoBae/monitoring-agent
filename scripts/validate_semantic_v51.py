"""Fresh independent full-question validation; all attempts and costs retained."""
import hashlib,json,shutil,sys
from pathlib import Path
import haiku_rejudge as api
import budget_registry as budget
from semantic_judge_v51 import SYSTEM,validate
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'eval/v5/semantic-validation-v51';hp=ROOT/'eval/v5/semantic-holdout-v51.json'
    if out.exists():raise ValueError('No overwrite or silent retry')
    controls=api.read(hp)['cases']
    if len(controls)!=20:raise ValueError('Exactly 20 pre-frozen independent controls required')
    prior=budget.preflight(ROOT,out);out.mkdir();(out/'raw').mkdir()
    api.save(out/'manifest.json',{'purpose':'new full-question semantic validation before comparison grading',
        'repeats':3,'cases':20,'gate':'All pass/unsupported/complete/correct labels agree in all60judgments',
        'prior_campaign_cost_usd':prior['prior_campaign_cost_usd'],'budget_usd_including_prior':2,
        'holdout_sha256':api.sha(hp.read_bytes()),'system_sha256':api.sha(SYSTEM.encode()),
        'judge_code_sha256':api.sha((ROOT/'scripts/semantic_judge_v51.py').read_bytes()),
        'runner_sha256':api.sha(Path(__file__).read_bytes()),'no_tuning_on_holdout':True})
    (out/'system.txt').write_text(SYSTEM)
    for name in ('semantic_judge_v51.py','validate_semantic_v51.py','budget_registry.py','haiku_rejudge.py'):
        shutil.copy2(ROOT/'scripts'/name,out/name)
    key=api.key_from_env(ROOT/'.env');rows=[]
    for rep in range(3):
        for case in controls:
            ident=f"{case['id']}-r{rep}";payload=case['payload']
            raw=budget.paid_call(api,ROOT,out,ident,payload,key,'validation',SYSTEM)
            try:
                result=validate(api.response_json(raw),payload)
                mismatch=[k for k in ('pass','unsupported_claims','complete_answer','answer_correct') if result[k]!=case['expected'][k]]
                row={'id':case['id'],'rep':rep,'result':result,'expected':case['expected'],'mismatches':mismatch,
                     'status_agrees':result['answer_status']==case['expected']['answer_status']}
            except Exception as e:row={'id':case['id'],'rep':rep,'error':str(e),'mismatches':['format']}
            rows.append(row);api.append(out/'results.jsonl',row);print(ident,'PASS' if not row['mismatches'] else 'FAIL '+','.join(row['mismatches']),flush=True)
    result={'gate_passed':all(not row['mismatches'] for row in rows),'judgments':len(rows),'cases':20,'repeats':3,
            'failed':[{'id':r['id'],'rep':r['rep'],'mismatches':r['mismatches']} for r in rows if r['mismatches']],
            'descriptive_status_agreement':sum(r.get('status_agrees',False) for r in rows),'cost':budget.preflight(ROOT,out)}
    api.save(out/'summary.json',result);print(json.dumps(result),flush=True)
    if not result['gate_passed']:sys.exit(2)
if __name__=='__main__':main()
