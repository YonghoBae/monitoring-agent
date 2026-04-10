# 왜 단순 LLM 호출 대신 ReAct 에이전트인가

## "그냥 프롬프트 한 번 보내면 되지 않나?"

처음 이 프로젝트를 설계할 때 에이전트 구조는 고려하지 않았다. 알림이 오면 LLM에게 분석을 요청하고, 결과를 Discord로 전송하면 충분하다고 생각했다. 구조도 단순했다.

```
AlertEvent 생성 → ChatClient.prompt().user(alertInfo).call() → Discord 전송
```

그런데 실제로 돌려보니 LLM이 이런 답변을 계속 냈다.

> "해당 알람의 현재 상태를 확인해야 정확한 분석이 가능합니다. Prometheus에서 메트릭을 조회해주세요."

알림 내용을 그대로 요약해서 돌려주는 것과 다를 게 없었다. 운영자가 원하는 건 "지금 어떤 상태인지, 뭘 해야 하는지"인데, LLM은 그걸 모르고 있었다.

## 왜 모르는가

LLM의 학습 데이터에는 우리 서버가 없다. `ContainerDown` 알림이 왔을 때 그게 실제로 지금도 죽어있는지, 5초 전에 재시작됐는지, 어떤 컨테이너인지 — LLM은 알 방법이 없다.

인프라 알림의 특성상 "지금 이 순간"의 데이터가 핵심이다. 알림이 발생한 시점과 분석 시점 사이에도 상황이 바뀐다. 단순 호출로는 이 간극을 메울 수 없었다.

그렇다고 알림 정보와 함께 모든 메트릭을 사전에 긁어서 프롬프트에 넣는 방법도 있었다. 하지만 어떤 메트릭이 필요한지는 알림 종류에 따라 다르고, 불필요한 데이터까지 넣으면 LLM이 오히려 혼란스러워진다. 에이전트가 스스로 필요한 것만 골라 조회하는 게 맞았다.

## ReAct 패턴

ReAct(Reasoning + Acting)는 LLM이 단순히 답을 생성하는 게 아니라, 생각하고 → 행동하고 → 관찰한 결과를 다음 추론에 반영하는 루프를 반복하는 패턴이다.

```
[Thought] ContainerDown 알림인데, 지금도 죽어있는지 확인이 필요하다.
[Action]  verify_alert("nginx", {...})
[Obs]     CONFIRMED — 현재도 firing 중, activeAt: 2025-01-15T03:42:00Z

[Thought] 확인됐다. 로그에서 죽은 이유를 찾아야 한다.
[Action]  query_loki("nginx", "30")
[Obs]     OOMKilled: 메모리 제한 초과로 강제 종료

[Thought] 원인 확인됨. 결론 도출 가능.
[Answer]  근본 원인: 메모리 제한 초과로 인한 컨테이너 강제 종료...
```

루프 중간에 LLM이 관찰 결과를 받아 다음 행동을 결정하기 때문에, 사전에 어떤 데이터를 조회할지 정해두지 않아도 된다. 상황에 따라 필요한 도구만 골라 쓴다.

## Spring AI로 구현하기

Spring AI 1.1.0은 Gemini의 function calling을 추상화해준다. `@Tool` 어노테이션을 붙인 메서드를 `.tools()`에 넘기면, Gemini가 필요하다고 판단할 때 자동으로 해당 메서드를 호출하고 결과를 다음 턴에 반영하는 루프를 내부적으로 처리한다.

```java
String conclusion = chatClient.prompt()
        .system(systemPrompt)
        .user(alertDescription)
        .tools(agentTools, webSearchTool)
        .call()
        .content();
```

`.call().content()`가 반환되는 시점은 Gemini가 "더 이상 도구를 호출할 필요가 없다"고 판단해 최종 텍스트를 생성한 때다. 중간의 도구 호출 루프는 Spring AI가 처리한다.

