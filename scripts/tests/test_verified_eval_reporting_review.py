import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import report_verified_eval_v5 as report


def audit(**changes):
    value = {'answers': 70, 'ambiguous': 0, 'nonambiguous': 70,
             'nonambiguous_both_judges_match': 70, 'all_both_judges_match': 70,
             'automated_unresolved_in_sample': 0}
    value.update(changes)
    return value


class ReportingReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'docs').mkdir()
        self.base = self.root/'eval/v5'
        core_arm = {'stable_satisfied_findings': 60, 'requested_findings': 72,
                    'stable_field_accuracy_micro_percent': 83.3, 'stable_pass': 19,
                    'n': 24, 'stable_pass_percent': 79.2, 'unresolved': 2, 'runner_errors': 0}
        broad_arm = {'stable_all_field_micro_percent': 80, 'stable_base_field_micro_percent': 81,
                     'stable_structured_pass': 60, 'n': 105, 'unresolved': 2}
        core_audited_arm = {'both_reviewers_correct_fields': 60, 'field_denominator': 72,
                            'field_percent': 83.3, 'strict_pass_lower': 18,
                            'strict_pass_upper': 20, 'n': 24}
        workflow_arm = {'first_tool_counts': {'observations': 80}, 'median_elapsed_seconds': 5,
                        'median_delivered_tool_results': 2, 'n': 105}
        self.data = {
            'canonical-core/scoring-1/summary.json': {'answers': [{}]*48, 'judgments': 96,
                'arms': {a: copy.deepcopy(core_arm) for a in report.ARMS}},
            'legacy-scoring-v55/summary.json': {'answers': [{}]*210, 'judgments': 420,
                'arms': {a: copy.deepcopy(broad_arm) for a in report.ARMS}},
            'legacy-scoring-v55/family-analysis.json': {
                'within_benchmark_ordering': 'compact_plus_ahead',
                'primary_family_macro_percent': {'pi_plus': 75, 'compact_plus': 80},
                'paired_family_bootstrap_sensitivity_interval': [1, 9],
                'compact_minus_pi_percentage_points': 5,
                'repeat_differences_percentage_points': {'0': 4, '1': 5, '2': 6},
                'unresolved_sensitivity_difference_bounds': [1, 9]},
            'legacy-comparison-1/workflow-diagnostics.json': {
                'arms': {a: copy.deepcopy(workflow_arm) for a in report.ARMS}},
            'canonical-core/independent-review/agreement-summary.json': {
                'answers': 48, 'independent_finding_label_agreement': 140,
                'independent_finding_labels': 144, 'independent_reviewers_full_label_agreement': 45,
                'ambiguity_union': 3, 'consensus_nonambiguous_answers': 44,
                'consensus_nonambiguous_auto_full_agreement': 40,
                'audited_arms': {a: copy.deepcopy(core_audited_arm) for a in report.ARMS}},
            'legacy-answer-audit/agreement-summary.json': audit(),
            'legacy-bridge-validation-v55/summary.json': {'gate_passed': True, 'judgments': 60},
            'semantic-validation-v52/summary.json': {'gate_passed': True, 'judgments': 60},
            'canonical-core/comparison-1/manifest.json': {'status': 'completed', 'answers': 48},
            'legacy-comparison-1/manifest.json': {'status': 'completed', 'answers': 210},
        }

    def render(self):
        def synthetic_read(path):
            return self.data[str(path.relative_to(self.base))]
        with patch.object(report, 'ROOT', self.root), patch.object(report, 'BASE', self.base), \
                patch.object(report, 'read', side_effect=synthetic_read), \
                patch.object(report.budget, 'preflight', return_value={'total_campaigns_estimated_usd': 1.0}), \
                contextlib.redirect_stdout(io.StringIO()):
            report.main()
        return (self.root/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md').read_text()

    def test_full_synthetic_report_uses_schema_and_limits(self):
        text = self.render()
        self.assertIn('70/70개', text)
        self.assertIn('사람 정답 검증이나 전체 답변의 채점 정확도 인증이 아니다', text)
        self.assertIn('검수자 간 일치율을 추정하지 않는다', text)
        self.assertIn('보정한 결과는 아니다', text)
        self.assertNotIn('일관되게 앞섰다', text)
        self.assertIn('정확도 지표나 사전 우열 판정의 근거가 아니다', text)

    def test_disagreements_visible_before_any_result_table(self):
        self.data['legacy-answer-audit/agreement-summary.json'] = audit(
            ambiguous=3, nonambiguous=67, nonambiguous_both_judges_match=58,
            all_both_judges_match=60, automated_unresolved_in_sample=2)
        text = self.render()
        opening = text.split('## 1.')[0]
        self.assertIn('60/70개', opening)
        self.assertIn('완전 일치가 아닌 표본은 10개', opening)
        self.assertIn('모호한 표본은 3개', opening)
        self.assertIn('조건부 결과', opening)
        self.assertIn('67개에서는 58개가 모두 일치하고 9개는 완전 일치가 아니다', text)
        self.assertIn('자동 채점 미해결은 2개', text)

    def test_no_ordering_does_not_imply_equivalence(self):
        self.data['legacy-scoring-v55/family-analysis.json']['within_benchmark_ordering'] = 'not_established'
        self.assertIn('동등함을 입증한 결과가 아니다', self.render())

    def test_all_ambiguous_has_no_zero_division_or_hidden_denominator(self):
        self.data['legacy-answer-audit/agreement-summary.json'] = audit(
            ambiguous=70, nonambiguous=0, nonambiguous_both_judges_match=0)
        text = self.render()
        self.assertIn('70/70개', text)
        self.assertIn('0개에서는 0개', text)
        self.assertIn('조건부 결과', text)

    def test_inconsistent_audit_counts_rejected(self):
        variants = [audit(answers=69), audit(ambiguous=1),
                    audit(nonambiguous_both_judges_match=71),
                    audit(all_both_judges_match=69),
                    audit(automated_unresolved_in_sample=1)]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                report.broad_audit_text(value)

    def test_noninteger_audit_counts_rejected(self):
        for value in ('70', 70.0, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                report.broad_audit_text(audit(answers=value))

    def test_string_gate_cannot_qualify_report(self):
        self.data['legacy-bridge-validation-v55/summary.json']['gate_passed'] = 'false'
        with self.assertRaises(ValueError): self.render()
        self.assertFalse((self.root/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md').exists())

    def test_incomplete_campaign_cannot_qualify_report(self):
        self.data['legacy-comparison-1/manifest.json']['status'] = 'running'
        with self.assertRaises(ValueError): self.render()
        self.assertFalse((self.root/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md').exists())


if __name__ == '__main__':
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReportingReviewTest))
    print('Synthetic reporting tests:', result.testsRun,
          'failures:', len(result.failures), 'errors:', len(result.errors))
    if not result.wasSuccessful(): print(stream.getvalue())
    sys.exit(not result.wasSuccessful())
