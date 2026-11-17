"""Descriptive report only: never turns repeated views into independent incidents."""
import json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def main():
    base=ROOT/'eval/v5';summary=read(base/'scoring-1/summary.json');rows=summary['answers']
    provenance=read(base/'provenance.json');manifest=read(base/'comparison-2/manifest.json')
    cost=summary['cost'];amount=cost.get('total_campaigns_estimated_usd')
    lines=['# 홈서버 관제 평가 v5 — 범위를 한정한 검증 결과','',
      '공개 장애에서 가져온 두 원리를 격리 환경에서 재현하고, 정상·실패·복구·정보 부족의 8개 관측 조건으로 비교했다. 실제 pi와 우리 간소화 하네스가 같은 모델·도구·질문으로 각각 3회 실행했다. **전체 홈서버 정확도나 일반적인 최종 순위를 뜻하지 않는다.**','',
      '주 점수는 요청한 작업 상태와 직접 원인을 모두 근거에 맞게 답하고, 근거 없는 단정이 없다는 판정을 Haiku가 두 번 일치시킨 실행 비율이다. 불일치·잘못된 형식·실행 오류는 통과로 처리하지 않았다. 답변 미수집 건을 분모에서 빼지 않는다.','',
      '| 하네스 | 안정 통과 / 실행 수 | 비율 | 채점 1회 / 2회 통과 | 미해결 | 실행 오류 | 실행시간 중앙값 |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for arm,a in summary['arms'].items():
        rs=[r for r in rows if r['arm']==arm];rates=a['per_judge_repeat']
        lines.append(f"| {arm} | {a['stable_pass']}/{a['n']} | {a['stable_pass_percent']:.1f}% | {rates['0']['pass']}/{a['n']} · {rates['1']['pass']}/{a['n']} | {a['unresolved']} | {a['runner_errors']} | {statistics.median(r['elapsed_ms'] for r in rs)/1000:.1f}초 |")
    lines+=['','각 하네스의 24회 실행은 **8개 조건 × 3회 반복**이다. 서로 독립적인 실제 장애 24건이 아니다.','',
            '| 능력 구분 | compact_plus 안정 통과 | pi_plus 안정 통과 |','|---|---:|---:|']
    for label,phases in [('직접 원인이 보이는 실패',{'fault'}),('실패했지만 원인이 가려진 상황',{'partial'}),('관측된 정상/복구 작업',{'normal','recovered'})]:
        cells=[]
        for arm in ['compact_plus','pi_plus']:
            rs=[r for r in rows if r['arm']==arm and provenance[r['case']]['phase'] in phases]
            cells.append(f"{sum(r['stable_pass'] for r in rs)}/{len(rs)}")
        lines.append(f'| {label} | {cells[0]} | {cells[1]} |')
    lines+=['','정상/복구 조건이 절반이므로 전체 비율만으로 원인 진단 능력을 판단하지 않는다. 위 세 구분을 함께 본다.','',
            '| 관측 조건 | 원리 / 단계 | compact_plus 통과 / 3 | pi_plus 통과 / 3 |','|---|---|---:|---:|']
    for case,p in provenance.items():
        nums=[sum(r['stable_pass'] for r in rows if r['case']==case and r['arm']==arm) for arm in ['compact_plus','pi_plus']]
        lines.append(f"| {case} | {p['family']} / {p['phase']} | {nums[0]}/3 | {nums[1]}/3 |")
    pairs={'compact_only':0,'pi_only':0,'both_pass':0,'both_nonpass':0}
    for case in provenance:
        for rep in range(3):
            pair={r['arm']:r['stable_pass'] for r in rows if r['case']==case and r['rep']==rep}
            key='both_pass' if all(pair.values()) else 'both_nonpass' if not any(pair.values()) else 'compact_only' if pair['compact_plus'] else 'pi_only'
            pairs[key]+=1
    lines+=['',f"동일 조건·동일 반복의 24쌍: 둘 다 통과 {pairs['both_pass']}, compact만 통과 {pairs['compact_only']}, pi만 통과 {pairs['pi_only']}, 둘 다 미통과 {pairs['both_nonpass']}. 미해결 판정은 여기에서도 통과로 세지 않았다.",'',
      '## 신뢰 근거와 한계','',
      '- 공개 출처: [GitLab 사후보고서](https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/)의 구버전 pg_dump 문제, [PostgreSQL 컨테이너 이슈 #722](https://github.com/docker-library/postgres/issues/722)의 초기 SQL 접근 거부. 원본 사건 전체가 아니라 장애 원리를 다른 버전의 격리 환경에 적용했다.',
      '- 정상·장애·복구의 실제 실행 출력과 종료 코드를 보존했다. 덤프는 복원 후 표본 행 수 3과 합계 60을 확인했다. 초기 SQL 복구는 새 데이터 디렉터리에서 재시도했으며, 기존 장애 데이터를 수리한 결과가 아니다.',
      '- 독립 AI 검수자가 채점기 작성 전에 고정한 20개 문제를 3회씩 판정했다. 통과/근거 없는 주장 판정은 60/60 일치했다. 부가 설명용 답변 상태 분류는 57/60이며 점수 일치 판정에서 제외했다. 60개의 독립 문제나 사람 검수로 표현하지 않는다.',
      '- 수치·단위는 Decimal 코드로 분리했다. 최초 파서의 복합 단위/부호 결함과 수정본을 함께 보존했다. 이번 주 비교는 상태·원인만 평가하므로, 이것이 이전 76.7점의 수치 채점을 소급 인증하지는 않는다.',
      '- 모든 8개 조건에서 실제 도구로 정답 근거가 도달함을 검사했다. 조회 로그의 최신 30줄 선택, 300자 제한, 시간 범위를 실제 동작에 맞췄다. 채점기는 원본 백엔드 전체 데이터가 아닌 에이전트에게 실제 전달된 도구 응답만 사용한다.',
      '- 모델·질문·도구·출력 한도·조사 제한을 맞추고 순서를 교차했다. 시간/도구 한도에 도달하면 두 하네스 모두 같은 부분 결과 정책을 적용한다. Pi CLI 시작 시간은 제한에 포함되며, 총 추론 토큰 수가 같다고 주장하지 않는다.',
      '- 두 PostgreSQL 원리로 네트워크·디스크·OOM·인증서·GPU·홈서버 전체의 순위를 추론할 수 없다. 반복과 같은 원리의 변형을 독립 표본처럼 계산한 신뢰구간은 만들지 않았다.',
      '- 재생 환경의 백업 종료/버전/복원 기록이 운영 서버에 이미 수집된다는 뜻은 아니다. 현재 도구와 추가 수집 필요사항은 [도구 범위 감사](EVAL-V5-TOOL-COVERAGE.md)에 구분했다.','',
      '## 검증과 보존','',
      '- Python 최종 회귀 검사: 111개 실행, 5개 예정된 건너뛰기, 나머지 통과. Java 오프라인 계약 검사 18개, 실제 도구 재생 8개와 기존 숫자 통합 검사 1개 통과.',
      '- 실패했던 사전 검사도 보존했다. 로그 전용 세계 거부, 로그 순서/제한, 관측 기록 불일치, 종료 정책 차이, 파서와 중복 채점/비용 회계 문제를 비교 실행 전에 보완했다.',
      '- 이전 점수 원본 354개 파일의 해시 일치 확인. 새 결과는 별도 디렉터리에 저장했다. 운영 배포·운영 장애 주입·커밋/푸시는 하지 않았다.',
      f"- 누적 API 비용 추정: ${amount:.7f} / $2 한도." if amount is not None else '- 비용 회계 확인 필요: '+json.dumps(cost),
      '- 비용은 API 응답의 토큰 사용량과 요율로 계산한 추정이며 실제 청구서가 아니다. 모든 유료 요청의 원본과 상태를 중앙 등록부에서 관리했다.','',
      '## 검토 파일','',
      '- [사전 검사 근거](EVAL-V5-PREFLIGHT.md)',
      '- [출처/정답 독립 검토](EVAL-V5-INDEPENDENT-PROVENANCE-REVIEW.md)',
      '- [채점/비용 검토](EVAL-V5-SCORING-REVIEW.md)',
      '- [사전 고정한 비교 규약](EVAL-V5-PROTOCOL.md)',
      '- 최초 비교는 실행 순서가 모두 pi 먼저인 것을 답변 검토/채점 전에 발견하여 14개 답변을 보존하고 중단했다. 원본은 `eval/v5/comparison-1/`에 남겨 두었고 점수에서 제외했다. 사전 지정한 균형 순서로 새 비교를 시작했다.',
      '- 결과 원본: `eval/v5/comparison-2/`, 채점 원본: `eval/v5/scoring-1/`.',
      '- 본 보고서의 자동 표와 별개로 독립 AI의 답변 재검토 결과를 함께 확인해야 한다.','']
    path=ROOT/'docs/EVAL-V5-RESULTS-2026-11-17.md';path.write_text('\n'.join(lines))
    print(path)
if __name__=='__main__':main()
