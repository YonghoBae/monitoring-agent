"""Synthetic report checks; no actual evaluation answers or reviews are read."""
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


def cross_audit():
    clear = {'answers': 66, 'field_denominator': 152, 'common_endpoint_answers': 60,
        'common_endpoint_field_denominator': 140, 'reviewers_disagree': 6,
        'matches_common_endpoints': 50, 'differs_from_common_endpoints': 6,
        'invalid_for_common_endpoints': 4, 'all_invalid_automatic': 5}
    ambiguous = {'answers': 4, 'field_denominator': 10, 'common_endpoint_answers': 3,
        'common_endpoint_field_denominator': 8, 'reviewers_disagree': 1,
        'matches_common_endpoints': 2, 'differs_from_common_endpoints': 0,
        'invalid_for_common_endpoints': 1, 'all_invalid_automatic': 1}
    return {'answers': 70, 'field_denominator': 162, 'family_count': 28, 'any_reviewer_ambiguous': 4,
        'reviewer_agreement': {'raw_semantic_fields': {'agreement': 151, 'denominator': 162},
                              'combined_fields': {'agreement': 156, 'denominator': 162},
                              'strict_pass': {'agreement': 67, 'denominator': 70}},
        'automatic_comparison': {'all_answers': {key: clear[key] + ambiguous[key] for key in clear},
                                 'nonambiguous_answers': clear, 'ambiguous_answers': ambiguous},
        'arms': {'pi_plus': {'answers': 35, 'field_denominator': 81, 'metrics': {
                    'automatic_rep0': {'family_macro_percent': 60.2, 'strict_pass': 10},
                    'both_reviewers_true': {'family_macro_percent': 70.125, 'strict_pass': 12},
                    'either_reviewer_true': {'family_macro_percent': 80.875, 'strict_pass': 18}}},
                 'compact_plus': {'answers': 35, 'field_denominator': 81, 'metrics': {
                    'automatic_rep0': {'family_macro_percent': 55.75, 'strict_pass': 9},
                    'both_reviewers_true': {'family_macro_percent': 74.4, 'strict_pass': 14},
                    'either_reviewer_true': {'family_macro_percent': 88.8, 'strict_pass': 21}}}}}


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


    def add_cross_summary(self, required=True):
        relative = 'legacy-answer-audit/cross-agreement-summary.json'
        self.data[relative] = cross_audit()
        path = self.base/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        if required:
            lock = 'legacy-answer-audit/primary-review-lock.json'
            self.data[lock] = {'supplemental_cross_review': {'phase': 'synthetic supplemental review'}}
            (self.base/lock).touch()

    def test_declared_supplemental_audit_requires_summary(self):
        self.add_cross_summary()
        (self.base/'legacy-answer-audit/cross-agreement-summary.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Declared supplemental cross-review'):
            self.render()
        self.assertFalse((self.root/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md').exists())

    def test_supplemental_numbers_ranges_and_scope_are_separate(self):
        self.add_cross_summary()
        text = self.render()
        section = text.split('### 같은 70개 답변의 사후 보조 교차검수')[1].split('## 4.')[0]
        self.assertIn('의미 항목 일치는 151/162개', section)
        self.assertIn('최종 항목 일치는 156/162개', section)
        self.assertIn('통과 판정 일치는 67/70개', section)
        self.assertIn('모호하다고 표시한 답변은 4/70개', section)
        self.assertIn('모호하지 않은 66개', section)
        self.assertIn('표본은 60개(요청 항목 140개)', section)
        self.assertIn('일치 50/60개, 불일치 6/60개, 누락·무효 4/60개', section)
        self.assertIn('| 실제 Pi | 60.2% | 70.1–80.9% | 10/35 | 12–18/35 |', section)
        self.assertIn('원래 3회 반복의 자동 점수나 사전 우열 판정 조건을 대체·수정하지 않는다', section)
        self.assertIn('진실의 한계나 신뢰구간이 아니다', section)
        self.assertIn('사전등록된 분석은 아니다', section)
        self.assertIn('핵심 48개 시험이나 전체 3회 반복 점수와 합산하지 않는다', section)
        self.assertIn('사전계획 1차검수는 답변당 독립 AI 한 명', text)
        self.assertIn('(EVAL-V5-OBSERVED-TOOL-LIMITS-2026-11-17.md)', text)

    def test_present_optional_cross_summary_is_rendered(self):
        self.add_cross_summary(required=False)
        self.assertIn('### 같은 70개 답변의 사후 보조 교차검수', self.render())

    def test_malformed_cross_summary_cannot_produce_final_report(self):
        self.add_cross_summary()
        mutations = [lambda value: value.pop('reviewer_agreement'),
                     lambda value: value.update(answers='70'),
                     lambda value: value['reviewer_agreement']['combined_fields'].update(denominator=161),
                     lambda value: value['automatic_comparison']['nonambiguous_answers'].update(matches_common_endpoints=51),
                     lambda value: value['arms']['pi_plus']['metrics']['automatic_rep0'].update(family_macro_percent=float('nan')),
                     lambda value: value['arms']['pi_plus']['metrics']['both_reviewers_true'].update(strict_pass=19)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = cross_audit()
                mutate(value)
                self.data['legacy-answer-audit/cross-agreement-summary.json'] = value
                with self.assertRaises(ValueError): self.render()
                self.assertFalse((self.root/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md').exists())

    def test_zero_clear_consensus_does_not_print_zero_over_zero(self):
        self.add_cross_summary()
        value = self.data['legacy-answer-audit/cross-agreement-summary.json']
        for group in value['automatic_comparison'].values():
            group.update(common_endpoint_answers=0, common_endpoint_field_denominator=0,
                         reviewers_disagree=group['answers'], matches_common_endpoints=0,
                         differs_from_common_endpoints=0, invalid_for_common_endpoints=0)
        value['reviewer_agreement']['combined_fields']['agreement'] = 0
        value['reviewer_agreement']['raw_semantic_fields']['agreement'] = 0
        value['reviewer_agreement']['strict_pass']['agreement'] = 0
        text = self.render()
        self.assertIn('공통 판정 표본이 없어 자동 일치율을 계산하지 않는다', text)
        self.assertNotIn('0/0', text)


if __name__ == '__main__':
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReportingReviewTest))
    print('Synthetic reporting tests:', result.testsRun,
          'failures:', len(result.failures), 'errors:', len(result.errors))
    if not result.wasSuccessful(): print(stream.getvalue())
    sys.exit(not result.wasSuccessful())
