"""Arm-blinded grading with a frozen grid, distinct judgments, and shared budget."""
import argparse
from collections import Counter
from pathlib import Path
import budget_registry as budget
import haiku_rejudge as api
from semantic_judge_v5 import SYSTEM, validate
ROOT = Path(__file__).resolve().parents[1]
ARMS = ('pi_plus', 'compact_plus')
SCORING_INPUTS = ('scripts/run_eval_v5.py', 'scripts/score_eval_v5.py',
    'scripts/semantic_judge_v5.py', 'scripts/budget_registry.py', 'scripts/haiku_rejudge.py',
    'scripts/numeric_contract.py', 'docs/EVAL-V5-PROTOCOL.md', 'eval/paid-campaigns.json')

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

def verify_frozen(campaign):
    manifest = api.read(campaign/'manifest.json')
    if manifest.get('status') != 'completed' or manifest.get('answers') != 48:
        raise ValueError('Incomplete comparison')
    hashes = manifest.get('frozen_hashes', {})
    for required in (*SCORING_INPUTS, 'eval/v5/dataset.json', 'eval/v5/gold.json'):
        if required not in hashes: raise ValueError('Required input was not frozen: '+required)
    for rel, digest in hashes.items():
        path = campaign/'frozen-inputs'/rel
        if not path.is_file() or api.sha(path.read_bytes()) != digest:
            raise ValueError('Frozen input changed: '+rel)
    for rel in SCORING_INPUTS:
        if api.sha((ROOT/rel).read_bytes()) != hashes[rel]:
            raise ValueError('Scoring/protocol code changed since comparison freeze: '+rel)
    return manifest

def prepare(campaign, out):
    manifest = verify_frozen(campaign); freeze = campaign/'frozen-inputs'
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
        'mapping_sha256': api.sha(api.encode(mapping).encode()),
        'frozen_scoring_hashes': {rel: manifest['frozen_hashes'][rel] for rel in SCORING_INPUTS},
        'system_sha256': api.sha(SYSTEM.encode()),
        'judge_sha256': api.sha((ROOT/'scripts/semantic_judge_v5.py').read_bytes()),
        'scorer_sha256': api.sha(Path(__file__).read_bytes()), 'repeats': 2, 'answers': 48,
        'policy': 'Two distinct verdicts; disagreement/missing/duplicate/invalid = unresolved nonpass; no semantic repair'})
    (out/'system.txt').write_text(SYSTEM); print('Prepared 48 arm-blinded payloads.', flush=True)

def verified_mapping(out):
    manifest = api.read(out/'manifest.json'); campaign = Path(manifest['comparison'])
    if api.sha((campaign/'manifest.json').read_bytes()) != manifest['comparison_manifest_sha256']:
        raise ValueError('Comparison manifest changed')
    frozen = verify_frozen(campaign)
    for rel in SCORING_INPUTS:
        if manifest['frozen_scoring_hashes'].get(rel) != frozen['frozen_hashes'][rel]:
            raise ValueError('Prepared scoring hash differs from comparison freeze: '+rel)
    if (manifest['system_sha256'] != api.sha(SYSTEM.encode())
            or manifest['judge_sha256'] != api.sha((ROOT/'scripts/semantic_judge_v5.py').read_bytes())
            or manifest['scorer_sha256'] != api.sha(Path(__file__).read_bytes())):
        raise ValueError('Prepared judge, scorer, or prompt changed')
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
                row.update(result={'pass': False, 'unsupported_claims': False, 'answer_status': 'unanswered',
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
        labels = [(j['pass'], j['unsupported_claims'], tuple(sorted((f['key'], f['satisfied']) for f in j['findings']))) for j in valid.values()]
        agreement = complete and labels[0] == labels[1]
        stable = agreement and all(j['pass'] for j in valid.values()) and not m['runner_error']
        answers.append({**m, 'complete': complete, 'agreement': agreement, 'stable_pass': bool(stable),
            'integrity_errors': sorted(set(integrity)),
            'judge_results': {str(rep): {'pass': j['pass'], 'unsupported_claims': j['unsupported_claims']} for rep, j in valid.items()},
            'passes': [j['pass'] for j in valid.values()], 'unsupported': [j['unsupported_claims'] for j in valid.values()]})
    arms = {}
    for arm in ARMS:
        rs = [r for r in answers if r['arm'] == arm]
        arms[arm] = {'n': len(rs), 'stable_pass': sum(r['stable_pass'] for r in rs),
            'stable_pass_percent': 100*sum(r['stable_pass'] for r in rs)/len(rs),
            'unresolved': sum(not r['agreement'] for r in rs), 'runner_errors': sum(bool(r['runner_error']) for r in rs),
            'per_judge_repeat': {str(rep): {'n': len(rs), 'valid': sum(str(rep) in r['judge_results'] for r in rs),
                'pass': sum(r['judge_results'].get(str(rep), {}).get('pass', False) and not r['runner_error'] for r in rs),
                'pass_percent': 100*sum(r['judge_results'].get(str(rep), {}).get('pass', False) and not r['runner_error'] for r in rs)/len(rs)} for rep in (0, 1)},
            'per_repeat': {str(rep): {'n': sum(r['rep'] == rep for r in rs), 'stable_pass': sum(r['stable_pass'] for r in rs if r['rep'] == rep)} for rep in range(3)},
            'per_family': {family: {'n': sum(r['family'] == family for r in rs), 'stable_pass': sum(r['stable_pass'] for r in rs if r['family'] == family)} for family in sorted({r['family'] for r in rs})}}
    try: costs = budget.preflight(ROOT, out)
    except ValueError as error: costs = {'budget_blocked': str(error), 'local': api.cost_state(out)}
    result = {'arms': arms, 'answers': answers, 'judgments': len(judgments), 'cost': costs,
        'answer_status_limitation': 'Calibration answer_status matched 57/60; descriptive only, excluded from scored agreement.',
        'inference_limit': 'Eight correlated views from two mechanism families; no general home-server rank or independent n=24 claim.'}
    api.save(out/'summary.json', result); print(api.encode({'arms': arms, 'cost': result['cost']}), flush=True)

def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['prepare', 'run', 'summarize'])
    p.add_argument('--out', type=Path, default=ROOT/'eval/v5/scoring-1'); p.add_argument('--campaign', type=Path, default=ROOT/'eval/v5/comparison-2'); args = p.parse_args()
    if args.action == 'prepare': prepare(args.campaign, args.out)
    elif args.action == 'run': run(args.out)
    else: summarize(args.out)
if __name__ == '__main__': main()
