# 연구 사례와 홈서버 관제 평가 38종 비교

검토일: 2026-11-03. 범위: 기존 38개 시나리오 전체, 라이브 평가 러너·Judge·실제 도구 구현, 추가 대화 회귀 검사, 공개 논문과 저자 구현.
이번 작업은 비교 검토다. 데이터셋·평가 코드·운영 프롬프트는 수정하지 않았고 모델 평가도 다시 실행하지 않았다.

## 핵심 판단

**38종이라는 개수나 자체 시나리오를 사용한 접근 자체가 문제는 아니다. 현재 우선 고칠 부분은 정답의 근거, mock의 정확성, 합격 판정이다.**

- 38종의 `must_check`에는 `search_rag`를 반드시 호출하라는 명시적 요구가 없다. 기존 데이터셋 전체가 고정 호출 순서를 강요한다고 보는 것은 부정확하다.
- 실제로 살펴보면 메모리 OOM, 설정 오류, 임계치 초과와 정상 부하의 구분 등 재사용할 만한 상황이 포함돼 있다.
- 그러나 잘못된 쿼리·대상에도 원하는 관측값이 반환되고, 관측으로 알 수 없는 원인을 요구하는 경우가 있다. 이 환경에서는 모델의 조사 능력과 평가 환경의 결함이 섞인다.
- 연구에서도 필요한 도구·선행 조건을 요구한다. 따라서 행동 조건 자체를 전부 제거할 필요도 없다. **관측·업무 정책으로 정당화되는 조건인지, 특정 구현을 선호해서 넣은 조건인지**가 구분 기준이다.
- 앞선 v1 19/38, v4 17/38은 해당 mock·Judge에서 나온 결과다. 숫자를 폐기할 필요는 없지만, 운영 정확도나 프롬프트의 일반적인 우열로 확대 해석해서는 안 된다.

아래 개선 판단과 38종별 의견은 공개 연구를 현재 코드에 적용해 도출한 검토 의견이다. 외부 연구가 이 프로젝트의 데이터셋을 검증한 것은 아니다.

## 연구와 실제로 같은 점·다른 점

### AIOpsLab

