# LLM 출력 품질을 어떻게 측정할까

## "에이전트가 잘 분석하고 있는지 어떻게 알지?"

ReAct 루프가 돌아가기 시작하자 새로운 문제가 생겼다. 에이전트가 뭔가 답변을 내놓는데, 그게 "좋은" 분석인지 판단하기가 어려웠다. 짧게 끝낸 분석이 정확한 건지 아니면 조급하게 멈춘 건지, 긴 분석이 철저한 건지 아니면 장황하게 돌아간 건지.

직접 눈으로 보면서 판단할 수도 있었다. 그런데 그건 확인 가능한 샘플 몇 개에만 해당하는 이야기고, 운영 중에 쌓이는 수백 건의 분석을 매번 사람이 검토할 수는 없다. 자동으로 품질을 추적할 방법이 필요했다.

## 첫 번째 시도: Perplexity

NLP에서 언어 모델의 예측 확실성을 측정하는 지표로 Perplexity(PPL)가 쓰인다. 모델이 다음 토큰을 얼마나 확신하는지를 반영하는데, 수식으로는 이렇다.

```
PPL(W) = exp(-1/N * Σ log P(wᵢ | w₁...wᵢ₋₁))
```

모델이 각 토큰을 생성할 때의 확률 값(logprob)을 사용해 계산한다. PPL이 낮을수록 모델이 자신 있게 생성한 텍스트라는 의미다.

에이전트 답변에 PPL을 적용하면, "확신 없이 추측한 답변"과 "데이터 기반으로 확신을 가지고 생성한 답변"을 구분할 수 있을 것이라고 생각했다. Spring AI 1.1.0의 `ChatResponse` 객체에서 메타데이터를 꺼내는 방법을 찾아봤다.

막혔다.

## Gemini는 logprobs를 주지 않는다

Gemini API는 응답 토큰의 logprob를 제공하지 않는다. OpenAI API는 옵션으로 제공하지만, Gemini는 API 설계상 이 값이 없다.

Spring AI가 여러 모델을 추상화해주는 것도 문제의 일부였다. Spring AI의 `ChatResponse`는 모델 공통 인터페이스를 제공하는데, 모델별 로우레벨 응답 데이터에 접근하려면 추상화를 우회해야 한다. 그리고 Gemini는 우회해봐야 logprob 자체가 없다.

PPL은 현재 설정에서 불가능했다. 다른 방법을 찾아야 했다.

## LLM-as-a-Judge

"사람이 평가하기 어렵다면, 다른 LLM이 평가하면 어떨까"라는 아이디어가 LLM-as-a-Judge다. Zheng et al. (2023)의 "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" 논문에서 이 방식의 유효성을 실증적으로 검토했다.

핵심 아이디어는 단순하다. 평가할 텍스트와 채점 기준을 Judge LLM에 주고, 점수와 이유를 받는다. 정량 지표처럼 자동화가 가능하면서, 사람이 정의한 품질 기준을 반영할 수 있다.

여기서 G-Eval 방법(Liu et al., 2023, "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment")을 참고했다. G-Eval은 평가 전에 Chain-of-Thought로 평가 기준을 내부적으로 해석한 뒤 점수를 매기는 방식인데, 루브릭을 명확히 정의할수록 일관성이 높아진다.

## 4개 차원 설계

인프라 알림 분석이라는 특수한 맥락에 맞는 차원을 직접 설계했다. 일반적인 NLG 평가 차원이 아니라, "이 에이전트가 운영자에게 실제로 도움이 되는 분석을 했는가"를 기준으로 잡았다.

**Factuality** — 수집한 데이터로 결론이 뒷받침되는가

에이전트가 Prometheus에서 메트릭을 가져왔다면, 결론이 그 메트릭을 근거로 하는지 확인한다. 데이터 없이 "아마도 ~일 것입니다"라고 추측만 하면 낮은 점수를 받는다.

**Tool Use** — 필요한 도구를 적절히 사용했는가

과소(중요한 도구 누락)와 과다(같은 메트릭 반복 조회) 모두 감점 요인이다. ContainerDown 알림에서 로그를 확인하지 않았다면 Tool Use 점수가 낮아진다.

