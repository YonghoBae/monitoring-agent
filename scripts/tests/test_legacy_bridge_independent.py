"""Independent synthetic bridge audit. No benchmark answers or holdout labels.

These controls are authored separately from the scorer and its paid holdout.
They test composition and schema behavior; mocked semantic labels are not a
claim that any language model reliably produces those labels.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_legacy_eval_v5 as score
import validate_legacy_bridge_v5 as gate
from legacy_field_contract_v5 import build_request_schema

def contract(key='remaining', value=8, kind='numeric_quantity', unit='GB', json_type='number'):
    question = 'Report the observed free storage in GB.' if unit else 'Report the observed service state.'
    result = {'case_id': 'independent-synthetic', 'field_id': 'synthetic/'+key,
        'key': key, 'requested_question': question, 'scoring_kind': kind,
        'original_gold': {'key': key, 'value': value, 'tolerance': 0},
        'answer_binding': {'kind': 'requested_json_field', 'json_pointer': '/facts/'+key,
            'unit': unit, 'expected_json_type': json_type,
            'unit_authority': {'kind': 'explicit_requested_quantity', 'verbatim_question': question}},
        'window': {}, 'quantity_association': {}, 'evidence_policy': {}}
    if kind == 'numeric_quantity':
        result['numeric_contract'] = {'value': str(value), 'unit': unit, 'tolerance': {'absolute': '0', 'relative': '0'}}
    return result
def fixture(answer='done\n{"facts":{"remaining":8}}', contracts=None, extra=False):
    contracts = contracts or [contract()]; schema = build_request_schema(contracts)
    published = [{'key': key, **value} for key, value in schema['facts'].items()]
    if extra: published.append({'key': 'secondary', 'question': 'Report the observed secondary check.', 'type': 'string|null', 'unit': None})
    payload = {'question': 'Report each observed requested result.', 'requested_answer_fields': published,
        'answer': answer, 'reference': {'required_findings': [{'key': f['key'], 'statement': f['question']} for f in published]},
        'observations': [{'id': 'obs-storage', 'tool': 'query', 'input': '{"scope":"synthetic"}',
                          'output': 'Free storage is 8000000000 bytes; service state is healthy; secondary check passed.'}]}
    return payload, contracts, schema
def verdict(prepared, satisfied=None, unsupported=False):
    satisfied = satisfied or {}
    fields = [{'key': f['key'], 'satisfied': satisfied.get(f['key'], True),
        'answer_quote': 'done', 'observation_ids': ['obs-storage'], 'reason': 'Synthetic supplied semantic judgment'}
        for f in prepared['reference']['required_findings']]
    return {'pass': all(f['satisfied'] for f in fields) and not unsupported,
        'unsupported_claims': unsupported, 'answer_status': 'answered', 'findings': fields, 'reason': 'Synthetic verdict'}

class IndependentCompositionTest(unittest.TestCase):
    def test_numeric_code_and_semantics_are_both_required(self):
        for value, semantic, expected in ((8, True, True), (8, False, False), (7, True, False)):
            with self.subTest(value=value, semantic=semantic):
                p = score.build_payload(*fixture('done\n'+json.dumps({'facts': {'remaining': value}})))
                result = score.grade_components(p, verdict(p, {'remaining': semantic}))
                self.assertEqual(result['combined_fields']['remaining'], expected)
                self.assertEqual(result['structured_pass'], expected)
    def test_gib_number_and_rate_cannot_become_gb_count(self):
        for value in ('8 GiB', '8 GB/s', '8 GB-hour'):
            with self.subTest(value=value):
                p = score.build_payload(*fixture('done\n'+json.dumps({'facts': {'remaining': value}})))
                result = score.grade_components(p, verdict(p))
                self.assertFalse(result['combined_fields']['remaining'])
                self.assertFalse(result['structured_pass'])
    def test_no_identity_or_raw_world_fields_in_blind_payload(self):
        payload, contracts, schema = fixture()
        for hidden in ('arm', 'family', 'case', 'rawWorldTrace', 'prior_score'):
            with self.subTest(hidden=hidden), self.assertRaises(ValueError):
                score.build_payload(payload | {hidden: 'private'}, contracts, schema)
        prepared = score.build_payload(payload, contracts, schema)
        self.assertEqual(prepared['observations'], payload['observations'])
        self.assertNotIn('original_gold', json.dumps(prepared))
        self.assertNotIn('independent-synthetic', json.dumps(prepared))
    def test_missing_categorical_key_keeps_semantics_but_blocks_strict_format(self):
        c = contract('state', 'healthy', 'categorical', None, 'string|null')
        p = score.build_payload(*fixture('done\n{"facts":{}}', [c]))
        result = score.grade_components(p, verdict(p))
        self.assertTrue(result['combined_fields']['state'])
        self.assertEqual(p['structured_format_check']['status'], 'valid')
        self.assertFalse(result['structured_pass'])
    def test_wrong_categorical_json_type_cannot_pass_structured_schema(self):
        c = contract('state', 'healthy', 'categorical', None, 'string|null')
        for value in ([], {}, 7, True):
            with self.subTest(value=value):
                p = score.build_payload(*fixture('done\n'+json.dumps({'facts': {'state': value}}), [c]))
                result = score.grade_components(p, verdict(p))
                self.assertTrue(result['combined_fields']['state'])
                self.assertFalse(result['structured_pass'])
    def test_null_categorical_unknown_can_pass_when_semantically_supported(self):
        c = contract('state', 'unknown', 'explicit_unknown', None, 'string|null')
        p = score.build_payload(*fixture('done\n{"facts":{"state":null}}', [c]))
        self.assertTrue(score.grade_components(p, verdict(p))['structured_pass'])
    def test_secondary_schema_is_checked_outside_original_binding_subset(self):
        p = score.build_payload(*fixture(extra=True))
        result = score.grade_components(p, verdict(p))
        self.assertTrue(result['combined_fields']['secondary'])
        self.assertFalse(result['structured_pass'])
        p = score.build_payload(*fixture('done\n{"facts":{"remaining":8,"secondary":"passed"}}', extra=True))
        self.assertTrue(score.grade_components(p, verdict(p))['structured_pass'])
    def test_unsupported_or_runner_failure_blocks_strict_pass(self):
        p = score.build_payload(*fixture())
        for unsupported, error in ((True, ''), (False, 'tool transport failed')):
            result = score.grade_components(p, verdict(p, unsupported=unsupported), error)
            self.assertTrue(result['combined_fields']['remaining'])
            self.assertFalse(result['structured_pass'])
    def test_invalid_final_json_has_no_numeric_credit(self):
        for answer in ('done\n{"facts":{"remaining":8},"other":NaN}',
                       'done\n{"facts":{"remaining":8}} trailing prose',
                       'done\n{"facts":{"remaining":8,"remaining":8}}'):
            with self.subTest(answer=answer):
                p = score.build_payload(*fixture(answer))
                result = score.grade_components(p, verdict(p))
                self.assertFalse(result['combined_fields']['remaining'])
                self.assertFalse(result['structured_pass'])
    def test_only_published_measurement_window_reaches_judge(self):
        payload, contracts, _ = fixture()
        contracts[0]['window'] = {'hidden_source_expression': 'PRIVATE_WINDOW_CANARY'}
        metadata = {'lookback_seconds': 300, 'aggregation': 'rate'}
        schema = build_request_schema(contracts, {'remaining': metadata})
        payload['requested_answer_fields'] = [{'key': key, **spec} for key, spec in schema['facts'].items()]
        prepared = score.build_payload(payload, contracts, schema)
        self.assertEqual(prepared['deterministic_numeric_checks'][0]['window'], metadata)
        self.assertNotIn('PRIVATE_WINDOW_CANARY', json.dumps(prepared))
        broken = copy.deepcopy(payload); broken['requested_answer_fields'][0]['measurement']['lookback_seconds'] = 60
        with self.assertRaises(ValueError): score.build_payload(broken, contracts, schema)

class IndependentLedgerAndSummaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.out = self.root/'eval/v5/legacy-scoring'
        (self.out/'payloads').mkdir(parents=True)
        for relative in score.LEDGERS:
            child = self.root/relative; child.mkdir(); score.api.save(child/'manifest.json', {})
        p = patch.object(score, 'ROOT', self.root); p.start(); self.addCleanup(p.stop)
    def mapping(self, answer='done\n{"facts":{"remaining":8}}'):
        prepared = score.build_payload(*fixture(answer)); rows = []
        for i, arm in enumerate(score.ARMS):
            ident = f'synthetic-{i}'; score.api.save(self.out/'payloads'/f'{ident}.json', prepared)
            rows.append({'id': ident, 'case': 'synthetic', 'family': 'synthetic', 'source_tier': 'synthetic',
                'arm': arm, 'rep': 0, 'runner_error': '', 'payload_sha256': score.api.sha(score.api.encode(prepared).encode())})
        return prepared, rows
    def test_exclusive_ledger_lock_prevents_simultaneous_owner(self):
        child = self.root/score.LEDGERS[0]
        with score.ledger_run_lock(child):
            with self.assertRaisesRegex(ValueError, 'already running'):
                with score.ledger_run_lock(child): self.fail('Second owner entered')
        with score.ledger_run_lock(child): pass
    def test_empty_answers_make_no_paid_calls_and_ledger_cannot_replay(self):
        _, mapping = self.mapping('')
        with patch.object(score, '_verified_mapping', return_value=mapping), \
             patch.object(score.api, 'key_from_env', return_value='synthetic-unused-key'), \
             patch.object(score.budget, 'preflight', return_value={}), \
             patch.object(score.budget, 'paid_call', side_effect=AssertionError('Empty answers must not spend')):
            result = score.run(self.out)
            self.assertEqual(result['judgments'], 4)
            self.assertTrue(all(a['stable_structured_pass'] == 0 for a in result['arms'].values()))
            with self.assertRaisesRegex(ValueError, 'replay'): score.run(self.out, judge_rep=0)
    def test_missing_duplicate_and_wrong_ledger_verdicts_remain_unresolved(self):
        prepared, mapping = self.mapping()
        with patch.object(score, '_verified_mapping', return_value=mapping), patch.object(score.budget, 'preflight', return_value={}):
            for mode in ('missing', 'duplicate', 'wrong_ledger', 'disagreement'):
                for rep, relative in enumerate(score.LEDGERS):
                    rows = []
                    for m in mapping:
                        if mode == 'missing' and rep == 1: continue
                        semantic = verdict(prepared, {'remaining': False}) if mode == 'disagreement' and rep == 1 else verdict(prepared)
                        row = {'id': m['id'], 'judge_rep': 0 if mode == 'wrong_ledger' else rep, 'semantic_result': semantic}
                        rows.append(row)
                        if mode == 'duplicate' and rep == 0: rows.append(row)
                    (self.root/relative/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                result = score.summarize(self.out)
                with self.subTest(mode=mode):
                    self.assertEqual(len(result['answers']), 2)
                    for arm in result['arms'].values():
                        self.assertEqual(arm['n'], 1); self.assertEqual(arm['all_finding_denominator'], 1)
                        self.assertEqual(arm['unresolved'], 1); self.assertEqual(arm['stable_structured_pass'], 0)
    def test_global_accounting_counts_both_planned_ledgers_and_blocks_unknown_outcome(self):
        score.api.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2, 'campaigns': list(score.LEDGERS)})
        for rep, relative in enumerate(score.LEDGERS):
            rows = [{'event': 'started', 'request_id': f'synthetic-{rep}'},
                    {'event': 'completed', 'request_id': f'synthetic-{rep}', 'cost_usd': 0.75}]
            (self.root/relative/'requests.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        state = score.budget.state(self.root, self.root/score.LEDGERS[0])
        self.assertEqual(state['total_campaigns_estimated_usd'], 1.5)
        self.assertEqual(state['prior_campaign_cost_usd'], 0.75)
        score.api.append(self.root/score.LEDGERS[1]/'requests.jsonl', {'event': 'started', 'request_id': 'unknown-result'})
        with self.assertRaisesRegex(ValueError, 'Uncertain'): score.budget.state(self.root, self.root/score.LEDGERS[0])
    def test_plan_is_frozen_before_collection_and_detects_current_or_snapshot_change(self):
        base = self.root/'migration'; base.mkdir(); validation = self.root/'validation'; validation.mkdir()
        names = ('dataset.json', 'field-contracts.json', 'request-schemas.json', 'extra-answer-fields.json',
                 'semantic-references.json', 'measurement-definitions.json', 'build-manifest.json', 'source-audit.json', 'preflight.json', 'numeric-bridge-holdout.json')
        for name in names: (base/name).write_text('{"synthetic":true}')
        for name in ('manifest.json', 'summary.json'): (validation/name).write_text('{"synthetic":true}')
        script = self.root/'scripts/synthetic.py'; script.parent.mkdir(); script.write_text('# synthetic freeze input\n')
        score.api.save(self.root/'eval/paid-campaigns.json', {'synthetic': True})
        with patch.object(score, 'CODE', ('scripts/synthetic.py',)), patch.object(score, 'VALIDATION', validation), \
             patch.object(score, '_inputs', return_value=None), patch.object(score, '_bridge_gate', return_value=None), \
             patch.object(score, 'bridge_identity', return_value={'synthetic': 'identity'}), \
             patch.object(score.budget, 'preflight', return_value={}):
            plan = score.freeze_plan(base)
            self.assertEqual(plan['expected_answers'], 210)
            self.assertEqual(plan['judge_ledgers'], list(score.LEDGERS))
            self.assertEqual(plan['max_paid_calls_per_child'], 210)
            score.verify_plan(base/'scoring-plan.json')
            with self.assertRaises(ValueError): score.freeze_plan(base)
            frozen = self.root/plan['snapshot_relative']/'scripts/synthetic.py'
            for path in (script, frozen):
                original = path.read_bytes(); path.write_bytes(original+b'# mutation\n')
                with self.subTest(path=str(path)), self.assertRaises(ValueError): score.verify_plan(base/'scoring-plan.json')
                path.write_bytes(original)

class IndependentValidationGateTest(unittest.TestCase):
    def document(self):
        cases = []
        for index in range(20):
            p, c, s = fixture()
            cases.append({'id': f'synthetic-{index}', 'payload': p, 'contracts': c, 'request_schema': s,
                'expected_numeric': {'remaining': {'status': 'pass', 'numeric_correct': True, 'value_correct': True}},
                'expected_format_status': 'valid',
                'expected': {'pass': True, 'unsupported_claims': False, 'findings': {'remaining': True}}})
        return {'cases': cases}
    def test_twenty_synthetic_controls_validate_without_api(self):
        with patch.object(gate.budget, 'paid_call', side_effect=AssertionError('No paid call')):
            self.assertEqual(len(gate.prepare_controls(self.document())), 20)
    def test_preflight_rejects_wrong_labels_types_coverage_and_duplicate_ids(self):
        for mode in ('count', 'duplicate_id', 'numeric_false', 'integer_boolean', 'missing_numeric', 'missing_finding', 'format'):
            d = self.document(); first = d['cases'][0]
            if mode == 'count': d['cases'].pop()
            if mode == 'duplicate_id': d['cases'][1]['id'] = first['id']
            if mode == 'numeric_false': first['expected_numeric']['remaining']['numeric_correct'] = False
            if mode == 'integer_boolean': first['expected_numeric']['remaining']['numeric_correct'] = 1
            if mode == 'missing_numeric': first['expected_numeric'] = {}
            if mode == 'missing_finding': first['expected']['findings'] = {}
            if mode == 'format': first['expected_format_status'] = 'ungradable'
            with self.subTest(mode=mode), self.assertRaises(ValueError): gate.prepare_controls(d)
    def test_final_combined_failure_not_hidden_by_raw_semantic_agreement(self):
        d = self.document(); c = d['cases'][0]
        p = score.build_payload(*fixture('done\n{"facts":{"remaining":7}}'))
        components = score.grade_components(p, verdict(p))
        mismatches, _ = gate.compare(c, components)
        self.assertEqual(set(mismatches), {'pass', 'finding:remaining'})
    def test_default_validator_run_is_offline_on_synthetic_document(self):
        with tempfile.TemporaryDirectory() as folder:
            holdout = Path(folder)/'synthetic.json'; holdout.write_text(json.dumps(self.document()))
            with patch.object(gate, 'HOLDOUT', holdout), patch.object(gate, 'EXPECTED_HOLDOUT_SHA', gate.api.sha(holdout.read_bytes())), \
                 patch.object(gate.budget, 'preflight', side_effect=AssertionError('No paid registration needed')), \
                 patch.object(gate.budget, 'paid_call', side_effect=AssertionError('No paid call')):
                self.assertEqual(gate.run()['offline_controls_passed'], 20)
if __name__ == '__main__': unittest.main()
