"""Run pre-frozen independent controls once per planned repeat; retain all failures."""
import argparse, hashlib, json, sys
from pathlib import Path
import haiku_rejudge as api
from semantic_judge_v5 import SYSTEM, validate

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--repeats',type=int,default=3)
    args=p.parse_args();out=args.out
    if out.exists(): raise ValueError('Output must be new; no silent retry/resume')
    out.mkdir(parents=True);(out/'raw').mkdir()
    hp=ROOT/'eval/v5/semantic-holdout.json'
    manifest={'purpose':'independent semantic validation, before agent answer scoring','repeats':args.repeats,
              'gate':'All 20 pass/unsupported labels must match in all repeats. answer_status audited separately.',
              'prior_campaign_cost_usd':0.0386223,'budget_usd_including_prior':2,
              'holdout_sha256':api.sha(hp.read_bytes()),'system_sha256':api.sha(SYSTEM.encode()),
              'judge_code_sha256':api.sha((ROOT/'scripts/semantic_judge_v5.py').read_bytes()),
              'no_tuning_on_holdout':True}
    api.save(out/'manifest.json',manifest);(out/'system.txt').write_text(SYSTEM)
    controls=json.loads(hp.read_text())['cases'];key=api.key_from_env(ROOT/'.env');results=[]
    for rep in range(args.repeats):
        for case in controls:
            ident=f"{case['id']}-r{rep}";payload=case['payload']
            raw=api.call(out,ident,payload,key,'validation',system=SYSTEM)
            try:
                result=validate(api.response_json(raw),payload)
                mismatches=[k for k in ('pass','unsupported_claims') if result[k]!=case['expected'][k]]
                row={'id':case['id'],'rep':rep,'result':result,'expected':case['expected'],'mismatches':mismatches,
                     'status_agrees':result['answer_status']==case['expected']['answer_status']}
            except Exception as e:
                row={'id':case['id'],'rep':rep,'error':str(e),'mismatches':['format']}
            results.append(row);api.append(out/'results.jsonl',row)
            print(ident, 'PASS' if not row['mismatches'] else 'FAIL '+','.join(row['mismatches']),flush=True)
    summary={'gate_passed':all(not r['mismatches'] for r in results),'judgments':len(results),
             'failed':[{'id':r['id'],'rep':r['rep'],'mismatches':r['mismatches']} for r in results if r['mismatches']],
             'cost':api.cost_state(out)}
    api.save(out/'summary.json',summary);print(json.dumps(summary),flush=True)
    if not summary['gate_passed']:sys.exit(2)

if __name__=='__main__':main()
