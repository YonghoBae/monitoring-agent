"""Synthetic V5.2 scoring checks; original judge validator, no live answers or calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_canonical_core_v5 as score
from semantic_judge_v5 import SYSTEM


class CanonicalScoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v52-offline-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.campaign = self.root/'eval/v5/canonical-core/comparison-1'
        self.out = self.root/'eval/v5/canonical-core/scoring-1'; real_root = score.ROOT
        for rel in score.SCORING_INPUTS:
            if rel == 'eval/paid-campaigns.json':
                continue  # Synthetic registry is written below; never copy the local budget state.
            path = self.root/rel; path.parent.mkdir(parents=True, exist_ok=True)
            if rel == score.GOLD_REL: path.write_text('{}')
            else: shutil.copyfile(real_root/rel, path)
        self.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2,
            'campaigns': ['eval/prior', 'eval/v5/canonical-core/scoring-1']})
        self.root_patch = patch.object(score, 'ROOT', self.root); self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.dataset = {'scenarios': [{'id': f'fixture-{i}', 'split': 'test',
            'family': 'left' if i < 4 else 'right', 'question': 'Give status and restore-check outcome.',
            'answer_fields': [{'key': 'operation_status'}, {'key': 'secondary_check'}, {'key': 'direct_cause'}]} for i in range(8)]}
        self.original_gold = {s['id']: {'reference': {'required_findings': [{'key': 'operation_status'}, {'key': 'direct_cause'}]}}
                              for s in self.dataset['scenarios']}
        self.gold = {s['id']: {'reference': {'required_findings': [{'key': 'operation_status'}, {'key': 'secondary_check'}, {'key': 'direct_cause'}],
            'coverage_policy': 'Secondary evidence may be prose; no third JSON key or numeric requirement.'}}
            for s in self.dataset['scenarios']}
        self.save(self.root/score.GOLD_REL, self.gold)
        archive = {score.DATASET_REL: json.dumps(self.dataset), score.GOLD_REL: json.dumps(self.gold), 'eval/v5/gold.json': json.dumps(self.original_gold),
            'scripts/score_eval_v5.py': '# frozen old scorer, not the amended scorer\n',
            'scripts/semantic_judge_v5.py': (real_root/'scripts/semantic_judge_v5.py').read_text()}
        hashes = {}
        for rel, text in archive.items():
            path = self.campaign/'frozen-inputs'/rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            hashes[rel] = score.api.sha(path.read_bytes())
        self.save(self.campaign/'manifest.json', {'status': 'completed', 'answers': 48, 'frozen_hashes': hashes, 'dataset_path': score.DATASET_REL})
        gold_patch = patch.object(score, 'APPROVED_GOLD_SHA', score.api.sha((self.root/score.GOLD_REL).read_bytes()))
        gold_patch.start(); self.addCleanup(gold_patch.stop)
        self.rows = [{'id': s['id'], 'family': s['family'], 'arm': arm, 'rep': rep, 'answer': 'done',
            'error': '', 'elapsedMs': 1, 'trace': {'kind': 'delivered_tool_results', 'captureSupported': True,
            'observations': [{'id': 'delivered', 'output': 'exact evidence'}]}, 'rawWorldTrace': {'private': 'UNSEEN RAW DATA'}}
            for s in self.dataset['scenarios'] for arm in score.ARMS for rep in range(3)]
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        self.save(self.root/score.VALIDATION_REL/'manifest.json', {'system_sha256': score.api.sha(SYSTEM.encode()),
            'judge_code_sha256': score.api.sha((self.root/'scripts/semantic_judge_v5.py').read_bytes()),
            'holdout_sha256': 'synthetic independent holdout identity'})
        self.save(self.root/score.VALIDATION_REL/'summary.json', {'gate_passed': True, 'judgments': 60, 'cases': 20})

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def write_rows(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()): score.prepare(self.campaign, self.out)
        return score.api.read(self.out/'mapping.json')

    def verdict(self, satisfied=(True, True, True), unsupported=False, keys=('operation_status', 'secondary_check', 'direct_cause')):
        return {'pass': all(satisfied) and not unsupported, 'unsupported_claims': unsupported,
            'answer_status': 'answered', 'findings': [{'key': key, 'satisfied': good, 'answer_quote': 'done',
            'observation_ids': ['delivered'], 'reason': 'synthetic'} for key, good in zip(keys, satisfied)], 'reason': 'synthetic'}

    def summarize_pair(self, mapping, first, second):
        self.write_rows(self.out/'results.jsonl', [{'id': m['id'], 'judge_rep': rep, 'result': result}
            for m in mapping for rep, result in enumerate((first, second))])
        with contextlib.redirect_stdout(io.StringIO()): score.summarize(self.out)
        return score.api.read(self.out/'summary.json')

    def test_confirmatory_requests_all_three_fields_and_only_delivered_evidence(self):
        mapping = self.prepare()
        for item in mapping:
            payload = score.api.read(self.out/'payloads'/f"{item['id']}.json")
            self.assertEqual(payload['question'], self.dataset['scenarios'][0]['question'])
            self.assertEqual(payload['requested_answer_fields'], self.dataset['scenarios'][0]['answer_fields'])
            self.assertEqual(len(payload['reference']['required_findings']), 3)
            self.assertEqual(payload['answer'], 'done')
            self.assertEqual(payload['observations'], [{'id': 'delivered', 'output': 'exact evidence'}])
            self.assertNotIn('UNSEEN RAW DATA', json.dumps(payload))
            self.assertFalse({'arm', 'case', 'family', 'rep'} & set(payload))
        original = score.api.read(self.campaign/'frozen-inputs/eval/v5/gold.json')
        self.assertEqual(original, self.original_gold)

    def test_secondary_missing_retains_two_thirds_field_accuracy_but_not_strict_pass(self):
        mapping = self.prepare(); result = self.verdict((True, False, True))
        summary = self.summarize_pair(mapping, result, result)
        for arm in summary['arms'].values():
            self.assertEqual((arm['n'], arm['requested_findings'], arm['stable_satisfied_findings']), (24, 72, 48))
            self.assertAlmostEqual(arm['stable_field_accuracy_micro_percent'], 100*2/3)
            self.assertEqual(arm['stable_all_findings_correct'], 0)
            self.assertEqual(arm['stable_unsupported_free'], 24)
            self.assertEqual(arm['stable_pass'], 0); self.assertEqual(arm['unresolved'], 0)
            self.assertEqual(arm['per_finding']['secondary_check']['stable_satisfied'], 0)

    def test_all_findings_correct_and_unsupported_free_are_distinct(self):
        mapping = self.prepare(); result = self.verdict(unsupported=True)
        summary = self.summarize_pair(mapping, result, result)
        for arm in summary['arms'].values():
            self.assertEqual(arm['stable_all_findings_correct'], 24)
            self.assertEqual(arm['stable_unsupported_free'], 0); self.assertEqual(arm['stable_pass'], 0)

    def test_every_scored_label_disagreement_is_unresolved(self):
        mapping = self.prepare()
        pairs = [(self.verdict((True, False, True)), self.verdict((True, True, False))),
                 (self.verdict((True, False, True)), self.verdict((True, False, True), unsupported=True)),
                 (self.verdict(), self.verdict((True, False, True)))]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                summary = self.summarize_pair(mapping, first, second)
                self.assertTrue(all(a['unresolved'] == 24 and a['stable_pass'] == 0 for a in summary['arms'].values()))

    def test_old_or_missing_dataset_path_rejected(self):
        path = self.campaign/'manifest.json'; original = score.api.read(path)
        for relative in ('eval/v5/dataset.json', '../../outside.json', None):
            manifest = dict(original); manifest['dataset_path'] = relative; self.save(path, manifest)
            with self.subTest(relative=relative), self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.out.exists())
    def test_missing_third_requested_field_rejected_even_with_complete_rubric(self):
        path = self.campaign/'frozen-inputs'/score.DATASET_REL
        dataset = copy.deepcopy(self.dataset); dataset['scenarios'][0]['answer_fields'].pop(1)
        self.save(path, dataset)
        manifest = score.api.read(self.campaign/'manifest.json')
        manifest['frozen_hashes'][score.DATASET_REL] = score.api.sha(path.read_bytes())
        self.save(self.campaign/'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'explicitly requested'): self.prepare()
    def test_runner_errors_missing_and_duplicate_judgments_keep_denominator(self):
        self.rows[0]['error'] = 'synthetic runner error'; self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        mapping = self.prepare(); summary = self.summarize_pair(mapping, self.verdict(), self.verdict())
        self.assertEqual(sum(a['n'] for a in summary['arms'].values()), 48)
        self.assertEqual(sum(a['stable_pass'] for a in summary['arms'].values()), 47)
        for reps in ((0,), (0, 0)):
            self.write_rows(self.out/'results.jsonl', [{'id': m['id'], 'judge_rep': rep, 'result': self.verdict()} for m in mapping for rep in reps])
            with contextlib.redirect_stdout(io.StringIO()): score.summarize(self.out)
            summary = score.api.read(self.out/'summary.json')
            self.assertTrue(all(a['n'] == 24 and a['unresolved'] == 24 for a in summary['arms'].values()))

    def test_gate_requires_twenty_cases_sixty_judgments_and_pass(self):
        for summary in ({'gate_passed': False, 'judgments': 60, 'cases': 20},
                        {'gate_passed': True, 'judgments': 59, 'cases': 20},
                        {'gate_passed': True, 'judgments': 60, 'cases': 19}):
            self.save(self.root/score.VALIDATION_REL/'summary.json', summary)
            with self.subTest(summary=summary), self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.out.exists())

    def test_old_archive_new_reference_and_original_judge_hashes_are_enforced(self):
        self.prepare()
        paths = (self.campaign/'frozen-inputs/scripts/score_eval_v5.py', self.root/'scripts/semantic_judge_v5.py',
                 self.root/score.GOLD_REL, self.out/'frozen-scoring'/score.GOLD_REL,
                 self.campaign/'raw-comparison/results.jsonl', self.root/score.VALIDATION_REL/'summary.json')
        for path in paths:
            original = path.read_bytes(); path.write_bytes(original+b' ')
            try:
                with self.subTest(path=str(path)), self.assertRaises(ValueError): score.verified_mapping(self.out)
            finally: path.write_bytes(original)

    def test_reference_identity_and_coverage_requirements_fail_closed(self):
        for mode in ('missing_case', 'missing_secondary', 'missing_policy'):
            gold = copy.deepcopy(self.gold); case = next(iter(gold))
            if mode == 'missing_case': gold.pop(case)
            if mode == 'missing_secondary': gold[case]['reference']['required_findings'].pop(1)
            if mode == 'missing_policy': gold[case]['reference'].pop('coverage_policy')
            self.save(self.root/score.GOLD_REL, gold)
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.prepare()

    def test_grid_and_unregistered_paths_fail_closed(self):
        with self.assertRaises(ValueError): score.prepare(self.campaign, self.root/'eval/arbitrary')
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', [self.rows[0]]*48)
        with self.assertRaises(ValueError): self.prepare()


if __name__ == '__main__': unittest.main()