도구는 두 클래스로 나뉘어 있다. `AgentTools`에 4개, `WebSearchTool`에 1개다.

```java
// AgentTools — 인프라 데이터 조회 (읽기전용)
@Tool(description = "Prometheus에서 해당 알람이 현재도 발생 중인지 확인한다.")
public String verify_alert(String alertName, String labelsJson) { ... }

@Tool(description = "Prometheus에서 PromQL 메트릭을 조회한다.")
public String query_prometheus(String promql, String timeRangeMinutes) { ... }

@Tool(description = "Loki에서 컨테이너 로그를 조회한다.")
public String query_loki(String containerName, String timeRangeMinutes) { ... }

@Tool(description = "과거 알람 및 해결 사례를 지식베이스에서 검색한다.")
public String search_rag(String query) { ... }

// WebSearchTool — 외부 검색 (최후의 수단)
@Tool(description = "...")
public String web_search(String query) { ... }
```

시스템 프롬프트에는 도구 호출 순서를 명시했다.

```
[도구 호출 순서]
1. search_rag — 우리 서버 과거 사례 먼저 확인
2. verify_alert — 알람이 현재도 발생 중인지 확인
3. query_prometheus / query_loki — 가설 검증에 필요한 메트릭·로그만 선택 조회
4. web_search — 1~3으로 해결 방법을 못 찾았을 때만 사용하는 최후의 수단
```

순서에 이유가 있다. RAG를 먼저 보는 건, 과거에 같은 알림이 왔을 때 어떻게 해결했는지가 가장 유용한 정보이기 때문이다. verify_alert를 그 다음에 두는 건, 알림이 이미 해소됐을 수도 있기 때문이다. 이미 사라진 알림을 Prometheus와 Loki에서 열심히 파는 건 낭비다.

## 분석 파이프라인 전체 흐름

ReAct 루프 이후에도 단계가 더 있다. 결론이 나오면 `ReflectionAgent`가 그 결론을 검증한다. "데이터 근거가 있는가", "실행 가능한 조치인가" 같은 기준으로 평가하고, 불충분하다고 판단하면 루프를 한 번 더 돌린다.

```java
// ReActAgent.runInternal() 중
String reflectionOutput = reflectionAgent.reflect(alert,
        new AgentResult(conclusion, reasoningChain, iterationCount, null, recommendation));

if (reflectionOutput != null && reflectionOutput.startsWith("INSUFFICIENT")) {
    // 피드백을 반영해 재분석
    String retriedConclusion = chatClient.prompt()
            .system(systemPrompt)
            .user(userMessage + "\n\n[이전 분석 검토 결과]\n" + reflectionOutput + "\n\n위 피드백을 반영해서 다시 분석해줘.")
            .tools(retryTools, webSearchTool)
            .call()
            .content();
}
```

그리고 최종 결론은 `AgentJudgeEvaluator`가 4개 차원으로 품질 점수를 매겨 DB에 저장한다. 이 평가 결과는 쌓이면서 분석 품질 이력이 된다.

## 한계

루프를 도는 횟수는 Gemini가 결정하기 때문에 통제하기 어렵다. 시스템 프롬프트에 종료 기준을 명시했지만, 모델이 이를 얼마나 충실히 따르는지는 실행마다 다르다.

```
[종료 기준: 이 조건을 만족하면 즉시 결론 내려]
- 근본 원인 가설이 데이터로 확인되거나 배제됐을 때
- 같은 방향을 가리키는 데이터 포인트 2~3개가 모였을 때
```

이 프롬프트가 항상 통하는 건 아니다. 가끔 필요 이상으로 도구를 호출하고, 가끔 너무 일찍 멈춘다. Reflection이 후자를 잡아주기는 하지만, 전자에 대한 hard limit은 없다. 이 문제는 프롬프트 설계 이야기인데, 그건 다음 글에서 다룬다.
