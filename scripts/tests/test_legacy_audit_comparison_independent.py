"""Independent synthetic endpoint/provenance tests; never opens actual audit data."""
import contextlib
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compare_legacy_answer_audit_v5 as comparison


def fixture():
    payload = {
        'question': 'Report storage and service condition.',
        'requested_answer_fields': [{'key': 'storage'}, {'key': 'condition'}],
        'answer': 'Storage is 12 GB. Service is healthy.',
        'reference': {'required_findings': [{'key': 'storage'}, {'key': 'condition'}]},
        'observations': [{'id': 'obs-storage', 'output': '12 GB'},
                         {'id': 'obs-service', 'output': 'healthy'}],
        'requested_schema_policy': {},
        'deterministic_numeric_checks': [{'key': 'storage', 'status': 'pass', 'numeric_correct': True}],
        'measurement_scope': {'all_field_keys': ['storage', 'condition'],
                              'numeric_field_keys': ['storage'],
                              'base_field_keys': ['storage', 'condition']},
        'structured_format_check': {'status': 'valid'},
        'requested_schema_check': {'valid': True, 'status': 'valid'},
    }
    review = {
        'findings': {'storage': True, 'condition': True},
        'unsupported_claims': False, 'pass': True, 'ambiguous': False,
        'notes': [{'key': 'storage', 'quote': 'Storage is 12 GB.', 'observation_ids': ['obs-storage']},
                  {'key': 'condition', 'quote': 'Service is healthy.', 'observation_ids': ['obs-service']}],
    }
    return payload, review


