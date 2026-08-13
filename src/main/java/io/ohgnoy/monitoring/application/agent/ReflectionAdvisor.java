package io.ohgnoy.monitoring.application.agent;

import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClientRequest;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.client.advisor.api.CallAdvisor;
import org.springframework.ai.chat.client.advisor.api.CallAdvisorChain;
import org.springframework.core.Ordered;

import java.util.concurrent.atomic.AtomicReference;

/**
 * ReAct 에이전트 결론을 자기검증하는 Advisor.
 *
 * 동작:
 *   1. chain.nextCall() 로 ReAct 결론을 얻는다.
 *   2. Gemini를 호출해 결론이 SUFFICIENT / INSUFFICIENT 인지 판정한다.
 *   3. 판정 결과를 reflectionResultHolder에 남긴다.
 *      재분석은 체인 안에서 수행하지 않는다 — DefaultAroundAdvisorChain은 advisor를
 *      소모하는 Deque라 같은 chain으로 nextCall을 다시 부르면
 *      "No CallAdvisors available to execute"로 실패한다. INSUFFICIENT 시의
 *      재분석은 홀더를 읽은 ReActAgent가 새 요청으로 수행한다.
 *
 * ReActAgent는 .advisors(spec -> spec.param(...).advisors(this)) 로 등록하고,
 * reflectionResultHolder(AtomicReference)로 결과를 전달받는다.
 */
public class ReflectionAdvisor implements CallAdvisor {

    private static final Logger log = LoggerFactory.getLogger(ReflectionAdvisor.class);

    static final String CTX_ALERT = "alert";
    static final String CTX_AGENT_TOOLS = "agentTools";
    static final String CTX_REFLECTION_RESULT = "reflectionResultHolder";

    private final ChatClient chatClient;

    public ReflectionAdvisor(ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    @Override
    public String getName() {
        return "ReflectionAdvisor";
    }

    @Override
    public int getOrder() {
        // LOWEST_PRECEDENCE는 터미널 ChatModelCallAdvisor(Integer.MAX_VALUE)와 동순위가 되어
        // 정렬 결과에 따라 이 advisor가 체인에서 실행되지 않는다. 반드시 그보다 앞서야 한다.
        return Ordered.LOWEST_PRECEDENCE - 1000;
    }

    @Override
    public ChatClientResponse adviseCall(ChatClientRequest request, CallAdvisorChain chain) {
        ChatClientResponse initialResponse = chain.nextCall(request);

        AlertEvent alert = (AlertEvent) request.context().get(CTX_ALERT);
        if (alert == null) {
            // ConversationAgent 등 alert 컨텍스트가 없는 경우 pass-through
            return initialResponse;
        }

        AgentTools agentTools = (AgentTools) request.context().get(CTX_AGENT_TOOLS);
        @SuppressWarnings("unchecked")
        AtomicReference<String> resultHolder =
                (AtomicReference<String>) request.context().get(CTX_REFLECTION_RESULT);

        // 모델이 빈 응답을 반환하면 getResult()가 null일 수 있다 — 검증 없이 통과시킨다.
        if (initialResponse.chatResponse() == null
                || initialResponse.chatResponse().getResult() == null
                || initialResponse.chatResponse().getResult().getOutput() == null) {
            log.warn("[ReflectionAdvisor] 모델 응답이 비어 있어 자기검증 건너뜀 — alertId={}", alert.getId());
            return initialResponse;
        }

        String conclusion = initialResponse.chatResponse().getResult().getOutput().getText();
        String reasoningChain = agentTools != null ? agentTools.getReasoningLog() : "";

        log.info("[ReflectionAdvisor] 자기검증 시작 — alertId={}", alert.getId());
        String reflectionResult = evaluate(alert, conclusion, reasoningChain);

        if (resultHolder != null) {
            resultHolder.set(reflectionResult);
        }

        if (reflectionResult != null && reflectionResult.startsWith("INSUFFICIENT")) {
            log.info("[ReflectionAdvisor] 근거 불충분 판정 — 재분석은 ReActAgent가 수행. alertId={}", alert.getId());
        }

        return initialResponse;
    }

    private String evaluate(AlertEvent alert, String conclusion, String reasoningChain) {
        try {
            return chatClient.prompt()
                    .user(buildReflectionPrompt(alert, conclusion, reasoningChain))
                    .call()
                    .content();
        } catch (Exception e) {
            log.warn("[ReflectionAdvisor] 검증 실패 — alertId={}: {}", alert.getId(), e.getMessage());
            return "SUFFICIENT";
        }
    }

    private String buildReflectionPrompt(AlertEvent alert, String conclusion, String reasoningChain) {
        return """
                다음은 모니터링 에이전트가 알람을 분석한 결과야. 이 분석을 비판적으로 검토해줘.

                [원본 알람]
                - 알람명: %s
                - 메시지: %s
                - 레이블: %s

                [에이전트 분석 결론]
                %s

                [사용한 도구와 관찰 결과]
                %s

                검토 기준:
                1. 근본 원인 진단이 수집된 데이터와 논리적으로 일치하는가?
                2. 보안 이상징후(외부 접근, 인증 실패, 비정상 패턴) 가능성을 확인했는가?
                3. 즉시 조치 항목이 현재 상황에서 실제로 효과가 있는가?
                4. 중요한 데이터를 수집하지 않은 채 결론을 냈는가?

                문제가 없으면 "SUFFICIENT" 한 단어만 응답해.
                개선이 필요하면 "INSUFFICIENT: [구체적 이유와 추가로 확인해야 할 항목]" 형식으로만 응답해.
                """.formatted(
                alert.getAlertName(),
                alert.getMessage(),
                alert.getLabelsJson(),
                conclusion,
                reasoningChain.isBlank() ? "도구 호출 없음" : reasoningChain
        );
    }
}
