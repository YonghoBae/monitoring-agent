import copy
import unittest

from analyze_legacy_eval_v5 import analyze, percentile


def fixture():
    scenes = [{'id': case, 'family': family, 'answer_fields': [{'key': 'x'}]}
              for case, family in [('a', 'shared'), ('b', 'shared'), ('c', 'single')]]
    rows = []
    for scene in scenes:
        for arm in ('pi_plus', 'compact_plus'):
            for rep in range(3):
                rows.append({'case': scene['id'], 'family': scene['family'], 'arm': arm, 'rep': rep,
                             'stable_fields': {'x': arm == 'compact_plus' and scene['family'] == 'shared'},
                             'scored_agreement': True})
    return {'answers': rows}, {'scenarios': scenes}


class AnalysisTests(unittest.TestCase):
    def test_family_equal_weight_not_duplicate_case_weight(self):
        summary, dataset = fixture()
        result = analyze(summary, dataset, draws=1000)
        self.assertEqual(result['primary_family_macro_percent']['compact_plus'], 50)
        self.assertEqual(result['family_count'], 2)
        self.assertEqual(result['within_benchmark_ordering'], 'not_established')

    def test_duplicate_or_missing_answer_rejected(self):
        summary, dataset = fixture()
        summary['answers'][-1] = copy.deepcopy(summary['answers'][0])
        with self.assertRaises(ValueError):
            analyze(summary, dataset, draws=10)

    def test_wrong_family_or_hidden_findings_rejected(self):
        for change in ('family', 'fields'):
            summary, dataset = fixture()
            if change == 'family':
                summary['answers'][0]['family'] = 'invented'
            else:
                summary['answers'][0]['stable_fields']['unrequested'] = True
            with self.assertRaises(ValueError):
                analyze(summary, dataset, draws=10)

    def test_unresolved_can_block_apparent_lead(self):
        summary, dataset = fixture()
        for row in summary['answers']:
            row['stable_fields']['x'] = row['arm'] == 'compact_plus'
            row['scored_agreement'] = row['arm'] == 'compact_plus'
        result = analyze(summary, dataset, draws=100)
        self.assertEqual(result['paired_family_bootstrap_sensitivity_interval'], [100, 100])
        self.assertEqual(result['unresolved_sensitivity_difference_bounds'][0], 0)
        self.assertEqual(result['within_benchmark_ordering'], 'not_established')

    def test_consistent_complete_lead_and_reproducibility(self):
        summary, dataset = fixture()
        for row in summary['answers']:
            row['stable_fields']['x'] = row['arm'] == 'compact_plus'
        first = analyze(summary, dataset, draws=100)
        self.assertEqual(first, analyze(summary, dataset, draws=100))
        self.assertEqual(first['within_benchmark_ordering'], 'compact_plus_ahead')
        self.assertEqual(first['general_harness_ranking'], 'not_established_by_this_selected_benchmark')

    def test_percentile_linear_interpolation(self):
        self.assertAlmostEqual(percentile([0, 10], .25), 2.5)
        self.assertEqual(percentile([7], .975), 7)
    def test_boolean_repeat_and_truthy_agreement_strings_rejected(self):
        for key, value in (('rep', False), ('rep', 0.0), ('scored_agreement', 'false'), ('scored_agreement', 1)):
            summary, dataset = fixture(); summary['answers'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                analyze(summary, dataset, draws=10)
    def test_duplicate_source_cases_and_finding_keys_rejected(self):
        for mode in ('case', 'finding'):
            summary, dataset = fixture()
            if mode == 'case': dataset['scenarios'].append(copy.deepcopy(dataset['scenarios'][0]))
            else: dataset['scenarios'][0]['answer_fields'].append({'key': 'x'})
            with self.subTest(mode=mode), self.assertRaises(ValueError): analyze(summary, dataset, draws=10)
    def test_nonpositive_or_boolean_draw_count_rejected(self):
        summary, dataset = fixture()
        for draws in (0, -1, True, 10.0):
            with self.subTest(draws=draws), self.assertRaises(ValueError): analyze(summary, dataset, draws=draws)


if __name__ == '__main__':
    unittest.main()
