"""Independent v54 atomic/tri-state tests, authored without fresh holdout access."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic_judge_v54 as judge
import structured_haiku_v54 as transport
import score_legacy_eval_v54 as score
from test_legacy_bridge_independent import contract, fixture

def prepared(answer='done\n{"facts":{"state":"healthy"}}'):
    return score.build_payload(*fixture(answer, [contract('state', 'healthy', 'categorical', None, 'string|null')]))
def atomic(p, unsupported=False, satisfied=True):
    return {'unsupported_claims': unsupported, 'answer_status': 'answered',
        'findings': [{'key': 'state', 'satisfied': satisfied, 'answer_quote': p['answer'],
                      'observation_ids': ['obs-storage'], 'reason': 'Synthetic atomic control'}],
        'reason': 'Synthetic atomic control'}

class IndependentV54CompositionTest(unittest.TestCase):
    def test_model_pass_is_absent_and_rejected_while_code_derives_it(self):
        p = prepared(); response = atomic(p)
        schema = transport.request_body(p)['output_config']['format']['schema']
        self.assertNotIn('pass', schema['properties']); self.assertNotIn('derived_pass', schema['properties'])
        self.assertTrue(judge.validate(response, p)['derived_pass'])
        self.assertFalse(judge.validate(atomic(p, unsupported=True), p)['derived_pass'])
        for key in ('pass', 'derived_pass'):
            with self.subTest(key=key), self.assertRaises(ValueError): judge.validate(response | {key: True}, p)
        self.assertNotIn('derived_pass', response)
    def test_invalid_schema_preserves_content_but_never_clean_or_strict_credit(self):
        for answer in ('done\n{"facts":{}}', 'done\n{"facts":{"state":false}}', 'done\n{"facts":{"state":"healthy",}}'):
            p = prepared(answer)
            for raw in (False, True):
                with self.subTest(answer=answer, raw=raw):
                    result = score.grade_components(p, atomic(p, unsupported=raw))
                    self.assertTrue(result['combined_fields']['state'])
                    self.assertEqual(result['unsupported_assessment'], 'unassessed')
                    self.assertIsNone(result['unsupported_claims'])
                    self.assertIs(result['raw_unsupported_claims'], raw)
                    self.assertFalse(result['structured_pass'])
    def test_valid_schema_flag_and_runner_failure_affect_strict_pass(self):
        p = prepared()
        for raw, error, expected in ((False, '', True), (True, '', False), (False, 'transport error', False)):
            result = score.grade_components(p, atomic(p, unsupported=raw), error)
            self.assertEqual(result['unsupported_assessment'], 'assessed')
            self.assertIs(result['unsupported_claims'], raw)
            self.assertEqual(result['structured_pass'], expected)
    def test_numeric_code_failure_still_blocks_correct_semantic_content(self):
        p = score.build_payload(*fixture('done\n{"facts":{"remaining":"8"}}'))
        response = {'unsupported_claims': False, 'answer_status': 'answered', 'reason': 'Synthetic',
            'findings': [{'key': 'remaining', 'satisfied': True, 'answer_quote': p['answer'],
                          'observation_ids': ['obs-storage'], 'reason': 'Synthetic'}]}
        result = score.grade_components(p, response)
        self.assertFalse(result['combined_fields']['remaining'])
        self.assertIsNone(result['unsupported_claims']); self.assertFalse(result['structured_pass'])
    def test_source_identity_binds_new_atomic_transport_and_judge(self):
        self.assertIs(score.api, transport); self.assertIs(score.validate, judge.validate)
        identity = score.bridge_identity()
        self.assertEqual(identity['transport_code_sha256'], score.digest(Path(transport.__file__)))
        self.assertEqual(identity['judge_code_sha256'], score.digest(Path(judge.__file__)))
        self.assertTrue(all('v54' in path for path in score.LEDGERS))
        self.assertIn('scripts/structured_haiku_v54.py', score.CODE)

class IndependentV54BoundsTest(unittest.TestCase):
    def test_unique_answer_bounds_coverage_and_missing_verdicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); out = root/'eval/v5/legacy-scoring-v54'; (out/'payloads').mkdir(parents=True)
            mapping = []; ledgers = [[], []]
            kinds = ('clean', 'flagged', 'disagreement', 'unassessed', 'missing', 'invalid_judgment')
            for arm in score.ARMS:
                for kind in kinds:
                    p = prepared('done\n{"facts":{}}' if kind == 'unassessed' else 'done\n{"facts":{"state":"healthy"}}')
                    ident = f'{arm}-{kind}'; score.api.save(out/'payloads'/f'{ident}.json', p)
                    mapping.append({'id': ident, 'case': kind, 'family': kind, 'source_tier': 'synthetic',
                                    'arm': arm, 'rep': 0, 'runner_error': ''})
                    for rep in range(2):
                        if kind == 'missing' and rep == 1: continue
                        response = atomic(p, unsupported=(kind == 'flagged' or kind == 'disagreement' and rep == 1 or kind == 'unassessed' and rep == 1))
                        if kind == 'invalid_judgment' and rep == 1: response['findings'][0]['answer_quote'] = 'NOT IN ANSWER'
                        ledgers[rep].append({'id': ident, 'judge_rep': rep, 'semantic_result': response})
            for rep, relative in enumerate(score.LEDGERS):
                child = root/relative; child.mkdir(); score.api.save(child/'manifest.json', {})
                (child/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in ledgers[rep]))
            with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), \
                 patch.object(score.budget, 'preflight', return_value={}):
                result = score.summarize(out)
            for arm in result['arms'].values():
                self.assertEqual(arm['n'], 6); self.assertEqual(arm['unsupported_assessment_denominator'], 6)
                self.assertEqual(arm['unsupported_count_bounds'], {'lower': 1, 'upper': 5})
                self.assertEqual(arm['stable_unsupported_free'], 1)
                self.assertEqual(arm['unsupported_format_eligible'], 5)
                self.assertEqual(arm['unsupported_assessed_both'], 3)
                self.assertEqual(arm['unsupported_assessment_coverage_percent'], 50)
                self.assertEqual(arm['unsupported_unassessed_format_or_schema'], 1)
                self.assertEqual(arm['unsupported_specific_disagreements'], 1)
                self.assertEqual(arm['unsupported_unresolved'], 4)
                self.assertEqual(arm['stable_structured_pass'], 1)
                self.assertEqual(arm['all_finding_denominator'], 6)
            for answer in result['answers']:
                if answer['case'] == 'unassessed':
                    self.assertTrue(answer['stable_fields']['state'])
                    self.assertFalse(answer['stable_unsupported_free'])
                    self.assertFalse(answer['stable_unsupported_present'])
                    self.assertFalse(answer['stable_structured_pass'])
                    self.assertFalse(answer['scored_agreement'])
if __name__ == '__main__': unittest.main()
