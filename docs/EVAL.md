# 라이브 에이전트 평가 (Live Evaluation)

현재 기준은 **40개 × 4조건, 실제 모델 160답변을 검토한 [최종 결과](EVAL-V4-RESULTS-2026-11-16.md)**다. 실행 원본 v4와 정답 한 항목을 정정한 재사용 revision 4.1을 구분한다. [사례별 점수](EVAL-V4-CASE-SCORES.md), [설계·제약](EVAL-V4-PROTOCOL.md), [커버리지](EVAL-V4-COVERAGE.md), [재현 명령](EVAL-V4-RUNBOOK.md), [조회 도구 감사](EVAL-V4-TOOL-AUDIT.md)를 먼저 확인한다. 아래 v1/v2/v3 설명과 과거 합격률은 이전 실험 기록이며, 검증된 실운영 정확도로 해석하지 않는다. v4는 원답·관측을 보존하고 출력 계약 점수와 인용 기반 내용 검토를 구분한다.

알람 분석 프롬프트의 효과를 **재현 가능한 조건**에서 측정하는 평가 하네스. 기존 데이터셋은 38종이며 대화 회귀 평가는 별도다.

## 설계

| 요소 | 값 | 이유 |
|------|-----|------|
| 데이터셋 | `src/test/resources/eval-dataset-v2.yml` (시나리오 38종) | 시나리오별 정답 기준(must_check / forbidden_actions / minimum_scores) 포함. 적대 시나리오(STALE 알람, 검증 불가 알람, 플래핑, 동시 다운 함정) 포함 |
| 관측 데이터 | 시나리오별 고정 mock (Prometheus / Loki / RAG / 컨테이너 목록) | 실제 서버 상태에 흔들리지 않는 재현성 확보 |
| 에이전트 | 실제 LLM, 운영과 동일 경로 (ReActAgent + ReflectionAdvisor + WebSearchTool) | 측정 대상 = 모델 행동. temperature는 운영 기본값 유지 (변동성 자체가 측정 대상) |
| 프롬프트 arm | `EVAL_ARMS`로 선택. v1/v2/v3 = 기존 비교 자료, v4 = 공통 정책과 모드별 종료 기준 | 모든 arm에 현재 실행 제한이 적용되므로 순수 프롬프트 비교다. 과거 런타임과 동일하지 않음 |
| Judge | 실제 LLM, **temperature 0**, 기본 **gemini-2.5-pro** (에이전트와 분리) | 채점 기준(자)은 흔들리면 안 됨. 같은 모델로 채점하면 자기 응답 선호 편향 발생 — 더 강한 별도 모델 사용 |
| 반복 | arm당 시나리오별 3회 (기본) | 에이전트 변동성 반영, p50/p95 산출 |
| 판정 | pass = 4개 차원(Factuality/Tool Use/Actionability/Safety) 모두 시나리오별 minimum_scores 이상 | 단일 점수 평균의 왜곡 방지 |

총 실행 수 (기본): 38 시나리오 × 2 arm × 3회 = **228 에이전트 실행 + 228 Judge 호출** (+ Reflection 추가 호출).

## 수치형 v3 평가

새 모델의 전체 탐색에는 실제 PromQL 계산을 수행하는 `GroundedEvalRunner`를 사용한다.
v1/v2 설명형 요약과 채점 기준이 달라 과거 합격률과 직접 비교하지 않는다.
전수 검토 기록은 [2026-11-16 데이터셋 검토](EVAL-DATASET-REVIEW-2026-11-16.md)에 있다.
이 검증은 fixture 내부 일관성 검사다. [운영 대표성 검토](EVAL-REPRESENTATIVENESS-AUDIT-2026-11-16.md)에서
실제 규칙과 발화 조건 불일치 및 실제 이력과의 연결 부재를 확인했다. 현재 38종을 운영 정확도
벤치마크로 해석하지 않는다.

```bash
# PyYAML, Docker, 로컬 prom/prometheus:v2.53.0 이미지 필요
rtk proxy python3 scripts/audit_eval_dataset.py
EVAL_BASE_URL=http://<ollama-address>:11434 \
EVAL_MODEL=qwen3.5:9b-pi32k EVAL_JUDGE_MODEL=qwen3.5:9b-pi32k \
EVAL_ARMS=v4 EVAL_REPEATS=1 \
rtk proxy ./gradlew evalRun --tests '*GroundedEvalRunner' --console=plain
```

