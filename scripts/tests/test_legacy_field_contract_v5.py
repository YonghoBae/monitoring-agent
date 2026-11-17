"""Offline synthetic adapter checks; legacy fixtures supply contracts, never live answers."""
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from legacy_field_contract_v5 import build_request_schema, extract_final_facts, grade_fields
import numeric_contract_v12 as numeric

ROOT = Path(__file__).resolve().parents[2]


class LegacyFieldContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidecar = json.loads((ROOT/'eval/v5/legacy-migration/field-contracts.json').read_text())

    def contracts(self, case='disk_space_low'):
        return copy.deepcopy([f for f in self.sidecar['fields'] if f['case_id'] == case])

    def grade(self, answer, case='disk_space_low', contracts=None, schema=None):
        fields = self.contracts(case) if contracts is None else contracts
        return grade_fields(answer, fields, request_schema=build_request_schema(fields) if schema is None else schema)

    def test_complete_enclosing_object_and_spans_are_verbatim(self):
        answer = '설명입니다.\n```json\n { "facts" : {"available_gb":8,"used_percent":92}, "extra":{"braces":"} [ \\\" {"}} \n```\n'
        result = self.grade(answer)
        self.assertTrue(result['all_deterministic_fields_pass'])
        start, end = result['answer_object_span']
        self.assertEqual(answer[start:end], result['answer_object_quote'])
        self.assertIn(result['facts_quote'], answer)
        for field in result['fields']:
            start, end = field['span']; self.assertEqual(answer[start:end], field['quote'])
            self.assertEqual(field['semantic_association'], 'not_assessed')
            self.assertEqual(field['window_association'], 'not_assessed')
            self.assertEqual(field['evidence_grounding'], 'not_assessed')

    def test_nonfinite_constants_and_duplicates_anywhere_in_selected_object_reject(self):
        extras = ['"x":NaN', '"x":Infinity', '"x":-Infinity', '"x":{"a":1,"a":2}',
                  '"x":[{"a":1,"\\u0061":2}]', '"x":1,"x":2']
        for extra in extras:
            for placement in ('before', 'after'):
                facts = '"facts":{"available_gb":8,"used_percent":92}'
                answer = '{'+(extra+','+facts if placement == 'before' else facts+','+extra)+'}'
                with self.subTest(extra=extra, placement=placement):
                    result = self.grade(answer)
                    self.assertEqual(result['format_status'], 'ungradable')
                    self.assertTrue(result['structured_nonpass'])
                    self.assertTrue(all(f['numeric_correct'] is None for f in result['fields']))

    def test_duplicate_bound_keys_and_facts_roots_reject(self):
        for answer in ('{"facts":{"available_gb":8,"available_gb":7,"used_percent":92}}',
                       '{"facts":{},"facts":{"available_gb":8,"used_percent":92}}'):
            with self.subTest(answer=answer): self.assertEqual(self.grade(answer)['format_status'], 'ungradable')

    def test_final_block_not_an_earlier_nested_or_valid_example_is_selected(self):
        earlier = '```json\n{"facts":{"available_gb":1,"used_percent":1}}\n```\n'
        final = '```json\n{"facts":{"available_gb":8,"used_percent":92}}\n```'
        self.assertTrue(self.grade(earlier+final)['all_deterministic_fields_pass'])
        for tail in ('```json\n{"facts":{"available_gb":8},"x":NaN}\n```',
                     '```json\n{"wrapper":{"facts":{"available_gb":8}}}\n```',
                     '```text\n{"facts":{"available_gb":8}}\n```'):
            with self.subTest(tail=tail): self.assertEqual(self.grade(earlier+tail)['format_status'], 'ungradable')

    def test_prose_and_malformed_format_are_ungradable_not_numeric_false(self):
        cases = ['8 GB and 92%', 'unknown', '', '{"facts":{"available_gb":8,}}',
                 '{"facts":{"available_gb":8}', '[{"facts":{"available_gb":8}}]',
                 '```json\n{"facts":{}}', '{"facts":{}} trailing',
                 '{"facts":{}} {"not_facts":8}']
        for answer in cases:
            with self.subTest(answer=answer):
                result = self.grade(answer)
                self.assertEqual(result['format_status'], 'ungradable')
                self.assertTrue(result['structured_nonpass'])
                self.assertTrue(all(f['status'] == 'ungradable' and f['numeric_correct'] is None for f in result['fields']))

    def test_missing_null_and_string_unknown_remain_distinct(self):
        for value, presence, reason in [('{}', 'missing', 'missing_field'),
            ('{"empty":null}', 'null', 'explicit_null_requires_semantic_unknown_check'),
            ('{"empty":"unknown"}', 'value', 'typed_exact_match')]:
            with self.subTest(value=value):
                field = self.grade('{"facts":'+value+'}', case='inventory_unavailable')['fields'][0]
                self.assertEqual(field['presence'], presence); self.assertEqual(field['reason'], reason)
                if presence != 'value': self.assertIsNone(field['value_correct'])
                self.assertEqual(field['reported_unknown'], presence != 'missing')

    def test_categorical_codes_respect_published_json_number_type(self):
        for literal, passed in [('1', True), ('1.0', True), ('1e0', True), ('1.1', False),
                                ('true', False), ('false', False), ('"1"', False), ('"1 count"', False)]:
            with self.subTest(literal=literal):
                answer = '{"facts":{"exit_code":'+literal+',"cause":"unknown"}}'
                field = self.grade(answer, case='backup_exit_failed')['fields'][0]
                self.assertEqual(field['status'] == 'pass', passed)
                self.assertIsNone(field['numeric_correct'])
                self.assertIs(type(field['value_correct']), bool)

    def test_numeric_booleans_and_unit_strings_do_not_become_numbers(self):
        for literal in ('true', 'false', '"8"', '"7.45058 GiB"', '[8]', '{"value":8}'):
            with self.subTest(literal=literal):
                field = self.grade('{"facts":{"available_gb":'+literal+',"used_percent":92}}')['fields'][0]
                self.assertEqual(field['status'], 'ungradable'); self.assertIsNone(field['numeric_correct'])

    def test_explicit_schema_is_required_and_cannot_borrow_gold_units(self):
        answer = '{"facts":{"available_gb":8,"used_percent":92}}'
        for schema in ({}, {'facts': {'available_gb': {'type': 'number'}}}):
            with self.subTest(schema=schema):
                result = self.grade(answer, schema=schema)
                self.assertTrue(all(f['reason'] == 'unbound_request_schema' for f in result['fields']))
        contracts = self.contracts(); contracts[0]['answer_binding']['unit'] = None
        with self.assertRaises(ValueError): build_request_schema(contracts)

    def test_schema_discloses_no_gold_values_or_evidence(self):
        schema = build_request_schema(self.contracts())
        self.assertNotIn('original_gold', json.dumps(schema))
        for field in schema['facts'].values():
            self.assertEqual(set(field), {'question', 'type', 'unit'})

    def test_no_gb_gib_relabeling_and_tolerance_is_preserved(self):
        field = self.grade('{"facts":{"available_gb":7.45058,"used_percent":92}}')['fields'][0]
        self.assertFalse(field['numeric_correct']); self.assertEqual(field['unit'], 'GB')
        self.assertEqual(field['original_gold']['tolerance'], .01)
        self.assertEqual(field['numeric_result']['allowed_error'], '10000000')

    def test_inconsistent_sidecar_does_not_change_value_or_tolerance(self):
        fields = self.contracts(); fields[0]['numeric_contract']['tolerance']['absolute'] = '100'
        result = self.grade('{"facts":{"available_gb":7,"used_percent":92}}', contracts=fields)
        self.assertEqual(result['fields'][0]['reason'], 'inconsistent_numeric_sidecar')
        self.assertEqual(result['fields'][0]['original_gold']['value'], 8)

    def test_all_62_source_values_and_tolerances_survive_adapter(self):
        source = ROOT/self.sidecar['source_dataset']
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), self.sidecar['source_sha256'])
        original = json.loads(source.read_text())
        checked = 0
        for scene in original['scenarios']:
            if scene['split'] != 'test': continue
            contracts = self.contracts(scene['id'])
            for field, gold in zip(contracts, scene['gold']): self.assertEqual(field['original_gold'], gold)
            answer = json.dumps({'facts': {g['key']: g['value'] for g in scene['gold']}}, ensure_ascii=False)
            result = self.grade(answer, contracts=contracts)
            with self.subTest(case=scene['id']): self.assertTrue(result['all_deterministic_fields_pass'], result)
            for field, gold in zip(result['fields'], scene['gold']): self.assertEqual(field['original_gold'], gold)
            json.dumps(result); checked += len(result['fields'])
        self.assertEqual(checked, 62)

    def test_new_units_exact_conversions_and_dimensions(self):
        cases = [('3 day', '259200', 's', 'pass'), ('172800 s', '2', 'day', 'pass'),
                 ('1.25 days', '108000', 's', 'pass'), ('88 °C', '88', '°C', 'pass'),
                 ('88 Celsius', '88', '°C', 'pass'), ('3.8 cores', '3.8', 'core', 'pass'),
                 ('3.8 코어', '3.8', 'core', 'pass'), ('88 °F', '88', '°C', 'ungradable'),
                 ('361.15 K', '88', '°C', 'ungradable'), ('3.8 count', '3.8', 'core', 'fail'),
                 ('380 %', '3.8', 'core', 'fail'), ('88 s', '88', '°C', 'fail')]
        for text, value, unit, status in cases:
            with self.subTest(text=text):
                self.assertEqual(numeric.grade_numeric(text, text, {'value': value, 'unit': unit})['status'], status)

    def test_depth_and_number_bounds_fail_closed(self):
        for extra in ('['*66+'0'+']'*66, '1e1001', '9'*257):
            with self.subTest(extra=extra):
                answer = '{"facts":{"available_gb":8,"used_percent":92},"extra":'+extra+'}'
                self.assertEqual(self.grade(answer)['format_status'], 'ungradable')


if __name__ == '__main__': unittest.main()
