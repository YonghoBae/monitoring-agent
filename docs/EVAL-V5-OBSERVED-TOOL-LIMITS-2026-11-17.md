# 실제 답변 검수에서 확인한 도구와 기준의 한계

210개 응답을 모두 수집하고 독립 검수 원본을 봉인한 뒤 확인한 진단이다. 질문·정답·도구·채점 코드는 변경하지 않았다. 아래 내용은 후속 개선의 근거이며, 개선된 버전의 성능을 측정했다는 뜻이 아니다.

## 로그를 찾을 수 있었지만 선택한 조회 경로에서 빠진 경우

독립 표본 `sample-1971104c30a04016a8940bc18e32021a`는 Alertmanager reload 실패 지표와 일반적인 `Loading configuration file failed` 로그만 받았다. 따라서 YAML 오류를 확인하지 못했다고 답했다. 이 미확인 진술 자체는 근거 없는 원인 단정보다 타당하지만, 질문이 요청한 직접 원인을 밝혀낸 답변은 아니다.

원인은 단순히 데이터셋에 정답 로그가 없어서가 아니다. `AgentTools.query_loki`는 컨테이너를 라벨로 선택하지 않고 `{job="docker"} |= 컨테이너이름`으로 로그 **본문**을 검색한다. 일반 오류 줄에는 설정 파일 경로에 `alertmanager`가 들어가지만, 다음 `err="yaml: line 42: ..."` 줄에는 그 이름이 없다. 실제 전달 기록에서도 두 번째 줄이 빠졌다.

수집 전 공통 도구 검증에서는 같은 시나리오의 `read_container_logs`가 두 줄 모두 전달했다. 두 하네스 모두 이 대체 도구를 사용할 수 있었다. 따라서 이 사례는 조회 도구의 선택과 필터 의미를 구분하는 능력, 그리고 도구 설명의 부족을 함께 드러낸다. 교차 검수자가 표시한 “reference와 전달 로그의 불일치”는 보존하되, 정답 근거가 어느 도구로도 접근 불가능했다는 뜻으로 확대하지 않는다.

- 코드: `src/main/java/io/ohgnoy/monitoring/application/agent/tools/AgentTools.java:146–166`
- 실제 전달 기록: `eval/v5/legacy-answer-audit/batch-1.json`의 위 표본
- 사전 접근성 증거: `eval/v5/legacy-migration/replay-tool-evidence-20261117/alertmanager_reload_failed.json`
- 후속 개선: 로그 조회의 선택 라벨과 본문 필터를 명시적으로 구분하고, 원문 조회·주변 문맥·잘림 여부를 제공한다. 실제 수집 라벨을 확인한 뒤 구현해야 한다.

## 작은 상대 변화가 “유지”로 요약되는 경우

표본 `sample-c623584f60154288a0867b63595e4113`에서 MySQL slow-query counter의 5분 관측은 최솟값 `10034.833333333334`, 최댓값·현재값 `10038`과 함께 `→유지`를 전달했다. 답변도 이를 “유지”라고 설명해, 요구한 증가 상황을 설명하지 못했다.

`PrometheusQueryService.detectTrend`는 구간 앞·뒤 4분의 1 평균의 **상대 변화가 10%를 넘을 때만** 상승으로 표시한다. 누적 counter의 큰 기준값에 비해 작은 새 증가, 또는 짧은 구간의 메모리 증가를 “변화 없음”처럼 읽게 할 수 있다. 표본의 요약은 실제 도구 출력이므로, 그 표현을 따른 답변을 순수한 날조로만 분류해서도 안 된다.

- 코드: `src/main/java/io/ohgnoy/monitoring/infrastructure/prometheus/PrometheusQueryService.java:272–293`
- 실제 전달 기록: 위 표본 `delivered-6`
- 후속 개선: 첫 값·마지막 값·절대 변화·관측 구간을 표시하고, counter는 reset을 고려한 `increase`/`rate`와 구분한다. “상대 변화 10% 이하”와 “변화 없음”을 같은 말로 표현하지 않는다. 단위·메트릭 종류도 함께 전달해야 한다.

## 해결된 사전 조건이 개별 채점 문구에는 조건부로 남은 경우

OOM victim finding에는 “host/kernel 로그가 양쪽에서 불가함을 입증할 때까지 blocked”라는 조건부 문구가 남아 있다. 사전 `semantic-boundary-preflight.json`은 두 조회 경로에서 kernel 로그가 전달되지 않음을 입증했고, `semantic-references.json` 최상위 `resolved_source_conditions`에도 해결 상태와 증거 해시가 있다. 그러나 그 해결 설명이 개별 blind packet의 reference에는 함께 포함되지 않아 두 검수자가 모호성을 표시했다.

이번 점수·검수 원본을 사후 수정하지 않는다. 모호성 표시와 해결 증거를 함께 보존한다. 다음 판에서는 같은 정답을 유지하더라도, 검증 완료된 관측 경계를 개별 reference에도 자족적으로 설명한 뒤 새로 고정해야 한다.

## 해석 범위

도구 수를 늘리는 것만으로 해결되는 문제와, 기존 도구의 표현·선택·결론 도출 문제는 다르다. 이번 자료는 두 종류가 모두 있음을 보여준다. 운영 서버의 모든 로그 수집 경로나 실제 장애 빈도를 조사한 결과는 아니다. 더 넓은 읽기 전용 정보 요구사항은 [기존 도구 범위 검토](EVAL-V5-TOOL-COVERAGE.md)에 정리되어 있다.
