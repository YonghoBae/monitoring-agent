"""Freeze and run the preregistered 48-answer v5 comparison, without scoring."""
import datetime,hashlib,json,os,shutil,subprocess,urllib.request
from pathlib import Path
from score_eval_v5 import SCORING_INPUTS, validate_grid
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
    out=ROOT/'eval/v5/comparison-2'
    if out.exists():raise RuntimeError('New output directory required; preserve all prior attempts')
    out.mkdir();frozen=out/'frozen-inputs';frozen.mkdir()
    paths=list((ROOT/'src/main').rglob('*'))+list((ROOT/'src/test/java/io/ohgnoy/monitoring/eval').glob('*.java'))
    paths += [ROOT/p for p in ['eval/v5/dataset.json','eval/v5/gold.json','eval/v5/provenance.json','docs/EVAL-V5-PROTOCOL.md','build.gradle','scripts/numeric_fixture.py','scripts/build_eval_v5.py','scripts/pi_eval_extension.ts','scripts/run_eval_v5.py','scripts/score_eval_v5.py','scripts/semantic_judge_v5.py','scripts/numeric_contract.py',*SCORING_INPUTS]]
    paths += list((ROOT/'eval/v5/sources').rglob('*'))
    hashes={}
    for path in paths:
        if not path.is_file():continue
        rel=path.relative_to(ROOT);hashes[str(rel)]=digest(path);target=frozen/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    endpoint=os.environ.get('EVAL_BASE_URL','http://127.0.0.1:11434');model=os.environ.get('EVAL_MODEL','qwen3.5:9b-pi32k')
    def get(path):
        with urllib.request.urlopen(endpoint+path,timeout=20) as r:return json.load(r)
    selected=[m for m in get('/api/tags')['models'] if m['name']==model]
    if len(selected)!=1:raise RuntimeError('Model identity missing')
    manifest={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'model':selected[0],
              'endpoint':endpoint,'loaded_models_before':get('/api/ps'),'pi_version':subprocess.check_output(['pi','--version'],text=True).strip(),
              'arms':['pi_plus','compact_plus'],'repeats':3,'expected_answers':48,'frozen_hashes':hashes,
              'protocol_sha256':digest(ROOT/'docs/EVAL-V5-PROTOCOL.md'),'status':'running'}
    save(out/'manifest.json',manifest)
    env=os.environ.copy();env.update(RUN_HARNESS_COMPARISON='1',EVAL_DATASET='eval/v5/dataset.json',EVAL_SPLIT='test',COMPARE_ARMS='pi_plus,compact_plus',EVAL_REPEATS='3',EVAL_ONLY='')
    env['PYTHONPATH']=str(ROOT/'.venv-eval/lib/python3.12/site-packages')
    print('START',out,flush=True)
    with (out/'run.log').open('w') as log:
        result=subprocess.run(['./gradlew','evalRun','--tests','*HarnessComparisonRunner','--no-daemon','--console=plain'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    changed=[p for p,h in hashes.items() if digest(ROOT/p)!=h]
    manifest.update(exit_code=result.returncode,changed_inputs=changed,loaded_models_after=get('/api/ps'))
    lines=(out/'run.log').read_text().splitlines();marker='COMPARISON_COMPLETE '
    target=next((Path(s.split(marker,1)[1].strip()) for s in lines if marker in s),None)
    if target:
        shutil.copytree(target,out/'raw-comparison');manifest['raw_source']=str(target)
        rows=[json.loads(s) for s in (target/'results.jsonl').read_text().splitlines()]
        manifest['answers']=len(rows);manifest['runner_errors']=sum(bool(r['error']) for r in rows)
        try:
            validate_grid(rows,json.loads((frozen/'eval/v5/dataset.json').read_text()))
            manifest['grid_valid']=True
        except (ValueError,KeyError,TypeError) as error:
            manifest['grid_valid']=False;manifest['grid_error']=str(error)
    manifest['status']='completed' if result.returncode==0 and not changed and manifest.get('grid_valid') is True else 'invalid_or_incomplete'
    manifest['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save(out/'manifest.json',manifest)
    print(manifest['status'],manifest.get('answers'), 'answers',flush=True)
    if manifest['status']!='completed':raise SystemExit(1)
if __name__=='__main__':main()