**Actionability** — 권고 조치가 구체적이고 실행 가능한가

"더 조사가 필요합니다"나 "모니터링을 강화하세요"는 운영자에게 아무 도움이 안 된다. "docker restart nginx 후 메모리 사용량 추이 확인"처럼 즉시 실행 가능한 항목이 있어야 한다.

**Hallucination Risk** — 확인되지 않은 주장이 없는가

정상 수치를 이상으로 판단하거나, 데이터에 없는 원인을 단정하는 경우를 잡아내는 차원이다. 오탐(false positive)은 운영자가 불필요한 대응을 하게 만들기 때문에 별도 차원으로 분리했다.

Judge LLM이 이 4개 차원을 채점한다. 시스템 프롬프트에 출력 형식을 고정했다.

```
Factuality: X/10
[이유 한 문장]

Tool Use: X/10
[이유 한 문장]

Actionability: X/10
[이유 한 문장]

Hallucination Risk: X/10
[이유 한 문장]

절대로 위 형식 외의 내용을 추가하지 마.
```

형식을 엄격하게 고정한 건 파싱 때문이다. 형식이 조금이라도 달라지면 정규식 파싱이 실패하고, 그 경우 5점(중간값)으로 처리한다.

```java
// AgentJudgeEvaluator
private static final Pattern SCORE_PATTERN =
        Pattern.compile("(?i)(Factuality|Tool Use|Actionability|Hallucination Risk)\\s*:\\s*(\\d+)\\s*/\\s*10");
```

점수는 `AgentEvaluation` 엔티티로 DB에 저장된다.

```java
// AgentEvaluation 생성자
this.overallScore = (factualityScore + toolUseScore + actionabilityScore + hallucinationRiskScore) / 4.0;
```

4개 차원의 단순 평균이 overall score가 된다. `isHighQuality()` 헬퍼가 7.0 이상이면 true를 반환한다. 이 이력이 쌓이면 에이전트 품질 추이를 추적할 수 있다.

## 고정 시나리오로 테스트

품질 측정 자체를 검증하기 위해 고정 시나리오(`eval-scenarios.json`)를 만들었다. 5개 알림 유형에 대해 "이 알림에선 어떤 도구가 사용돼야 하는가", "최대 도구 호출 횟수는 몇 번인가", "최소 Judge 점수는 몇 점이어야 하는가"를 사전 정의했다.

```json
{
  "id": "container-oom-killed",
  "expectedCriteria": {
    "shouldUsePrometheus": true,
    "shouldRecommendRestartApproval": true,
    "shouldSuggestMemoryInvestigation": true,
    "maxToolCalls": 5,
    "minJudgeScore": 6
  }
}
```

프롬프트를 바꾸거나 도구 우선순위를 조정할 때, 이 시나리오로 회귀 테스트를 돌린다. "이전보다 좋아졌나"를 점수로 비교할 수 있다.

## 한계

Judge LLM도 편향이 있다. 같은 답변을 주더라도 매번 점수가 완전히 같지는 않다. 신뢰 있는 수치를 얻으려면 같은 알림에 대해 3~5회 실행해서 평균을 내야 한다. 운영 환경에서 매 알림마다 5번씩 Judge를 돌리는 건 비용과 지연 면에서 현실적이지 않다.

그래서 현재 구조에서 Judge 평가는 분석 품질의 절대적인 지표가 아니라 이력 관리 용도로 쓴다. 점수가 갑자기 낮아지는 패턴이 보이면 프롬프트나 도구 설계를 다시 검토하는 신호로 활용한다. Judge가 평가에 실패하더라도 알림 처리 자체는 막지 않도록 에러 처리를 분리해뒀다.

```java
// ReActAgent.run()
public AgentResult run(AlertEvent alert, ActionRecommendation recommendation) {
    AgentResult result = runInternal(alert, recommendation, buildAlertDescription(alert, recommendation));
    judgeEvaluator.evaluate(alert, result); // 실패해도 result 반환엔 영향 없음
    return result;
}
```

Judge 평가 실패가 운영에 영향을 주는 건 과도한 결합이라고 판단했다.
