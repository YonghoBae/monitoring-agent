"""Supplemental review tests using only temporary35-case synthetic data."""
import contextlib
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compare_legacy_cross_review_v5 as cross


class SupplementalCrossReviewTest(unittest.TestCase):
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
        self.scenes = []
        self.samples = []
        for case in range(35):
            keys = ['value', 'status'] + (['detail'] if case < 11 else [])
            family = f'family-{case if case < 28 else case-28}'
            self.scenes.append({'id': f'case-{case}', 'family': family,
                                'answer_fields': [{'key': key} for key in keys]})
            for arm in cross.ARMS:
                for rep in range(3):
                    ident = f'answer-{len(self.mapping)}'
                    payload = {'question': f'Synthetic question {case}',
                        'requested_answer_fields': [{'key': key} for key in keys],
                        'answer': 'value is 12 GB. status is healthy. detail is confirmed.',
                        'reference': {'required_findings': [{'key': key} for key in keys]},
                        'observations': [{'id': 'o', 'output': '12 GB; healthy; confirmed'}],
                        'requested_schema_policy': {},
                        'deterministic_numeric_checks': [{'key': 'value', 'status': 'pass', 'numeric_correct': True}],
                        'measurement_scope': {'all_field_keys': keys, 'base_field_keys': keys, 'numeric_field_keys': ['value']},
                        'structured_format_check': {'status': 'valid'},
                        'requested_schema_check': {'valid': True, 'status': 'valid'}}
                    review = {'id': 'blind-'+ident, 'findings': {key: True for key in keys},
                        'unsupported_claims': False, 'pass': True, 'ambiguous': False,
                        'reason': 'Synthetic independent rationale kept verbatim.',
                        'notes': [{'key': key, 'quote': key+' is', 'observation_ids': ['o'],
                                   'reason': 'Synthetic evidence note '+key} for key in keys]}
                    self.save(self.scoring/'payloads'/f'{ident}.json', payload)
                    source = {'id': ident, 'case': f'case-{case}', 'family': family, 'arm': arm, 'rep': rep,
                        'runner_error': '', 'payload_sha256': cross.api.sha(cross.api.encode(payload))}
                    self.mapping.append(source)
                    component = {'combined_fields': {key: True for key in keys}, 'structured_pass': True}
                    self.answers.append({**source, 'judge_components': {'0': copy.deepcopy(component), '1': copy.deepcopy(component)},
                        'complete': True, 'integrity_errors': [], 'scored_agreement': True,
                        'stable_fields': {key: True for key in keys}, 'stable_structured_pass': True})
                    if rep == 0: self.samples.append((source, payload, review))
        self.save(self.root/'eval/v5/legacy-migration/dataset.json', {'scenarios': self.scenes})
        self.save_source()
        packet_hashes = {}
        for batch in (1, 2):
            packet = []; private = []; labels = []
            for source, payload, review in self.samples[(batch-1)*35:batch*35]:
                ident = review['id']
                visible = {key: payload[key] for key in ('question', 'requested_answer_fields', 'answer',
                    'reference', 'observations', 'requested_schema_policy')}
                visible['numeric_rubric'] = []
                packet.append({'id': ident, 'payload': visible})
                private.append({'id': ident, 'scorer_id': source['id'], 'case': source['case'], 'arm': source['arm'], 'rep': 0})
                labels.append(review)
            packet_path = self.out/f'batch-{batch}.json'
            self.save(packet_path, packet)
            packet_hashes[packet_path.name] = cross.api.sha(packet_path.read_bytes())
            self.save(self.out/f'batch-{batch}-mapping-private.json', private)
            for suffix in ('review', 'crossreview'):
                self.save(self.out/f'batch-{batch}-{suffix}.json',
                    {'source_batch_sha256': packet_hashes[packet_path.name], 'rows': labels})
        self.save(self.out/'manifest.json', {'source_mapping_sha256': self.digest(self.scoring/'mapping.json'),
                                           'packet_sha256': packet_hashes})
        self.seal()

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        cross.api.save(path, value)

    def digest(self, path):
        return cross.api.sha(path.read_bytes())

    def save_source(self):
        self.save(self.scoring/'mapping.json', self.mapping)
        self.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        if (self.out/'manifest.json').exists():
            manifest = cross.api.read(self.out/'manifest.json')
            manifest['source_mapping_sha256'] = self.digest(self.scoring/'mapping.json')
            self.save(self.out/'manifest.json', manifest)

    def seal(self):
        for kind, suffix in (('primary', 'review'), ('cross', 'crossreview')):
            self.save(self.out/f'{kind}-review-lock.json', {'locked_at': 'synthetic', 'review_hashes':
                {f'batch-{batch}-{suffix}.json': self.digest(self.out/f'batch-{batch}-{suffix}.json') for batch in (1, 2)}})

    def mutate_label(self, mutate, kind='crossreview', index=0, batch=1):
        path = self.out/f'batch-{batch}-{kind}.json'
        review = cross.api.read(path)
        mutate(review['rows'][index])
        self.save(path, review)
        self.seal()

    def change_payload(self, mutate):
        ident = self.mapping[0]['id']
        path = self.scoring/'payloads'/f'{ident}.json'
        payload = cross.api.read(path)
        mutate(payload)
        self.save(path, payload)
        digest = cross.api.sha(cross.api.encode(payload))
        self.mapping[0]['payload_sha256'] = digest
        self.answers[0]['payload_sha256'] = digest
        self.save_source()

    def update_auto(self, index=0, *, fields=None, strict=None, missing=None, errors=None):
        row = self.answers[index]
        if fields is not None:
            for c in row['judge_components'].values(): c['combined_fields'].update(fields)
        if strict is not None:
            for c in row['judge_components'].values(): c['structured_pass'] = strict
        if missing is not None: row['judge_components'].pop(missing)
        if errors is not None: row['integrity_errors'] = errors
        self.recompute_auto(index)

    def recompute_auto(self, index=0):
        row = self.answers[index]
        components = row['judge_components']
        row['complete'] = set(components) == {'0', '1'} and not row['integrity_errors']
        row['scored_agreement'] = bool(row['complete'] and components['0'] == components['1'])
        row['stable_fields'] = {key: bool(row['complete'] and all(c['combined_fields'][key] for c in components.values()))
                                for key in row['stable_fields']}
        row['stable_structured_pass'] = bool(row['scored_agreement'] and all(c['structured_pass'] for c in components.values()))
        self.save_source()

    def run_comparison(self, primary_effect=None):
        with patch.object(cross, 'ROOT', self.root), patch.object(cross.primary, 'ROOT', self.root), \
                patch.object(cross, '_verified_mapping', return_value=copy.deepcopy(self.mapping)) as source_check, \
                patch.object(cross.primary, '_verified_mapping', return_value=copy.deepcopy(self.mapping)) as primary_check, \
                contextlib.redirect_stdout(io.StringIO()):
            if primary_effect is None:
                cross.main()
            else:
                with patch.object(cross.primary, 'main', side_effect=primary_effect): cross.main()
            source_check.assert_called_once_with(self.scoring)
            primary_check.assert_called_once_with(self.scoring)
        return cross.api.read(self.out/'cross-agreement-summary.json')

    def test_complete_sample_and_field_denominators(self):
        result = self.run_comparison()
        self.assertEqual((result['answers'], result['field_denominator'], result['family_count']), (70, 162, 28))
        self.assertEqual(result['reviewer_agreement']['raw_semantic_fields'], {'agreement': 162, 'denominator': 162})
        self.assertEqual(result['reviewer_agreement']['strict_pass'], {'agreement': 70, 'denominator': 70})
        self.assertEqual(result['automatic_comparison']['all_answers']['matches_common_endpoints'], 70)
        for arm in cross.ARMS:
            self.assertEqual((result['arms'][arm]['answers'], result['arms'][arm]['field_denominator']), (35, 81))
            self.assertEqual(result['arms'][arm]['metrics']['primary']['correct_fields'], 81)
            self.assertEqual(result['arms'][arm]['metrics']['cross']['strict_pass'], 35)
        self.assertIn('not preregistered', result['scope'])
        self.assertIn('not human ground truth', result['scope'])

    def test_numeric_failure_can_mask_raw_semantic_disagreement(self):
        self.change_payload(lambda p: p['deterministic_numeric_checks'][0].update(status='fail', numeric_correct=False))
        self.update_auto(fields={'value': False}, strict=False)
        self.mutate_label(lambda r: (r['findings'].update(value=False), r.update(**{'pass': False})))
        result = self.run_comparison()
        self.assertEqual(result['reviewer_agreement']['raw_semantic_fields']['agreement'], 161)
        self.assertEqual(result['reviewer_agreement']['combined_fields']['agreement'], 162)
        self.assertEqual(result['reviewer_agreement']['strict_pass']['agreement'], 70)
        self.assertEqual(result['automatic_comparison']['all_answers']['matches_common_endpoints'], 70)
        first = result['rows'][0]
        self.assertEqual(first['differences']['raw_semantic_fields'], ['value'])
        self.assertEqual(first['differences']['combined_fields'], [])

    def test_endpoint_disagreement_yields_reviewer_ranges_not_auto_error(self):
        self.mutate_label(lambda r: (r['findings'].update(value=False), r.update(**{'pass': False})))
        result = self.run_comparison()
        self.assertEqual(result['automatic_comparison']['all_answers']['reviewers_disagree'], 1)
        self.assertEqual(result['automatic_comparison']['all_answers']['differs_from_common_endpoints'], 0)
        arm = result['arms']['pi_plus']['metrics']
        self.assertEqual((arm['both_reviewers_true']['correct_fields'], arm['either_reviewer_true']['correct_fields']), (80, 81))
        self.assertEqual((arm['both_reviewers_true']['strict_pass'], arm['either_reviewer_true']['strict_pass']), (34, 35))

    def test_field_union_does_not_invent_a_whole_answer_pass(self):
        self.mutate_label(lambda r: (r['findings'].update(value=False), r.update(**{'pass': False})), kind='review')
        self.mutate_label(lambda r: (r['findings'].update(status=False), r.update(**{'pass': False})))
        result = self.run_comparison()
        arm = result['arms']['pi_plus']['metrics']
        self.assertEqual((arm['both_reviewers_true']['correct_fields'], arm['either_reviewer_true']['correct_fields']), (79, 81))
        self.assertEqual((arm['both_reviewers_true']['strict_pass'], arm['either_reviewer_true']['strict_pass']), (34, 34))

    def test_auxiliary_unsupported_disagreement_does_not_change_failed_endpoints(self):
        self.change_payload(lambda p: p['deterministic_numeric_checks'][0].update(status='fail', numeric_correct=False))
        self.update_auto(fields={'value': False}, strict=False)
        self.mutate_label(lambda r: r.update(unsupported_claims=True, **{'pass': False}))
        result = self.run_comparison()
        self.assertEqual(result['reviewer_agreement']['unsupported_claims_auxiliary']['agreement'], 69)
        self.assertEqual(result['reviewer_agreement']['combined_fields']['agreement'], 162)
        self.assertEqual(result['reviewer_agreement']['strict_pass']['agreement'], 70)
        self.assertEqual(result['automatic_comparison']['all_answers']['matches_common_endpoints'], 70)

    def test_invalid_schema_blocks_strict_without_erasing_fields(self):
        self.change_payload(lambda p: p['requested_schema_check'].update(valid=False, status='invalid'))
        self.update_auto(strict=False)
        result = self.run_comparison()
        self.assertTrue(all(result['rows'][0]['primary_combined_fields'].values()))
        self.assertFalse(result['rows'][0]['primary_strict_pass'])
        self.assertEqual(result['arms']['pi_plus']['metrics']['primary']['correct_fields'], 81)
        self.assertEqual(result['arms']['pi_plus']['metrics']['primary']['strict_pass'], 34)

    def test_missing_invalid_judge_never_counts_as_match(self):
        self.update_auto(missing='1', errors=['invalid_judgment'])
        result = self.run_comparison()
        counts = result['automatic_comparison']['all_answers']
        self.assertEqual((counts['matches_common_endpoints'], counts['invalid_for_common_endpoints'], counts['all_invalid_automatic']), (69, 1, 1))
        self.assertEqual(result['rows'][0]['automatic_missing_judge_repetitions'], ['1'])

    def test_two_components_with_integrity_error_remain_invalid(self):
        self.update_auto(errors=['duplicate_judge_rep'])
        result = self.run_comparison()
        self.assertEqual(result['automatic_comparison']['all_answers']['invalid_for_common_endpoints'], 1)
        self.assertEqual(result['automatic_comparison']['all_answers']['matches_common_endpoints'], 69)

    def test_valid_automatic_disagreement_is_mismatch_not_invalid(self):
        self.answers[0]['judge_components']['1']['combined_fields']['value'] = False
        self.answers[0]['judge_components']['1']['structured_pass'] = False
        self.recompute_auto()
        result = self.run_comparison()
        counts = result['automatic_comparison']['all_answers']
        self.assertEqual((counts['differs_from_common_endpoints'], counts['invalid_for_common_endpoints']), (1, 0))
        self.assertEqual(result['rows'][0]['per_judge_differences_from_primary']['1'], ['finding:value', 'structured_pass'])

    def test_ambiguity_union_has_separate_consensus_denominators(self):
        self.mutate_label(lambda r: r.update(ambiguous=True), kind='review', index=0)
        self.mutate_label(lambda r: r.update(ambiguous=True), index=1)
        result = self.run_comparison()
        self.assertEqual(result['any_reviewer_ambiguous'], 2)
        counts = result['automatic_comparison']
        self.assertEqual(counts['all_answers']['common_endpoint_answers'], 70)
        self.assertEqual(counts['nonambiguous_answers']['common_endpoint_answers'], 68)
        self.assertEqual(counts['nonambiguous_answers']['matches_common_endpoints'], 68)
        self.assertEqual(counts['ambiguous_answers']['answers'], 2)
        self.assertEqual(result['field_denominator'], 162)
        self.assertEqual(counts['nonambiguous_answers']['common_endpoint_field_denominator'], 156)
        self.assertEqual(counts['ambiguous_answers']['common_endpoint_field_denominator'], 6)

    def test_invalid_automatic_count_preserved_when_reviewers_disagree(self):
        self.update_auto(missing='1', errors=['invalid_judgment'])
        self.mutate_label(lambda r: (r['findings'].update(value=False), r.update(**{'pass': False})))
        result = self.run_comparison()
        counts = result['automatic_comparison']['all_answers']
        self.assertEqual((counts['reviewers_disagree'], counts['all_invalid_automatic'], counts['invalid_for_common_endpoints']), (1, 1, 0))

    def test_family_macro_does_not_overweight_multi_case_family(self):
        def all_false(review):
            review['findings'] = {key: False for key in review['findings']}
            review['pass'] = False
        self.mutate_label(all_false, kind='review')
        self.mutate_label(all_false)
        self.update_auto(fields={'value': False, 'status': False, 'detail': False}, strict=False)
        result = self.run_comparison()
        metric = result['arms']['pi_plus']['metrics']['primary']
        self.assertAlmostEqual(metric['family_macro_percent'], 100 * 27.5 / 28)
        self.assertAlmostEqual(metric['field_micro_percent'], 100 * 78 / 81)
        self.assertEqual(result['family_field_percent']['primary']['family-0']['pi_plus'], 50)

    def test_preserves_all_original_review_notes_reasons_and_inputs(self):
        before = {path: path.read_bytes() for path in self.root.rglob('*.json')}
        result = self.run_comparison()
        for path, raw in before.items(): self.assertEqual(path.read_bytes(), raw)
        p = cross.api.read(self.out/'batch-1-review.json')['rows'][0]
        c = cross.api.read(self.out/'batch-1-crossreview.json')['rows'][0]
        self.assertEqual(result['rows'][0]['primary_review'], p)
        self.assertEqual(result['rows'][0]['cross_review'], c)
        self.assertIn('eval/v5/legacy-answer-audit/primary-review-lock.json', result['input_sha256'])
        self.assertIn('eval/v5/legacy-answer-audit/agreement-summary.json', result['input_sha256'])

    def test_changed_primary_or_cross_review_rejected_by_lock(self):
        for suffix in ('review', 'crossreview'):
            with self.subTest(suffix=suffix):
                path = self.out/f'batch-1-{suffix}.json'
                original = path.read_bytes()
                path.write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError, 'locked review hash'): self.run_comparison()
                path.write_bytes(original)
        self.assertFalse((self.out/'cross-agreement-summary.json').exists())

    def test_lock_must_name_exact_two_files(self):
        path = self.out/'cross-review-lock.json'
        lock = cross.api.read(path)
        lock['review_hashes']['unexpected.json'] = 'x'
        self.save(path, lock)
        with self.assertRaisesRegex(ValueError, 'exactly the two'): self.run_comparison()

    def test_missing_locked_review_rejected(self):
        (self.out/'batch-2-crossreview.json').unlink()
        with self.assertRaises(FileNotFoundError): self.run_comparison()

    def test_duplicate_or_missing_cross_review_rows_rejected(self):
        path = self.out/'batch-1-crossreview.json'
        original = cross.api.read(path)
        for mode in ('duplicate', 'missing'):
            with self.subTest(mode=mode):
                review = copy.deepcopy(original)
                if mode == 'duplicate': review['rows'][1] = copy.deepcopy(review['rows'][0])
                else: review['rows'].pop()
                self.save(path, review); self.seal()
                with self.assertRaises(ValueError): self.run_comparison()

    def test_resealed_review_for_wrong_packet_rejected(self):
        path = self.out/'batch-1-crossreview.json'
        review = cross.api.read(path); review['source_batch_sha256'] = 'wrong'
        self.save(path, review); self.seal()
        with self.assertRaisesRegex(ValueError, 'same exact35'): self.run_comparison()

    def test_changed_packet_rejected(self):
        path = self.out/'batch-1.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'packet hash'): self.run_comparison()

    def test_rehashed_packet_still_must_match_source(self):
        path = self.out/'batch-1.json'
        packet = cross.api.read(path); packet[0]['payload']['answer'] += ' fabricated'
        self.save(path, packet)
        digest = self.digest(path)
        manifest = cross.api.read(self.out/'manifest.json'); manifest['packet_sha256'][path.name] = digest
        self.save(self.out/'manifest.json', manifest)
        for suffix in ('review', 'crossreview'):
            review_path = self.out/f'batch-1-{suffix}.json'
            review = cross.api.read(review_path); review['source_batch_sha256'] = digest
            self.save(review_path, review)
        self.seal()
        with self.assertRaisesRegex(ValueError, 'verified source payload'): self.run_comparison()

    def test_duplicate_private_mapping_rejected(self):
        path = self.out/'batch-1-mapping-private.json'
        mapping = cross.api.read(path); mapping[1] = copy.deepcopy(mapping[0])
        self.save(path, mapping)
        with self.assertRaisesRegex(ValueError, 'duplicate IDs'): self.run_comparison()

    def test_private_mapping_wrong_rep_rejected(self):
        path = self.out/'batch-1-mapping-private.json'
        mapping = cross.api.read(path); mapping[0]['rep'] = 1
        self.save(path, mapping)
        with self.assertRaisesRegex(ValueError, 'repetition0'): self.run_comparison()

    def test_payload_and_summary_rehash_cannot_override_frozen_mapping(self):
        path = self.scoring/'payloads'/f"{self.mapping[0]['id']}.json"
        payload = cross.api.read(path); payload['deterministic_numeric_checks'][0].update(status='fail', numeric_correct=False)
        self.save(path, payload)
        self.answers[0]['payload_sha256'] = cross.api.sha(cross.api.encode(payload))
        self.save(self.scoring/'summary.json', {'judgments': 420, 'answers': self.answers})
        with self.assertRaisesRegex(ValueError, 'verified source mapping'): self.run_comparison()

    def test_frozen_verifier_failure_aborts(self):
        with patch.object(cross, 'ROOT', self.root), patch.object(cross, '_verified_mapping', side_effect=ValueError('Frozen source changed')):
            with self.assertRaisesRegex(ValueError, 'Frozen source changed'): cross.main()
        self.assertFalse((self.out/'cross-agreement-summary.json').exists())

    def test_incomplete_automatic_ledger_rejected(self):
        self.save(self.scoring/'summary.json', {'judgments': 419, 'answers': self.answers})
        with self.assertRaisesRegex(ValueError, 'Complete automatic'): self.run_comparison()

    def test_automatic_stable_scores_must_match_components(self):
        self.answers[0]['stable_fields']['value'] = False
        self.save_source()
        with self.assertRaisesRegex(ValueError, 'contradict judge components'): self.run_comparison()

    def test_non_boolean_manual_label_and_wrong_quote_rejected(self):
        path = self.out/'batch-1-crossreview.json'
        original = cross.api.read(path)
        for mode in ('label', 'quote'):
            with self.subTest(mode=mode):
                review = copy.deepcopy(original)
                if mode == 'label': review['rows'][0]['findings']['value'] = 1
                else: review['rows'][0]['notes'][0]['quote'] = 'never delivered answer quote'
                self.save(path, review); self.seal()
                with self.assertRaises(ValueError): self.run_comparison()

    def test_inconsistent_numeric_composition_rejected(self):
        self.change_payload(lambda p: p['deterministic_numeric_checks'][0].update(numeric_correct=False))
        with self.assertRaisesRegex(ValueError, 'Inconsistent deterministic'): self.run_comparison()

    def test_wrong_dataset_field_denominator_rejected(self):
        self.scenes[0]['answer_fields'].pop()
        self.save(self.root/'eval/v5/legacy-migration/dataset.json', {'scenarios': self.scenes})
        with self.assertRaisesRegex(ValueError, '81-field'): self.run_comparison()

    def test_primary_summary_must_bind_to_the_same_primary_endpoints(self):
        original_main = cross.primary.main
        def tampered_summary():
            original_main()
            path = self.out/'agreement-summary.json'
            summary = cross.api.read(path)
            summary['rows'][0]['independent_structured_pass'] = False
            self.save(path, summary)
        with self.assertRaisesRegex(ValueError, 'official primary comparison'):
            self.run_comparison(tampered_summary)

    def test_input_change_during_primary_comparison_rejected(self):
        original_main = cross.primary.main
        def concurrent_change():
            original_main()
            path = self.out/'batch-1-crossreview.json'
            path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'Input changed during comparison'):
            self.run_comparison(concurrent_change)
        self.assertFalse((self.out/'cross-agreement-summary.json').exists())


if __name__ == '__main__':
    unittest.main()
