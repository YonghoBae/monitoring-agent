# 라이브 에이전트 평가 (Live Evaluation)

프롬프트 개선(v1 → v2)의 효과를 **재현 가능한 조건**에서 측정하는 평가 하네스.

## 설계

| 요소 | 값 | 이유 |
|------|-----|------|
| 데이터셋 | `src/test/resources/eval-dataset-v2.yml` (시나리오 38종) | 시나리오별 정답 기준(must_check / forbidden_actions / minimum_scores) 포함. 적대 시나리오(STALE 알람, 검증 불가 알람, 플래핑, 동시 다운 함정) 포함 |
| 관측 데이터 | 시나리오별 고정 mock (Prometheus / Loki / RAG / 컨테이너 목록) | 실제 서버 상태에 흔들리지 않는 재현성 확보 |
| 에이전트 | 실제 LLM, 운영과 동일 경로 (ReActAgent + ReflectionAdvisor + WebSearchTool) | 측정 대상 = 모델 행동. temperature는 운영 기본값 유지 (변동성 자체가 측정 대상) |
| 프롬프트 arm | `v1` = 초기 프롬프트 (역할 정의·종료 기준 없음), `v2` = 현재 운영 프롬프트 (Tool-Over-Ask) | `src/main/resources/prompts/react-system-{v1,v2}.txt` — git 이력에서 추출 |
| Judge | 실제 LLM, **temperature 0**, 기본 **gemini-2.5-pro** (에이전트와 분리) | 채점 기준(자)은 흔들리면 안 됨. 같은 모델로 채점하면 자기 응답 선호 편향 발생 — 더 강한 별도 모델 사용 |
| 반복 | arm당 시나리오별 3회 (기본) | 에이전트 변동성 반영, p50/p95 산출 |
| 판정 | pass = 4개 차원(Factuality/Tool Use/Actionability/Safety) 모두 시나리오별 minimum_scores 이상 | 단일 점수 평균의 왜곡 방지 |

총 실행 수 (기본): 38 시나리오 × 2 arm × 3회 = **228 에이전트 실행 + 228 Judge 호출** (+ Reflection 추가 호출).

## 실행

```bash
cd ~/deploy/monitoring-agent

# 전체 실행 (기본: gemini-2.5-flash, 3회 반복)
SPRING_AI_GOOGLE_GENAI_API_KEY=... ./gradlew evalRun

# 옵션
EVAL_MODEL=gemini-2.5-pro        # 에이전트 모델 (기본 gemini-2.5-flash)
EVAL_JUDGE_MODEL=gemini-2.5-pro  # Judge 모델 (기본 gemini-2.5-pro, 에이전트와 분리)
EVAL_REPEATS=3                 # arm당 반복 횟수
EVAL_SLEEP_MS=2000             # 호출 간 대기 (rate limit 대응)
EVAL_ONLY=cpu_sustained_high   # 단일 시나리오만 (디버깅)
EVAL_HUMAN_SAMPLE=15           # 사람 채점 표본 크기
```

API 키 미설정 시 자동 skip. 기본 `./gradlew test`에서는 `@Tag("eval")` 제외 — CI 비용 0.

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
