"""Synthetic audit-packet checks; never opens real answers or private mappings."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_legacy_answer_audit_v5 as audit

class IndependentAuditPacketTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'eval/v5/legacy-scoring-v55'
        self.out = self.root/'eval/v5/legacy-answer-audit'
        (self.source/'payloads').mkdir(parents=True)
        self.mapping = []; contracts = []
        for case in range(35):
            case_id = f'synthetic-{case}'
            contracts.append({'case_id': case_id, 'key': 'value', 'original_gold': {'value': case+1, 'tolerance': .1},
                'answer_binding': {'unit': 'GB'}, 'scoring_kind': 'numeric_quantity', 'requested_question': 'Report observed storage.'})
            for arm in ('pi_plus', 'compact_plus'):
                for rep in range(3):
                    ident = f'row-{len(self.mapping)}'
                    p = {'question': 'Synthetic question '+str(case), 'requested_answer_fields': [{'key': 'value'}],
                        'answer': 'AUDIT_INCLUDED' if rep == 0 else 'EXCLUDED_OTHER_REPEAT',
                        'reference': {'required_findings': [{'key': 'value', 'statement': 'Use observations.'}]},
                        'observations': [{'id': 'o', 'tool': 'synthetic', 'input': '{}', 'output': 'exact delivered text'}],
                        'requested_schema_policy': {'null_policy': 'reported_unknown_requires_semantic_judgment'},
                        'deterministic_numeric_checks': [{'status': 'VERDICT_CANARY'}],
                        'requested_schema_check': {'status': 'VERDICT_CANARY'}}
                    audit.api.save(self.source/'payloads'/f'{ident}.json', p)
                    self.mapping.append({'id': ident, 'case': case_id, 'arm': arm, 'rep': rep,
                        'payload_sha256': audit.api.sha(audit.api.encode(p))})
        audit.api.save(self.source/'mapping.json', self.mapping)
        folder = self.root/'eval/v5/legacy-migration'; folder.mkdir()
        audit.api.save(folder/'field-contracts.json', {'fields': contracts})
        (self.root/'docs').mkdir(); (self.root/'docs/EVAL-V5-LEGACY-ANALYSIS-PLAN.md').write_text('Synthetic prospective plan')
    def run_preparer(self, mapping=None):
        with patch.object(audit, 'ROOT', self.root), patch.object(audit, '_verified_mapping', return_value=self.mapping if mapping is None else mapping) as verified, contextlib.redirect_stdout(io.StringIO()):
            audit.main(); verified.assert_called_once_with(self.source)
    def test_exact_sample_balanced_packets_and_no_computed_verdict_leak(self):
        self.run_preparer(); all_ids = []; selected = []
        for index, expected_pi in ((1, 18), (2, 17)):
            packet = audit.api.read(self.out/f'batch-{index}.json')
            # Only synthetic mappings created by this test are inspected.
            private = audit.api.read(self.out/f'batch-{index}-mapping-private.json')
            self.assertEqual(len(packet), 35); self.assertEqual(sum(r['arm'] == 'pi_plus' for r in private), expected_pi)
            self.assertTrue(all(r['rep'] == 0 for r in private)); selected.extend(private)
            for item in packet:
                all_ids.append(item['id']); p = item['payload']
                self.assertEqual(set(p), {'question', 'requested_answer_fields', 'answer', 'reference', 'observations', 'requested_schema_policy', 'numeric_rubric'})
                self.assertEqual(p['answer'], 'AUDIT_INCLUDED')
                self.assertEqual(p['observations'][0]['output'], 'exact delivered text')
                self.assertEqual(len(p['numeric_rubric']), 1)
                self.assertNotIn('VERDICT_CANARY', json.dumps(item))
                self.assertNotIn('pi_plus', json.dumps(item)); self.assertNotIn('compact_plus', json.dumps(item))
        self.assertEqual(len(set(all_ids)), 70)
        self.assertEqual(len({(r['case'], r['arm']) for r in selected}), 70)
        manifest = audit.api.read(self.out/'manifest.json')
        self.assertNotIn('seed', manifest); self.assertIn('SystemRandom', manifest['allocation'])
        with self.assertRaisesRegex(ValueError, 'immutable'): self.run_preparer()
    def test_failed_frozen_mapping_verification_stops_before_packet_creation(self):
        with patch.object(audit, 'ROOT', self.root), patch.object(audit, '_verified_mapping', side_effect=ValueError('Frozen input changed')):
            with self.assertRaisesRegex(ValueError, 'Frozen'): audit.main()
        self.assertFalse(self.out.exists())
    def test_changed_payload_hash_is_rejected(self):
        ident = next(r['id'] for r in self.mapping if r['rep'] == 0)
        path = self.source/'payloads'/f'{ident}.json'; p = audit.api.read(path); p['answer'] += ' CHANGED'; audit.api.save(path, p)
        with self.assertRaisesRegex(ValueError, 'identity changed'): self.run_preparer()
if __name__ == '__main__': unittest.main()
