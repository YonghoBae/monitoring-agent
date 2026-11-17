"""V5.1 measurement amendment: required fields and full-question completion remain distinct."""
import argparse
from collections import Counter
from pathlib import Path
import budget_registry as budget
import haiku_rejudge as api
SYSTEM = None
validate = None

def load_judge():
    global SYSTEM, validate
    from semantic_judge_v51 import SYSTEM as system, validate as validator
    SYSTEM, validate = system, validator
ROOT = Path(__file__).resolve().parents[1]
ARMS = ('pi_plus', 'compact_plus')
SCORING_INPUTS = ('scripts/score_eval_v51.py', 'scripts/semantic_judge_v51.py',
    'scripts/budget_registry.py', 'scripts/haiku_rejudge.py', 'eval/paid-campaigns.json')
VALIDATION_REL = 'eval/v5/semantic-validation-v51'
AMENDMENT = {
    'kind': 'post_preregistered_measurement_amendment_before_paid_comparison_grading',
    'reason': 'An arm-blinded review exposed a gap between enumerated field completion and the full question.',
    'new_components': ['answer_correct', 'complete_answer'],
    'model_prompts_worlds_answers_changed': False,
    'arm_information_used_to_choose_rule': False,
    'required_field_metrics_retained_separately': True,
}


def validate_grid(rows, dataset, case_key='id'):
    scenes = dataset['scenarios']; ids = [s['id'] for s in scenes]
    if len(ids) != 8 or len(set(ids)) != 8 or any(s['split'] != 'test' for s in scenes):
        raise ValueError('Expected eight unique preregistered test views')
    expected = {(case, arm, rep) for case in ids for arm in ARMS for rep in range(3)}
    families = {s['id']: s['family'] for s in scenes}; actual = []
    for row in rows:
        if type(row.get('rep')) is not int: raise ValueError('Invalid comparison repetition')
        cell = (row[case_key], row['arm'], row['rep'])
        if cell not in expected or row.get('family') != families.get(row[case_key]):
            raise ValueError('Unexpected comparison cell/family')
        actual.append(cell)
    if len(actual) != 48 or len(set(actual)) != 48 or set(actual) != expected:
        raise ValueError('Missing or duplicate comparison cells; exact 8x2x3 grid required')

def verify_model_archive(campaign):
    """Check original immutable snapshots, without requiring the old scorer to be current."""
    manifest = api.read(campaign/'manifest.json')
    if manifest.get('status') != 'completed' or manifest.get('answers') != 48:
        raise ValueError('Incomplete comparison')
    hashes = manifest.get('frozen_hashes', {})
    for required in ('eval/v5/dataset.json', 'eval/v5/gold.json'):
        if required not in hashes: raise ValueError('Required model input was not frozen: '+required)
    for rel, digest in hashes.items():
        path = campaign/'frozen-inputs'/rel
        if not path.is_file() or api.sha(path.read_bytes()) != digest:
            raise ValueError('Original model archive changed: '+rel)
    return manifest

def validation_gate():
    load_judge()
    folder = ROOT/VALIDATION_REL
    manifest = api.read(folder/'manifest.json'); summary = api.read(folder/'summary.json')
    if summary.get('gate_passed') is not True or type(summary.get('judgments')) is not int or summary['judgments'] != 60:
        raise ValueError('V5.1 independent 60-judgment validation gate has not passed')
    if manifest.get('system_sha256') != api.sha(SYSTEM.encode()):
        raise ValueError('V5.1 validation prompt mismatch')
    if manifest.get('judge_code_sha256') != api.sha((ROOT/'scripts/semantic_judge_v51.py').read_bytes()):
        raise ValueError('V5.1 validation judge-code mismatch')
    if not manifest.get('holdout_sha256'):
        raise ValueError('V5.1 independent holdout identity missing')
    return {name: api.sha((folder/name).read_bytes()) for name in ('manifest.json', 'summary.json')}

def freeze_scoring(out):
    hashes = {}
    for rel in SCORING_INPUTS:
        source = ROOT/rel; target = out/'frozen-scoring'/rel
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
        hashes[rel] = api.sha(source.read_bytes())
    return hashes


