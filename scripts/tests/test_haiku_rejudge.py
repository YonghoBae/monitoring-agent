import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('haiku_rejudge', Path(__file__).parents[1] / 'haiku_rejudge.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class HaikuReviewTest(unittest.TestCase):
    def setUp(self):
        self.payload = h.calibration()[0]['payload']
        self.valid = {'fields': [{'key': 'value', 'value': 8, 'quote': '8 GB',
                      'evidence_supported': True, 'evidence': [{'id': 'obs-1', 'quote': '8000000000'}],
                      'reason': 'Explicit decimal GB, supported by bytes.'}],
                      'unsupported_claims': [], 'gold_issue': False, 'gold_issue_reason': ''}

    def test_valid_and_wrong_number(self):
        self.assertEqual(h.validate(self.valid, self.payload)['score'], 100)
        self.valid['fields'][0]['value'] = 7.45
        self.assertEqual(h.validate(self.valid, self.payload)['score'], 0)

    def test_boolean_not_numeric(self):
        self.assertFalse(h.matches(True, {'value': 1, 'tolerance': 0}))
        self.assertFalse(h.matches(float('nan'), {'value': 1, 'tolerance': 0}))

    def test_fabricated_answer_quote_rejected(self):
        self.valid['fields'][0]['quote'] = 'not in answer'
        with self.assertRaises(ValueError): h.validate(self.valid, self.payload)

    def test_fabricated_evidence_rejected(self):
        for evidence in [[{'id': 'obs-missing', 'quote': '8000000000'}],
                         [{'id': 'obs-1', 'quote': 'invented data'}], []]:
            self.valid['fields'][0]['evidence'] = evidence
            with self.assertRaises(ValueError): h.validate(self.valid, self.payload)

    def test_duplicate_fields_rejected(self):
        self.valid['fields'].append(copy.deepcopy(self.valid['fields'][0]))
        with self.assertRaises(ValueError): h.validate(self.valid, self.payload)

    def test_no_evidence_cannot_score(self):
        self.valid['fields'][0].update(evidence_supported=False, evidence=[])
        self.assertEqual(h.validate(self.valid, self.payload)['score'], 0)

    def test_incomplete_response_rejected(self):
        for reason in ['max_tokens', 'refusal', 'tool_use']:
            with self.assertRaises(ValueError):
                h.parse_response({'model': h.MODEL, 'stop_reason': reason}, self.payload)

    def test_thinking_block_not_parsed_as_answer(self):
        response = {'model': h.MODEL, 'stop_reason': 'end_turn', 'content': [
            {'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': json.dumps(self.valid)}]}
        self.assertEqual(h.parse_response(response, self.payload)['score'], 100)

    def test_claim_quote_rejected(self):
        self.valid['unsupported_claims'] = [{'quote': 'invented', 'reason': 'bad'}]
        with self.assertRaises(ValueError): h.validate(self.valid, self.payload)

    def test_cost_and_ambiguous_request(self):
        self.assertAlmostEqual(h.usage_cost({'input_tokens': 10000, 'output_tokens': 1000}), .0015)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            h.append(out/'requests.jsonl', {'event': 'started', 'request_id': 'a'})
            self.assertEqual(h.cost_state(out)['unresolved_requests'], 1)
            h.append(out/'requests.jsonl', {'event': 'completed', 'request_id': 'a', 'cost_usd': .0015})
            self.assertEqual(h.cost_state(out)['unresolved_requests'], 0)
            self.assertEqual(h.cost_state(out)['estimated_usd'], .0015)

    def test_blinding_and_uniform_exclusion(self):
        scene = {'question': 'q', 'task_mode': 'question', 'answer_fields': [{'key': 'a'}, {'key': 'b'}],
                 'gold': [{'key': 'a', 'value': 1}, {'key': 'b', 'value': 2}]}
        row = {'arm': 'compact_plus', 'answer': '1', 'trace': {'observations': []}}
        result = h.packet(scene, row, {'b': 'unsupported gold'})
        self.assertNotIn('compact_plus', h.encode(result))
        self.assertEqual([f['key'] for f in result['reference_fields']], ['a'])

    def test_calibration_complete_unique(self):
        cases = h.calibration()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c['id'] for c in cases}), 20)
        self.assertTrue(any(c['expected_pass'] for c in cases))
        self.assertTrue(any(not c['expected_pass'] for c in cases))

    def test_escaped_and_fragmented_evidence(self):
        source = '{"cpu":"0","mode":"idle"}, middle, {"cpu":"3","mode":"idle"}'
        quote = '\\"cpu\\":\\"0\\" ... \\"cpu\\":\\"3\\"'
        self.assertEqual(h.quote_parts(quote, [source], True), ['"cpu":"0"', '"cpu":"3"'])
        with self.assertRaises(ValueError): h.quote_parts(quote, [source], False)
        with self.assertRaises(ValueError): h.quote_parts('"cpu":"0" ... invented', [source], True)
        with self.assertRaises(ValueError): h.quote_parts('"cpu":"3" ... "cpu":"0"', [source], True)

    def test_json_newline_and_nested_log_content(self):
        self.assertEqual(h.quote_parts('unknowns:\\nnone', ['unknowns:\nnone']), ['unknowns:\nnone'])
        obs = h.observation({'id': 'o', 'source': 'log', 'target': 'x', 'status': 'ok',
                             'data': ['err="yaml: line 42"']})
        self.assertEqual(h.quote_parts('err="yaml: line 42"', h.evidence_sources(obs)), ['err="yaml: line 42"'])

    def test_quote_repair_preserves_semantic_decisions(self):
        repair = {'fields': [{'key': 'value', 'quote': '8 GB',
                  'evidence': [{'id': 'obs-1', 'quote': '8000000000'}]}], 'claim_quotes': []}
        original = copy.deepcopy(self.valid)
        original['fields'][0]['quote'] = 'invalid'
        result = h.apply_quote_repair(original, repair, self.payload)
        self.assertEqual(result['score'], 100)
        for key in ['value', 'reason', 'evidence_supported']:
            self.assertEqual(result['fields'][0][key], original['fields'][0][key])
        repair['fields'][0]['value'] = 999
        with self.assertRaises(ValueError): h.apply_quote_repair(original, repair, self.payload)

    def test_quote_repair_cannot_change_evidence_id(self):
        repair = {'fields': [{'key': 'value', 'quote': '8 GB',
                  'evidence': [{'id': 'obs-999', 'quote': '8000000000'}]}], 'claim_quotes': []}
        with self.assertRaises(ValueError): h.apply_quote_repair(self.valid, repair, self.payload)


if __name__ == '__main__':
    unittest.main()