장애를 주입한 서비스·부하·관측 데이터를 함께 구성하고 탐지, 위치 특정, 원인 분석, 복구를 나눠 평가한다. 정확성과 시간·행동 수·토큰 비용을 분리한다. 공개 포트 오류 예제에서는 실제 결함 대상과 답을 비교하고 복구 후 설정·상태도 확인한다. 선택적인 LLM 정성 평가도 존재하므로 “LLM 채점을 쓰면 연구 방식과 다르다”는 주장은 맞지 않는다. [논문 §2–3](https://arxiv.org/html/2501.06706v1), [결함·채점 구현 예제](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/orchestrator/problems/k8s_target_port_misconfig/target_port.py), [정량·선택적 정성 평가 분리](https://github.com/microsoft/AIOpsLab/blob/main/aiopslab/orchestrator/tasks/base.py)

우리 38종도 운영 장애별로 관측과 기대를 구성한다는 점은 유사하다. 다만 실제 장애 주입 대신 정해진 요약 문자열을 반환하고, 원인·대상·복구 상태를 직접 검증하는 판정기가 없다. 현재 용도는 **고정 관측 요약에 대한 알람 분석 응답 평가**에 가깝다. 읽기 전용 관제 평가에 실제 장애 주입이 반드시 필요한 것은 아니지만, 실제 복구 성공을 입증하는 평가와는 구분해야 한다.

### ToolSandbox

초기 상태·사용자 요청·도구를 구성하고, 필요한 중간·최종 조건인 milestones와 금지 사건인 minefields를 평가한다. 여러 도구·순서·시행착오를 허용하면서 필요한 시간적 의존성은 제한한다. 효율은 조건 충족 점수와 별도 측정한다. 시나리오 작성 후 다른 주석 작성자가 실행 가능성과 평가 조건을 검증하는 절차도 설명한다. [논문 §2.3·§3·부록 B.2](https://arxiv.org/html/2408.04682v2)

우리 `must_check`·`forbidden_actions`는 발상 면에서 가깝다. 차이는 이 조건을 프로그램이 상태·실행 기록에 대조하지 않고 LLM의 네 개 점수로 간접 판단한다는 점이다. 충분한 근거에 도달한 다른 조사 경로를 인정할 수 있다는 장점은 살리되, 필요한 사실·금지 사건을 명시적인 판정으로 옮길 여지가 있다.

### τ-bench

대화와 읽기 도구의 선택은 달라도 최종 DB 상태와 필수 전달 정보로 성공을 판정한다. 반복 실행의 신뢰성도 측정한다. 다만 원 논문도 최종 상태가 맞는 것만으로 중간 승인 등 모든 정책 준수를 보장하지는 못한다고 인정한다. [논문 §3](https://arxiv.org/html/2406.12045v1), [상태·출력 판정 코드](https://github.com/sierra-research/tau-bench/blob/main/tau_bench/envs/base.py)

우리 38종 중 27개는 READ_ONLY이므로 DB 변경 성공을 그대로 정답으로 가져오면 안 된다. 조회 대상·단위·시간·확인한 사실과 불확실성에 대한 결과 조건이 더 적절하다. 승인·실행 경로는 별도 상태 검사로 검증할 수 있다. τ-bench를 근거로 “최종 답만 맞으면 어떤 행동도 괜찮다”고 해석해서도 안 된다.

공개 저장소의 main 구현은 논문 발표 시점과 달라질 수 있다. 여기서는 버전이 지정된 논문과 검토일의 공개 구현을 구분해 참고했다.

## 비교표

| 비교 항목 | 연구에서 참고할 원칙 | 현재 38종 | 판단 |
|---|---|---|---|
| 상황별 과제 | 초기 상태·목표·정책을 명시 | 알람, mock, 기대·금지 항목 존재 | 유지할 기반 |
| 원인 정답의 근거 | 알려진 결함 또는 명시적인 상태 | `situation`에만 있는 원인이 일부 존재 | 관측으로 입증 가능한 범위와 분리 |
| 도구 실행의 의미 | 인자와 상태에 맞는 결과 | 키워드 포함 여부로 문자열 반환 | 우선 보완 |
| 대체 조사 경로 | 필수 의존성만 제한 | 자연어 조건이므로 유연성은 있으나 판정 불투명 | 정보 요구와 구현 선호를 구분 |
| 금지 행동 | 명시적인 사건·정책 위반 검사 | Judge의 safety 점수에 의존 | 실제 금지 사건은 별도 검사 |
| 상태·오류 변화 | 도구 사용·상태에 따라 결과 변화 | 시나리오 내부 대부분 고정 반환 | 정적 분석 회귀에는 유효, 복구·상호작용 검증에는 부족 |
| 성공과 효율 | 정확성과 비용을 분리 | 점수·호출 수·지연 모두 기록 | 기록은 적절, 적은 호출을 곧 개선으로 해석하면 안 됨 |
| 반복 신뢰성 | 동일 과제 반복 | 기본 3회, 최근 실행은 1회 | 최근 결과로 안정성·우월성 입증 불가 |
| 사람의 기준 검증 | 실행 가능성·주석 타당성 점검 | 구조 검사는 있으나 의미·실행 가능성 검증은 보장하지 않음 | 추가 필요 |

## 코드에서 확인한 주요 차이

### 1. 조회가 틀려도 근거를 받을 수 있다

[러너의 matchByKeyword](../src/test/java/io/ohgnoy/monitoring/eval/LiveEvalRunner.java:372)는 쿼리에 등록된 키워드가 포함되면 정해진 응답을 돌려준다. PromQL 문법·메트릭 존재·대상 레이블·시간 범위를 검사하지 않는다. 알람 검증 mock도 임의의 이름·레이블에 같은 결과를 돌려준다.

같은 매칭 규칙을 정적으로 재현하면 다음과 같다. 실제 Prometheus 요청이나 모델 재평가를 실행한 결과는 아니다.

| 입력 | 현재 mock 응답 |
|---|---|
| `sum(node_filesystem_avail_bytes{mountpoint="/wrong"}) /` — 문법이 완성되지 않은 식 | `/var/lib/docker`의 7일 추세와 사용률 87% |
| `node_cpu_nonexistent_metric{instance="wrong-host"}` — 정의된 관측과 다른 이름·대상 | CPU 92% |

이 문제는 저장된 실행 기록에서도 드러난다. `disk_space_low`에서 v4가 `node_filesystem_usage_percent` 같은 식으로 조회했는데도 동일한 디스크 관측값이 반환됐다. 따라서 이 평가를 **정확한 PromQL·대상 선택 검증**으로 설명하기는 어렵다.

정적인 요약 mock 자체는 유효한 회귀 검사 방식이다. 다만 이를 유지한다면 측정 대상을 “제공된 관측 요약을 해석하는 능력”으로 좁히거나, 별도 쿼리 계약 검사를 추가해야 한다.

### 2. 정답 설명과 실제로 알 수 있는 정보가 다르다

`situation`은 스키마 검사에서는 존재 여부를 확인하지만, 라이브 러너의 Judge 입력에는 직접 전달되지 않는다. Judge는 알람·실제 얻은 도구 기록·결론·자연어 채점 기준을 받는다. 숨겨진 설명을 에이전트에게 주지 않는 것은 적절하지만, 판정에는 명시적인 근거와 정답 범위가 필요하다. [입력 구성](../src/main/java/io/ohgnoy/monitoring/application/agent/evaluation/AgentJudgeEvaluator.java:157)

| 시나리오 | 요구 또는 설명 | 현재 관측의 한계 | 적절한 수정 방향 |
|---|---|---|---|
| `redis_memory_evictions` | 어떤 데이터 종류가 퇴출되는지 확인 | 사용량·퇴출 수·allkeys-lru만 있고 키 용도·세션 매핑은 없음 | 종류 미확정을 허용하거나 관련 관측 추가 |
| `loki_ingestion_stopped` | 위치 파일 유실이 원인, shipping 계층 특정 | 수집량 0·다른 target 정상·빈 Promtail 로그만 존재 | 수집 경로 이상 가설과 파일 유실 확정을 구분 |
| `mysql_replication_stopped_binlog` | replica가 로그를 필요로 하는지 확인 | binlog·만료 설정만 있고 복제 상태·RAG 정보는 없음 | 복제 확인 전 삭제 보류를 성공으로 인정하거나 관측 추가 |
| `time_drift_ntp` | UDP 123 방화벽 차단이 원인 | 오프셋·비동기 상태·응답 timeout만 존재 | 방화벽·서버·경로 문제를 가설로 두거나 방화벽 근거 추가 |

이 경우 정답을 맞히지 못한 모델만 탓하면, 오히려 관측에 없는 원인을 추측하는 모델을 보상할 수 있다.

### 3. 운영 경로와 평가 경로가 다르다

운영 [AlertAnalysisChain](../src/main/java/io/ohgnoy/monitoring/application/pipeline/AlertAnalysisChain.java:78)은 STALE이면 ReAct 분석 전에 종료한다. 반면 `cpu_transient_spike`와 `stale_disk_alert_resolved`는 ReActAgent를 직접 호출하고 추가 추세 확인을 요구한다.

두 시나리오는 에이전트의 강건성 검사로 유지할 수 있다. 그러나 운영 정책상 이미 충분한 해소 확인으로 종료한 행동을 추가 조회 부족으로 감점한 뒤, 이를 운영 실패율에 그대로 포함하는 것은 재검토해야 한다.

또한 38종의 권한 분포는 READ_ONLY 27개, NEEDS_APPROVAL 10개, NONE 1개다. AUTO는 없다. 러너는 실제 승인·실행 파이프라인을 실행하지 않는다. 따라서 이 38종으로 실제 승인 준수·자동 복구 성공을 입증할 수는 없다.

### 4. 호스트 로그의 가용성을 mock이 과장할 수 있다

실제 [query_loki](../src/main/java/io/ohgnoy/monitoring/application/agent/tools/AgentTools.java:161)는 Docker 로그 job에서 컨테이너 이름을 본문 필터로 검색한다. 검토한 Promtail 설정도 Docker 파일만 수집한다. 반면 mock은 쿼리 문자열에 `kernel`, `systemd`, `sshd` 등이 있으면 준비된 호스트 로그를 반환할 수 있다.

따라서 `host_oom_killer`, `time_drift_ntp`, `security_ssh_bruteforce`가 mock에서 풀린다고 해서 운영 도구로 같은 근거를 얻을 수 있다고 볼 수 없다. 호스트 로그 수집·도구 경로를 추가하거나 해당 증거를 얻지 못하는 경우를 정당한 결과로 처리해야 한다. 컨테이너 이름과 실제 로그 레이블·본문의 매핑도 별도 확인 대상이다.

### 5. 합격은 직접적인 사건 판정이 아니라 네 개 점수의 임계치다

[passesMinimumScores](../src/test/java/io/ohgnoy/monitoring/eval/LiveEvalRunner.java:283)는 factuality/tool_use/actionability/safety 점수만 비교한다. `verdict`, `missing_requirements`, `unsupported_claims`를 독립적인 실패 조건으로 검사하지 않는다. 금지 행동도 현재는 Judge의 점수에 반영되기를 기대하는 구조다.

이는 무조건 잘못된 방식이라는 뜻은 아니다. 다만 안전 위반을 다른 답변 장점과 분리해 검사하는 장치가 없으며, 7점과 8점의 차이가 실제 운영상 무엇을 의미하는지 교정된 근거도 확인되지 않았다.

저장된 76건에서 Judge의 `verdict=pass`지만 최종 점수 기준으로 실패한 건은 11건이었다. 반대로 `verdict!=pass`인데 최종 합격한 사례는 이번 기록에는 없었다. 앞의 11건은 버그로 단정할 일이 아니라, **어느 합격 정의를 사용할지 명확히 해야 한다는 증거**다.

앞선 설명에서 “원인·조치가 없으면 무조건 감점한다”고 요약한 것도 정확하지 않았다. 실제 Judge 지시는 그런 내용 없이 **추가 조사 계획만** 말하고 끝내는 경우를 감점한다. 정직한 확인 불가 결론을 전부 금지하는 문구는 아니다. 문제는 상황별 유효한 종료 결과와 근거 범위가 명시적인 판정으로 구현되지 않았다는 점이다. [Judge 지시](../src/main/java/io/ohgnoy/monitoring/application/agent/evaluation/AgentJudgeEvaluator.java:129)

### 6. 시간과 원시 관측의 의미도 맞춰야 한다

알람 생성에는 실행 시점의 `Instant.now()`를 쓰지만 mock의 발생 시각·백업 시각은 고정된 2026년 8월 값이다. 오래 지속된 알람 자체가 모순은 아니지만, 상대 시간·재조회 범위의 기준 시각이 명시돼 있지 않아 재현성에 영향을 준다. 실제 v4 기록에는 8월 발생 시각과 11월 현재 시각의 차이를 이유로 현재 firing 확인을 의심한 답변이 있었다.

또 일부 mock은 단순 지표에 “추론 정상”, “상위 고카디널리티 메트릭” 같은 추가 진단까지 함께 넣는다. 실제 [Prometheus 범위 요약](../src/main/java/io/ohgnoy/monitoring/infrastructure/prometheus/PrometheusQueryService.java:251)은 첫 시계열의 최소·최대·현재·추세만 반환한다. 동일한 정보 수준인지 검증해야 한다.

## 38종별 검토

“유지”는 현재 판정의 과학적 타당성을 인증한다는 뜻이 아니라, 과제 소재와 기본 목적을 재사용할 수 있다는 뜻이다. 모든 항목에는 위 mock·합격 판정 문제가 공통으로 적용된다. 아래는 시나리오별 추가 조정점이다.

| # | 시나리오 | 비교 판단·필요 조정 |
|---:|---|---|
| 1 | [cpu_sustained_high](../src/test/resources/eval-dataset-v2.yml:33) | 유지. CPU/부하의 지속성 판단은 타당하다. 특정 과거 원인 재현보다 현재 대상·단위·기간의 근거를 평가한다. 원인 미확정도 허용한다. |
| 2 | [cpu_transient_spike](../src/test/resources/eval-dataset-v2.yml:64) | 운영 정합 조정. STALE 종료 정책과 추가 추세 조회 요구를 분리한다. |
| 3 | [container_down_bind_error](../src/test/resources/eval-dataset-v2.yml:92) | 유지. bind 오류 로그가 원인 판단을 뒷받침한다. 로그를 얻는 경로·순서는 대체 가능하게 둔다. |
| 4 | [container_memory_oom](../src/test/resources/eval-dataset-v2.yml:126) | 유지·용어 정밀화. Java heap OOM 근거와 메모리 추세를 평가하되 커널/cgroup OOM까지 확정하게 만들지 않는다. |
| 5 | [gpu_temperature_high](../src/test/resources/eval-dataset-v2.yml:159) | 유지. 제공된 경고·종료 임계치와 영향에 따른 대응을 평가한다. 특정 온도를 보편 규칙으로 만들지 않는다. |
| 6 | [disk_space_low](../src/test/resources/eval-dataset-v2.yml:188) | 유지·mock 수정. mountpoint·기간·여유/사용의 방향을 검사한다. 존재하지 않는 식에도 관측을 주는 문제를 우선 수정한다. |
| 7 | [instance_down_network](../src/test/resources/eval-dataset-v2.yml:215) | 조건 조정. 동일 호스트 target 동시 down으로 범위를 넓히는 것은 타당하지만 호스트·네트워크·수집 경로 중 단일 원인 확정은 요구하지 않는다. |
| 8 | [http_error_rate_high](../src/test/resources/eval-dataset-v2.yml:243) | 유지. 5xx와 DB timeout/pool 증거의 관계를 평가한다. 배포 회귀 확정에는 추가 근거가 필요하다. |
| 9 | [postgres_connections_high](../src/test/resources/eval-dataset-v2.yml:275) | 유지. DB 연결량과 앱 pool 상태를 함께 해석하되 연결 누수 등 세부 원인은 가설로 허용한다. |
| 10 | [alertmanager_reload_failed](../src/test/resources/eval-dataset-v2.yml:305) | 유지. YAML parse 오류라는 직접 근거가 있다. 파일 수정·재시작 여부는 별도 권한 정책으로 평가한다. |
| 11 | [nginx_upstream_502](../src/test/resources/eval-dataset-v2.yml:338) | 관측 보강. `up=1`과 connection refused만으로 프로세스 hang을 확정할 수 없다. upstream 접근 불가 진단과 컨테이너·앱 health를 구분한다. |
| 12 | [redis_memory_evictions](../src/test/resources/eval-dataset-v2.yml:373) | 관측 보강. 퇴출 key 종류·세션 용도가 제공되지 않는다. 영향 미확정과 추가 확인 필요를 유효하게 평가한다. |
| 13 | [mysql_slow_queries](../src/test/resources/eval-dataset-v2.yml:401) | 조건 조정. 느린 SQL 식별은 가능하지만 인덱스 부재는 EXPLAIN·스키마 없이 확정하지 않게 한다. |
| 14 | [container_restart_loop](../src/test/resources/eval-dataset-v2.yml:432) | 유지. 누락된 환경변수라는 직접 로그가 있다. 원인 수정 전 반복 재시작 회피는 이 과제의 정책·근거로 정당화된다. |
| 15 | [host_memory_leak](../src/test/resources/eval-dataset-v2.yml:465) | 유지·불확실성 허용. Jellyfin RSS 증가 특정은 가능하다. 누수 의심과 확정을 구분하고 사용자 영향 없는 재시작을 당연시하지 않는다. |
| 16 | [disk_io_saturation](../src/test/resources/eval-dataset-v2.yml:494) | 유지. 백업 일정은 RAG와 현재 시작 로그로 제공된다. 그 정보를 확인하는 것이 필요하지 반드시 특정 호출 순서가 필요한 것은 아니다. |
| 17 | [cert_expiry_soon](../src/test/resources/eval-dataset-v2.yml:522) | 유지. 만료 7일·인증 갱신 port bind 오류는 유효한 관측이다. 남은 일수는 일관된 기준 시각으로 제공한다. |
| 18 | [prometheus_target_missing](../src/test/resources/eval-dataset-v2.yml:553) | 유지·도구 계약 점검. missing과 0을 구분하는 과제는 타당하다. 사라진 exporter의 과거 로그를 실제로 조회할 수 있어야 한다. |
| 19 | [gpu_memory_full](../src/test/resources/eval-dataset-v2.yml:585) | 관측 보강. VRAM 97%와 GPU 사용률만으로 서비스 영향 없음은 검증할 수 없다. 처리량·오류·지연 근거나 미확정 결과가 필요하다. |
| 20 | [loki_ingestion_stopped](../src/test/resources/eval-dataset-v2.yml:613) | 관측 보강. 수집 경로 이상과 위치 파일 유실 확정은 다르다. 파일·권한·배송 오류 증거 없이 정확한 원인을 맞히게 만들지 않는다. |
| 21 | [alert_flapping](../src/test/resources/eval-dataset-v2.yml:641) | 유지·정책 정밀화. flapping·현재 up·healthcheck 지연을 구분한다. 서비스 영향 관측 없이 정상/전면 장애 어느 쪽도 확정하지 않는다. |
| 22 | [stale_disk_alert_resolved](../src/test/resources/eval-dataset-v2.yml:673) | 운영 정합 조정. 이미 해소된 상태의 무조치 종료를 성공으로 인정할 조건을 명시한다. |
| 23 | [security_ssh_bruteforce](../src/test/resources/eval-dataset-v2.yml:700) | 유지·로그 경로 보강. 반복 시도와 fail2ban 조치는 근거가 있다. Docker 조회가 실제 SSH 호스트 로그를 얻을 수 있는지는 별도 검증한다. |
| 24 | [network_probe_latency](../src/test/resources/eval-dataset-v2.yml:733) | 유지. DNS 단계 지연과 내부 지연을 구분하는 과제다. ISP 등 특정 원인까지 단정하도록 요구하지 않는다. |
| 25 | [postgres_autovacuum_bloat](../src/test/resources/eval-dataset-v2.yml:760) | 정답 범위 조정. 설명의 쓰기 부하와 로그의 lock 획득 실패를 구분한다. 관측된 lock 차단 및 추가 가설을 인정한다. |
| 26 | [jellyfin_transcode_cpu](../src/test/resources/eval-dataset-v2.yml:787) | 유지·영향 보강. 사용자 작업과 부하 상관은 판단 가능하다. 예상 작업이라는 이유만으로 모든 서비스가 정상이라고 단정하지 않는다. |
| 27 | [backup_job_failed](../src/test/resources/eval-dataset-v2.yml:818) | 유지·시간 정합 수정. tar 단계 공간 부족과 복구 시점 위험은 타당하다. 고정 날짜와 ‘3일 전’을 동일한 논리 시계에 맞춘다. |
| 28 | [host_oom_killer](../src/test/resources/eval-dataset-v2.yml:852) | 유지·로그 경로 보강. 커널 kill 대상과 모델 로드의 근거는 유용하지만 실제 kernel 로그 수집·조회 경로가 필요하다. |
| 29 | [unknown_metric_alert](../src/test/resources/eval-dataset-v2.yml:887) | 유지·중요한 양성 사례. 확인 불가와 무조치 종료가 정답이 될 수 있는 경우다. 진단 문장의 화려함보다 허위 수치·조치 부재를 평가한다. |
| 30 | [multi_container_down_daemon](../src/test/resources/eval-dataset-v2.yml:916) | 상태 일관성 보강. 여러 컨테이너 동시 down·daemon 종료 로그와 기본 실행 중 목록이 함께 반환된다. daemon 상태에 맞는 inventory 결과·오류를 정의한다. |
| 31 | [grafana_datasource_error](../src/test/resources/eval-dataset-v2.yml:949) | 관측 보강. 하드코딩 IP와 경로 실패는 보인다. 네트워크 재생성·현재 IP 변경의 확정에는 설정·주소 비교 근거가 필요하다. |
| 32 | [nginx_rate_limit_burst](../src/test/resources/eval-dataset-v2.yml:979) | 유지·단정 완화. 거부가 한 내부 IP에 집중된 사실과 봇 주기 설정 오류·전체 사용자 무영향의 확정은 구분한다. |
| 33 | [couchdb_compaction_disk](../src/test/resources/eval-dataset-v2.yml:1008) | 유지·수치 해석 조정. disk/data 차이는 회수 여지의 근거다. 차액 39GB가 반드시 회수된다고 보장하지 않고 실행 여유 공간·정책도 구분한다. |
| 34 | [websocket_connection_drop](../src/test/resources/eval-dataset-v2.yml:1036) | 수치·정답 범위 조정. 41→39는 전체 복구와 같지 않다. 주어진 시각은 67초 차이이므로 ‘1분 이내’보다 ‘약 1분, 대부분 복구’가 정확하다. |
| 35 | [prometheus_storage_growth](../src/test/resources/eval-dataset-v2.yml:1067) | 관측 보강. head series 총량과 원인 메트릭·라벨 카디널리티는 서로 다른 정보다. 한 쿼리에 정답 요약까지 주는 추상화를 명시하거나 별도 관측을 제공한다. |
| 36 | [mysql_replication_stopped_binlog](../src/test/resources/eval-dataset-v2.yml:1095) | 관측 보강. replica 유무는 제공되지 않는다. 보존·삭제 판단을 보류하는 답을 인정하거나 복제 상태 관측을 추가한다. |
| 37 | [code_server_unauthorized_access](../src/test/resources/eval-dataset-v2.yml:1122) | 유지·보안 범위 명시. 스캔 시도·접근 노출 검토는 타당하다. 인증 실패를 침해 성공으로 확대하지 않고 실제 노출 설정은 별도 근거로 다룬다. |
| 38 | [time_drift_ntp](../src/test/resources/eval-dataset-v2.yml:1152) | 관측 보강. NTP timeout은 UDP 123 차단의 확정 증거가 아니다. 불확실성을 인정하거나 firewall·네트워크 근거를 추가한다. |

## 추가한 대화 13종도 같은 기준으로 돌아봐야 한다

최근 대화 회귀에는 실제 승인 저장 호출·실행 미발생·새 턴 조회 같은 유용한 직접 검사가 있다. 그러나 모두가 조사 방식과 무관한 품질 검사는 아니다.

- [CPU 검사](../src/test/java/io/ohgnoy/monitoring/ConversationBehaviorAuditTest.java:118)는 `systemSummary("cpu")` 호출을 요구하고 hardwareSummary 호출을 금지한다. 일반 PromQL로 정확하게 답한 대체 경로도 실패할 수 있다. 전용 도구 라우팅 회귀 검사로는 유효하지만 전체 답변 품질 점수와는 분리해야 한다.
- `알려주`라는 문자열을 일괄 금지하면 적절한 대상 확인 질문도 걸릴 수 있다. “도구로 알아낼 구현 정보를 사용자에게 떠넘겼는가”라는 의미를 평가해야 한다.
- `32`, `10` 포함 여부만으로 수치의 대상·단위·부정 여부가 맞다고 보장할 수 없다. 구조화된 관측과 전달 사실을 비교하거나 보조 의미 평가가 필요하다.
- 따라서 “13/13 회귀 검사 통과”라는 설명은 유지할 수 있지만 “자유로운 대화 과제 100% 정확”이라고 설명하면 안 된다.

이는 38종을 비판하면서 새 테스트에는 특정 구현을 강제하는 문제를 남기지 않기 위한 동일한 검토다.

## 유지할 것과 보완 순서

**38종의 소재는 유지한다. 모든 `must_check`를 삭제하거나 무조건 큰 외부 벤치마크로 바꿀 필요는 없다.**

1. 측정 목표를 분리한다. 알람 분석의 근거·결론, 사용자 질문 대응, 승인·실행 상태, 복구 성공은 각각 다른 결과다.
2. 시나리오마다 관측 가능한 사실, 확정 가능한 결론, 허용할 가설·미확정 결과, 금지할 실제 사건, 업무 정책을 구분한다. 관측할 수 없는 필수 항목은 보강하거나 조건부로 바꾼다.
3. mock이 입력 문법·대상·시간·오류를 구분하도록 한다. 이 단계가 어렵다면 mock 결과 해석 평가와 실제 도구 계약 평가를 명시적으로 분리한다.
4. 필수 사실·권한 위반 등 객관적인 부분을 직접 검사하고, 대체 가능한 조사 경로·표현은 허용한다. 필요한 정보에 이미 도달했다면 특정 도구 호출을 추가로 요구하지 않는다.
5. 의미 평가에는 LLM을 보조로 사용할 수 있다. 정답·근거·허용 불확실성에 맞는 rubric을 검증하고, 사람 표본 점검으로 교정한다. Judge의 7점/8점만으로 운영 실패를 정의하지 않는다.
6. 기준이 검증된 후 보류 데이터·변형 상황에서 반복 측정한다. 기존 19/38·17/38과 새 기준 결과는 평가 버전·모델·반복 조건을 구분해 기록한다.

실제 서비스에 장애를 주입해야 하는 것은 아니다. 포트폴리오의 주장이 ‘알람 관측 요약을 해석하는 에이전트 평가’라면 경량 mock으로도 설명 가능하다. ‘실제 장애 진단·자동 복구의 신뢰성’까지 주장한다면 도구·관측·권한·복구 상태를 연결한 별도 검증이 필요하다.

## 포트폴리오에 대한 해석

현재 근거에 맞는 표현은 다음과 같다.

> 38개 알람 상황과 고정된 관측 요약으로 에이전트의 분석 응답을 비교 평가했다. 도구 호출 기록과 답변을 LLM Judge로 채점했으며, mock의 현실성·정답 관측 가능성·채점 기준의 한계를 확인했다.

현재 38종만으로 ‘운영 상황 대부분에서 정확’, ‘승인 정책과 실제 복구까지 검증’, ‘특정 프롬프트가 일반적으로 우수’를 입증했다고 표현하는 것은 근거를 넘어선다.

기존 실험 수치가 소급해서 허위가 되는 것은 아니다. 실험 조건과 평가가 측정한 범위를 정확히 밝히고, 개선된 기준으로 얻은 결과를 다른 버전의 실험으로 기록하면 된다.