def prepare(campaign, out):
    load_judge(); manifest = verify_model_archive(campaign); validation_hashes = validation_gate()
    freeze = campaign/'frozen-inputs'
    dataset = api.read(freeze/'eval/v5/dataset.json')
    scenes = {s['id']: s for s in dataset['scenarios']}; gold = api.read(freeze/'eval/v5/gold.json')
    rows = api.lines(campaign/'raw-comparison/results.jsonl'); validate_grid(rows, dataset)
    previous = budget.preflight(ROOT, out)['prior_campaign_cost_usd']
    if out.exists(): raise ValueError('Output already exists')
    for row in rows:
        if row['trace'].get('kind') != 'delivered_tool_results' or row['trace'].get('captureSupported') is not True:
            raise ValueError('Exact delivered observation capture required')
        if not isinstance(row['answer'], str) or not isinstance(row['error'], str):
            raise ValueError('Invalid answer/error row')
    out.mkdir(); (out/'raw').mkdir(); (out/'payloads').mkdir()
    scoring_hashes = freeze_scoring(out)
    for name in validation_hashes:
        target = out/'frozen-validation'/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/VALIDATION_REL/name).read_bytes())
    rows = sorted(rows, key=lambda r: api.sha((r['id']+r['arm']+str(r['rep'])).encode()))
    mapping = []
    for n, row in enumerate(rows):
        ident = f'answer-{n+1:03d}'; scene = scenes[row['id']]
        payload = {'question': scene['question']+'\nRequested fields: '+api.encode(scene['answer_fields']),
                   'answer': row['answer'], 'reference': gold[row['id']]['reference'],
                   'observations': row['trace']['observations']}
        api.save(out/'payloads'/f'{ident}.json', payload)
        mapping.append({'id': ident, 'case': row['id'], 'family': row['family'], 'arm': row['arm'],
                        'rep': row['rep'], 'runner_error': row['error'], 'elapsed_ms': row['elapsedMs'],
                        'payload_sha256': api.sha(api.encode(payload).encode())})
    api.save(out/'mapping.json', mapping)
    api.save(out/'manifest.json', {'comparison': str(campaign.resolve()), 'prior_campaign_cost_usd': previous,
        'comparison_manifest_sha256': api.sha((campaign/'manifest.json').read_bytes()),
        'comparison_results_sha256': api.sha((campaign/'raw-comparison/results.jsonl').read_bytes()),
        'mapping_sha256': api.sha(api.encode(mapping).encode()),
        'frozen_scoring_hashes': scoring_hashes, 'validation_hashes': validation_hashes,
        'measurement_amendment': AMENDMENT,
        'system_sha256': api.sha(SYSTEM.encode()),
        'judge_sha256': api.sha((ROOT/'scripts/semantic_judge_v51.py').read_bytes()),
        'scorer_sha256': api.sha(Path(__file__).read_bytes()), 'repeats': 2, 'answers': 48,
        'policy': 'Two distinct verdicts; any scored field/pass/correctness/completeness/unsupported disagreement or invalidity is unresolved nonpass; no semantic repair'})
    (out/'system.txt').write_text(SYSTEM); print('Prepared 48 arm-blinded payloads.', flush=True)

def verified_mapping(out):
    load_judge()
    manifest = api.read(out/'manifest.json'); campaign = Path(manifest['comparison'])
    if manifest.get('measurement_amendment') != AMENDMENT:
        raise ValueError('Measurement amendment changed')
    if api.sha((campaign/'manifest.json').read_bytes()) != manifest['comparison_manifest_sha256']:
        raise ValueError('Comparison manifest changed')
    verify_model_archive(campaign)
    if api.sha((campaign/'raw-comparison/results.jsonl').read_bytes()) != manifest['comparison_results_sha256']:
        raise ValueError('Original model results changed after measurement freeze')
    for rel in SCORING_INPUTS:
        expected = manifest['frozen_scoring_hashes'].get(rel)
        frozen = out/'frozen-scoring'/rel
        if not frozen.is_file() or api.sha(frozen.read_bytes()) != expected:
            raise ValueError('Frozen V5.1 scoring input changed: '+rel)
        if api.sha((ROOT/rel).read_bytes()) != expected:
            raise ValueError('Current V5.1 scoring input differs from its own freeze: '+rel)
    if (manifest['system_sha256'] != api.sha(SYSTEM.encode())
            or manifest['judge_sha256'] != api.sha((ROOT/'scripts/semantic_judge_v51.py').read_bytes())
            or manifest['scorer_sha256'] != api.sha(Path(__file__).read_bytes())):
        raise ValueError('Prepared V5.1 judge, scorer, or prompt changed')
    if manifest['validation_hashes'] != validation_gate():
        raise ValueError('Independent V5.1 validation artifacts changed')
    for name, digest in manifest['validation_hashes'].items():
        if api.sha((out/'frozen-validation'/name).read_bytes()) != digest:
            raise ValueError('Frozen V5.1 validation snapshot changed')
    mapping = api.read(out/'mapping.json')
    if api.sha(api.encode(mapping).encode()) != manifest['mapping_sha256']: raise ValueError('Mapping changed')
    validate_grid(mapping, api.read(campaign/'frozen-inputs/eval/v5/dataset.json'), 'case')
    if len({m['id'] for m in mapping}) != 48: raise ValueError('Duplicate blinded answer IDs')
    for m in mapping:
        payload = api.read(out/'payloads'/f"{m['id']}.json")
        if m['payload_sha256'] != api.sha(api.encode(payload).encode()): raise ValueError('Payload changed')
    return mapping