class IndependentAuditCompositionTest(unittest.TestCase):
    def setUp(self):
        self.payload, self.review = fixture()

    def compose(self, runner_error=''):
        return comparison.compose_review(self.review, self.payload, runner_error)

    def test_semantic_success_cannot_override_numeric_failure(self):
        self.payload['deterministic_numeric_checks'][0].update(status='fail', numeric_correct=False)
        fields, strict = self.compose()
        self.assertEqual(fields, {'storage': False, 'condition': True})
        self.assertFalse(strict)

    def test_ungradable_numeric_field_remains_unsatisfied(self):
        self.payload['deterministic_numeric_checks'][0].update(status='ungradable', numeric_correct=None)
        fields, strict = self.compose()
        self.assertFalse(fields['storage'])
        self.assertTrue(fields['condition'])
        self.assertFalse(strict)

    def test_numeric_success_cannot_override_semantic_failure(self):
        self.review['findings']['storage'] = False
        self.review['pass'] = False
        fields, strict = self.compose()
        self.assertFalse(fields['storage'])
        self.assertFalse(strict)

    def test_valid_success_is_pass(self):
        self.assertEqual(self.compose(), ({'storage': True, 'condition': True}, True))

    def test_empty_answer_with_all_false_labels_remains_nonpass(self):
        self.payload['answer'] = ''
        self.review['findings'] = {'storage': False, 'condition': False}
        self.review.update(notes=[], **{'pass': False})
        self.assertEqual(self.compose(), ({'storage': False, 'condition': False}, False))

    def test_invalid_schema_preserves_fields_but_blocks_strict_pass(self):
        self.payload['requested_schema_check'].update(valid=False, status='missing_required_key')
        fields, strict = self.compose()
        self.assertEqual(fields, {'storage': True, 'condition': True})
        self.assertFalse(strict)

    def test_invalid_format_blocks_strict_pass(self):
        self.payload['structured_format_check']['status'] = 'invalid'
        self.assertFalse(self.compose()[1])

    def test_runner_error_blocks_strict_pass(self):
        self.assertFalse(self.compose('runner failed')[1])

    def test_unsupported_claim_blocks_strict_pass(self):
        self.review.update(unsupported_claims=True, **{'pass': False})
        fields, strict = self.compose()
        self.assertTrue(all(fields.values()))
        self.assertFalse(strict)

    def test_non_substring_quote_rejected(self):
        self.review['notes'][0]['quote'] = 'Storage is 13 GB.'
        with self.assertRaises(ValueError): self.compose()

    def test_substring_notes_survive_native_schema_adapter_unchanged(self):
        self.review['notes'][0]['quote'] = '12 GB'
        self.review['notes'][1]['quote'] = 'healthy'
        before = copy.deepcopy(self.review)
        self.assertTrue(self.compose()[1])
        self.assertEqual(self.review, before)

    def test_whitespace_quote_cannot_support_satisfied_field(self):
        self.review['notes'][0]['quote'] = ' '
        with self.assertRaises(ValueError): self.compose()

    def test_observation_ids_must_be_array_not_string(self):
        self.review['notes'][0]['observation_ids'] = 'obs-storage'
        with self.assertRaises(ValueError): self.compose()

    def test_duplicate_observation_ids_rejected(self):
        self.review['notes'][0]['observation_ids'] = ['obs-storage', 'obs-storage']
        with self.assertRaises(ValueError): self.compose()

    def test_undelivered_observation_rejected(self):
        self.review['notes'][0]['observation_ids'] = ['not-delivered']
        with self.assertRaises(ValueError): self.compose()

    def test_missing_field_label_rejected(self):
        del self.review['findings']['condition']
        with self.assertRaises(ValueError): self.compose()

    def test_unknown_field_label_rejected(self):
        self.review['findings']['other'] = True
        with self.assertRaises(ValueError): self.compose()

    def test_each_satisfied_field_requires_its_own_nonempty_quote(self):
        for replacement in (None, '', 'wrong-key'):
            with self.subTest(replacement=replacement):
                self.payload, self.review = fixture()
                if replacement is None: self.review['notes'].pop()
                elif replacement == '': self.review['notes'][1]['quote'] = ''
                else: self.review['notes'][1]['key'] = replacement
                with self.assertRaises(ValueError): self.compose()

    def test_false_finding_does_not_require_supporting_quote(self):
        self.review['findings']['condition'] = False
        self.review['pass'] = False
        self.review['notes'].pop()
        self.assertEqual(self.compose(), ({'storage': True, 'condition': False}, False))

    def test_non_boolean_labels_rejected(self):
        for key in ('unsupported_claims', 'pass', 'ambiguous', 'storage'):
            with self.subTest(key=key):
                self.payload, self.review = fixture()
                if key == 'storage': self.review['findings'][key] = 1
                else: self.review[key] = 1
                with self.assertRaises(ValueError): self.compose()

    def test_contradictory_semantic_pass_rejected(self):
        self.review['pass'] = False
        with self.assertRaises(ValueError): self.compose()

    def test_non_boolean_schema_validity_rejected(self):
        self.payload['requested_schema_check']['valid'] = 'false'
        with self.assertRaises(ValueError): self.compose()

    def test_missing_numeric_check_cannot_silently_become_semantic_only(self):
        self.payload['deterministic_numeric_checks'] = []
        with self.assertRaises(ValueError): self.compose()

    def test_duplicate_numeric_check_cannot_overwrite_failure(self):
        self.payload['deterministic_numeric_checks'].insert(0,
            {'key': 'storage', 'status': 'fail', 'numeric_correct': False})
        with self.assertRaises(ValueError): self.compose()

    def test_unknown_numeric_check_rejected(self):
        self.payload['deterministic_numeric_checks'].append(
            {'key': 'unknown', 'status': 'pass', 'numeric_correct': True})
        with self.assertRaises(ValueError): self.compose()

    def test_numeric_status_must_agree_with_correctness(self):
        self.payload['deterministic_numeric_checks'][0]['numeric_correct'] = False
        with self.assertRaises(ValueError): self.compose()

    def test_measurement_scope_must_include_all_findings(self):
        self.payload['measurement_scope']['all_field_keys'] = ['storage']
        with self.assertRaises(ValueError): self.compose()


class IndependentAuditComparisonProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scoring = self.root/'eval/v5/legacy-scoring-v55'
        self.out = self.root/'eval/v5/legacy-answer-audit'
        (self.scoring/'payloads').mkdir(parents=True)
        self.out.mkdir(parents=True)
        self.mapping = []
        self.answers = []
        samples = []
        for case in range(35):
            for arm in ('pi_plus', 'compact_plus'):
                for rep in range(3):
                    ident = f'answer-{len(self.mapping)}'
                    payload, review = fixture()
                    payload['question'] += f' Synthetic case {case}.'
                    comparison.api.save(self.scoring/'payloads'/f'{ident}.json', payload)
                    source = {'id': ident, 'case': f'case-{case}', 'arm': arm, 'rep': rep,
                              'payload_sha256': comparison.api.sha(comparison.api.encode(payload))}
                    self.mapping.append(source)
                    component = {'combined_fields': {'storage': True, 'condition': True},
                                 'structured_pass': True}
                    self.answers.append({**source, 'runner_error': '',
                        'judge_components': {'0': copy.deepcopy(component), '1': copy.deepcopy(component)},
                        'stable_fields': component['combined_fields'], 'stable_structured_pass': True,
                        'scored_agreement': True})
                    if rep == 0: samples.append((source, payload, review))
        comparison.api.save(self.scoring/'mapping.json', self.mapping)
        comparison.api.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        hashes = {}
        for index in (1, 2):
            packet = []; private = []; reviews = []
            for source, payload, review in samples[(index-1)*35:index*35]:
                ident = 'blind-'+source['id']
                visible = {key: payload[key] for key in ('question', 'requested_answer_fields', 'answer',
                    'reference', 'observations', 'requested_schema_policy')}
                visible['numeric_rubric'] = []
                packet.append({'id': ident, 'payload': visible})
                private.append({'id': ident, 'scorer_id': source['id'], 'case': source['case'],
                                'arm': source['arm'], 'rep': source['rep']})
                reviews.append({'id': ident, **review})
            packet_path = self.out/f'batch-{index}.json'
            comparison.api.save(packet_path, packet)
            hashes[packet_path.name] = comparison.api.sha(packet_path.read_bytes())
            comparison.api.save(self.out/f'batch-{index}-mapping-private.json', private)
            comparison.api.save(self.out/f'batch-{index}-review.json',
                                {'source_batch_sha256': hashes[packet_path.name], 'rows': reviews})
        comparison.api.save(self.out/'manifest.json',
            {'source_mapping_sha256': comparison.api.sha((self.scoring/'mapping.json').read_bytes()),
             'packet_sha256': hashes})

    def run_comparator(self):
        # Production verifies frozen plans and all payloads through this boundary.
        # Only synthetic integration fixtures replace that external verifier; the
        # comparator must still bind every summary row to its returned mapping.
        with patch.object(comparison, 'ROOT', self.root), \
                patch.object(comparison, '_verified_mapping', return_value=self.mapping) as verified, \
                contextlib.redirect_stdout(io.StringIO()):
            comparison.main()
            verified.assert_called_once_with(self.scoring)
        return comparison.api.read(self.out/'agreement-summary.json')

    def test_frozen_verification_failure_aborts_before_output(self):
        with patch.object(comparison, 'ROOT', self.root), \
                patch.object(comparison, '_verified_mapping', side_effect=ValueError('Frozen source changed')):
            with self.assertRaisesRegex(ValueError, 'Frozen source changed'):
                comparison.main()
        self.assertFalse((self.out/'agreement-summary.json').exists())

    def test_summary_metadata_cannot_override_verified_mapping(self):
        self.answers[-1]['case'] = 'unregistered-case'
        comparison.api.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        with self.assertRaises(ValueError): self.run_comparator()

    def test_duplicate_summary_identity_rejected(self):
        self.answers[-1] = copy.deepcopy(self.answers[0])
        comparison.api.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        with self.assertRaises(ValueError): self.run_comparator()

    def test_duplicate_private_mapping_row_rejected(self):
        path = self.out/'batch-1-mapping-private.json'
        mapping = comparison.api.read(path)
        mapping.append(copy.deepcopy(mapping[0]))
        comparison.api.save(path, mapping)
        with self.assertRaises(ValueError): self.run_comparator()

    def test_complete_synthetic_audit_counts_all_70_endpoints(self):
        summary = self.run_comparator()
        self.assertEqual(summary['answers'], 70)
        self.assertEqual(summary['all_both_judges_match'], 70)
        self.assertEqual(summary['nonambiguous_both_judges_match'], 70)
        self.assertEqual(summary['automated_unresolved_in_sample'], 0)
        self.assertEqual(len(summary['rows']), 70)

    def test_ambiguity_exclusion_keeps_full_denominator_visible(self):
        path = self.out/'batch-1-review.json'
        review = comparison.api.read(path)
        review['rows'][0]['ambiguous'] = True
        comparison.api.save(path, review)
        # The ambiguous answer is also the sole endpoint disagreement. Filtering
        # it must affect the nonambiguous statistic without erasing the full count.
        component = self.answers[0]['judge_components']['1']
        component['combined_fields']['storage'] = False
        component['structured_pass'] = False
        self.answers[0]['scored_agreement'] = False
        comparison.api.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        summary = self.run_comparator()
        self.assertEqual((summary['answers'], summary['ambiguous'], summary['nonambiguous']), (70, 1, 69))
        self.assertEqual(summary['all_both_judges_match'], 69)
        self.assertEqual(summary['nonambiguous_both_judges_match'], 69)
        self.assertEqual(summary['automated_unresolved_in_sample'], 1)
        self.assertEqual(summary['rows'][0]['per_judge_disagreements'],
                         {'0': [], '1': ['finding:storage', 'structured_pass']})

    def test_changed_hidden_numeric_payload_cannot_be_authorized_by_summary_hash(self):
        # Keep the original frozen source mapping and blind packet unchanged.
        # A regenerated summary is not authority to change deterministic evidence.
        ident = self.mapping[0]['id']
        path = self.scoring/'payloads'/f'{ident}.json'
        payload = comparison.api.read(path)
        payload['deterministic_numeric_checks'][0].update(status='fail', numeric_correct=False)
        comparison.api.save(path, payload)
        self.answers[0]['payload_sha256'] = comparison.api.sha(comparison.api.encode(payload))
        comparison.api.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        with self.assertRaises(ValueError): self.run_comparator()

    def test_duplicate_review_id_rejected(self):
        path = self.out/'batch-1-review.json'
        review = comparison.api.read(path)
        review['rows'][1]['id'] = review['rows'][0]['id']
        comparison.api.save(path, review)
        with self.assertRaises(ValueError): self.run_comparator()

    def test_changed_blind_packet_rejected(self):
        path = self.out/'batch-1.json'
        packet = comparison.api.read(path)
        packet[0]['payload']['answer'] += ' Changed.'
        comparison.api.save(path, packet)
        with self.assertRaises(ValueError): self.run_comparator()

    def test_review_attached_to_wrong_packet_rejected(self):
        path = self.out/'batch-1-review.json'
        review = comparison.api.read(path)
        review['source_batch_sha256'] = 'wrong-packet'
        comparison.api.save(path, review)
        with self.assertRaises(ValueError): self.run_comparator()

    def test_private_mapping_cannot_select_other_repetition(self):
        path = self.out/'batch-1-mapping-private.json'
        mapping = comparison.api.read(path)
        mapping[0]['rep'] = 1
        comparison.api.save(path, mapping)
        with self.assertRaises(ValueError): self.run_comparator()


if __name__ == '__main__':
    unittest.main()
