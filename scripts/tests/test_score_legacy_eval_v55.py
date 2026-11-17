"""Synthetic bridge/scorer tests. Never reads independent bridge controls or model answers."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_legacy_eval_v55 as score
from legacy_field_contract_v5 import build_request_schema

REAL_ROOT = Path(__file__).resolve().parents[2]


class LegacyScorerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidecar = json.loads((REAL_ROOT/'eval/v5/legacy-migration/field-contracts.json').read_text())
        cls.dataset = json.loads((REAL_ROOT/'eval/v5/legacy-migration/dataset.json').read_text())

    def case(self, case='disk_space_low', answer=None, extra=False):
        contracts = copy.deepcopy([f for f in self.sidecar['fields'] if f['case_id'] == case])
        schema = build_request_schema(contracts)
        published = [{'key': key, **value} for key, value in schema['facts'].items()]
        if extra: published.append({'key': 'extra_clause', 'question': 'Give the requested secondary outcome.', 'type': 'string|null', 'unit': None})
        if answer is None: answer = 'done\n'+json.dumps({'facts': {f['key']: f['original_gold']['value'] for f in contracts}})
        payload = {'question': 'Synthetic explicit field request.', 'requested_answer_fields': published,
            'answer': answer, 'reference': {'required_findings': [{'key': f['key'], 'statement': f['question']} for f in published]},
            'observations': [{'id': 'o', 'tool': 'synthetic', 'input': '{}', 'output': 'Synthetic reached observation'}]}
        return payload, contracts, schema

    def verdict(self, prepared, overrides=None, unsupported=False):
        overrides = overrides or {}; findings = []
        for finding in prepared['reference']['required_findings']:
            good = overrides.get(finding['key'], True)
            findings.append({'key': finding['key'], 'satisfied': good, 'answer_quote': prepared['answer'].splitlines()[0],
                             'observation_ids': ['o'], 'reason': 'synthetic control'})
        return {'unsupported_claims': unsupported, 'answer_status': 'answered', 'findings': findings, 'reason': 'synthetic'}

    def test_numeric_false_cannot_be_overridden_by_semantic_true(self):
        payload, contracts, schema = self.case(answer='done\n{"facts":{"available_gb":7.45058,"used_percent":92}}')
        prepared = score.build_payload(payload, contracts, schema)
        result = score.grade_components(prepared, self.verdict(prepared))
        self.assertFalse(result['combined_fields']['available_gb'])
        self.assertTrue(result['raw_semantic_fields']['available_gb'])
        self.assertEqual(result['numeric_labels']['available_gb'], {'status': 'fail', 'numeric_correct': False})
        self.assertFalse(result['structured_pass'])

    def test_code_true_still_requires_quantity_and_evidence_semantics(self):
        prepared = score.build_payload(*self.case())
        result = score.grade_components(prepared, self.verdict(prepared, {'available_gb': False}))
        self.assertTrue(result['numeric_labels']['available_gb']['numeric_correct'])
        self.assertFalse(result['combined_fields']['available_gb'])

    def test_categorical_paraphrases_and_null_unknown_are_not_string_exact(self):
        for literal in ('"cannot conclude whether the inventory is empty"', 'null'):
            with self.subTest(literal=literal):
                prepared = score.build_payload(*self.case('inventory_unavailable', 'done\n{"facts":{"empty":'+literal+'}}'))
                result = score.grade_components(prepared, self.verdict(prepared))
                self.assertEqual(prepared['deterministic_numeric_checks'], [])
                self.assertTrue(result['combined_fields']['empty']); self.assertTrue(result['structured_pass'])

    def test_invalid_format_keeps_semantic_categorical_credit_but_not_strict_pass(self):
        prepared = score.build_payload(*self.case('inventory_unavailable', 'done'))
        result = score.grade_components(prepared, self.verdict(prepared))
        self.assertTrue(result['combined_fields']['empty']); self.assertTrue(result['format_ungradable'])
        self.assertFalse(result['structured_pass'])
        numeric = score.build_payload(*self.case(answer='done: available 8 GB, used 92%'))
        result = score.grade_components(numeric, self.verdict(numeric))
        self.assertTrue(all(not x for x in result['combined_fields'].values()))
        self.assertTrue(all(x['status'] == 'ungradable' for x in result['numeric_labels'].values()))

    def test_numeric_symbols_accept_json_number_equivalence_but_not_booleans(self):
        for literal, correct in [('1', True), ('1.0', True), ('true', False), ('"1"', False)]:
            with self.subTest(literal=literal):
                prepared = score.build_payload(*self.case('backup_exit_failed', 'done\n{"facts":{"exit_code":'+literal+',"cause":"unknown"}}'))
                result = score.grade_components(prepared, self.verdict(prepared))
                self.assertEqual(result['combined_fields']['exit_code'], correct)
                self.assertEqual(len(result['numeric_labels']), 1)

    def test_unpublished_or_relabelled_bindings_are_rejected(self):
        payload, contracts, schema = self.case(extra=True)
        for mutate in ('unit', 'question', 'extra', 'duplicate'):
            bad = copy.deepcopy(payload)
            if mutate == 'unit': bad['requested_answer_fields'][0]['unit'] = 'GiB'
            if mutate == 'question': bad['requested_answer_fields'][0]['question'] = 'Different quantity'
            if mutate == 'extra': bad['requested_answer_fields'].pop()
            if mutate == 'duplicate': bad['requested_answer_fields'].append(bad['requested_answer_fields'][0])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): score.build_payload(bad, contracts, schema)

    def test_no_arm_raw_world_or_prior_score_leaks(self):
        payload, contracts, schema = self.case()
        for key in ('arm', 'rawWorldTrace', 'prior_score'):
            bad = dict(payload, **{key: 'hidden'})
            with self.subTest(key=key), self.assertRaises(ValueError): score.build_payload(bad, contracts, schema)
        prepared = score.build_payload(payload, contracts, schema)
        self.assertEqual(prepared['observations'], payload['observations'])
        self.assertEqual(prepared['question'], payload['question']); self.assertEqual(prepared['answer'], payload['answer'])

    def test_bad_entire_json_object_fails_numeric_checks(self):
        prepared = score.build_payload(*self.case(answer='done\n{"facts":{"available_gb":8,"used_percent":92},"unrelated":NaN}'))
        result = score.grade_components(prepared, self.verdict(prepared))
        self.assertTrue(result['format_ungradable']); self.assertFalse(result['structured_pass'])
        self.assertTrue(all(not x for x in result['combined_fields'].values()))

    def test_scored_disagreement_can_differ_from_raw_semantic_disagreement(self):
        prepared = score.build_payload(*self.case(answer='done\n{"facts":{"available_gb":7,"used_percent":92}}'))
        first = score.grade_components(prepared, self.verdict(prepared))
        second = score.grade_components(prepared, self.verdict(prepared, {'available_gb': False}))
        self.assertNotEqual(first['raw_semantic_fields'], second['raw_semantic_fields'])
        self.assertEqual(first['combined_fields'], second['combined_fields'])
        self.assertEqual(first['structured_pass'], second['structured_pass'])

    def test_runner_error_only_prevents_strict_execution_pass(self):
        prepared = score.build_payload(*self.case())
        result = score.grade_components(prepared, self.verdict(prepared), runner_error='transport failure')
        self.assertTrue(result['all_findings_correct']); self.assertFalse(result['structured_pass'])

    def test_210_answer_summary_keeps_62_vs_81_denominators_when_judgments_missing(self):
        with tempfile.TemporaryDirectory(prefix='legacy-summary-test-') as tmp:
            root = Path(tmp); out = root/'eval/v5/legacy-scoring-v55'; (out/'payloads').mkdir(parents=True)
            mapping = []
            for scene in self.dataset['scenarios']:
                contracts = copy.deepcopy([f for f in self.sidecar['fields'] if f['case_id'] == scene['id']])
                schema = build_request_schema(contracts, {f['key']: f['measurement'] for f in scene['answer_fields'] if 'measurement' in f})
                base_payload = {'question': scene['question'], 'requested_answer_fields': scene['answer_fields'],
                    'answer': 'done\n'+json.dumps({'facts': {f['key']: f['original_gold']['value'] for f in contracts}}),
                    'reference': {'required_findings': [{'key': f['key'], 'statement': f['question']} for f in scene['answer_fields']]},
                    'observations': [{'id': 'o', 'tool': 'synthetic', 'input': '{}', 'output': 'synthetic'}]}
                prepared = score.build_payload(base_payload, contracts, schema)
                for arm in score.ARMS:
                    for rep in range(3):
                        ident = f'a{len(mapping)}'; score.api.save(out/'payloads'/f'{ident}.json', prepared)
                        mapping.append({'id': ident, 'case': scene['id'], 'arm': arm, 'rep': rep, 'family': scene['family'],
                            'source_tier': scene['provenance']['kind'], 'runner_error': ''})
            for relative in score.LEDGERS:
                path = root/relative; path.mkdir(); score.api.save(path/'manifest.json', {})
            with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), patch.object(score.budget, 'preflight', return_value={'total_campaigns_estimated_usd': 0}):
                summary = score.summarize(out)
            self.assertEqual(len(summary['answers']), 210)
            for arm in summary['arms'].values():
                self.assertEqual(arm['n'], 105); self.assertEqual(arm['base_field_denominator'], 186)
                self.assertEqual(arm['all_finding_denominator'], 243); self.assertEqual(arm['numeric_field_denominator'], 105)
                self.assertEqual(arm['unresolved'], 105); self.assertEqual(arm['stable_structured_pass'], 0)

    def test_requested_schema_presence_type_and_parse_are_separate(self):
        for facts in ('{}', '{"empty":true}', '{"empty":42}', '{"empty":[]}'):
            with self.subTest(facts=facts):
                prepared = score.build_payload(*self.case('inventory_unavailable', 'done\n{"facts":'+facts+'}'))
                result = score.grade_components(prepared, self.verdict(prepared))
                self.assertTrue(result['format_valid'])
                self.assertFalse(result['requested_schema_valid'])
                self.assertTrue(result['combined_fields']['empty'])
                self.assertFalse(result['structured_pass'])
        prepared = score.build_payload(*self.case(extra=True))
        self.assertFalse(prepared['requested_schema_check']['valid'])
        self.assertEqual(prepared['requested_schema_check']['failures'][0]['key'], 'extra_clause')
    def test_explicit_measurement_binding_and_no_hidden_reference_window(self):
        payload, contracts, _ = self.case()
        key = contracts[0]['key']
        measurement = {'lookback_seconds': 300, 'aggregation': 'rate'}
        schema = build_request_schema(contracts, {key: measurement})
        payload['requested_answer_fields'] = [{'key': k, **v} for k, v in schema['facts'].items()]
        prepared = score.build_payload(payload, contracts, schema)
        self.assertEqual(prepared['deterministic_numeric_checks'][0]['window'], measurement)
        self.assertIsNone(prepared['deterministic_numeric_checks'][1]['window'])
        bad = copy.deepcopy(payload); bad['requested_answer_fields'][0]['measurement']['lookback_seconds'] = 900
        with self.assertRaises(ValueError): score.build_payload(bad, contracts, schema)
        for bad_measurement in ({'lookback_seconds': True, 'aggregation': 'rate'},
                                {**measurement, 'event_offsets': [0]}, {'lookback_seconds': 0, 'aggregation': 'rate'}):
            with self.subTest(measurement=bad_measurement), self.assertRaises(ValueError):
                build_request_schema(contracts, {key: bad_measurement})
    def test_ledger_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory(prefix='legacy-lock-test-') as tmp:
            child = Path(tmp)
            with score.ledger_run_lock(child):
                with self.assertRaises(ValueError):
                    with score.ledger_run_lock(child): self.fail('Concurrent ledger owner')
            with score.ledger_run_lock(child): pass
    def test_two_planned_210_ledgers_mock_calls_and_replay_refusal(self):
        prepared = score.build_payload(*self.case())
        verdict = self.verdict(prepared)
        with tempfile.TemporaryDirectory(prefix='legacy-paid-mock-') as tmp:
            root = Path(tmp); out = root/'eval/v5/legacy-scoring-v55'; (out/'payloads').mkdir(parents=True)
            mapping = []
            for n in range(210):
                ident = f'a{n}'; score.api.save(out/'payloads'/f'{ident}.json', prepared)
                mapping.append({'id': ident, 'runner_error': '', 'payload_sha256': score.api.sha(score.api.encode(prepared).encode())})
            for relative in score.LEDGERS: (root/relative).mkdir()
            with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), \
                 patch.object(score.api, 'key_from_env', return_value='mock'), \
                 patch.object(score.budget, 'preflight', return_value={}), \
                 patch.object(score.budget, 'paid_call', return_value={}) as paid, \
                 patch.object(score.api, 'response_json', return_value=verdict), \
                 patch.object(score, 'summarize', return_value={}):
                score.run(out)
                self.assertEqual(paid.call_count, 420)
                self.assertEqual([len(score.api.lines(root/r/'results.jsonl')) for r in score.LEDGERS], [210, 210])
                with self.assertRaises(ValueError): score.run(out, 0)
                self.assertEqual(paid.call_count, 420)
    def test_parse_or_schema_failure_masks_even_fabricated_prose_to_unassessed(self):
        for answer in ('The host exploded. done', 'done\n{"facts":{"empty":true}}', 'done\n{"facts":{}}'):
            for raw_flag in (True, False):
                with self.subTest(answer=answer, raw_flag=raw_flag):
                    prepared = score.build_payload(*self.case('inventory_unavailable', answer))
                    result = score.grade_components(prepared, self.verdict(prepared, unsupported=raw_flag))
                    self.assertEqual(result['unsupported_assessment'], 'unassessed')
                    self.assertIsNone(result['unsupported_claims'])
                    self.assertIs(result['raw_unsupported_claims'], raw_flag)
                    self.assertFalse(result['structured_pass'])
                    self.assertTrue(result['combined_fields']['empty'])
    def test_valid_false_numeric_entity_and_window_facts_remain_assessed(self):
        prepared = score.build_payload(*self.case(answer='done\n{"facts":{"available_gb":7,"used_percent":92}}'))
        result = score.grade_components(prepared, self.verdict(prepared, unsupported=True))
        self.assertEqual(result['unsupported_assessment'], 'assessed')
        self.assertIs(result['unsupported_claims'], True)
        self.assertFalse(result['combined_fields']['available_gb'])
        self.assertFalse(result['structured_pass'])
        for mismatch in ('wrong entity', 'wrong observation window'):
            with self.subTest(mismatch=mismatch):
                prepared = score.build_payload(*self.case())
                verdict = self.verdict(prepared, {'available_gb': False}, unsupported=True)
                verdict['findings'][0]['reason'] = mismatch
                result = score.grade_components(prepared, verdict)
                self.assertTrue(result['numeric_labels']['available_gb']['numeric_correct'])
                self.assertFalse(result['combined_fields']['available_gb'])
                self.assertIs(result['unsupported_claims'], True)
                self.assertFalse(result['structured_pass'])
    def test_native_atomic_contract_derives_pass_and_rejects_model_pass_or_null_flag(self):
        prepared = score.build_payload(*self.case())
        atomic = self.verdict(prepared)
        self.assertNotIn('pass', atomic)
        self.assertTrue(score.grade_components(prepared, atomic)['structured_pass'])
        for value in (True, False, None):
            with self.subTest(model_pass=value), self.assertRaises(ValueError):
                score.grade_components(prepared, {**atomic, 'pass': value})
        with self.assertRaises(ValueError):
            score.grade_components(prepared, {**atomic, 'unsupported_claims': None})
    def test_unsupported_bounds_use_unique_answer_union_and_all_answer_denominator(self):
        kinds = ('clean', 'asserted_wrong', 'parse_invalid', 'schema_invalid', 'missing',
                 'duplicate', 'unsupported_disagreement', 'field_disagreement')
        with tempfile.TemporaryDirectory(prefix='v54-unsupported-bounds-') as tmp:
            root = Path(tmp); out = root/'eval/v5/legacy-scoring-v55'; (out/'payloads').mkdir(parents=True)
            for relative in score.LEDGERS:
                child = root/relative; child.mkdir(); score.api.save(child/'manifest.json', {})
            mapping = []
            for arm in score.ARMS:
                for kind in kinds:
                    answer = ('done' if kind == 'parse_invalid' else 'done\n{"facts":{}}' if kind == 'schema_invalid'
                              else 'done\n{"facts":{"empty":"unknown"}}')
                    prepared = score.build_payload(*self.case('inventory_unavailable', answer))
                    ident = arm+'-'+kind; score.api.save(out/'payloads'/f'{ident}.json', prepared)
                    mapping.append({'id': ident, 'case': kind, 'arm': arm, 'rep': 0, 'family': kind,
                                    'source_tier': 'synthetic', 'runner_error': ''})
                    for rep in (0, 1):
                        if kind == 'missing' and rep == 1: continue
                        unsupported = kind == 'asserted_wrong' or (kind == 'unsupported_disagreement' and rep == 1)
                        overrides = {'empty': False} if kind == 'field_disagreement' and rep == 1 else None
                        row = {'id': ident, 'judge_rep': rep, 'semantic_result': self.verdict(prepared, overrides, unsupported)}
                        score.api.append(root/score.LEDGERS[rep]/'results.jsonl', row)
                        if kind == 'duplicate' and rep == 0: score.api.append(root/score.LEDGERS[rep]/'results.jsonl', row)
            with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), \
                 patch.object(score.budget, 'preflight', return_value={}):
                summary = score.summarize(out)
            for main_arm in summary['arms'].values():
                self.assertFalse(any('unsupported' in key for key in main_arm))
                self.assertEqual(main_arm['n'], 8)
                arm = main_arm['unvalidated_auxiliary_diagnostics']
                self.assertEqual(arm['unsupported_assessment_denominator'], 8)
                self.assertEqual(arm['unsupported_format_eligible'], 6)
                self.assertEqual(arm['unsupported_assessed_both'], 4)
                self.assertEqual(arm['unsupported_unassessed_format_or_schema'], 2)
                self.assertEqual(arm['unsupported_specific_disagreements'], 1)
                self.assertEqual(arm['unsupported_unresolved'], 5)
                self.assertEqual(arm['stable_unsupported_free'], 2)
                self.assertEqual(arm['unsupported_count_bounds'], {'lower': 1, 'upper': 6})
                self.assertEqual(arm['unsupported_percent_bounds'], {'lower': 12.5, 'upper': 75.0})
                self.assertEqual(main_arm['unresolved'], 4)
                self.assertEqual(main_arm['stable_structured_pass'], 1)
    def test_atomic_composition_is_identical_to_frozen_v54(self):
        import inspect
        import score_legacy_eval_v54 as previous
        self.assertEqual(inspect.getsource(score.grade_components), inspect.getsource(previous.grade_components))
        self.assertEqual(score.SYSTEM, previous.SYSTEM)
        self.assertIs(score.api, previous.api)
    def test_only_final_fields_and_strict_pass_control_scored_agreement(self):
        for wrong_numeric, invalid_verdict in ((True, False), (False, False), (True, True)):
            with self.subTest(wrong_numeric=wrong_numeric, invalid_verdict=invalid_verdict), tempfile.TemporaryDirectory(prefix='v55-agreement-') as tmp:
                root = Path(tmp); out = root/'eval/v5/legacy-scoring-v55'; (out/'payloads').mkdir(parents=True)
                for relative in score.LEDGERS:
                    child = root/relative; child.mkdir(); score.api.save(child/'manifest.json', {})
                answer = 'done\n{"facts":{"available_gb":'+('7' if wrong_numeric else '8')+',"used_percent":92}}'
                prepared = score.build_payload(*self.case(answer=answer))
                mapping = []
                for arm in score.ARMS:
                    ident = arm; score.api.save(out/'payloads'/f'{ident}.json', prepared)
                    mapping.append({'id': ident, 'case': 'synthetic', 'arm': arm, 'rep': 0, 'family': 'synthetic',
                                    'source_tier': 'synthetic', 'runner_error': ''})
                    for rep in (0, 1):
                        verdict = self.verdict(prepared, unsupported=rep == 1)
                        if invalid_verdict and rep == 1: verdict['unsupported_claims'] = None
                        score.api.append(root/score.LEDGERS[rep]/'results.jsonl', {'id': ident, 'judge_rep': rep, 'semantic_result': verdict})
                with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), \
                     patch.object(score.budget, 'preflight', return_value={}):
                    summary = score.summarize(out)
                for row in summary['answers']:
                    self.assertEqual(row['scored_agreement'], wrong_numeric and not invalid_verdict)
                    self.assertFalse(row['stable_structured_pass'])
                    self.assertFalse(any('unsupported' in key for key in row))
                    aux = row['unvalidated_auxiliary_diagnostics']
                    self.assertEqual(aux['validation_status'], 'unvalidated_auxiliary_only_not_for_ranking')
                    if invalid_verdict: self.assertIn('invalid_judgment', row['integrity_errors'])
                    else: self.assertTrue(aux['raw_semantic_disagreement'])
                for arm in summary['arms'].values():
                    self.assertEqual(arm['unresolved'], 0 if wrong_numeric and not invalid_verdict else 1)
                    self.assertFalse(any('unsupported' in key for key in arm))
                    self.assertNotIn('raw_semantic_disagreements', arm)
    def test_independent_gate_rejects_wrong_pipeline_or_failed_labels(self):
        with tempfile.TemporaryDirectory(prefix='legacy-gate-test-') as tmp:
            root = Path(tmp); base = root/'migration'; validation = root/'validation'; base.mkdir(); validation.mkdir()
            (base/'numeric-bridge-holdout-v55.json').write_text('{"synthetic_test_only":true}')
            identity = {'scorer_code_sha256': 'test-scorer'}
            manifest = {**identity, 'holdout_sha256': score.digest(base/'numeric-bridge-holdout-v55.json')}
            score.api.save(validation/'manifest.json', manifest)
            score.api.save(validation/'summary.json', {'gate_passed': True, 'cases': 20, 'judgments': 60})
            with patch.object(score, 'VALIDATION', validation), patch.object(score, 'bridge_identity', return_value=identity):
                score._bridge_gate(base)
                score.api.save(validation/'summary.json', {'gate_passed': False, 'cases': 20, 'judgments': 60})
                with self.assertRaises(ValueError): score._bridge_gate(base)
                score.api.save(validation/'summary.json', {'gate_passed': True, 'cases': 20, 'judgments': 60})
                score.api.save(validation/'manifest.json', {**manifest, 'scorer_code_sha256': 'different'})
                with self.assertRaises(ValueError): score._bridge_gate(base)


if __name__ == '__main__': unittest.main()
