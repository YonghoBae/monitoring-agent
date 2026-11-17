"""Frozen independent end-to-end numeric/semantic bridge validation; no retries."""
import argparse
import json
import shutil
from pathlib import Path

import budget_registry as budget
import structured_haiku_v5 as api
import score_legacy_eval_v53 as scorer

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / 'eval/v5/legacy-migration/numeric-bridge-holdout-v53.json'
OUT = ROOT / 'eval/v5/legacy-bridge-validation-v53'
EXPECTED_HOLDOUT_SHA = '100e162fafd2dca3e5143ec4aeb2002f1a039f3b429dc26e3dc3267972f252f4'


def prepare_controls(document):
    cases = document['cases']
    if len(cases) != 20 or len({c['id'] for c in cases}) != 20:
        raise ValueError('Exactly 20 distinct independently frozen controls required')
    prepared = []
    for case in cases:
        payload = scorer.build_payload(case['payload'], case['contracts'], case['request_schema'])
        actual = scorer.grade_fields(case['payload']['answer'], case['contracts'], request_schema=case['request_schema'])
        fields = {f['key']: f for f in actual['fields']}
        if set(case['expected_numeric']) != set(fields):
            raise ValueError(f"{case['id']}: manual deterministic expectations must be exhaustive")
        for key, expected in case['expected_numeric'].items():
            for label in ('status', 'numeric_correct', 'value_correct'):
                if fields[key][label] != expected[label] or type(fields[key][label]) is not type(expected[label]):
                    raise ValueError(f"{case['id']}/{key}/{label}: deterministic control mismatch")
        if actual['format_status'] != case['expected_format_status']:
            raise ValueError(f"{case['id']}: format control mismatch")
        if set(case['expected']['findings']) != set(payload['measurement_scope']['all_field_keys']):
            raise ValueError('Manual final finding labels must be exhaustive')
        prepared.append((case, payload))
    return prepared


def compare(case, components):
    expected = case['expected']
    mismatches = []
    if components['structured_pass'] != expected['pass']:
        mismatches.append('pass')
    if components['unsupported_claims'] != expected['unsupported_claims']:
        mismatches.append('unsupported_claims')
    mismatches += ['finding:' + key for key, value in expected['findings'].items()
                   if components['combined_fields'][key] != value]
    diagnostic = ['finding:' + key for key, value in case.get('expected_semantic_findings', {}).items()
                  if components['raw_semantic_fields'][key] != value]
    return mismatches, diagnostic


def run(execute=False):
    if api.sha(HOLDOUT.read_bytes()) != EXPECTED_HOLDOUT_SHA:
        raise ValueError('Independent holdout changed')
    prepared = prepare_controls(api.read(HOLDOUT))
    identity = scorer.bridge_identity()
    if not execute:
        return {'offline_controls_passed': len(prepared), 'bridge_identity': identity}
    if OUT.exists():
        raise ValueError('No overwrite, continuation, or silent retry of this validation')
    prior = budget.preflight(ROOT, OUT)
    OUT.mkdir(); (OUT / 'raw').mkdir(); (OUT / 'payloads').mkdir()
    names = ('score_legacy_eval_v53.py', 'legacy_field_contract_v5.py', 'numeric_contract_v12.py',
             'semantic_judge_v5.py', 'semantic_judge_v53.py', 'structured_haiku_v5.py', 'validate_legacy_bridge_v53.py', 'budget_registry.py', 'haiku_rejudge.py')
    hashes = {f'scripts/{name}': api.sha((ROOT / 'scripts' / name).read_bytes()) for name in names}
    hashes['eval/paid-campaigns.json'] = api.sha((ROOT / 'eval/paid-campaigns.json').read_bytes())
    manifest = {**identity, 'holdout_sha256': EXPECTED_HOLDOUT_SHA, 'cases': 20, 'repeats': 3,
        'purpose': 'Fresh independent end-to-end numeric/semantic bridge v5.3 validation with constrained JSON output',
        'gate': 'All manually authored deterministic/format labels before spending; all final combined pass, unsupported, and per-field labels in every one of 60 judgments',
        'diagnostic_only': 'Raw semantic finding labels where arithmetic/format code changes final outcomes; answer_status is unscored',
        'no_tuning_on_holdout': True, 'frozen_hashes': hashes,
        'prior_campaign_cost_usd': prior['prior_campaign_cost_usd'], 'budget_usd_including_prior': 2}
    api.save(OUT / 'manifest.json', manifest)
    shutil.copy2(HOLDOUT, OUT / 'independent-holdout.json')
    for name in names:
        shutil.copy2(ROOT / 'scripts' / name, OUT / name)
    (OUT / 'system.txt').write_text(scorer.SYSTEM)
    for case, payload in prepared:
        api.save(OUT / 'payloads' / f"{case['id']}.json", payload)
    key = api.key_from_env(ROOT / '.env'); rows = []
    for rep in range(3):
        for case, payload in prepared:
            if any(api.sha((ROOT / path).read_bytes()) != digest for path, digest in hashes.items()):
                raise ValueError('Frozen validation dependency changed')
            ident = f"{case['id']}-r{rep}"
            raw = budget.paid_call(api, ROOT, OUT, ident, payload, key, 'legacy-bridge-validation-v53', system=scorer.SYSTEM)
            row = {'id': case['id'], 'rep': rep}
            try:
                result = api.response_json(raw)
                components = scorer.grade_components(payload, result)
                mismatches, diagnostic = compare(case, components)
                row.update(semantic_result=result, components=components, mismatches=mismatches,
                           diagnostic_semantic_mismatches=diagnostic)
            except Exception as error:
                row.update(error=str(error), mismatches=['invalid_judgment'])
            rows.append(row); api.append(OUT / 'results.jsonl', row)
            print(ident, 'PASS' if not row['mismatches'] else 'FAIL ' + ','.join(row['mismatches']), flush=True)
    changed = [path for path, digest in hashes.items() if api.sha((ROOT / path).read_bytes()) != digest]
    summary = {'gate_passed': len(rows) == 60 and not changed and all(not r['mismatches'] for r in rows),
        'cases': 20, 'judgments': len(rows), 'repeats': 3, 'offline_controls_passed': len(prepared),
        'changed_inputs': changed,
        'failed': [{'id': r['id'], 'rep': r['rep'], 'mismatches': r['mismatches']} for r in rows if r['mismatches']],
        'diagnostic_semantic_disagreements': sum(bool(r.get('diagnostic_semantic_mismatches')) for r in rows),
        'cost': budget.preflight(ROOT, OUT)}
    api.save(OUT / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run(args.execute)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.execute and not result['gate_passed']:
        raise SystemExit(2)
