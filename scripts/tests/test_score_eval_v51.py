"""Offline V5.1 scorer tests with synthetic model archives and a stub semantic validator."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_eval_v51 as score


def synthetic_validate(result, payload):
    if not isinstance(result, dict): raise ValueError('Not an object')
    for key in ('pass', 'answer_correct', 'complete_answer', 'unsupported_claims'):
        if type(result.get(key)) is not bool: raise ValueError('Invalid boolean')
    expected = {f['key'] for f in payload['reference']['required_findings']}
    findings = result.get('findings', [])
    if len(findings) != len(expected) or {f['key'] for f in findings} != expected:
        raise ValueError('Invalid fields')
    for finding in findings:
        if type(finding['satisfied']) is not bool or finding['answer_quote'] not in payload['answer']:
            raise ValueError('Invalid finding')
    if result['pass'] != (all(f['satisfied'] for f in findings) and result['answer_correct'] and result['complete_answer'] and not result['unsupported_claims']):
        raise ValueError('Inconsistent overall pass')
    return result


class V51ScoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v51-offline-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.campaign = self.root/'eval/v5/comparison-2'
        self.out = self.root/'eval/v5/scoring-v51'
        real_root = score.ROOT
        for rel in score.SCORING_INPUTS:
            if rel == 'eval/paid-campaigns.json':
                continue  # Synthetic registry is written below; never copy the local budget state.
            path = self.root/rel; path.parent.mkdir(parents=True, exist_ok=True)
            if rel == 'scripts/semantic_judge_v51.py': path.write_text('# synthetic semantic judge\n')
            else: shutil.copyfile(real_root/rel, path)
        self.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2,
            'campaigns': ['eval/prior', 'eval/v5/scoring-v51']})
        module = types.ModuleType('semantic_judge_v51'); module.SYSTEM = 'synthetic v51 prompt'
        module.validate = synthetic_validate
        self.modules = patch.dict(sys.modules, {'semantic_judge_v51': module}); self.modules.start()
        self.addCleanup(self.modules.stop)
        self.root_patch = patch.object(score, 'ROOT', self.root); self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.dataset = {'scenarios': [{'id': f'fixture-{i}', 'split': 'test',
            'family': 'left' if i < 4 else 'right', 'question': 'Give status and restore-check outcome.',
            'answer_fields': ['status', 'cause']} for i in range(8)]}
        gold = {s['id']: {'reference': {'required_findings': [{'key': 'status'}, {'key': 'cause'}]}}
                for s in self.dataset['scenarios']}
        archive = {'eval/v5/dataset.json': json.dumps(self.dataset), 'eval/v5/gold.json': json.dumps(gold),
                   'scripts/score_eval_v5.py': '# ORIGINAL frozen scorer, intentionally unlike current code\n'}
        hashes = {}
        for rel, text in archive.items():
            p = self.campaign/'frozen-inputs'/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
            hashes[rel] = score.api.sha(p.read_bytes())
        self.save(self.campaign/'manifest.json', {'status': 'completed', 'answers': 48, 'frozen_hashes': hashes})
        self.rows = [{'id': s['id'], 'family': s['family'], 'arm': arm, 'rep': rep,
            'answer': 'done', 'error': '', 'elapsedMs': 1,
            'trace': {'kind': 'delivered_tool_results', 'captureSupported': True,
                      'observations': [{'id': 'delivered', 'output': 'exact evidence'}]},
            'rawWorldTrace': {'private': 'UNSEEN RAW DATA'}}
            for s in self.dataset['scenarios'] for arm in score.ARMS for rep in range(3)]
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        self.save(self.root/score.VALIDATION_REL/'manifest.json', {
            'system_sha256': score.api.sha(module.SYSTEM.encode()),
            'judge_code_sha256': score.api.sha((self.root/'scripts/semantic_judge_v51.py').read_bytes()),
            'holdout_sha256': 'synthetic independent control identity'})
        self.save(self.root/score.VALIDATION_REL/'summary.json', {'gate_passed': True, 'judgments': 60})

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def write_rows(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()): score.prepare(self.campaign, self.out)
        return score.api.read(self.out/'mapping.json')

    def verdict(self, satisfied=(True, True), complete=True, unsupported=False, correct=True):
        return {'pass': all(satisfied) and correct and complete and not unsupported, 'answer_correct': correct,
            'complete_answer': complete, 'unsupported_claims': unsupported, 'answer_status': 'answered',
            'findings': [{'key': key, 'satisfied': good, 'answer_quote': 'done',
                          'observation_ids': ['delivered'], 'reason': 'synthetic'}
                         for key, good in zip(('status', 'cause'), satisfied)], 'reason': 'synthetic'}

    def summarize_pair(self, mapping, first, second):
        rows = [{'id': m['id'], 'judge_rep': rep, 'result': result}
                for m in mapping for rep, result in enumerate((first, second))]
        self.write_rows(self.out/'results.jsonl', rows)
        with contextlib.redirect_stdout(io.StringIO()): score.summarize(self.out)
        return score.api.read(self.out/'summary.json')

    def test_original_archive_and_new_measurement_are_frozen_separately(self):
        mapping = self.prepare(); self.assertEqual(len(score.verified_mapping(self.out)), 48)
        manifest = score.api.read(self.out/'manifest.json')
        self.assertTrue(manifest['measurement_amendment']['required_field_metrics_retained_separately'])
        self.assertFalse(manifest['measurement_amendment']['arm_information_used_to_choose_rule'])
        self.assertIn('scripts/score_eval_v51.py', manifest['frozen_scoring_hashes'])
        for item in mapping:
            payload = score.api.read(self.out/'payloads'/f"{item['id']}.json")
            self.assertEqual(set(payload), {'question', 'answer', 'reference', 'observations'})
            self.assertNotIn('UNSEEN RAW DATA', json.dumps(payload))

    def test_required_fields_do_not_imply_full_completion(self):
        mapping = self.prepare(); result = self.verdict(complete=False)
        summary = self.summarize_pair(mapping, result, result)
        for arm in summary['arms'].values():
            self.assertEqual((arm['n'], arm['stable_required_fields'], arm['stable_complete_answer'], arm['stable_pass']), (24, 24, 0, 0))
            self.assertEqual(arm['unresolved'], 0)
            self.assertEqual(arm['per_finding']['status']['stable_satisfied'], 24)
            self.assertEqual(arm['per_judge_repeat']['0']['required_fields_satisfied'], 24)

    def test_wrong_secondary_clause_is_complete_but_not_correct(self):
        mapping = self.prepare(); result = self.verdict(correct=False)
        summary = self.summarize_pair(mapping, result, result)
        for arm in summary['arms'].values():
            self.assertEqual(arm['stable_required_fields'], 24)
            self.assertEqual(arm['stable_complete_answer'], 24)
            self.assertEqual(arm['stable_answer_correct'], 0)
            self.assertEqual(arm['stable_pass'], 0)

    def test_disagreement_in_each_scored_component_is_unresolved(self):
        mapping = self.prepare()
        pairs = [
            (self.verdict(complete=False, correct=True), self.verdict(complete=False, correct=False)),
            (self.verdict(complete=False, unsupported=True), self.verdict(complete=True, unsupported=True)),
            (self.verdict(satisfied=(False, False), complete=False), self.verdict(satisfied=(False, False), complete=False, unsupported=True)),
            (self.verdict(satisfied=(False, False), complete=False), self.verdict(satisfied=(False, True), complete=False)),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                summary = self.summarize_pair(mapping, first, second)
                for arm in summary['arms'].values():
                    self.assertEqual(arm['stable_pass'], 0); self.assertEqual(arm['unresolved'], 24)

    def test_two_full_valid_passes_preserve_runner_error_denominator(self):
        self.rows[0]['error'] = 'synthetic runner error'; self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        mapping = self.prepare(); summary = self.summarize_pair(mapping, self.verdict(), self.verdict())
        self.assertEqual(sum(a['n'] for a in summary['arms'].values()), 48)
        self.assertEqual(sum(a['stable_pass'] for a in summary['arms'].values()), 47)

    def test_missing_complete_answer_is_invalid(self):
        mapping = self.prepare(); bad = self.verdict(); bad.pop('complete_answer')
        summary = self.summarize_pair(mapping, self.verdict(), bad)
        self.assertTrue(all(a['unresolved'] == 24 and a['stable_pass'] == 0 for a in summary['arms'].values()))

    def test_duplicate_or_missing_judge_repetitions_are_nonpassing(self):
        mapping = self.prepare()
        for repetitions in ((0,), (0, 0)):
            self.write_rows(self.out/'results.jsonl', [{'id': m['id'], 'judge_rep': rep, 'result': self.verdict()} for m in mapping for rep in repetitions])
            with contextlib.redirect_stdout(io.StringIO()): score.summarize(self.out)
            summary = score.api.read(self.out/'summary.json')
            self.assertTrue(all(a['n'] == 24 and a['unresolved'] == 24 for a in summary['arms'].values()))

    def test_exact_grid_rejects_48_duplicate_rows(self):
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', [self.rows[0]]*48)
        with self.assertRaises(ValueError): self.prepare()

    def test_validation_gate_requires_60_passed_frozen_judgments(self):
        for summary in ({'gate_passed': False, 'judgments': 60}, {'gate_passed': True, 'judgments': 59}):
            self.save(self.root/score.VALIDATION_REL/'summary.json', summary)
            with self.subTest(summary=summary), self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.out.exists())

    def test_original_archive_and_new_judge_mutations_are_both_rejected(self):
        self.prepare()
        for path in (self.campaign/'frozen-inputs/scripts/score_eval_v5.py', self.root/'scripts/semantic_judge_v51.py',
                     self.out/'frozen-scoring/scripts/score_eval_v51.py', self.root/score.VALIDATION_REL/'summary.json',
                     self.campaign/'raw-comparison/results.jsonl'):
            raw = path.read_bytes(); path.write_bytes(raw+b' ')
            try:
                with self.subTest(path=str(path)), self.assertRaises(ValueError): score.verified_mapping(self.out)
            finally: path.write_bytes(raw)

    def test_unknown_output_path_and_prior_paid_log_block_run(self):
        with self.assertRaises(ValueError): score.prepare(self.campaign, self.root/'eval/unregistered')
        self.prepare(); self.write_rows(self.out/'requests.jsonl', [{'event': 'started', 'request_id': 'prior'}])
        with self.assertRaisesRegex(ValueError, 'No silent rerun'): score.run(self.out)


if __name__ == '__main__': unittest.main()