`build/eval/grounded-<timestamp>/`에 보정 18건과 실제 실행 결과·관측 trace를 저장한다.
Gradle의 binary/XML/HTML 보고서는 별도의 invocation UUID 경로에 저장해 다른 실행의 보고서를 덮어쓰지 않는다.
기본 arm은 v1/v2/v4, 기본 반복은 3회이므로 탐색 시 위와 같이 명시한다.
단일 사례는 `EVAL_ONLY=<id>`, 보정만 실행하려면 `EVAL_CALIBRATION_ONLY=true`를 지정한다.
Judge의 보정 일치율·미판정·잘못된 합격을 반드시 확인한다. 같은 모델 Judge와 1회 반복은
탐색용이며 독립적으로 검증된 모델 순위가 아니다. 라우터가 모델명을 고정한다면 실제 모델
선택이 가능한 직접 엔드포인트를 사용한다.

## 로컬 운영 모델 평가

### 평가 parser 준비 (strict-summary-v1)

```bash
rtk proxy python3 -m venv .venv-eval
rtk proxy .venv-eval/bin/pip install -r scripts/requirements-eval.txt
export EVAL_PROMQL_PYTHON="$PWD/.venv-eval/bin/python"
rtk proxy "$EVAL_PROMQL_PYTHON" -m unittest discover -s scripts/tests -p test_eval_fixture.py
rtk proxy ./gradlew test --tests '*StrictObservationFixtureTest' --tests '*FixtureSummaryTest'
```

새 러너는 `promql-parser==0.11.0`으로 실제 AST를 파싱한다. parser 미설치는 시작 오류이며 예전 키워드 매칭으로 돌아가지 않는다.
기존 38종은 설명형 관측 요약이다. 메트릭 이름·알려진 레이블이 맞는 단순 selector만 관측 요약을 반환하며 **PromQL 계산값으로 표시하지 않는다**.
문법 오류는 인자 오류, 존재하지 않는 메트릭·불일치 대상은 빈 결과다. 계산식·알 수 없는 레이블/시각 변경 등 기존 데이터로 평가할 수 없는 정상 쿼리는 `unsupported_fixture`다.
이 상태는 모델 실패·Judge 파싱 실패와 구분해 `evaluationStatus=ungraded_fixture` 및 `unsupportedQueries`로 기록한다.
미판정이 하나라도 있으면 서로 다른 유효 사례 집합으로 순위를 만드는 일을 막기 위해 합격률 비교표를 생성하지 않는다.
전체 PromQL 계산 평가를 재개하려면 수치 시계열 fixture와 계산 엔진이 추가로 필요하다. 현재 변경은 설명형 요약을 임의의 계산 결과로 반환하는 것을 막는 범위다.

Loki mock은 정확한 컨테이너 이름·Docker source·시간 범위·limit을 검사한다. 기존 inventory로 출처를 증명할 수 없는 로그는 미판정으로 기록한다.
알람 검증도 이름과 레이블이 일치할 때만 해당 fixture 상태를 반환한다. 기존 데이터셋·기대 정답·과거 실행 결과는 변경하지 않았다.

```bash
EVAL_BASE_URL=http://<router-address>:8081 \
EVAL_MODEL=qwen3:8b EVAL_JUDGE_MODEL=qwen3:8b \
EVAL_ARMS=v1,v4 EVAL_REPEATS=1 \
rtk proxy ./gradlew evalRun --tests '*LiveEvalRunner' --console=plain
```

로컬 모델에서는 API 키 없이 실행한다. `EVAL_JUDGE_BASE_URL`로 별도 OpenAI 호환 Judge를 지정할 수 있다.
`EVAL_API_KEY`가 없으면 로컬 기본값 `ollama`를 사용한다. 로컬 agent/Judge는 temperature 0, maxTokens 1536, API 재시도 1회로 고정한다.
라우터가 모델을 고정하는 경우 요청한 모델명과 실제 모델이 다를 수 있으므로 라우터 설정도 함께 기록한다.

