package io.ohgnoy.monitoring.application.agent; // 패키지 정의

import io.ohgnoy.monitoring.application.agent.tools.*; // 도구 관련 클래스 임포트
import io.ohgnoy.monitoring.infrastructure.discord.ConversationSession; // 디스코드 세션 정보 클래스 임포트
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient; // Spring AI의 핵심 채팅 클라이언트
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor; // 대화 기록(Memory) 관리 어드바이저
import org.springframework.beans.factory.ObjectProvider; // 빈(Bean)을 유연하게 주입받기 위한 프로바이더
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import java.time.Duration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty; // 특정 설정값 존재 여부에 따른 활성화 설정
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service; // 스프링 서비스 빈 등록

/**
 * Discord 대화형 에이전트.
 * 운영자가 Discord에서 자유롭게 질문하거나 명령을 지시할 수 있도록 대화 히스토리를 유지한다.
 * ReActAgent와 달리 MessageChatMemoryAdvisor로 대화 컨텍스트를 유지하며,
 * execute_command 도구를 통해 명령 실행을 제안할 수 있다.
 */
@Service // 이 클래스를 스프링 서비스 빈으로 등록
@ConditionalOnProperty(name = "discord.bot.token") // 'discord.bot.token' 설정이 있어야만 이 빈을 생성함
public class ConversationAgent {

    private static final Logger log = LoggerFactory.getLogger(ConversationAgent.class); // 로그 기록을 위한 로거

    @Nullable
    private final ChatClient chatClient; // LLM과 통신하는 클라이언트 (API 키가 없으면 null일 수 있음)
    private final AgentToolsFactory agentToolsFactory; // 공통 도구(메트릭 조회 등) 생성 팩토리
    private final ConversationToolsFactory conversationToolsFactory; // 대화 맥락 전용 도구 생성 팩토리
    private final WebSearchTool webSearchTool; // 웹 검색 도구

    @Value("${agent.max-tool-calls:12}") private int maxToolCalls = 12;
    @Value("${agent.timeout-seconds:90}") private int timeoutSeconds = 90;
    @Value("${agent.discovery-tools-enabled:false}") private boolean discoveryToolsEnabled;
    private java.time.Clock observationClock = java.time.Clock.systemUTC();

    // 생성자를 통한 의존성 주입 (Constructor Injection)
    public ConversationAgent(@Qualifier("agentChatClient") ObjectProvider<ChatClient> chatClientProvider,
                             AgentToolsFactory agentToolsFactory,
                             ConversationToolsFactory conversationToolsFactory,
                             WebSearchTool webSearchTool) {
        // ChatClient가 빈으로 등록되어 있지 않아도 에러를 내지 않고 null을 반환하도록 ObjectProvider 사용
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
        // ChatClient(Gemini 등)가 설정되지 않은 경우 예외 처리
        if (chatClient == null) {
            return "에이전트 비활성화 상태입니다. (Gemini API 키 미설정)";
        }

        // 요청 정보 로그 출력 (채널 ID, 알림 ID, 메시지 내용)
        log.info("[ConversationAgent] 대화 처리: channelId={}, alertId={}, message={}",
                session.channelId(), session.alertId(), userMessage);

        // 대화 기록(Memory)을 관리하는 Advisor 생성
        // session.chatMemory()를 통해 해당 채널의 이전 대화 내용을 불러옴
        MessageChatMemoryAdvisor memoryAdvisor = MessageChatMemoryAdvisor
                .builder(session.chatMemory())
                .conversationId(session.channelId()) // 채널별로 대화 구분
                .order(0) // 실행 순서 지정 (가장 먼저 실행되어야 도구 호출 내역까지 메모리에 기록됨)
                .build();

        // 현재 세션에 맞는 도구들 생성
        AgentTools agentTools = agentToolsFactory.createAgentTools();
        ConversationTools convTools = conversationToolsFactory
                .create(session.channelId(), session.alertId());
        Object[] toolObjects = discoveryToolsEnabled
                ? new Object[]{agentTools, convTools, webSearchTool, agentToolsFactory.createDiscoveryTools()}
                : new Object[]{agentTools, convTools, webSearchTool};

        AgentExecution execution = new AgentExecution(maxToolCalls, Duration.ofSeconds(timeoutSeconds), java.time.Clock.systemUTC(), observationClock);
        try {
            // Spring AI Fluent API를 사용하여 LLM 요청 구성 및 호출
            String response = execution.call(() -> chatClient.prompt()
                    .advisors(memoryAdvisor) // 대화 기록 적용
                    .system(buildSystemPrompt(session)) // 시스템 프롬프트(페르소나) 설정
                    .user(userMessage) // 사용자 질문 설정
                    .toolCallbacks(execution.callbacks(toolObjects)) // 사용 가능한 도구들 등록 (Function Calling)
                    .call() // LLM 호출
                    .content()); // 응답 텍스트 추출

            // 도구 호출 결과 로그 기록
            log.info("[ConversationAgent] 응답 완료: channelId={}, toolCalls={}",
                    session.channelId(), execution.callCount());

            // 도구가 실제로 사용되었다면 추론 로그(Reasoning Log) 출력
            if (execution.callCount() > 0) {
                log.debug("[ConversationAgent] 도구 호출 내역:\n{}", execution.summary());
            }
            return execution.finishConversation(response);

        } catch (Exception e) {
            // 에러 발생 시 로그를 남기고 사용자에게 에러 메시지 반환
            log.error("[ConversationAgent] 처리 실패: channelId={}: {}", session.channelId(), e.getMessage());
            return execution.finishConversation(null);
        }
    }

    /**
     * AI의 페르소나와 행동 지침을 정의하는 시스템 프롬프트를 생성한다.
     */
    private String buildSystemPrompt(ConversationSession session) {
        return AgentPrompts.common() + "\n" + AgentPrompts.load("conversation-system.txt")
                + (session.alertId() == null ? "\n[자유 대화 모드]" : "\n[현재 알람 ID: " + session.alertId() + "]");
    }
}
