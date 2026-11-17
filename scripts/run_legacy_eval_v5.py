"""Gated, serial 210-answer legacy run. Default action is filesystem-only check.

No model or metadata endpoint is contacted without `run --execute`. Independent
source/reachability gates, a root-approved protocol, and a frozen scorer manifest
must already exist. This driver never builds approvals, runs judges, or warms a
model automatically. The operator must preload the exact protocol model first.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import budget_registry

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'eval/v5/legacy-migration'
ARMS = ('pi_plus', 'compact_plus')
ORDER_POLICY = 'within-family-ordinal-plus-repeat-plus-alternating-odd-family-phase-v1'


def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()


def local_path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute(): raise ValueError('Expected repository-relative artifact path')
    path = (ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()): raise ValueError('Artifact path leaves repository')
    return path


def order_plan(dataset):
    counts = Counter(); ordinals = {}
    scenes = dataset['scenarios']
    if len(scenes) != 35 or any(s['split'] != 'test' for s in scenes): raise ValueError('Expected all 35 test scenes')
    for scene in scenes:
        if scene['id'] in ordinals: raise ValueError('Duplicate case ID')
        ordinals[scene['id']] = counts[scene['family']]; counts[scene['family']] += 1
    phases = {}; odd_index = 0
    for family, size in counts.items():
        phases[family] = odd_index % 2 if size % 2 else 0
        if size % 2: odd_index += 1
    order = []
    for scene in scenes:
        for rep in range(3):
            parity = (ordinals[scene['id']] + rep + phases[scene['family']]) % 2
            for position, arm in enumerate(ARMS[parity:]+ARMS[:parity]):
                order.append({'id': scene['id'], 'family': scene['family'], 'arm': arm, 'rep': rep,
                    'armPosition': position, 'familyOrdinal': ordinals[scene['id']], 'familyPhase': phases[scene['family']]})
    first = [r for r in order if r['armPosition'] == 0]
    global_counts = Counter(r['arm'] for r in first)
    if global_counts != {'pi_plus': 53, 'compact_plus': 52}: raise ValueError('Unexpected global order balance')
    for rep in range(3):
        counts_by_arm = Counter(r['arm'] for r in first if r['rep'] == rep)
        if sorted(counts_by_arm.values()) != [17, 18]: raise ValueError('Unbalanced repeat order')
    for family, size in counts.items():
        positions = Counter(r['arm'] for r in first if r['family'] == family)
        if abs(positions['pi_plus']-positions['compact_plus']) != size % 2: raise ValueError('Unbalanced family order')
    return {'policy': ORDER_POLICY, 'family_sizes': dict(counts), 'family_phases': phases,
            'first_positions': dict(global_counts), 'order': order}


def validate_grid(rows, dataset):
    expected = order_plan(dataset)['order']
    if len(rows) != 210: raise ValueError('Exactly 210 answers required; partial results remain archived')
    for row, cell in zip(rows, expected):
        for key in ('rep', 'armPosition', 'familyOrdinal', 'familyPhase'):
            if type(row.get(key)) is not int: raise ValueError('Invalid integer grid metadata')
        if any(row.get(key) != value for key, value in cell.items()): raise ValueError('Missing, duplicate, reordered, or unexpected comparison cell')
        if not isinstance(row.get('answer'), str) or not isinstance(row.get('error'), str): raise ValueError('Answer/error must remain explicit strings')
        trace = row.get('trace', {})
        if trace.get('kind') != 'delivered_tool_results' or trace.get('captureSupported') is not True:
            raise ValueError('Exact delivered evidence required')
    return True


def _verified_artifacts(manifest):
    result = []
    for rel, expected in manifest.get('artifact_hashes', {}).items():
        path = local_path(rel)
        if not path.is_file() or digest(path) != expected: raise ValueError('Gate artifact changed: '+rel)
        result.append(path)
    return result


def preflight(base=BASE):
    base = Path(base); dataset_path = base/'dataset.json'; schemas_path = base/'request-schemas.json'
    build = read(base/'build-manifest.json'); dataset = read(dataset_path)
    source = Path(build['source_dataset']); contracts = Path(build['field_contracts'])
    expected = {'source_dataset_sha256': digest(source), 'field_contracts_sha256': digest(contracts),
                'built_dataset_sha256': digest(dataset_path)}
    if any(build.get(key) != value for key, value in expected.items()): raise ValueError('Build identities changed')
    if build.get('request_schemas_sha256') != digest(schemas_path): raise ValueError('Published request schemas changed')
    extras_path = Path(build['extra_answer_fields']); extras = read(extras_path)
    measurements_path = Path(build['measurement_definitions']); measurements = read(measurements_path)
    if build.get('measurement_definitions_sha256') != digest(measurements_path): raise ValueError('Published measurement definitions changed')
    if build.get('extra_answer_fields_sha256') != digest(extras_path) or sum(len(v) for v in extras.values()) != 19:
        raise ValueError('Explicit secondary-clause descriptors changed')
    if build.get('builder_sha256') != digest(ROOT/'scripts/build_legacy_eval_v5.py') or build.get('schema_adapter_sha256') != digest(ROOT/'scripts/legacy_field_contract_v5.py'):
        raise ValueError('Builder/adapter changed after prospective dataset creation')
    source_cases = {s['id']: s for s in read(source)['scenarios'] if s['split'] == 'test'}
    schemas = read(schemas_path)
    for scene in dataset['scenarios']:
        original = source_cases[scene['id']]
        for key in original:
            if key != 'answer_fields' and scene.get(key) != original[key]: raise ValueError('Original scene content changed')
        published_base = [{'key': f['key'], **schemas[scene['id']]['facts'][f['key']]} for f in original['answer_fields']]
        if scene['answer_fields'] != published_base + extras.get(scene['id'], []):
            raise ValueError('Published base binding subset or secondary descriptors changed')
    if sum(len(scene['answer_fields']) for scene in dataset['scenarios']) != 81:
        raise ValueError('All 81 findings must be explicitly requested')
    artifacts = [dataset_path, schemas_path, base/'build-manifest.json', source, contracts, extras_path, measurements_path]
    gates = {}
    for name in ('source-audit.json', 'preflight.json'):
        path = base/name; gate = read(path)
        if gate.get('status') != 'passed' or gate.get('blockers') != []:
            raise ValueError('Independent gate has unresolved blockers: '+name)
        if any(gate.get(key) != value for key, value in expected.items()): raise ValueError('Independent gate identities mismatch: '+name)
        artifacts.extend([path, *_verified_artifacts(gate)]); gates[name] = digest(path)
    protocol_path = base/'protocol.json'; protocol = read(protocol_path)
    conditions = {'status': 'approved', 'benchmark_kind': 'controlled_regression', 'arms': list(ARMS),
                  'repeats': 3, 'expected_answers': 210, 'case_ids': [s['id'] for s in dataset['scenarios']]}
    if any(protocol.get(key) != value for key, value in conditions.items()): raise ValueError('Root protocol is absent, unapproved, or has different scope')
    if protocol.get('generation') != {'temperature': 0, 'max_output_tokens': 1536, 'reasoning_effort': 'none'}:
        raise ValueError('Model-generation protocol changed')
    if type(protocol['generation']['temperature']) not in (int, float) or type(protocol['generation']['max_output_tokens']) is not int:
        raise ValueError('Invalid generation parameter types')
    if protocol.get('limits') != {'uncached_tool_calls': 12, 'timeout_seconds': 90}: raise ValueError('Tool/deadline protocol changed')
    model = protocol.get('model', {})
    if model.get('name') != 'qwen3.5:9b-pi32k' or not model.get('digest') or not model.get('base_url'):
        raise ValueError('Exact 9B model identity/endpoint required')
    scoring_spec = protocol['scoring_manifest']; scoring_path = local_path(scoring_spec['path'])
    if digest(scoring_path) != scoring_spec['sha256']: raise ValueError('Scorer freeze manifest changed')
    scoring = read(scoring_path)
    if scoring.get('status') != 'frozen' or not scoring.get('frozen_hashes'): raise ValueError('A reviewed scorer freeze is required before model collection')
    for rel, expected_hash in scoring['frozen_hashes'].items():
        path = local_path(rel)
        if digest(path) != expected_hash: raise ValueError('Frozen scorer input changed: '+rel)
        artifacts.append(path)
    registry = ROOT/'eval/paid-campaigns.json'
    registry_value = read(registry)
    # Read-only accounting; no API helper or HTTP call is invoked here.
    costs = budget_registry.state(ROOT, local_path(registry_value['campaigns'][0]))
    artifacts.extend([protocol_path, scoring_path, registry])
    return {'dataset': dataset, 'dataset_path': dataset_path, 'protocol': protocol,
            'gates': gates, 'hashes': expected, 'artifacts': artifacts, 'cost_snapshot': costs,
            'order_plan': order_plan(dataset)}


def freeze_inputs(check, out):
    paths = list((ROOT/'src/main').rglob('*')) + list((ROOT/'src/test/java/io/ohgnoy/monitoring/eval').glob('*.java'))
    paths += check['artifacts']
    paths += [ROOT/p for p in ('build.gradle', 'settings.gradle', 'gradlew', 'gradle/wrapper/gradle-wrapper.properties',
        'scripts/build_legacy_eval_v5.py', 'scripts/run_legacy_eval_v5.py', 'scripts/legacy_field_contract_v5.py',
        'scripts/numeric_contract_v12.py', 'scripts/numeric_fixture.py', 'scripts/eval_fixture.py',
        'scripts/pi_eval_extension.ts', 'scripts/requirements-eval.txt', 'scripts/budget_registry.py')]
    hashes = {}
    for path in paths:
        if not path.is_file(): continue
        relative = str(path.resolve().relative_to(ROOT.resolve())); target = out/'frozen-inputs'/relative
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        hashes[relative] = digest(target)
    return hashes


@contextmanager
def model_run_lock():
    path = ROOT/'build/eval/.legacy-model-run.lock'; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('Another legacy model run is active') from error
        try: yield
        finally: fcntl.flock(handle, fcntl.LOCK_UN)


def run(base, out, *, execute=False):
    if execute is not True: raise ValueError('Explicit run --execute required; no automatic model start')
    check = preflight(base); out = Path(out)
    if out.exists(): raise ValueError('New output directory required; never overwrite or silently retry')
    model = check['protocol']['model']; endpoint = model['base_url']
    def metadata(path):
        with urllib.request.urlopen(endpoint+path, timeout=20) as response: return json.load(response)
    with model_run_lock():
        selected = [item for item in metadata('/api/tags')['models'] if item['name'] == model['name'] and item['digest'] == model['digest']]
        loaded = metadata('/api/ps')
        if len(selected) != 1 or not any(item.get('name') == model['name'] and item.get('digest') == model['digest'] for item in loaded['models']):
            raise ValueError('Preload the exact frozen model before starting; cold-start requests are not scored')
        out.mkdir(parents=True); frozen = freeze_inputs(check, out)
        manifest = {'status': 'running', 'started_at': now(), 'preflight_verified': True,
            'model': selected[0], 'endpoint': endpoint, 'loaded_models_before': loaded,
            'pi_version': subprocess.check_output(['pi', '--version'], text=True).strip(),
            'arms': list(ARMS), 'repeats': 3, 'expected_answers': 210,
            'built_dataset_sha256': check['hashes']['built_dataset_sha256'],
            'frozen_hashes': frozen, 'gate_manifest_hashes': check['gates'],
            'protocol_sha256': digest(Path(base)/'protocol.json'), 'cost_snapshot_before': check['cost_snapshot'],
            'cost_schema': read(ROOT/'eval/paid-campaigns.json'), 'paid_calls_by_this_driver': 0,
            'scope': 'Controlled legacy regression benchmark; not natural incident replay'}
        save(out/'order-plan.json', check['order_plan']); save(out/'manifest.json', manifest)
        env = os.environ.copy(); env.update(RUN_HARNESS_COMPARISON='0', RUN_LEGACY_HARNESS_COMPARISON='1',
            EVAL_DATASET=str(check['dataset_path'].resolve()), EVAL_MODEL=model['name'], EVAL_BASE_URL=endpoint,
            EVAL_SPLIT='test', EVAL_ONLY='', EVAL_REPEATS='3', COMPARE_ARMS=','.join(ARMS),
            LEGACY_RUN_MANIFEST=str((out/'manifest.json').resolve()), LEGACY_RAW_OUTPUT_DIR=str((out/'raw-comparison').resolve()))
        env['PYTHONPATH'] = str(ROOT/'.venv-eval/lib/python3.12/site-packages')
        try:
            with (out/'run.log').open('w') as log:
                process = subprocess.run(['./gradlew', 'evalRun', '--tests', '*LegacyHarnessComparisonRunner',
                    '--no-daemon', '--console=plain'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            manifest['exit_code'] = process.returncode
            manifest['changed_inputs'] = [rel for rel, expected in frozen.items() if not (ROOT/rel).is_file() or digest(ROOT/rel) != expected]
            raw = out/'raw-comparison/results.jsonl'
            rows = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()] if raw.exists() else []
            manifest['answers'] = len(rows); manifest['runner_errors'] = sum(bool(row.get('error')) for row in rows)
            validate_grid(rows, check['dataset'])
            manifest['grid_valid'] = True
            manifest['raw_hashes'] = {str(path.relative_to(out)): digest(path) for path in (out/'raw-comparison').rglob('*') if path.is_file()}
            manifest['status'] = 'completed' if process.returncode == 0 and not manifest['changed_inputs'] else 'invalid_or_incomplete'
        except Exception as error:
            manifest.update(status='invalid_or_incomplete', error=str(error))
        finally:
            manifest['finished_at'] = now()
            manifest['changed_inputs'] = [rel for rel, expected in frozen.items() if not (ROOT/rel).is_file() or digest(ROOT/rel) != expected]
            manifest['raw_hashes'] = {str(path.relative_to(out)): digest(path) for path in (out/'raw-comparison').rglob('*') if path.is_file()}
            if (out/'run.log').exists(): manifest['run_log_sha256'] = digest(out/'run.log')
            if manifest['changed_inputs']: manifest['status'] = 'invalid_or_incomplete'
            try: manifest['loaded_models_after'] = metadata('/api/ps')
            except Exception as error: manifest['model_metadata_error'] = str(error)
            save(out/'manifest.json', manifest)
        if manifest['status'] != 'completed': raise RuntimeError('Legacy run incomplete; inspect preserved manifest and raw outputs')
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'run'], nargs='?', default='check')
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--out', type=Path, default=ROOT/'eval/v5/legacy-comparison-1')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.action == 'run': print(json.dumps(run(args.base, args.out, execute=args.execute), ensure_ascii=False, indent=2))
    else:
        try:
            result = preflight(args.base)
            print(json.dumps({'status': 'ready_not_started', 'expected_answers': 210,
                'first_positions': result['order_plan']['first_positions'], 'cost_snapshot': result['cost_snapshot']}, indent=2))
        except (ValueError, OSError, KeyError) as error:
            print(json.dumps({'status': 'blocked_not_started', 'reason': str(error)}, ensure_ascii=False)); raise SystemExit(2)


if __name__ == '__main__': main()
