package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;

/**
 * ReAct 에이전트의 결론을 자기검증(Reflection)하는 에이전트.
 *
 * 응답 형식:
 * - "SUFFICIENT" → 결론이 충분함, 통과
 * - "INSUFFICIENT: <이유와 추가 확인 필요 항목>" → 재분석 필요
 */
@Service
public class ReflectionAgent {

    private static final Logger log = LoggerFactory.getLogger(ReflectionAgent.class);

    private final ChatClient chatClient;

    public ReflectionAgent(@Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel) {
        this.chatClient = chatModel != null ? ChatClient.builder(chatModel).build() : null;
    }

    /**
     * ReAct 결론을 검증한다.
     *
     * @return "SUFFICIENT" 또는 "INSUFFICIENT: <이유>"
     */
    public String reflect(AlertEvent alert, AgentResult initialResult) {
        if (chatClient == null || initialResult.conclusion() == null) {
            return "SUFFICIENT";
        }

        log.info("[ReflectionAgent] 자기검증 시작 — alertId={}", alert.getId());

        String prompt = buildReflectionPrompt(alert, initialResult);

        try {
            String result = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            log.info("[ReflectionAgent] 검증 결과 — alertId={}: {}",
                    alert.getId(), result.startsWith("SUFFICIENT") ? "SUFFICIENT" : "INSUFFICIENT");
            return result;
        } catch (Exception e) {
            log.warn("[ReflectionAgent] 검증 실패 — alertId={}: {}", alert.getId(), e.getMessage());
            return "SUFFICIENT"; // 검증 실패 시 원본 결론 유지
        }
    }

    private String buildReflectionPrompt(AlertEvent alert, AgentResult result) {
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
                result.conclusion(),
                result.reasoningChain().isBlank() ? "도구 호출 없음" : result.reasoningChain()
        );
    }
}