def run(out):
    if (out/'results.jsonl').exists() or (out/'requests.jsonl').exists(): raise ValueError('No silent rerun')
    mapping = verified_mapping(out); budget.preflight(ROOT, out); key = api.key_from_env(ROOT/'.env')
    for rep in range(2):
        for m in mapping:
            payload = api.read(out/'payloads'/f"{m['id']}.json")
            if m['payload_sha256'] != api.sha(api.encode(payload).encode()): raise ValueError('Payload changed')
            row = {'id': m['id'], 'judge_rep': rep}
            if not payload['answer'].strip():
                row.update(result={'pass': False, 'answer_correct': False, 'complete_answer': False, 'unsupported_claims': False, 'answer_status': 'unanswered',
                    'findings': [{'key': x['key'], 'satisfied': False, 'answer_quote': '', 'observation_ids': [],
                                 'reason': 'Empty answer'} for x in payload['reference']['required_findings']],
                    'reason': 'Deterministic empty-answer rule'}, method='deterministic_empty')
            else:
                try:
                    raw = budget.paid_call(api, ROOT, out, f"{m['id']}-r{rep}", payload, key, 'comparison', system=SYSTEM)
                except Exception as error:
                    row.update(error=str(error), method='api_error'); api.append(out/'results.jsonl', row)
                    summarize(out); raise
                try: row.update(result=validate(api.response_json(raw), payload), method='haiku')
                except Exception as error: row.update(error=str(error), method='invalid')
            api.append(out/'results.jsonl', row)
            print(m['id'], rep, row.get('result', {}).get('pass', 'INVALID'), flush=True)
    summarize(out)

