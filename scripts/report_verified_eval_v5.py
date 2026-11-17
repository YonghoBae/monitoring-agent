"""Generate final scoped report only after both complete reviewed campaigns exist."""
import json
import math
from pathlib import Path

import budget_registry as budget

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'eval/v5'
ARMS = ('pi_plus', 'compact_plus')
NAMES = {'pi_plus': '실제 Pi', 'compact_plus': '우리 간소화 하네스'}


def read(path):
    return json.loads(path.read_text())


def broad_audit_text(audit):
    """Describe audit endpoints without treating the reviewer as ground truth."""
    keys = ('answers', 'ambiguous', 'nonambiguous', 'nonambiguous_both_judges_match',
            'all_both_judges_match', 'automated_unresolved_in_sample')
    if any(type(audit[key]) is not int or not 0 <= audit[key] <= 70 for key in keys):
        raise ValueError('Independent audit counts must be integers within the fixed70 sample')
    n, ambiguous, clear, clear_match, all_match, unresolved = (audit[key] for key in keys)
    if (n != 70 or ambiguous + clear != n or clear_match > clear
            or not clear_match <= all_match <= clear_match + ambiguous or unresolved > n - all_match):
        raise ValueError('Independent audit denominators or agreement counts contradict each other')
    unmatched = n - all_match
    clear_unmatched = clear - clear_match
    headline = (f'사전계획 1차 독립 AI 검수와 자동 채점 두 번의 최종 판정이 모두 일치한 표본은 {all_match}/{n}개다. '
                f'완전 일치가 아닌 표본은 {unmatched}개, 모호한 표본은 {ambiguous}개다. ')
    if unmatched or ambiguous:
        headline += '이 검수 한계를 고려해 위 우열 판정은 자동 채점에 따른 조건부 결과로 해석한다.'
    else:
        headline += '이 표본 일치는 사람 정답 검증이나 전체 답변의 채점 정확도 인증이 아니다.'
    detail = (f'넓은 시험은 사전에 정한 {n}개 답변(모든 35문항·양쪽 하네스·첫 반복)을 별도로 검수했다. '
              f'전체 표본에서 독립 판정과 자동 채점 두 번의 항목·엄격 통과 판정이 모두 일치한 것은 {all_match}/{n}개다. '
              f'모호한 {ambiguous}개를 제외한 {clear}개에서는 {clear_match}개가 모두 일치하고 {clear_unmatched}개는 완전 일치가 아니다. '
              f'표본 내 자동 채점 미해결은 {unresolved}개다. 완전 일치가 아닌 수에는 자동 채점 누락·무효도 포함될 수 있어 이를 곧바로 채점 오류 수로 해석하지 않는다. '
              '사전계획 1차검수는 답변당 독립 AI 한 명이 의미 판정했으며, 수치·형식 검사는 자동 채점과 같은 고정 코드를 사용했다. '
              '이 1차검수만으로는 같은 답변을 여러 독립 검수자가 중복 판정한 설계가 아니므로 검수자 간 일치율을 추정하지 않는다. '
              '자동 점수를 검수 결과로 덮어쓰거나 모호·불일치 답변을 전체 분모에서 제외하지 않았다.')
    return headline, detail


