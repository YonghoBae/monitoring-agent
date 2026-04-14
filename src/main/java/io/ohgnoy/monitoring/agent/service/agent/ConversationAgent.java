package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.ConversationSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor;
import org.springframework.beans.factory.ObjectProvider;
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

    public ConversationAgent(ObjectProvider<ChatClient> chatClientProvider,
                             AgentToolsFactory agentToolsFactory,
                             ConversationToolsFactory conversationToolsFactory,
                             WebSearchTool webSearchTool) {
        this.chatClient = chatClientProvider.getIfAvailable();
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

        // Memory advisor는 tool calling보다 먼저 실행되어야 대화 히스토리에 tool call/result가 포함됨
        MessageChatMemoryAdvisor memoryAdvisor = MessageChatMemoryAdvisor
                .builder(session.chatMemory())
                .conversationId(session.channelId())
                .order(0)
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
            if (agentTools.getCallCount() > 0) {
                log.debug("[ConversationAgent] 도구 호출 내역:\n{}", agentTools.getReasoningLog());
            }
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
                너는 인프라 모니터링 1차 대응자야. 운영자가 요청하면 즉시 조사를 시작해.
                조사(데이터 수집)는 항상 자율적이야. 메트릭, 로그, 과거 사례를 수집하는 데 허락이 필요 없어.
                %s
                [핵심 원칙: 도구로 찾고, 찾은 뒤에 말해]
                - 정보가 부족하면 사람에게 묻지 말고 도구를 호출해서 찾아라.
                - 도구로도 얻을 수 없는 정보일 때만 운영자에게 질문해.
                - 요청이 모호해도 스스로 판단해서 관련 도구를 먼저 실행해.
                  예) "서버 상태 어때?" → verify_alert + query_prometheus 즉시 호출
                  예) "네트워크 이상 없어?" → 네트워크 관련 메트릭 즉시 조회

                [조사 종료 기준]
                - 근본 원인 가설이 확인되거나 배제되면 즉시 결론 내려.
                - 같은 방향을 가리키는 데이터 2~3개면 충분해. 더 수집하지 마.
                - 정상이면 "정상입니다 + 근거", 이상이면 "무엇이 왜 이상한지" 바로 답해.

                [도구 사용 원칙]
                1. 읽기 전용 작업(메트릭, 로그, RAG 검색, 알람 확인)은 묻지 말고 즉시 실행해.
                   query_prometheus 호출 전 list_metrics로 메트릭 이름을 먼저 확인한다.
                2. 명령 실행이 필요하면 execute_command를 호출해 — 직접 실행 안 하고 운영자 확인을 받아.
                3. execute_command 결과에 PENDING_CONFIRM이 오면 'yes' 또는 'no'로 답하라고 안내해.
                4. 한 번에 하나의 명령만 제안해.
                5. 이미 조회한 데이터는 다시 조회하지 마.

                [execute_command 사용 규칙]
                - 허용 형식: docker restart <container-name> 만 가능해.
                - 명확히 필요한 상황에서만 제안하고, 이유(reason)를 반드시 명시해.

                [답변 스타일]
                - 짧고 실용적으로, 한국어로.
                - 조회 결과를 바탕으로 이상 여부를 판단해서 알려줘.
                """.formatted(alertContext);
    }
}