에이전트와 같은 모델/엔드포인트로 채점하면 자기 선호 편향이 생긴다. 이 결과는 회귀 탐색용이며 독립적인 품질 검증으로 해석하지 않는다.
`conditions.json`에 실행 모델, 로컬 여부, 동일 엔드포인트 여부, 반복 횟수와 공통 실행 제한 적용 여부를 기록한다.
1회 실행은 전체 시나리오 탐색이다. 안정성 비교에는 기본 3회 이상 반복과 독립 Judge 또는 사람 채점을 추가한다.

## 대화·실제 관측값 평가

```bash
OLLAMA_ROUTER_SMOKE_URL=http://<router-address>:8081 \
rtk proxy ./gradlew evalRun --tests '*ConversationBehaviorAuditTest' --tests '*HardwareConversationLiveSmokeTest' --console=plain
```

`ConversationBehaviorAuditTest`: 실제 대화 에이전트와 모델, 고정 관측 mock, 명령 실행 mock. 개념 설명·복수 항목·부분 실패·조회 실패·재조회·전체 상태·명령 승인·대상 모호성 등을 검증한다.
`HardwareConversationLiveSmokeTest`: 실제 모델과 Prometheus를 이용하는 읽기 전용 검사. 명령 실행과 Discord 발송은 하지 않는다.
테스트가 통과해도 모든 문장의 의미까지 정확하다는 보장은 없다. 수치/단위·근거 없는 원인 단정은 별도 표본 검토가 필요하다.

## 실행

```bash
cd ~/deploy/monitoring-agent

# 전체 실행 (기본: gemini-2.5-flash, 3회 반복)
SPRING_AI_GOOGLE_GENAI_API_KEY=... ./gradlew evalRun

# 옵션
EVAL_MODEL=gemini-2.5-pro        # 에이전트 모델 (기본 gemini-2.5-flash)
EVAL_ARMS=v1,v4                 # 비교할 프롬프트 버전
EVAL_JUDGE_MODEL=gemini-2.5-pro  # Judge 모델 (기본 gemini-2.5-pro, 에이전트와 분리)
EVAL_REPEATS=3                 # arm당 반복 횟수
EVAL_SLEEP_MS=2000             # 호출 간 대기 (rate limit 대응)
EVAL_ONLY=cpu_sustained_high   # 단일 시나리오만 (디버깅)
EVAL_HUMAN_SAMPLE=15           # 사람 채점 표본 크기
```

Gemini 경로는 API 키 미설정 시 자동 skip. 로컬 경로는 `EVAL_BASE_URL`로 명시 실행한다. 기본 `./gradlew test`에서는 `@Tag("eval")` 제외 — CI 비용 0.

## 출력 (`build/eval/run-<timestamp>/`)

- `results.jsonl` — 실행당 1줄 (점수, 도구 호출 수, 지연, 결론, 추론 로그). 실행 중 즉시 flush — 중단돼도 부분 결과 보존
- `summary.md` — arm 비교표 (차원별 mean/p50/p95, pass rate, parse fail, 평균 도구 호출/지연) + 시나리오별 v1/v2 Δ
- `human-grading.md` — **blind 사람 채점 시트** (arm 라벨 숨김, 고정 seed 표본)
- `human-grading-key.csv` — 채점 후 대조용 키

## 사람 채점 절차 (Judge 순환논증 방어)

Judge를 직접 만들었으므로 Judge 점수만으로 개선을 주장하면 순환논증.
표본 10~20건을 직접 채점해 Judge와의 방향 일치율을 확인한다.

1. `human-grading.md` 열고 arm 모른 채 4개 차원 0~10 채점
2. `human-grading-key.csv`와 대조해 run별 arm 확인
3. 사람 점수와 Judge 점수의 방향 일치(v1<v2 여부) 비율 기록
4. 포트폴리오에 "사람 채점 N건 중 M건 방향 일치" 형태로 병기

## 포트폴리오 수치 갱신 시 명시할 것

- 모델명 + 시나리오 수 + 반복 횟수 (예: "gemini-2.5-flash, 38 시나리오 × 3회")
- Judge temperature 0 고정
- 관측 데이터 mock 고정 (재현 가능) — 실서버 부하 아님
- 사람 채점 표본과 일치율
- **나온 숫자를 그대로 싣는다** — 나쁘게 나와도. 측정 조건이 명시된 낮은 숫자가 조건 없는 100%보다 강하다.
