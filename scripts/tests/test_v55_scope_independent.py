"""Independent v55 endpoint-scope checks; no fresh controls or model answers."""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_legacy_eval_v54 as prior
import score_legacy_eval_v55 as score
from test_legacy_bridge_independent import contract, fixture

def payload(invalid=False):
    answer = 'done\n{"facts":{}}' if invalid else 'done\n{"facts":{"state":"healthy"}}'
    return score.build_payload(*fixture(answer, [contract('state', 'healthy', 'categorical', None, 'string|null')]))
def atomic(p, field=True, unsupported=False):
    return {'unsupported_claims': unsupported, 'answer_status': 'answered', 'reason': 'Synthetic',
        'findings': [{'key': 'state', 'satisfied': field, 'answer_quote': p['answer'],
                      'observation_ids': ['obs-storage'], 'reason': 'Synthetic'}]}

class IndependentV55ScopeTest(unittest.TestCase):
    def test_atomic_transport_payload_and_final_composition_are_unchanged(self):
        self.assertIs(score.api, prior.api); self.assertIs(score.validate, prior.validate)
        self.assertEqual(score.SYSTEM, prior.SYSTEM)
        self.assertEqual(inspect.getsource(score.build_payload), inspect.getsource(prior.build_payload))
        self.assertEqual(inspect.getsource(score.grade_components), inspect.getsource(prior.grade_components))
        p = payload()
        self.assertFalse(score.grade_components(p, atomic(p, unsupported=True))['structured_pass'])
        self.assertTrue(score.grade_components(p, atomic(p))['structured_pass'])
    def test_only_final_outcome_disagreements_are_scored_and_auxiliary_is_separate(self):
        patterns = {
            'failed_fields_flag_disagreement': [(False, False), (False, True)],
            'correct_fields_flag_disagreement': [(True, False), (True, True)],
            'field_disagreement': [(False, False), (True, False)],
            'clean': [(True, False), (True, False)],
            'invalid_format_flag_disagreement': [(True, False), (True, True)],
            'missing': [(True, False)],
            'invalid_judgment': [(True, False), (True, False)],
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); out = root/'eval/v5/legacy-scoring-v55'; (out/'payloads').mkdir(parents=True)
            mapping = []; ledgers = [[], []]
            for arm in score.ARMS:
                for case, pairs in patterns.items():
                    p = payload(case == 'invalid_format_flag_disagreement'); ident = f'{arm}-{case}'
                    score.api.save(out/'payloads'/f'{ident}.json', p)
                    mapping.append({'id': ident, 'case': case, 'family': case, 'source_tier': 'synthetic',
                                    'arm': arm, 'rep': 0, 'runner_error': ''})
                    for rep, (field, flag) in enumerate(pairs):
                        result = atomic(p, field, flag)
                        if case == 'invalid_judgment' and rep == 1: result['findings'][0]['answer_quote'] = 'invented quote'
                        ledgers[rep].append({'id': ident, 'judge_rep': rep, 'semantic_result': result})
            for rep, relative in enumerate(score.LEDGERS):
                child = root/relative; child.mkdir(); score.api.save(child/'manifest.json', {})
                (child/'results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in ledgers[rep]))
            with patch.object(score, 'ROOT', root), patch.object(score, '_verified_mapping', return_value=mapping), \
                 patch.object(score.budget, 'preflight', return_value={}):
                summary = score.summarize(out)
            self.assertEqual(summary['validated_outcomes'], ['combined_fields', 'structured_pass'])
            for row in summary['answers']:
                expected_agreement = row['case'] in ('failed_fields_flag_disagreement', 'clean', 'invalid_format_flag_disagreement')
                self.assertEqual(row['scored_agreement'], expected_agreement, row['case'])
                self.assertEqual(row['stable_structured_pass'], row['case'] == 'clean')
                if row['case'] in ('missing', 'invalid_judgment'):
                    self.assertFalse(row['stable_fields']['state']); self.assertFalse(row['complete'])
                self.assertFalse(any('unsupported' in key for key in row))
                auxiliary = row['unvalidated_auxiliary_diagnostics']
                self.assertEqual(auxiliary['validation_status'], 'unvalidated_auxiliary_only_not_for_ranking')
                self.assertIn('raw_judge_components', auxiliary)
                for component in row['judge_components'].values():
                    self.assertFalse(any('unsupported' in key for key in component))
                    self.assertNotIn('derived_semantic_pass', component)
            for arm in summary['arms'].values():
                self.assertEqual(arm['n'], 7); self.assertEqual(arm['all_finding_denominator'], 7)
                self.assertEqual(arm['unresolved'], 4); self.assertEqual(arm['stable_structured_pass'], 1)
                self.assertFalse(any('unsupported' in key for key in arm))
                self.assertIn('unsupported_count_bounds', arm['unvalidated_auxiliary_diagnostics'])
    def test_all_valid_fields_plus_fabrication_remains_nonpass(self):
        p = payload(); result = score.grade_components(p, atomic(p, field=True, unsupported=True))
        self.assertTrue(result['all_findings_correct'])
        self.assertEqual(result['unsupported_assessment'], 'assessed')
        self.assertTrue(result['unsupported_claims'])
        self.assertFalse(result['structured_pass'])
if __name__ == '__main__': unittest.main()