def summarize(out):
    mapping = verified_mapping(out); judgments = api.lines(out/'results.jsonl')
    ids = {m['id'] for m in mapping}
    if any(j.get('id') not in ids for j in judgments): raise ValueError('Judgment for unknown answer ID')
    answers = []
    for m in mapping:
        js = [j for j in judgments if j['id'] == m['id']]
        counts = Counter(j.get('judge_rep') for j in js if type(j.get('judge_rep')) is int); integrity = []
        if any(type(j.get('judge_rep')) is not int or j['judge_rep'] not in (0, 1) for j in js): integrity.append('invalid_judge_repeat')
        if any(counts[rep] > 1 for rep in (0, 1)): integrity.append('duplicate_judge_repeat')
        if set(counts) != {0, 1}: integrity.append('missing_judge_repeat')
        payload = api.read(out/'payloads'/f"{m['id']}.json"); valid = {}
        for j in js:
            if type(j.get('judge_rep')) is not int or j['judge_rep'] not in (0, 1) or counts[j['judge_rep']] != 1: continue
            try: valid[j['judge_rep']] = validate(j['result'], payload)
            except Exception: integrity.append('invalid_judgment')
        complete = not integrity and len(js) == 2 and len(valid) == 2
        labels = [(j['pass'], j['answer_correct'], j['complete_answer'], j['unsupported_claims'], tuple(sorted((f['key'], f['satisfied']) for f in j['findings']))) for j in valid.values()]
        agreement = complete and labels[0] == labels[1]
        stable = agreement and all(j['pass'] for j in valid.values()) and not m['runner_error']
        finding_keys = [f['key'] for f in payload['reference']['required_findings']]
        finding_stability = {key: complete and not m['runner_error'] and all(next(f['satisfied'] for f in j['findings'] if f['key'] == key) for j in valid.values()) for key in finding_keys}
        answers.append({**m, 'complete': complete, 'agreement': agreement, 'stable_pass': bool(stable),
            'finding_stability': finding_stability,
            'stable_required_fields': complete and all(finding_stability.values()),
            'stable_answer_correct': complete and not m['runner_error'] and all(j['answer_correct'] for j in valid.values()),
            'stable_complete_answer': complete and not m['runner_error'] and all(j['complete_answer'] for j in valid.values()),
            'stable_no_unsupported_claims': complete and not m['runner_error'] and all(not j['unsupported_claims'] for j in valid.values()),
            'integrity_errors': sorted(set(integrity)),
            'judge_results': {str(rep): {'pass': j['pass'], 'answer_correct': j['answer_correct'], 'complete_answer': j['complete_answer'], 'unsupported_claims': j['unsupported_claims'], 'findings': {f['key']: f['satisfied'] for f in j['findings']}} for rep, j in valid.items()},
            'passes': [j['pass'] for j in valid.values()], 'unsupported': [j['unsupported_claims'] for j in valid.values()]})
    arms = {}
    for arm in ARMS:
        rs = [r for r in answers if r['arm'] == arm]
        arms[arm] = {'n': len(rs), 'stable_pass': sum(r['stable_pass'] for r in rs),
            'stable_pass_percent': 100*sum(r['stable_pass'] for r in rs)/len(rs),
            'stable_required_fields': sum(r['stable_required_fields'] for r in rs),
            'stable_answer_correct': sum(r['stable_answer_correct'] for r in rs),
            'stable_complete_answer': sum(r['stable_complete_answer'] for r in rs),
            'stable_no_unsupported_claims': sum(r['stable_no_unsupported_claims'] for r in rs),
            'per_finding': {key: {'n': len(rs), 'stable_satisfied': sum(r['finding_stability'][key] for r in rs)} for key in sorted({key for r in rs for key in r['finding_stability']})},
            'unresolved': sum(not r['agreement'] for r in rs), 'runner_errors': sum(bool(r['runner_error']) for r in rs),
            'per_judge_repeat': {str(rep): {'n': len(rs), 'valid': sum(str(rep) in r['judge_results'] for r in rs),
                'pass': sum(r['judge_results'].get(str(rep), {}).get('pass', False) and not r['runner_error'] for r in rs),
                'answer_correct': sum(r['judge_results'].get(str(rep), {}).get('answer_correct', False) and not r['runner_error'] for r in rs),
                'complete_answer': sum(r['judge_results'].get(str(rep), {}).get('complete_answer', False) and not r['runner_error'] for r in rs),
                'unsupported_claims': sum(r['judge_results'].get(str(rep), {}).get('unsupported_claims', False) for r in rs),
                'required_fields_satisfied': sum(str(rep) in r['judge_results'] and all(r['judge_results'][str(rep)]['findings'].values()) and not r['runner_error'] for r in rs),
                'pass_percent': 100*sum(r['judge_results'].get(str(rep), {}).get('pass', False) and not r['runner_error'] for r in rs)/len(rs)} for rep in (0, 1)},
            'per_repeat': {str(rep): {'n': sum(r['rep'] == rep for r in rs), 'stable_pass': sum(r['stable_pass'] for r in rs if r['rep'] == rep)} for rep in range(3)},
            'per_family': {family: {'n': sum(r['family'] == family for r in rs), 'stable_pass': sum(r['stable_pass'] for r in rs if r['family'] == family)} for family in sorted({r['family'] for r in rs})}}
    try: costs = budget.preflight(ROOT, out)
    except ValueError as error: costs = {'budget_blocked': str(error), 'local': api.cost_state(out)}
    result = {'arms': arms, 'answers': answers, 'judgments': len(judgments), 'cost': costs,
        'measurement_amendment': AMENDMENT,
        'answer_status_limitation': 'answer_status is descriptive and excluded from scored agreement. Original V5 calibration was 57/60; V5.1 is a separate frozen validation.',
        'inference_limit': 'Eight correlated views from two mechanism families; no general home-server rank or independent n=24 claim.'}
    api.save(out/'summary.json', result); print(api.encode({'arms': arms, 'cost': result['cost']}), flush=True)

def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['prepare', 'run', 'summarize'])
    p.add_argument('--out', type=Path, default=ROOT/'eval/v5/scoring-v51'); p.add_argument('--campaign', type=Path, default=ROOT/'eval/v5/comparison-2'); args = p.parse_args()
    if args.action == 'prepare': prepare(args.campaign, args.out)
    elif args.action == 'run': run(args.out)
    else: summarize(args.out)
if __name__ == '__main__': main()
