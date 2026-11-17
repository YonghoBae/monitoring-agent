"""Synthetic offline scoring/budget tests; no holdout, agent answer, or API access."""
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
import budget_registry as budget
import score_eval_v5 as score


class ScoringContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v5-offline-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.campaign = self.root/'eval/v5/comparison-1'
        self.out = self.root/'eval/v5/scoring-1'
        for rel in score.SCORING_INPUTS:
            if rel == 'eval/paid-campaigns.json':
                continue  # Synthetic registry is written below; never copy the local budget state.
            dest = self.root/rel; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(score.ROOT/rel, dest)
        self.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2,
            'campaigns': ['eval/prior', 'eval/v5/scoring-1']})
        self.dataset = {'scenarios': [{'id': f'synthetic-{i}', 'split': 'test',
            'family': 'a' if i < 4 else 'b', 'question': 'Operation?', 'answer_fields': ['status']}
            for i in range(8)]}
        self.gold = {s['id']: {'reference': {'required_findings': [{'key': 'status', 'statement': 'done'}]}}
                     for s in self.dataset['scenarios']}
        self.rows = [{'id': s['id'], 'family': s['family'], 'arm': arm, 'rep': rep,
            'answer': 'done', 'error': '', 'elapsedMs': 1,
            'trace': {'kind': 'delivered_tool_results', 'captureSupported': True,
                      'observations': [{'id': 'obs', 'output': 'delivered only'}]},
            'rawWorldTrace': {'unseen': 'DO_NOT_INCLUDE'}}
            for s in self.dataset['scenarios'] for arm in score.ARMS for rep in range(3)]
        self.save(self.root/'eval/v5/dataset.json', self.dataset)
        self.save(self.root/'eval/v5/gold.json', self.gold)
        hashes = {}
        for rel in (*score.SCORING_INPUTS, 'eval/v5/dataset.json', 'eval/v5/gold.json'):
            dest = self.campaign/'frozen-inputs'/rel; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root/rel, dest); hashes[rel] = score.api.sha(dest.read_bytes())
        self.save(self.campaign/'manifest.json', {'status': 'completed', 'answers': 48, 'frozen_hashes': hashes})
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        self.root_patch = patch.object(score, 'ROOT', self.root); self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def write_rows(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()): score.prepare(self.campaign, self.out)
        return score.api.read(self.out/'mapping.json')

    def result(self, passed=True):
        return {'pass': passed, 'unsupported_claims': False, 'answer_status': 'answered',
                'findings': [{'key': 'status', 'satisfied': passed, 'answer_quote': 'done',
                              'observation_ids': ['obs'], 'reason': 'synthetic'}], 'reason': 'synthetic'}

    def summary(self, judgments):
        self.write_rows(self.out/'results.jsonl', judgments)
        with contextlib.redirect_stdout(io.StringIO()): score.summarize(self.out)
        return score.api.read(self.out/'summary.json')

    def ledger(self, rel, cost, pending=False):
        rows = [{'event': 'started', 'request_id': 'synthetic-request'}]
        if not pending: rows.append({'event': 'completed', 'request_id': 'synthetic-request', 'cost_usd': cost})
        self.write_rows(self.root/rel/'requests.jsonl', rows)

    def test_exact_grid_rejects_missing_duplicate_wrong_arm_and_bool_repeat(self):
        score.validate_grid(self.rows, self.dataset)
        for mutate in ('missing', 'duplicate', 'arm', 'bool'):
            rows = copy.deepcopy(self.rows)
            if mutate == 'missing': rows.pop()
            if mutate == 'duplicate': rows[-1] = rows[0]
            if mutate == 'arm': rows[0]['arm'] = 'unregistered'
            if mutate == 'bool': rows[0]['rep'] = False
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): score.validate_grid(rows, self.dataset)

    def test_payloads_are_blinded_and_use_exact_delivered_observations(self):
        mapping = self.prepare(); self.assertEqual(len(mapping), 48)
        for item in mapping:
            payload = score.api.read(self.out/'payloads'/f"{item['id']}.json")
            self.assertEqual(set(payload), {'question', 'answer', 'reference', 'observations'})
            self.assertEqual(payload['observations'], [{'id': 'obs', 'output': 'delivered only'}])
            self.assertNotIn('DO_NOT_INCLUDE', json.dumps(payload))

    def test_unsupported_capture_is_rejected_before_output_creation(self):
        self.rows[0]['trace']['captureSupported'] = False
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.out.exists())

    def test_missing_duplicate_invalid_and_disagreement_keep_full_denominator(self):
        mapping = self.prepare()
        for mode in ('missing', 'duplicate', 'invalid', 'disagreement'):
            judgments = []
            for m in mapping:
                judgments.append({'id': m['id'], 'judge_rep': 0, 'result': self.result()})
                if mode == 'missing': continue
                j = {'id': m['id'], 'judge_rep': 0 if mode == 'duplicate' else 1,
                     'result': self.result(mode != 'disagreement')}
                if mode == 'invalid': j.pop('result'); j['error'] = 'invalid response'
                judgments.append(j)
            with self.subTest(mode=mode):
                summary = self.summary(judgments)
                for arm in score.ARMS:
                    self.assertEqual(summary['arms'][arm]['n'], 24)
                    self.assertEqual(summary['arms'][arm]['stable_pass'], 0)
                    self.assertEqual(summary['arms'][arm]['unresolved'], 24)

    def test_two_distinct_valid_passes_and_error_denominator(self):
        self.rows[0]['error'] = 'runner error'
        self.write_rows(self.campaign/'raw-comparison/results.jsonl', self.rows)
        mapping = self.prepare()
        js = [{'id': m['id'], 'judge_rep': rep, 'result': self.result()} for m in mapping for rep in (0, 1)]
        summary = self.summary(js)
        self.assertEqual(sum(a['n'] for a in summary['arms'].values()), 48)
        self.assertEqual(sum(a['stable_pass'] for a in summary['arms'].values()), 47)
        self.assertEqual(sum(a['runner_errors'] for a in summary['arms'].values()), 1)
        self.assertIn('57/60', summary['answer_status_limitation'])
        for arm in summary['arms'].values():
            self.assertEqual(set(arm['per_judge_repeat']), {'0', '1'})

    def test_frozen_code_and_snapshot_hashes_are_enforced(self):
        self.prepare()
        for path in (self.root/'scripts/semantic_judge_v5.py', self.root/'scripts/score_eval_v5.py',
                     self.campaign/'frozen-inputs/scripts/budget_registry.py'):
            original = path.read_bytes(); path.write_bytes(original+b'\n# changed\n')
            try:
                with self.subTest(path=str(path)), self.assertRaises(ValueError): score.verified_mapping(self.out)
            finally: path.write_bytes(original)

    def test_payload_and_mapping_tampering_are_rejected(self):
        mapping = self.prepare()
        for path in (self.out/'mapping.json', self.out/'payloads'/f"{mapping[0]['id']}.json"):
            original = path.read_bytes(); self.save(path, {})
            try:
                with self.subTest(path=str(path)), self.assertRaises(ValueError): score.verified_mapping(self.out)
            finally: path.write_bytes(original)

    def test_global_budget_uses_own_cost_once_not_manifest_priors(self):
        self.ledger('eval/prior', .7); self.ledger('eval/v5/scoring-1', .2)
        self.save(self.root/'eval/prior/manifest.json', {'prior_campaign_cost_usd': 100})
        state = budget.preflight(self.root, self.out)
        self.assertEqual(state['total_campaigns_estimated_usd'], .9)
        self.assertEqual(state['prior_campaign_cost_usd'], .7)

    def test_unregistered_duplicate_paths_and_prior_pending_stop_calls(self):
        with self.assertRaises(ValueError): budget.preflight(self.root, self.root/'eval/arbitrary')
        self.ledger('eval/prior', 0, pending=True)
        with self.assertRaisesRegex(ValueError, 'Uncertain'): budget.preflight(self.root, self.out)
        self.ledger('eval/prior', .1)
        self.save(self.root/'eval/paid-campaigns.json', {'version': 1, 'budget_usd': 2,
            'campaigns': ['eval/prior', 'eval/prior/../prior', 'eval/v5/scoring-1']})
        with self.assertRaisesRegex(ValueError, 'Duplicate'): budget.preflight(self.root, self.out)

    def test_global_reservation_blocks_before_network(self):
        self.ledger('eval/prior', 1.9999)
        self.save(self.out/'manifest.json', {'prior_campaign_cost_usd': 0})
        with patch.object(score.api.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')) as http:
            with self.assertRaisesRegex(ValueError, 'Cost/call cap'):
                budget.paid_call(score.api, self.root, self.out, 'test', {}, 'unused', 'offline', system='test')
            http.assert_not_called()
        self.assertEqual(score.api.read(self.out/'manifest.json')['prior_campaign_cost_usd'], 1.9999)


if __name__ == '__main__': unittest.main()
