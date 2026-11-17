"""Filesystem-only check by default; explicit run --execute starts 48 answers.

Requires root-approved protocol and scorer freeze, exact already-loaded Qwen
identity, unchanged source provenance, and the independent v52 judge gate.
Never calls a judge, warms a model, registers approval, or retries a campaign.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import build_canonical_core_v5 as builder
import score_canonical_core_v5 as scorer

ROOT = Path(__file__).resolve().parents[1]
BASE_REL = 'eval/v5/canonical-core'
DATASET_REL = BASE_REL+'/dataset.json'
MODEL_DIGEST = '2872f35f2b99c438d19beb6cfaf7002a3150f04c0d850542ca52a554414c233f'
ARMS = ('pi_plus', 'compact_plus')
ORDER_POLICY = 'within-family-ordinal-plus-repeat-rotation-v1'
sha, read, save = builder.sha, builder.read, builder.save
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def local_path(rel):
    if not isinstance(rel, str) or Path(rel).is_absolute(): raise ValueError('Repository-relative artifact path required')
    path = (ROOT/rel).resolve()
    if not path.is_relative_to(ROOT.resolve()): raise ValueError('Artifact path leaves repository')
    return path
def order_plan(dataset):
    counts = Counter(); result = []
    for scene in dataset['scenarios']:
        ordinal = counts[scene['family']]; counts[scene['family']] += 1
        for rep in range(3):
            parity = (ordinal+rep) % 2
            for position, arm in enumerate(ARMS[parity:]+ARMS[:parity]):
                result.append({'id': scene['id'], 'family': scene['family'], 'arm': arm, 'rep': rep,
                               'position': position, 'family_ordinal': ordinal})
    first = [cell for cell in result if cell['position'] == 0]
    if len(result) != 48 or Counter(c['arm'] for c in first) != {'pi_plus': 12, 'compact_plus': 12}:
        raise ValueError('Expected balanced eight-case core')
    for family in counts:
        if Counter(c['arm'] for c in first if c['family'] == family) != {'pi_plus': 6, 'compact_plus': 6}:
            raise ValueError('Family order imbalance')
    for rep in range(3):
        if Counter(c['arm'] for c in first if c['rep'] == rep) != {'pi_plus': 4, 'compact_plus': 4}:
            raise ValueError('Repeat order imbalance')
    return {'policy': ORDER_POLICY, 'first_positions': {'pi_plus': 12, 'compact_plus': 12}, 'order': result}
def validate_grid(rows, dataset):
    scorer.validate_grid(rows, dataset)
    for row, cell in zip(rows, order_plan(dataset)['order']):
        if any(row.get(k) != cell[k] for k in ('id', 'family', 'arm', 'rep')):
            raise ValueError('Actual answer order differs from counterbalanced plan')
        if not isinstance(row.get('answer'), str) or not isinstance(row.get('error'), str):
            raise ValueError('Explicit answer and error strings required')
        if row.get('trace', {}).get('kind') != 'delivered_tool_results' or row['trace'].get('captureSupported') is not True:
            raise ValueError('Exact delivered tool responses required')
    return True
def preflight():
    base = ROOT/BASE_REL; dataset = read(ROOT/DATASET_REL); builder.verify(dataset)
    build = read(base/'build-manifest.json')
    identities = {'source_dataset_sha256': sha(ROOT/builder.SOURCE_REL),
        'approved_gold_sha256': sha(ROOT/builder.GOLD_REL), 'provenance_sha256': sha(ROOT/builder.PROVENANCE_REL),
        'built_dataset_sha256': sha(ROOT/DATASET_REL), 'builder_sha256': sha(ROOT/'scripts/build_canonical_core_v5.py')}
    if any(build.get(k) != v for k, v in identities.items()): raise ValueError('Build identity changed')
    validation = scorer.validation_gate()
    protocol = read(base/'protocol.json')
    required = {'status': 'approved', 'benchmark_kind': 'confirmatory_canonical_core', 'arms': list(ARMS),
        'repeats': 3, 'expected_answers': 48, 'case_ids': [s['id'] for s in dataset['scenarios']],
        'dataset_path': DATASET_REL, 'dataset_sha256': sha(ROOT/DATASET_REL),
        'gold_path': builder.GOLD_REL, 'gold_sha256': builder.GOLD_SHA, 'order_policy': ORDER_POLICY,
        'generation': {'temperature': 0, 'max_output_tokens': 1536, 'reasoning_effort': 'none'},
        'limits': {'uncached_tool_calls': 12, 'timeout_seconds': 90}}
    if any(protocol.get(k) != v for k, v in required.items()): raise ValueError('Canonical protocol absent, unapproved, or mismatched')
    model = protocol.get('model', {})
    if model.get('name') != 'qwen3.5:9b-pi32k' or model.get('digest') != MODEL_DIGEST or not model.get('base_url'):
        raise ValueError('Exact Qwen name, digest, and endpoint required')
    gate_spec = protocol['scoring_manifest']; gate_path = local_path(gate_spec['path'])
    if sha(gate_path) != gate_spec['sha256']: raise ValueError('Scorer freeze manifest changed')
    gate = read(gate_path); hashes = gate.get('frozen_hashes', {})
    if gate.get('status') != 'frozen' or gate.get('validation_hashes') != validation:
        raise ValueError('Reviewed scorer freeze with matching v52 validation required')
    required_scoring = set(scorer.SCORING_INPUTS) | {DATASET_REL, 'scripts/build_canonical_core_v5.py', 'scripts/run_canonical_core_v5.py'}
    if not required_scoring <= set(hashes): raise ValueError('Scorer freeze omits required canonical input')
    artifacts = [ROOT/DATASET_REL, base/'build-manifest.json', base/'protocol.json', gate_path,
        ROOT/builder.SOURCE_REL, ROOT/'eval/v5/gold.json', ROOT/builder.PROVENANCE_REL]
    for rel, expected in hashes.items():
        path = local_path(rel)
        if sha(path) != expected: raise ValueError('Frozen scoring input changed: '+rel)
        artifacts.append(path)
    for name in validation: artifacts.append(ROOT/scorer.VALIDATION_REL/name)
    # Read-only paid-campaign registration/budget gate; never an API request.
    cost = scorer.budget.preflight(ROOT, base/'scoring-1')
    return {'dataset': dataset, 'protocol': protocol, 'artifacts': artifacts, 'order_plan': order_plan(dataset),
        'validation_hashes': validation, 'cost_snapshot': cost}
def freeze_inputs(check, out):
    paths = list((ROOT/'src/main').rglob('*')) + list((ROOT/'src/test/java/io/ohgnoy/monitoring/eval').glob('*.java'))
    paths += check['artifacts'] + list((ROOT/'eval/v5/sources').rglob('*'))
    paths += [ROOT/p for p in ('build.gradle', 'settings.gradle', 'gradlew', 'gradle/wrapper/gradle-wrapper.properties',
        'scripts/numeric_fixture.py', 'scripts/eval_fixture.py', 'scripts/pi_eval_extension.ts', 'scripts/requirements-eval.txt')]
    hashes = {}
    for path in paths:
        if not path.is_file(): continue
        rel = str(path.resolve().relative_to(ROOT.resolve())); target = out/'frozen-inputs'/rel
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target); hashes[rel] = sha(target)
    return hashes
@contextmanager
def model_run_lock():
    path = ROOT/'build/eval/.canonical-model-run.lock'; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('Another canonical model run is active') from error
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)
def loaded_identity(tags, loaded, model):
    selected = [m for m in tags['models'] if m.get('name') == model['name'] and m.get('digest') == MODEL_DIGEST]
    if len(selected) != 1 or not any(m.get('name') == model['name'] and m.get('digest') == MODEL_DIGEST for m in loaded['models']):
        raise ValueError('Exact frozen model must already be loaded; no automatic warm-up')
    return selected[0]
def run(*, execute=False):
    if execute is not True: raise ValueError('Explicit run --execute required')
    check = preflight(); out = ROOT/BASE_REL/'comparison-1'
    if out.exists(): raise ValueError('Never overwrite or silently retry a campaign')
    model = check['protocol']['model']; endpoint = model['base_url'].rstrip('/')
    def metadata(path):
        with urllib.request.urlopen(endpoint+path, timeout=20) as response: return json.load(response)
    with model_run_lock():
        tags = metadata('/api/tags'); loaded = metadata('/api/ps'); selected = loaded_identity(tags, loaded, model)
        out.mkdir(); frozen = freeze_inputs(check, out)
        manifest = {'status': 'running', 'started_at': now(), 'dataset_path': DATASET_REL,
            'gold_path': builder.GOLD_REL, 'model': selected, 'endpoint': endpoint,
            'loaded_models_before': loaded, 'pi_version': subprocess.check_output(['pi', '--version'], text=True).strip(),
            'arms': list(ARMS), 'repeats': 3, 'expected_answers': 48, 'frozen_hashes': frozen,
            'protocol_sha256': sha(ROOT/BASE_REL/'protocol.json'), 'validation_hashes': check['validation_hashes'],
            'cost_snapshot_before': check['cost_snapshot'], 'paid_calls_by_this_driver': 0,
            'scope': 'Confirmatory canonical core: eight correlated views from two mechanism families'}
        save(out/'manifest.json', manifest); save(out/'order-plan.json', check['order_plan'])
        env = os.environ.copy(); env.update(RUN_HARNESS_COMPARISON='1', RUN_LEGACY_HARNESS_COMPARISON='0',
            EVAL_DATASET=DATASET_REL, EVAL_MODEL=model['name'], EVAL_BASE_URL=endpoint, EVAL_SPLIT='test',
            EVAL_ONLY='', EVAL_REPEATS='3', COMPARE_ARMS=','.join(ARMS),
            PYTHONPATH=str(ROOT/'.venv-eval/lib/python3.12/site-packages'))
        prior_raw_dirs = set((ROOT/'build/eval').glob('comparison-*'))
        try:
            with (out/'run.log').open('w') as log:
                process = subprocess.run(['./gradlew', 'evalRun', '--tests', '*HarnessComparisonRunner',
                    '--no-daemon', '--console=plain'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            manifest['exit_code'] = process.returncode
            markers = re.findall(r'COMPARISON_COMPLETE (.+)', (out/'run.log').read_text())
            if len(markers) != 1: raise ValueError('Exactly one runner completion marker required; partial run retained in build/eval')
            raw = Path(markers[0].strip()).resolve()
            if not raw.is_relative_to((ROOT/'build/eval').resolve()): raise ValueError('Unexpected raw output location')
            shutil.copytree(raw, out/'raw-comparison')
            manifest['raw_source_directory'] = str(raw)
            if sha(out/'raw-comparison/dataset.json') != sha(ROOT/DATASET_REL): raise ValueError('Runner used a different dataset')
            conditions = read(out/'raw-comparison/conditions.json')
            if conditions.get('armOrderPolicy') != ORDER_POLICY: raise ValueError('Runner counterbalancing policy changed')
            rows = [json.loads(line) for line in (out/'raw-comparison/results.jsonl').read_text().splitlines() if line.strip()]
            manifest.update(answers=len(rows), runner_errors=sum(bool(r.get('error')) for r in rows))
            validate_grid(rows, check['dataset']); manifest['grid_valid'] = True
            manifest['status'] = 'completed' if process.returncode == 0 else 'invalid_or_incomplete'
        except Exception as error: manifest.update(status='invalid_or_incomplete', error=str(error))
        finally:
            manifest['finished_at'] = now()
            if not (out/'raw-comparison').exists():
                candidates = [p for p in (ROOT/'build/eval').glob('comparison-*') if p not in prior_raw_dirs and p.is_dir()]
                manifest['partial_raw_candidates'] = [str(p) for p in candidates]
                if len(candidates) == 1:
                    shutil.copytree(candidates[0], out/'raw-comparison')
                    manifest['raw_source_directory'] = str(candidates[0])
            manifest['changed_inputs'] = [rel for rel, digest in frozen.items() if not (ROOT/rel).is_file() or sha(ROOT/rel) != digest]
            if manifest['changed_inputs']: manifest['status'] = 'invalid_or_incomplete'
            manifest['raw_hashes'] = {str(p.relative_to(out)): sha(p) for p in (out/'raw-comparison').rglob('*') if p.is_file()}
            if (out/'run.log').exists(): manifest['run_log_sha256'] = sha(out/'run.log')
            try:
                manifest['loaded_models_after'] = metadata('/api/ps')
                loaded_identity(tags, manifest['loaded_models_after'], model)
            except Exception as error: manifest.update(status='invalid_or_incomplete', model_metadata_error=str(error))
            save(out/'manifest.json', manifest)
        if manifest['status'] != 'completed': raise RuntimeError('Canonical run incomplete; preserved manifest and outputs require review')
        return manifest
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'run'], nargs='?', default='check')
    parser.add_argument('--execute', action='store_true'); args = parser.parse_args()
    try:
        if args.action == 'run': result = run(execute=args.execute)
        else:
            check = preflight(); result = {'status': 'ready_not_started', 'expected_answers': 48,
                'first_positions': check['order_plan']['first_positions'], 'cost_snapshot': check['cost_snapshot']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'status': 'blocked_not_started', 'reason': str(error)}, ensure_ascii=False)); raise SystemExit(2)
if __name__ == '__main__': main()