def cross_audit_section(audit):
    """Render only the supplemental repetition0 comparison, with explicit limits."""
    def count(value, maximum, label):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError('Malformed cross-review count: ' + label)
        return value

    try:
        if (count(audit['answers'], 70, 'answers') != 70
                or count(audit['field_denominator'], 162, 'fields') != 162
                or count(audit['family_count'], 28, 'families') != 28):
            raise ValueError('Cross-review requires the fixed70-answer/162-field/28-family sample')
        ambiguous = count(audit['any_reviewer_ambiguous'], 70, 'ambiguity')
        agreement = audit['reviewer_agreement']
        for key, denominator in (('raw_semantic_fields', 162), ('combined_fields', 162), ('strict_pass', 70)):
            item = agreement[key]
            if count(item['denominator'], denominator, key) != denominator:
                raise ValueError('Cross-review agreement denominator changed')
            count(item['agreement'], denominator, key)
        if agreement['combined_fields']['agreement'] < agreement['raw_semantic_fields']['agreement']:
            raise ValueError('Shared deterministic composition cannot create new field disagreements')
        comparisons = audit['automatic_comparison']
        answer_keys = ('answers', 'common_endpoint_answers', 'reviewers_disagree', 'matches_common_endpoints',
                       'differs_from_common_endpoints', 'invalid_for_common_endpoints', 'all_invalid_automatic')
        field_keys = ('field_denominator', 'common_endpoint_field_denominator')
        for name, expected in (('all_answers', 70), ('nonambiguous_answers', 70 - ambiguous), ('ambiguous_answers', ambiguous)):
            group = comparisons[name]
            for key in answer_keys: count(group[key], expected, name + '.' + key)
            for key in field_keys: count(group[key], 162, name + '.' + key)
            common = group['common_endpoint_answers']
            invalid = group['invalid_for_common_endpoints']
            if (group['answers'] != expected or common + group['reviewers_disagree'] != expected
                    or sum(group[key] for key in ('matches_common_endpoints', 'differs_from_common_endpoints', 'invalid_for_common_endpoints')) != common
                    or not invalid <= group['all_invalid_automatic'] <= invalid + group['reviewers_disagree']
                    or not common <= group['common_endpoint_field_denominator'] <= group['field_denominator']
                    or group['field_denominator'] < expected
                    or (expected == 0 and group['field_denominator'] != 0)
                    or (common == 0 and group['common_endpoint_field_denominator'] != 0)):
                raise ValueError('Cross-review automatic comparison counts contradict each other')
        if (comparisons['all_answers']['field_denominator'] != 162 or
                any(comparisons['all_answers'][key] != comparisons['nonambiguous_answers'][key] + comparisons['ambiguous_answers'][key]
                    for key in answer_keys + field_keys)):
            raise ValueError('Cross-review clear/ambiguous partitions do not preserve full denominators')
        if set(audit['arms']) != set(ARMS):
            raise ValueError('Cross-review must retain both arms')
        for arm in ARMS:
            item = audit['arms'][arm]
            if count(item['answers'], 35, arm) != 35 or count(item['field_denominator'], 81, arm) != 81:
                raise ValueError('Cross-review arm denominator changed')
            for variant in ('automatic_rep0', 'both_reviewers_true', 'either_reviewer_true'):
                metric = item['metrics'][variant]
                value = metric['family_macro_percent']
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError('Invalid cross-review family-macro percentage')
                count(metric['strict_pass'], 35, arm + '.' + variant)
            low, high = (item['metrics'][key] for key in ('both_reviewers_true', 'either_reviewer_true'))
            if any(low[key] > high[key] for key in ('family_macro_percent', 'strict_pass')):
                raise ValueError('Cross-review range is reversed')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed supplemental cross-review summary') from error
    clear = comparisons['nonambiguous_answers']
    common = clear['common_endpoint_answers']
    automatic = (f"일치 {clear['matches_common_endpoints']}/{common}개, 불일치 {clear['differs_from_common_endpoints']}/{common}개, "
                 f"누락·무효 {clear['invalid_for_common_endpoints']}/{common}개") if common else '공통 판정 표본이 없어 자동 일치율을 계산하지 않는다'
    lines = ['### 같은 70개 답변의 사후 보조 교차검수', '',
        '자동 채점의 무효 출력이 관찰된 뒤, 사전선택된 동일한 70개 답변(모든 35문항·양쪽 하네스·첫 반복)에 검수자 한 명씩을 추가했다. 답변당 두 AI의 판정을 비교한 사후 보조 분석이며 사전등록된 분석은 아니다. 핵심 48개 시험이나 전체 3회 반복 점수와 합산하지 않는다.', '',
        f"수치·형식 합성 전 의미 항목 일치는 {agreement['raw_semantic_fields']['agreement']}/162개, 같은 고정 코드로 합성한 최종 항목 일치는 {agreement['combined_fields']['agreement']}/162개, 엄격한 질문 전체 통과 판정 일치는 {agreement['strict_pass']['agreement']}/70개다. 한 명이라도 모호하다고 표시한 답변은 {ambiguous}/70개다.", '',
        f"모호하지 않은 {clear['answers']}개 중 두 검수자의 모든 최종 항목과 엄격 통과 판정이 같은 표본은 {common}개(요청 항목 {clear['common_endpoint_field_denominator']}개)다. 이 공통 판정 표본과 자동 채점 두 번의 비교는 {automatic}. 자동 채점 둘 중 하나라도 다르면 불일치로, 유효한 두 판정이 없으면 누락·무효로 구분한다. 공통 판정도 사람 정답의 인증은 아니다.", '',
        '| 하네스 | 같은 첫 반복 자동 계열 점수 | 두 검수자 판정 범위: 계열 점수 | 같은 첫 반복 자동 엄격 통과 | 두 검수자 엄격 통과 범위 |',
        '|---|---:|---:|---:|---:|']
    for arm in ARMS:
        metrics = audit['arms'][arm]['metrics']
        auto, low, high = (metrics[key] for key in ('automatic_rep0', 'both_reviewers_true', 'either_reviewer_true'))
        lines.append(f"| {NAMES[arm]} | {auto['family_macro_percent']:.1f}% | {low['family_macro_percent']:.1f}–{high['family_macro_percent']:.1f}% | {auto['strict_pass']}/35 | {low['strict_pass']}–{high['strict_pass']}/35 |")
    lines += ['', '각 하네스의 분모는 같은 첫 반복 35개 답변·81개 요청 항목이며, 28개 계열에 같은 가중치를 준다. 범위의 하한은 두 검수자 모두 인정한 판정, 상한은 한 명 이상이 인정한 판정이다. 서로 다른 검수자의 항목을 합쳐 질문 전체 통과를 만들지 않는다. 이 범위는 검수자 차이이며 진실의 한계나 신뢰구간이 아니다. 모호한 답변도 전체 분모에 남긴다.', '',
              '이 보조 비교는 같은 고정 70개 표본에만 해당한다. 독립 AI들의 공통 오류 가능성이 남으며, 원래 3회 반복의 자동 점수나 사전 우열 판정 조건을 대체·수정하지 않는다. 모호함과 검수 불일치는 기존 결론의 해석 한계로 함께 남긴다.', '']
    return lines


