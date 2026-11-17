"""Sequential, opt-in model comparison with frozen artifact hashes and durable logs."""
import argparse,datetime,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wait-for',type=Path)
    ap.add_argument('--arms',default='production,pi,pi_plus,compact_plus')
    ap.add_argument('--phase',choices=['dev','test','all'],default='all')
    args=ap.parse_args()
    if args.wait_for:
        deadline=time.monotonic()+7200
        while not (args.wait_for.exists() and 'COMPARISON_COMPLETE ' in args.wait_for.read_text()):
            if time.monotonic()>deadline:raise RuntimeError('Prior comparison did not finish; refusing concurrent model load')
            time.sleep(10)
    folder=ROOT/'build/eval'/('campaign-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    artifacts={}
    paths=list((ROOT/'eval/v4').rglob('*'))+list((ROOT/'src/main').rglob('*'))+list((ROOT/'src/test/java/io/ohgnoy/monitoring/eval').glob('*.java'))
    paths += [ROOT/'scripts'/name for name in ['numeric_fixture.py','pi_eval_extension.ts','score_harness_comparison.py','build_eval_v4.py','validate_eval_v4.py','categorical_gold_contract.py']]
    for p in paths:
        if p.is_file():artifacts[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    model=os.environ.get('EVAL_MODEL','qwen3.5:9b-pi32k')
    endpoint=os.environ.get('EVAL_BASE_URL','http://127.0.0.1:11434')
    with urllib.request.urlopen(endpoint+'/api/tags',timeout=15) as r:
        selected=[m for m in json.load(r)['models'] if m['name']==model]
    if len(selected)!=1:raise RuntimeError('Requested model identity not found')
    request=urllib.request.Request(endpoint+'/api/show',data=json.dumps({'model':model}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as r: model_parameters=json.load(r).get('parameters','')
    manifest={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'artifacts':artifacts,
              'model':selected[0],'pi_version':subprocess.check_output(['pi','--version'],text=True).strip(),
              'model_parameters':model_parameters,'prometheus_image_id':subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','prom/prometheus:v2.53.0'],text=True).strip(),
              'observation_clock':'fixture logical time; timeout clock remains real UTC',
              'protocol':'Development confirmation followed by family-held-out test; single repeat; serial model requests; native and common-tool comparisons reported separately',
              'development_change':'All arms use corrected raw PromQL summaries; enhanced arms add filename-scoped logs matching live Loki labels; remove artificial log name prefixes; read-only candidate bypasses conversation approval-word filtering; no per-case prompt tuning',
              'runs':[]}
    def save():(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    save()
    phases=[('dev','pi_plus,compact_plus'),('test',args.arms)]
    for split,arms in phases:
        if args.phase!='all' and args.phase!=split:continue
        for rel,digest in artifacts.items():
            if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:raise RuntimeError('Frozen artifact changed: '+rel)
        env=os.environ.copy();env.update(RUN_HARNESS_COMPARISON='1',EVAL_SPLIT=split,COMPARE_ARMS=arms,EVAL_REPEATS='1')
        env['PYTHONPATH']=str(ROOT/'.venv-eval/lib/python3.12/site-packages')
        log=folder/(split+'.log');print('START',split,folder,flush=True)
        with log.open('w') as out:
            result=subprocess.run(['./gradlew','evalRun','--tests','*HarnessComparisonRunner','--no-daemon','--console=plain'],cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError('Comparison failed; inspect '+str(log))
        for rel,digest in artifacts.items():
            if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:raise RuntimeError('Artifact changed during comparison; result excluded: '+rel)
        marker='COMPARISON_COMPLETE '
        target=Path(next(line.split(marker,1)[1].strip() for line in log.read_text().splitlines() if marker in line))
        subprocess.run(['python3','scripts/score_harness_comparison.py',str(target)],cwd=ROOT,check=True)
        manifest['runs'].append({'split':split,'arms':arms,'path':str(target)});save()
    manifest['completed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print('CAMPAIGN_COMPLETE',folder,flush=True)
if __name__=='__main__':main()
