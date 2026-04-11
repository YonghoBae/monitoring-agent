package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.ChatClientRequest;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.client.advisor.api.CallAdvisor;
import org.springframework.ai.chat.client.advisor.api.CallAdvisorChain;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.core.Ordered;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

/**
 * ReAct 에이전트 결론을 자기검증하는 Advisor.
 *
 * ReflectionAgent를 별도 서비스로 두고 ReActAgent에서 수동 호출하던 방식을
 * Spring AI Advisor 패턴으로 대체한다.
 *
 * 동작:
 *   1. chain.nextCall() 로 ReAct 결론을 얻는다.
 *   2. Gemini를 호출해 결론이 SUFFICIENT / INSUFFICIENT 인지 판정한다.
 *   3. INSUFFICIENT 이면 피드백을 붙여 같은 chain으로 재분석을 요청한다.
 *
 * ReActAgent는 .advisors(spec -> spec.param(...).advisors(this)) 로 등록하고,
 * reflectionResultHolder(AtomicReference)로 결과를 전달받는다.
 */
public class ReflectionAdvisor implements CallAdvisor {

    private static final Logger log = LoggerFactory.getLogger(ReflectionAdvisor.class);

    static final String CTX_ALERT = "alert";
    static final String CTX_AGENT_TOOLS = "agentTools";
    static final String CTX_REFLECTION_RESULT = "reflectionResultHolder";
    private static final String CTX_RETRY_COUNT = "reflectionRetryCount";
    private static final int MAX_RETRIES = 1;

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
        return Ordered.LOWEST_PRECEDENCE;
    }

    @Override
    public ChatClientResponse adviseCall(ChatClientRequest request, CallAdvisorChain chain) {
        ChatClientResponse initialResponse = chain.nextCall(request);

        AlertEvent alert = (AlertEvent) request.context().get(CTX_ALERT);
        if (alert == null) {
            // ConversationAgent 등 alert 컨텍스트가 없는 경우 pass-through
            return initialResponse;
        }

        // 재시도 횟수 확인 — 무한 재귀 방지
        Integer retryCount = (Integer) request.context().get(CTX_RETRY_COUNT);
        if (retryCount != null && retryCount >= MAX_RETRIES) {
            log.info("[ReflectionAdvisor] 최대 재시도 횟수 도달 — alertId={}", alert.getId());
            return initialResponse;
        }

        AgentTools agentTools = (AgentTools) request.context().get(CTX_AGENT_TOOLS);
        @SuppressWarnings("unchecked")
        AtomicReference<String> resultHolder =
                (AtomicReference<String>) request.context().get(CTX_REFLECTION_RESULT);

        String conclusion = initialResponse.chatResponse().getResult().getOutput().getText();
        String reasoningChain = agentTools != null ? agentTools.getReasoningLog() : "";

        log.info("[ReflectionAdvisor] 자기검증 시작 — alertId={}", alert.getId());
        String reflectionResult = evaluate(alert, conclusion, reasoningChain);

        if (resultHolder != null) {
            resultHolder.set(reflectionResult);
        }

        if (reflectionResult != null && reflectionResult.startsWith("INSUFFICIENT")) {
            log.info("[ReflectionAdvisor] 재분석 트리거 — alertId={}", alert.getId());

            // 이전 도구 호출 결과를 포함하여 중복 호출 방지
            String retryAddition = "\n\n[이전 분석 검토 결과]\n" + reflectionResult
                    + "\n\n[이전 분석에서 수집한 데이터]\n" + (reasoningChain.isBlank() ? "없음" : reasoningChain)
                    + "\n\n위 피드백을 반영하고, 이미 수집한 데이터는 재조회하지 말고 추가 필요한 데이터만 수집해서 다시 분석해줘.";

            List<Message> retryMessages = request.prompt().getInstructions().stream()
                    .map(msg -> msg instanceof UserMessage
                            ? UserMessage.builder().text(msg.getText() + retryAddition).build()
                            : msg)
                    .collect(Collectors.toList());

            Prompt retryPrompt = new Prompt(retryMessages, request.prompt().getOptions());
            ChatClientRequest retryRequest = request.mutate()
                    .prompt(retryPrompt)
                    .context(Map.of(
                            CTX_ALERT, alert,
                            CTX_AGENT_TOOLS, agentTools,
                            CTX_REFLECTION_RESULT, resultHolder,
                            CTX_RETRY_COUNT, (retryCount != null ? retryCount : 0) + 1
                    ))
                    .build();
            return chain.nextCall(retryRequest);
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