def main():
    core = read(BASE/'canonical-core/scoring-1/summary.json')
    broad = read(BASE/'legacy-scoring-v55/summary.json')
    analysis = read(BASE/'legacy-scoring-v55/family-analysis.json')
    workflow = read(BASE/'legacy-comparison-1/workflow-diagnostics.json')
    core_audit = read(BASE/'canonical-core/independent-review/agreement-summary.json')
    broad_audit = read(BASE/'legacy-answer-audit/agreement-summary.json')
    bridge = read(BASE/'legacy-bridge-validation-v55/summary.json')
    semantic = read(BASE/'semantic-validation-v52/summary.json')
    for relative, count in [('canonical-core/comparison-1', 48), ('legacy-comparison-1', 210)]:
        manifest = read(BASE/relative/'manifest.json')
        if manifest.get('status') != 'completed' or manifest.get('answers') != count:
            raise ValueError('Both model campaigns must finish before a final report')
    if len(core['answers']) != 48 or core['judgments'] != 96 or len(broad['answers']) != 210 or broad['judgments'] != 420:
        raise ValueError('Incomplete scoring ledger')
    if bridge['gate_passed'] is not True or semantic['gate_passed'] is not True:
        raise ValueError('Required independent judge gate failed')
    if core_audit.get('answers') != 48 or broad_audit.get('answers') != 70:
        raise ValueError('Prospective independent answer audits must be complete')
    audit_headline, audit_detail = broad_audit_text(broad_audit)
    lock_path = BASE/'legacy-answer-audit/primary-review-lock.json'
    cross_path = BASE/'legacy-answer-audit/cross-agreement-summary.json'
    cross_required = lock_path.exists() and 'supplemental_cross_review' in read(lock_path)
    if cross_required and not cross_path.exists():
        raise ValueError('Declared supplemental cross-review must finish before a final report')
    cross_section = cross_audit_section(read(cross_path)) if cross_path.exists() else []
    cost = budget.preflight(ROOT, BASE/'canonical-core/scoring-1')
    verdict = {'compact_plus_ahead': '자동 채점 결과는 이 고정 회귀 시험의 사전 우열 판정 조건을 우리 간소화 하네스 쪽으로 충족했다.',
               'pi_plus_ahead': '자동 채점 결과는 이 고정 회귀 시험의 사전 우열 판정 조건을 실제 Pi 쪽으로 충족했다.',
               'not_established': '자동 채점 결과로는 이 고정 회귀 시험의 사전 우열 판정 조건을 충족하지 못했다. 이는 동등함을 입증한 결과가 아니다.'}[analysis['within_benchmark_ordering']]
    lines = ['# 홈서버 관제 평가 — 검증된 범위와 결과', '',
        verdict + ' 아래 점수는 명시된 시험에 대한 결과이며, 전체 홈서버 정확도나 일반적인 하네스 순위가 아니다.', '',
        audit_headline, '',
        '## 1. 실제로 재현한 장애 원리: 확인용 핵심 시험', '',
        '공개 사례에서 가져온 PostgreSQL 클라이언트/서버 버전 불일치와 초기 SQL 접근 거부를 격리 컨테이너에서 실행했다. 정상·실패·복구·정보 부족의 8개 관측 조건을 만들고 두 하네스를 각각 3회 실행했다. 같은 사건 전체를 재생한 데이터도, 독립적인 실제 장애 24건도 아니다.', '',
        '| 하네스 | 요청 항목 점수 | 질문 전체 안정 통과 | 채점 미해결 | 실행 오류 |',
        '|---|---:|---:|---:|---:|']
    for arm in ARMS:
        a = core['arms'][arm]
        lines.append(f"| {NAMES[arm]} | {a['stable_satisfied_findings']}/{a['requested_findings']} ({a['stable_field_accuracy_micro_percent']:.1f}%) | {a['stable_pass']}/{a['n']} ({a['stable_pass_percent']:.1f}%) | {a['unresolved']} | {a['runner_errors']} |")
    lines += ['', '상태, 후속 확인 결과, 직접 원인을 모두 질문에 명시했다. 후속 복원/조회 결과가 관측되지 않았으면 모른다고 답해야 한다. 일반적인 컨테이너 종료 코드만으로 특정 초기화 단계가 실패했다고 단정하지 않는다. 두 번의 채점이 모두 각 항목을 지지해야 항목 점수를 주며, 질문 전체 통과에는 근거 없는 주장도 없어야 한다.', '',
        '## 2. 넓은 상황 범위: 통제된 35문항 회귀 시험', '',
        '35개 문항·28개 상황 계열·81개 요청 항목을 양쪽에서 각각 3회 실행했다. 출처는 매뉴얼 기반 통제 시나리오 30개, 공개 사례의 장애 유형을 적용한 시나리오 2개, 비식별 운영 스냅샷 3개다. 35개 실제 장애의 해결 기록이라는 뜻이 아니다. 기존 62개 항목 외에 질문이 이미 요청했던 설명·불확실성 19개도 명시적으로 평가한다.', '',
        '| 하네스 | 주 점수: 계열별 동일 가중치 | 전체 항목 점수 | 원래 62항목 점수 | 엄격한 구조 포함 통과 | 채점 미해결 |',
        '|---|---:|---:|---:|---:|---:|']
    for arm in ARMS:
        a = broad['arms'][arm]
        lines.append(f"| {NAMES[arm]} | {analysis['primary_family_macro_percent'][arm]:.1f}% | {a['stable_all_field_micro_percent']:.1f}% | {a['stable_base_field_micro_percent']:.1f}% | {a['stable_structured_pass']}/{a['n']} | {a['unresolved']} |")
    lo, hi = analysis['paired_family_bootstrap_sensitivity_interval']
    lines += ['', f"주 점수 차이(우리 − Pi)는 {analysis['compact_minus_pi_percentage_points']:+.2f}%p다. 선택된 28개 계열을 함께 재표집한 민감도 구간은 [{lo:+.2f}, {hi:+.2f}]%p다. 이 구간은 선택한 시험 구성에 대한 민감도이며, 전체 홈서버 모집단의 정확도 신뢰구간이 아니다.", '',
        '주 점수는 문항 안에서 3회 반복을 평균하고, 계열 안에서 문항을 평균한 뒤 28개 계열에 같은 가중치를 준다. 210개 답변이나 420개 채점 판정을 독립적인 실제 장애로 취급하지 않는다. 전체 항목·원래 항목 점수는 같은 검증된 항목 판정의 추가 집계이며, 실패·미해결 답변도 각 분모에 남는다.', '',
        '숫자 35개 항목은 단위·차원·허용 오차를 결정적 코드로 확인한 뒤 의미·대상·시간 범위·실제 전달 근거도 별도로 확인한다. 나머지 항목은 의미 기반으로 판정한다. 잘못된 출력 형식과 사실 오류를 구분해 기록하며, 형식이 틀렸다는 이유만으로 의미상 맞는 비수치 설명의 항목 점수를 지우지는 않는다.', '',
        '엄격한 질문 전체 통과에는 요청 형식·스키마의 적합성, 모든 항목 정답, 평가 가능한 상태에서 근거 없는 주장이 없다는 판정, 실행 오류 없음이 모두 필요하다. 항목 점수와 엄격 통과에는 두 유효한 채점 반복의 지지가 필요하다. 별도의 무근거 주장 비율은 검증된 지표가 아니다.', '',
        '반복별 주 점수 차이: ' + ', '.join(f"{int(rep)+1}회 {value:+.2f}%p" for rep, value in analysis['repeat_differences_percentage_points'].items()) + '.',
        '채점 미해결 건을 양쪽에 가장 불리하거나 유리하게 놓은 차이 범위: ' + ', '.join(f'{v:+.2f}%p' for v in analysis['unresolved_sensitivity_difference_bounds']) + '.', '',
        '시험 내 우열 조건은 계열 민감도 구간의 0 제외, 세 반복의 동일한 방향, 채점 미해결 건을 앞선 쪽에 불리하게 놓아도 유지되는 방향을 모두 요구한다. 이 민감도 분석은 자동 채점 간 미해결을 다루며, 두 자동 채점이 공유한 오판이나 독립 검수와의 불일치를 보정한 결과는 아니다. 핵심 시험의 두 장애 계열에는 이 추론을 적용하지 않고 기술 통계만 제시한다.', '',
        '## 3. 신뢰를 위해 실제로 확인한 것', '',
        f"- 독립 AI 검수자가 작성하고 먼저 고정한 의미 채점 통제 문제 20개 × 3회에서 필수 판정 {semantic['judgments']}/{semantic['judgments']} 일치. 부가 상태 분류는 점수에서 제외했다.",
        f"- 별도로 작성한 수치·의미 연결 통제 문제 20개 × 3회에서 최종 판정 {bridge['judgments']}/{bridge['judgments']} 일치. 수치·형식 기대값은 유료 호출 전에 코드로 확인했다. 이 수치는 해당 통제 문제의 일치율이며 모든 답변에 대한 채점기 정확도 추정은 아니다.",
        '- 동일 Qwen 모델·동일 도구·출력/도구/시간 한도로 실제 Pi와 간소화 하네스를 비교했다. 실행 순서는 교차하고, 질문·정답·채점 코드·분석 규칙을 모델 답변 수집 전에 고정했다.',
        '- 채점기에 하네스 이름을 주지 않고, 에이전트에게 실제 전달된 도구 응답만 근거로 제공했다. 백엔드 원본의 숨겨진 정보로 답변을 정당화하지 않는다.',
        '- 모든 문항의 근거 도달성, 수치 허용 오차, 로그 시간 범위·최신 30줄·300자 제한, 정보 없음과 정상의 구분을 사전 검사했다.',
        '- 수치·의미 연결의 이전 전체 검증은 각각 7/60, 8/60, 1/60 미충족으로 남겼다. 마지막 1건은 이미 오답 처리된 답변의 부가 분류 차이였다. 최종 규약은 항목 점수와 완전 통과 여부로 고정하고 새 독립 문제로 검증했다. 부가 분류의 독립적인 환각률·무근거 주장 없는 비율은 인증하거나 순위에 사용하지 않는다. 이전 실패를 통과로 바꾸지 않았다.',
        '- 의미 판단의 두 번 불일치, 잘못된 인용/출력, 실행 오류를 통과로 숨기지 않았다. 실패한 채점기 검증과 중단한 비교도 비용·이력에서 제외하지 않았다.',
        f"- 핵심48개 답변은 서로의 판단을 보지 않은 두 AI가 교차 검수했다. 개별 항목 판정은 {core_audit['independent_finding_label_agreement']}/{core_audit['independent_finding_labels']} 일치했고, 근거 없는 주장 여부까지 포함한 전체 판정은 {core_audit['independent_reviewers_full_label_agreement']}/48개가 일치했다. 한 명이라도 표현 해석에 주석을 단 답변은 {core_audit['ambiguity_union']}개다. 양쪽이 명확하다고 보고 판정도 일치한 {core_audit['consensus_nonambiguous_answers']}개 중 자동 채점 두 번까지 모두 일치한 것은 {core_audit['consensus_nonambiguous_auto_full_agreement']}개다.",
        '- ' + audit_detail,
        '- 독립 검수자는 사람 대신 사용한 AI 서브에이전트다. 사람 검수라고 부르지 않으며, 공통 모델 편향과 출처 선택 편향은 남는다.', '',
        '## 4. 아직 증명하지 못한 것', '',
        '재현 시험은 두 PostgreSQL 장애 원리만 직접 입증한다. 네트워크·스토리지·GPU·OOM·인증서 등의 실제 사건 분포나 전체 원인 진단 정확도까지 대표하지 않는다. 반복 횟수는 장애 종류 수를 늘리지 않는다. 비교 대상은 조사·답변 능력이다. 격리 장애의 복구는 재현 스크립트가 수행했으며 에이전트의 자율 복구 실행 능력을 측정한 것은 아니다.', '',
        '재생 데이터에 제공된 백업 실행/복원 검사 기록이 운영 서버에서도 이미 수집된다는 뜻은 아니다. 현재 도구에는 호스트 커널 사건, 백업·복원 실행 이력, 로그 페이지 조회, 자세한 네트워크·마운트 정보 등의 공백이 있다. [실제 도구 범위와 우선 보완안](EVAL-V5-TOOL-COVERAGE.md)에 구분했다. 운영 관측이 없으면 모델 개선만으로 원인을 확정할 수 없다.', '',
        '과거 76.7은 이전 항목·채점 방식의 잠정 점수다. 이번 점수와 직접 비교해 성능 향상량이라고 계산할 수 없다. 요구 항목이 충분히 공개되지 않았던 탐색 비교도 확인용 최종 표와 분리했다.', '',
        '## 5. 비용과 재검토 경로', '',
        f"누적 Anthropic 채점 API 비용 추정은 ${cost['total_campaigns_estimated_usd']:.7f} / $2 한도다. 실패한 준비·검증 호출도 포함한다. 해당 API의 토큰 사용량과 등록한 요율에 따른 추정이며 청구서 확정액은 아니다.", '',
        '- [사전 분석 규칙](EVAL-V5-LEGACY-ANALYSIS-PLAN.md)',
        '- [최종 지표와 보조 진단의 범위](EVAL-V55-MEASUREMENT-SCOPE.md)',
        '- [평가에서 관찰된 도구 한계](EVAL-V5-OBSERVED-TOOL-LIMITS-2026-11-17.md)',
        '- [관측 가능성에 따른 정답 수정 이력](EVAL-V5-GOLD-OBSERVABILITY-ERRATA.md)',
        '- [핵심 시험 준비 및 검증](EVAL-V5-CANONICAL-CORE-READINESS.md)',
        '- 핵심 결과: `eval/v5/canonical-core/scoring-1/summary.json`',
        '- 넓은 결과: `eval/v5/legacy-scoring-v55/summary.json`, `family-analysis.json`',
        '- 독립 검수 비교: `eval/v5/legacy-answer-audit/agreement-summary.json`',
        '- 유료 호출 등록부: `eval/paid-campaigns.json`',
        '- 공개 원자료: `eval/v5/sources/`, 실제 격리 실행 기록: `eval/v5/capture-20261117/`', '',
        '운영 배포나 운영 서버 장애 주입 없이 평가 환경과 검증 코드를 보완했다.', '']
    diagnostics = ['실제 작업 방식도 전달된 도구 응답으로 비교했다. 다음은 넓은 회귀 시험의 보조 기술 통계이며, 정확도 지표나 사전 우열 판정의 근거가 아니다.', '',
        '| 하네스 | 실행시간 중앙값 | 전달된 도구 응답 수 중앙값 | 가장 흔한 첫 도구 |',
        '|---|---:|---:|---|']
    for arm in ARMS:
        a = workflow['arms'][arm]
        first = max(a['first_tool_counts'], key=a['first_tool_counts'].get)
        diagnostics.append(f"| {NAMES[arm]} | {a['median_elapsed_seconds']:.1f}초 | {a['median_delivered_tool_results']:g} | {first} ({a['first_tool_counts'][first]}/{a['n']}) |")
    diagnostics += ['', '도구 응답 수에는 캐시에서 전달된 결과도 포함된다. 같은 입력을 반복했다고 백엔드가 매번 재실행됐다는 뜻은 아니다. 시간에는 하네스 시작 비용도 포함되며, 두 하네스의 전체 추론 토큰 수가 같다고 주장하지 않는다.', '']
    at = lines.index('## 3. 신뢰를 위해 실제로 확인한 것')
    lines[at:at] = diagnostics
    audited = ['핵심 시험의 독립 교차 검수 점수도 함께 남긴다. 자동 점수를 덮어쓰는 값이 아니라, 같은48개 답변을 별도로 검토한 보조 결과다. 통과 범위는 두 검수자의 해석 차이를 반영한다.', '',
        '| 하네스 | 두 검수자 공통 항목 점수 | 두 검수자의 질문 전체 통과 범위 |',
        '|---|---:|---:|']
    for arm in ARMS:
        a = core_audit['audited_arms'][arm]
        audited.append(f"| {NAMES[arm]} | {a['both_reviewers_correct_fields']}/{a['field_denominator']} ({a['field_percent']:.1f}%) | {a['strict_pass_lower']}–{a['strict_pass_upper']}/{a['n']} |")
    audited += ['', '자동 채점과 독립 검수는 일부 후속 조회의 의미 구분과 부가 설명 해석에서 달랐다. 따라서 자동 점수를 사실 정확도의 절대값으로 취급하지 않는다.', '']
    at = lines.index('## 2. 넓은 상황 범위: 통제된 35문항 회귀 시험')
    lines[at:at] = audited
    if cross_section:
        at = lines.index('## 4. 아직 증명하지 못한 것')
        lines[at:at] = cross_section
    judge_diagnostics_path = BASE/'legacy-scoring-v55/judge-output-diagnostics.json'
    if judge_diagnostics_path.exists():
        d = read(judge_diagnostics_path)
        if d['judgments'] != broad['judgments']:
            raise ValueError('Judge diagnostics differ from completed scoring')
        lines[4:4] = [
            f"자동 채점 {d['judgments']}회 중 {d['invalid_judgments']}회가 무효였고, "
            f"{d['answers_with_invalid_judgment']}개 답변에 영향을 주었다. "
            f"판정 불일치까지 포함한 미해결 답변은 {d['answers_with_scored_disagreement_or_invalid']}/210개다. "
            '두 번의 유효한 지지가 있어야 항목 점수를 주므로, 아래 점수를 오류 없는 확정 정확도로 해석하지 않는다.', '',
            '[순위 미확정 근거와 실제 채점 불일치 해석](EVAL-V5-RELIABILITY-CONCLUSION-2026-11-17.md)', '']
    destination = ROOT/'docs/EVAL-V5-VERIFIED-RESULTS-2026-11-17.md'
    destination.write_text('\n'.join(lines))
    print(destination)


if __name__ == '__main__':
    main()
