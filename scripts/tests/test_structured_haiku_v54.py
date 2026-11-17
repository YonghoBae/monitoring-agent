"""Offline structured transport/schema tests; no benchmark or holdout answers."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import structured_haiku_v54 as api
import semantic_judge_v54 as judge
import budget_registry as budget


def payload(answer='Healthy.\n{"facts":{"health":"okay"}}', observations=True):
    return {'question': 'Report service health.', 'answer': answer,
            'reference': {'required_findings': [{'key': 'health', 'statement': 'Healthy.'}]},
            'observations': [{'id': 'observed-1', 'tool': 'status', 'input': '{}', 'output': 'okay'}] if observations else []}


def verdict(p):
    return {'unsupported_claims': False, 'answer_status': 'answered',
            'findings': [{'key': 'health', 'satisfied': True, 'answer_quote': p['answer'],
                          'observation_ids': [o['id'] for o in p['observations']], 'reason': 'Observed.'}],
            'reason': 'Observed.'}


def response(p):
    return {'model': api.MODEL, 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': json.dumps(verdict(p))}],
            'usage': {'input_tokens': 120, 'output_tokens': 80}}


class Reply(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode()); self.headers = {'request-id': 'mock-server-id'}


class StructuredSchemaTest(unittest.TestCase):
    def test_all_response_fields_required_and_no_additional_properties(self):
        schema = judge.response_schema(payload())
        for node in (schema, schema['properties']['findings']['items']):
            self.assertEqual(set(node['required']), set(node['properties']))
            self.assertIs(node['additionalProperties'], False)
        self.assertEqual(schema['properties']['findings']['items']['properties']['key']['enum'], ['health'])
    def test_quote_choices_preserve_exact_unicode_escaping_whitespace_and_full_answer(self):
        answer = '  경로 "C:\\temp" 정상  \r\n\n{"facts":{"health":"okay"}}\n'
        choices = judge.quote_choices(answer)
        self.assertIn('', choices); self.assertIn(answer, choices)
        self.assertIn('  경로 "C:\\temp" 정상  ', choices)
        self.assertTrue(all(choice in answer for choice in choices))
        self.assertEqual(len(choices), len(set(choices)))
    def test_no_expected_verdict_labels_enter_schema(self):
        p = payload(); schema = judge.response_schema(p)
        changed = copy.deepcopy(p); changed['reference']['required_findings'][0]['statement'] = 'Unhealthy.'
        changed['deterministic_numeric_checks'] = [{'numeric_correct': False}]
        self.assertEqual(schema, judge.response_schema(changed))
    def test_observation_enums_are_only_delivered_ids_and_empty_list_works(self):
        schema = judge.response_schema(payload())
        self.assertEqual(schema['properties']['findings']['items']['properties']['observation_ids']['items']['enum'], ['observed-1'])
        p = payload(observations=False); schema = judge.response_schema(p)
        self.assertEqual(schema['properties']['findings']['items']['properties']['observation_ids']['items'], {'type': 'string'})
        self.assertEqual(judge.validate(verdict(p), p), {**verdict(p), 'derived_pass': True})
        bad = verdict(p); bad['findings'][0]['observation_ids'] = ['invented']
        with self.assertRaises(ValueError): judge.validate(bad, p)
    def test_local_validator_rejects_duplicates_missing_case_changes_and_repaired_quotes(self):
        p = payload()
        for mutation in ('duplicate', 'missing', 'quote_case', 'quote_substring', 'extra', 'string_bool', 'ids_string'):
            bad = verdict(p)
            if mutation == 'duplicate': bad['findings'].append(copy.deepcopy(bad['findings'][0]))
            if mutation == 'missing': bad['findings'] = []
            if mutation == 'quote_case': bad['findings'][0]['answer_quote'] = p['answer'].lower()
            if mutation == 'quote_substring': bad['findings'][0]['answer_quote'] = 'Healthy'
            if mutation == 'extra': bad['extra'] = True
            if mutation == 'string_bool': bad['unsupported_claims'] = 'false'
            if mutation == 'ids_string': bad['findings'][0]['observation_ids'] = 'observed-1'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): judge.validate(bad, p)
    def test_empty_answer_requires_fixed_local_invariants(self):
        p = payload(''); bad = verdict(p)
        with self.assertRaises(ValueError): judge.validate(bad, p)
        good = {'unsupported_claims': False, 'answer_status': 'unanswered',
                'findings': [{'key': 'health', 'satisfied': False, 'answer_quote': '', 'observation_ids': [], 'reason': 'Empty'}], 'reason': 'Empty'}
        self.assertEqual(judge.validate(good, p), {**good, 'derived_pass': False})
    def test_request_uses_official_format_and_unchanged_model_effort(self):
        body = api.request_body(payload())
        self.assertEqual(body['output_config']['effort'], 'medium')
        self.assertEqual(body['output_config']['format'], {'type': 'json_schema', 'schema': judge.response_schema(payload())})
        self.assertEqual(body['model'], 'claude-haiku-5-5'); self.assertEqual(body['max_tokens'], 4096)
        self.assertNotIn('tools', body); self.assertNotIn('output_format', body)
    def test_strict_response_parse_never_strips_fences_or_repairs_json(self):
        p = payload(); value = response(p)
        self.assertEqual(api.response_json(value), verdict(p))
        for bad_text in ('```json\n{}\n```', '{"a":1,"a":2}', '{"a":NaN}', '{'):
            bad = copy.deepcopy(value); bad['content'][0]['text'] = bad_text
            with self.subTest(text=bad_text), self.assertRaises(ValueError): api.response_json(bad)
        for stop in ('max_tokens', 'refusal'):
            with self.subTest(stop=stop), self.assertRaises(ValueError): api.response_json({**value, 'stop_reason': stop})


class StructuredTransportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='structured-transport-')
        self.root = Path(self.tmp.name); self.out = self.root/'eval/current'; (self.out/'raw').mkdir(parents=True)
        api.save(self.out/'manifest.json', {'prior_campaign_cost_usd': 0})
        api.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2, 'campaigns': ['eval/prior', 'eval/current']})
        self.p = payload()
    def tearDown(self): self.tmp.cleanup()
    def test_real_request_body_reservation_and_actual_usage_ledger(self):
        with patch.object(api.urllib.request, 'urlopen', return_value=Reply(response(self.p))) as http:
            result = budget.paid_call(api, self.root, self.out, 'one', self.p, 'mock', 'test', judge.SYSTEM)
        request = http.call_args.args[0]; body = json.loads(request.data)
        self.assertEqual(body, api.request_body(self.p)); self.assertEqual(request.full_url, 'https://api.anthropic.com/v1/messages')
        events = api.lines(self.out/'requests.jsonl')
        reserve = ((len(request.data)+4096)*.10+api.MAX_OUTPUT*.50)/1e6
        self.assertEqual(events[0]['reserved_usd'], reserve)
        self.assertEqual(events[0]['payload_sha256'], api.sha(request.data))
        self.assertEqual(events[1]['cost_usd'], api.usage_cost(result['usage']))
        self.assertEqual(api.cost_state(self.out)['completed'], 1)
    def test_completed_or_http_failed_id_never_retried(self):
        with patch.object(api.urllib.request, 'urlopen', return_value=Reply(response(self.p))) as http:
            api.call(self.out, 'one', self.p, 'mock', 'test')
            with self.assertRaises(ValueError): api.call(self.out, 'one', self.p, 'mock', 'test')
            self.assertEqual(http.call_count, 1)
        error = urllib.error.HTTPError('mock', 429, 'limited', {}, None)
        with patch.object(api.urllib.request, 'urlopen', side_effect=error) as http:
            with self.assertRaises(RuntimeError): api.call(self.out, 'two', self.p, 'mock', 'test')
            with self.assertRaises(ValueError): api.call(self.out, 'two', self.p, 'mock', 'test')
            self.assertEqual(http.call_count, 1)
    def test_timeout_stays_unresolved_and_blocks_all_future_calls(self):
        with patch.object(api.urllib.request, 'urlopen', side_effect=TimeoutError('unknown outcome')) as http:
            with self.assertRaises(TimeoutError): api.call(self.out, 'one', self.p, 'mock', 'test')
            with self.assertRaises(ValueError): api.call(self.out, 'two', self.p, 'mock', 'test')
            self.assertEqual(http.call_count, 1)
        self.assertEqual(api.cost_state(self.out)['unresolved_requests'], 1)
        with self.assertRaises(ValueError): budget.preflight(self.root, self.out)
    def test_global_cost_prior_updated_and_reservation_blocks_before_http(self):
        prior = self.root/'eval/prior'; prior.mkdir()
        api.append(prior/'requests.jsonl', {'event': 'started', 'request_id': 'old'})
        api.append(prior/'requests.jsonl', {'event': 'completed', 'request_id': 'old', 'cost_usd': 1.9999})
        with patch.object(api.urllib.request, 'urlopen') as http:
            with self.assertRaises(ValueError): budget.paid_call(api, self.root, self.out, 'one', self.p, 'mock', 'test', judge.SYSTEM)
            http.assert_not_called()
        self.assertEqual(api.read(self.out/'manifest.json')['prior_campaign_cost_usd'], 1.9999)
        self.assertEqual(api.lines(self.out/'requests.jsonl'), [])
    def test_unregistered_campaign_and_uncertain_prior_refused_without_http(self):
        with patch.object(api.urllib.request, 'urlopen') as http:
            with self.assertRaises(ValueError): budget.paid_call(api, self.root, self.root/'other', 'one', self.p, 'mock', 'test', judge.SYSTEM)
            prior = self.root/'eval/prior'; prior.mkdir()
            api.append(prior/'requests.jsonl', {'event': 'started', 'request_id': 'old'})
            with self.assertRaises(ValueError): budget.paid_call(api, self.root, self.out, 'one', self.p, 'mock', 'test', judge.SYSTEM)
            http.assert_not_called()
    def test_call_cap_and_schema_bytes_counted_before_http(self):
        state = {'unresolved_requests': 0, 'total_campaigns_estimated_usd': 0, 'attempts': 240}
        with patch.object(api, 'cost_state', return_value=state), patch.object(api.urllib.request, 'urlopen') as http:
            with self.assertRaises(ValueError): api.call(self.out, 'one', self.p, 'mock', 'test')
            http.assert_not_called()
        huge = payload('x'*50000)
        with patch.object(api.urllib.request, 'urlopen') as http:
            with self.assertRaises(ValueError): api.call(self.out, 'huge', huge, 'mock', 'test')
            http.assert_not_called()
    def test_direct_call_lock_prevents_concurrent_submission(self):
        with api._call_lock(self.out), patch.object(api.urllib.request, 'urlopen') as http:
            with self.assertRaises(ValueError): api.call(self.out, 'one', self.p, 'mock', 'test')
            http.assert_not_called()


if __name__ == '__main__': unittest.main()
