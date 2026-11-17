"""Independent offline v53 transport/schema controls; no paid holdout access."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic_judge_v53 as judge
import structured_haiku_v5 as transport
import score_legacy_eval_v53 as score

def payload(answer='Observed "quoted" text.\n{"facts":{"state":"known"}}', observations=True):
    return {'question': 'Report state and scope.', 'answer': answer,
        'reference': {'required_findings': [{'key': 'state'}, {'key': 'scope'}]},
        'observations': [{'id': 'seen-1', 'tool': 'status', 'input': '{}', 'output': 'known'}] if observations else []}
def verdict(p):
    return {'pass': True, 'unsupported_claims': False, 'answer_status': 'answered',
        'findings': [{'key': key, 'satisfied': True, 'answer_quote': p['answer'],
                      'observation_ids': ['seen-1'] if p['observations'] else [], 'reason': 'Synthetic'}
                     for key in ('state', 'scope')], 'reason': 'Synthetic'}

class IndependentStructuredSchemaTest(unittest.TestCase):
    def test_quotes_are_exact_with_unicode_crlf_and_embedded_json(self):
        for answer in ('가나다 "x"\r\n{"facts":{"v":"\\n"}}', 'A\u2028B', '', '  \n\t'):
            with self.subTest(answer=answer):
                choices = judge.quote_choices(answer)
                self.assertEqual(len(choices), len(set(choices)))
                self.assertTrue(all(choice in answer for choice in choices))
                self.assertIn('', choices); self.assertIn(answer, choices)
                encoded = json.dumps(judge.response_schema(payload(answer)), ensure_ascii=False)
                self.assertEqual(json.loads(encoded)['properties']['findings']['items']['properties']['answer_quote']['enum'], choices)
    def test_exact_quotes_and_ids_revalidated_even_if_provider_ignores_enums(self):
        p = payload(); good = verdict(p); judge.validate(good, p)
        for mode in ('escaped', 'translated', 'missing', 'duplicate', 'new_id', 'id_case', 'empty_quote', 'unknown_key'):
            bad = copy.deepcopy(good)
            if mode == 'escaped': bad['findings'][0]['answer_quote'] = p['answer'].replace('"', '\\"')
            if mode == 'translated': bad['findings'][0]['answer_quote'] = '관측된 텍스트'
            if mode == 'missing': bad['findings'].pop()
            if mode == 'duplicate': bad['findings'][1] = copy.deepcopy(bad['findings'][0])
            if mode == 'new_id': bad['findings'][0]['observation_ids'] = ['unseen']
            if mode == 'id_case': bad['findings'][0]['observation_ids'] = ['SEEN-1']
            if mode == 'empty_quote': bad['findings'][0]['answer_quote'] = ''
            if mode == 'unknown_key': bad['extra'] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError): judge.validate(bad, p)
    def test_no_observations_does_not_admit_invented_citation(self):
        p = payload(observations=False); result = verdict(p)
        judge.validate(result, p)
        result['findings'][0]['observation_ids'] = ['invented']
        with self.assertRaises(ValueError): judge.validate(result, p)
    def test_boolean_types_and_pass_consistency_fail_closed(self):
        p = payload()
        for field, value in (('pass', 1), ('unsupported_claims', 0), ('pass', False), ('answer_status', 'Answered')):
            bad = verdict(p); bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): judge.validate(bad, p)
    def test_transport_refuses_fences_duplicate_keys_nonfinite_or_wrong_envelope(self):
        base = {'model': transport.MODEL, 'stop_reason': 'end_turn'}
        for text in ('```json\n{}\n```', '{"pass":true,"pass":false}', '{"x":NaN}', '{"x":Infinity}', '{'):
            with self.subTest(text=text), self.assertRaises((ValueError, json.JSONDecodeError)):
                transport.response_json(base | {'content': [{'type': 'text', 'text': text}]})
        for replacement in ({'model': 'different'}, {'stop_reason': 'max_tokens'}, {'stop_reason': 'refusal'}):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                transport.response_json(base | {'content': [{'type': 'text', 'text': '{}'}]} | replacement)
        with self.assertRaises(ValueError):
            transport.response_json(base | {'content': [{'type': 'text', 'text': '{}'}]*2})
    def test_v53_pipeline_freezes_new_helper_and_retains_numeric_adapter(self):
        self.assertIs(score.api, transport); self.assertIs(score.validate, judge.validate)
        required = {'scripts/score_legacy_eval_v53.py', 'scripts/semantic_judge_v53.py',
                    'scripts/structured_haiku_v5.py', 'scripts/haiku_rejudge.py',
                    'scripts/legacy_field_contract_v5.py', 'scripts/numeric_contract_v12.py'}
        self.assertTrue(required <= set(score.CODE))
        identity = score.bridge_identity()
        self.assertEqual(identity['transport_code_sha256'], score.digest(Path(transport.__file__)))
        self.assertEqual(identity['judge_code_sha256'], score.digest(Path(judge.__file__)))

class IndependentStructuredTransportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name); (self.out/'raw').mkdir()
        transport.save(self.out/'manifest.json', {'prior_campaign_cost_usd': 0})
    def response(self):
        result = {'model': transport.MODEL, 'stop_reason': 'end_turn',
                  'usage': {'input_tokens': 10, 'output_tokens': 10},
                  'content': [{'type': 'text', 'text': json.dumps(verdict(payload()))}]}
        response = io.StringIO(json.dumps(result)); response.headers = {'request-id': 'offline-test'}
        return response
    def test_reservation_includes_full_schema_and_completed_id_is_single_use(self):
        captured = []
        def fake_http(request, **kwargs): captured.append(request.data); return self.response()
        with patch.object(transport.urllib.request, 'urlopen', side_effect=fake_http):
            transport.call(self.out, 'one', payload(), 'unused-dummy', 'synthetic')
            with self.assertRaisesRegex(ValueError, 'already used'):
                transport.call(self.out, 'one', payload(), 'unused-dummy', 'synthetic')
        self.assertEqual(len(captured), 1)
        body = json.loads(captured[0]); schema = body['output_config']['format']['schema']
        self.assertEqual(body['output_config']['format']['type'], 'json_schema')
        self.assertEqual(schema, judge.response_schema(payload()))
        events = transport.lines(self.out/'requests.jsonl'); start = events[0]
        expected = ((len(captured[0])+4096)*.10 + transport.MAX_OUTPUT*.50)/1e6
        self.assertAlmostEqual(start['reserved_usd'], expected)
        self.assertEqual(start['response_schema_sha256'], transport.sha(transport.encode(schema)))
    def test_http_error_is_recorded_without_retry_or_new_identity(self):
        failure = urllib.error.HTTPError('https://example.invalid', 429, 'synthetic', {}, None)
        with patch.object(transport.urllib.request, 'urlopen', side_effect=failure) as http:
            with self.assertRaises(RuntimeError): transport.call(self.out, 'one', payload(), 'unused', 'synthetic')
            with self.assertRaisesRegex(ValueError, 'already used'): transport.call(self.out, 'one', payload(), 'unused', 'synthetic')
        self.assertEqual(http.call_count, 1)
        self.assertEqual([e['event'] for e in transport.lines(self.out/'requests.jsonl')], ['started', 'http_error'])
    def test_uncertain_outcome_blocks_even_different_request_id(self):
        with patch.object(transport.urllib.request, 'urlopen', side_effect=OSError('synthetic timeout')) as http:
            with self.assertRaises(OSError): transport.call(self.out, 'one', payload(), 'unused', 'synthetic')
            with self.assertRaisesRegex(ValueError, 'Uncertain'): transport.call(self.out, 'two', payload(), 'unused', 'synthetic')
        self.assertEqual(http.call_count, 1)
    def test_budget_ceiling_and_unsafe_request_id_stop_before_transmission(self):
        with patch.object(transport.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')):
            with self.assertRaises(ValueError): transport.call(self.out, '../escape', payload(), 'unused', 'synthetic')
            transport.save(self.out/'manifest.json', {'prior_campaign_cost_usd': 2})
            with self.assertRaisesRegex(ValueError, 'cap'): transport.call(self.out, 'one', payload(), 'unused', 'synthetic')
        self.assertFalse((self.out/'requests.jsonl').exists())
if __name__ == '__main__': unittest.main()
