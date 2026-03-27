package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.ConversationSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;

/**
 * Discord 대화형 에이전트.
 * 운영자가 Discord에서 자유롭게 질문하거나 명령을 지시할 수 있도록 대화 히스토리를 유지한다.
 * ReActAgent와 달리 MessageChatMemoryAdvisor로 대화 컨텍스트를 유지하며,
 * execute_command 도구를 통해 명령 실행을 제안할 수 있다.
 */
@Service
@ConditionalOnProperty(name = "discord.bot.token")
public class ConversationAgent {

    private static final Logger log = LoggerFactory.getLogger(ConversationAgent.class);

    @Nullable
    private final ChatClient chatClient;
    private final AgentToolsFactory agentToolsFactory;
    private final ConversationToolsFactory conversationToolsFactory;
    private final WebSearchTool webSearchTool;

    public ConversationAgent(@Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel,
                             AgentToolsFactory agentToolsFactory,
                             ConversationToolsFactory conversationToolsFactory,
                             WebSearchTool webSearchTool) {
        this.chatClient = chatModel != null ? ChatClient.builder(chatModel).build() : null;
        this.agentToolsFactory = agentToolsFactory;
        this.conversationToolsFactory = conversationToolsFactory;
        this.webSearchTool = webSearchTool;
    }

    /**
     * 운영자 메시지를 처리하고 응답을 반환한다.
     * MessageChatMemoryAdvisor가 대화 히스토리를 자동으로 관리한다.
     */
    public String chat(ConversationSession session, String userMessage) {
        if (chatClient == null) {
            return "에이전트 비활성화 상태입니다. (Gemini API 키 미설정)";
        }

        log.info("[ConversationAgent] 대화 처리: channelId={}, alertId={}, message={}",
                session.channelId(), session.alertId(), userMessage);

        MessageChatMemoryAdvisor memoryAdvisor = MessageChatMemoryAdvisor
                .builder(session.chatMemory())
                .conversationId(session.channelId())
                .build();

        AgentTools agentTools = agentToolsFactory.createAgentTools();
        ConversationTools convTools = conversationToolsFactory
                .create(session.channelId(), session.alertId());

        try {
            String response = chatClient.prompt()
                    .advisors(memoryAdvisor)
                    .system(buildSystemPrompt(session))
                    .user(userMessage)
                    .tools(agentTools, convTools, webSearchTool)
                    .call()
                    .content();

            log.info("[ConversationAgent] 응답 완료: channelId={}, toolCalls={}",
                    session.channelId(), agentTools.getCallCount());
            return response;

        } catch (Exception e) {
            log.error("[ConversationAgent] 처리 실패: channelId={}: {}", session.channelId(), e.getMessage());
            return "응답 생성 중 오류가 발생했습니다: " + e.getMessage();
        }
    }

    private String buildSystemPrompt(ConversationSession session) {
        String alertContext = session.alertId() != null
                ? "\n[현재 알림 ID: " + session.alertId() + "]\n이 알림과 관련된 대화를 이어가고 있어.\n"
                : "\n[자유 대화 모드]\n특정 알림 없이 인프라 상태를 조회하거나 문의할 수 있어.\n";

        return """
                너는 인프라/서비스 모니터링 어시스턴트야. 운영자와 실시간으로 대화하며 서버 문제를 같이 해결해.
                %s
                [도구 사용 원칙]
                1. 로그, 메트릭, 과거 사례 조회는 바로 실행하고 결과를 간결하게 설명해.
                2. 명령 실행이 필요하면 execute_command를 호출해 — 직접 실행하지 않고 운영자 확인을 받아.
                3. execute_command 결과에 PENDING_CONFIRM이 오면, 운영자에게 'yes' 또는 'no'로 답하라고 안내해.
                4. 한 번에 하나의 명령만 제안해. 불필요한 명령 제안은 금지.
                5. 이미 조회한 데이터는 다시 조회하지 마.

                [execute_command 사용 규칙]
                - 허용 형식: docker restart <container-name> 만 가능해.
                - 명확히 필요한 상황에서만 제안해.
                - 제안 시 이유(reason)를 반드시 명시해.

                [답변 스타일]
                - 짧고 실용적으로, 한국어로 답해.
                - 데이터 없이 추측하지 마. 먼저 조회해.
                - 근거가 불충분하면 추가 정보를 수집하거나 질문해.
                """.formatted(alertContext);
    }
}
