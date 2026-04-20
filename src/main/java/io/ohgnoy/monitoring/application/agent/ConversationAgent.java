package io.ohgnoy.monitoring.application.agent; // 패키지 정의

import io.ohgnoy.monitoring.application.agent.tools.*; // 도구 관련 클래스 임포트
import io.ohgnoy.monitoring.infrastructure.discord.ConversationSession; // 디스코드 세션 정보 클래스 임포트
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient; // Spring AI의 핵심 채팅 클라이언트
import org.springframework.ai.chat.client.advisor.MessageChatMemoryAdvisor; // 대화 기록(Memory) 관리 어드바이저
import org.springframework.beans.factory.ObjectProvider; // 빈(Bean)을 유연하게 주입받기 위한 프로바이더
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

    // 생성자를 통한 의존성 주입 (Constructor Injection)
    public ConversationAgent(ObjectProvider<ChatClient> chatClientProvider,
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

        try {
            // Spring AI Fluent API를 사용하여 LLM 요청 구성 및 호출
            String response = chatClient.prompt()
                    .advisors(memoryAdvisor) // 대화 기록 적용
                    .system(buildSystemPrompt(session)) // 시스템 프롬프트(페르소나) 설정
                    .user(userMessage) // 사용자 질문 설정
                    .tools(agentTools, convTools, webSearchTool) // 사용 가능한 도구들 등록 (Function Calling)
                    .call() // LLM 호출
                    .content(); // 응답 텍스트 추출

            // 도구 호출 결과 로그 기록
            log.info("[ConversationAgent] 응답 완료: channelId={}, toolCalls={}",
                    session.channelId(), agentTools.getCallCount());

            // 도구가 실제로 사용되었다면 추론 로그(Reasoning Log) 출력
            if (agentTools.getCallCount() > 0) {
                log.debug("[ConversationAgent] 도구 호출 내역:\n{}", agentTools.getReasoningLog());
            }
            return response;

        } catch (Exception e) {
            // 에러 발생 시 로그를 남기고 사용자에게 에러 메시지 반환
            log.error("[ConversationAgent] 처리 실패: channelId={}: {}", session.channelId(), e.getMessage());
            return "응답 생성 중 오류가 발생했습니다: " + e.getMessage();
        }
    }

    /**
     * AI의 페르소나와 행동 지침을 정의하는 시스템 프롬프트를 생성한다.
     */
    private String buildSystemPrompt(ConversationSession session) {
        // 현재 세션에 연결된 특정 알림(Alert)이 있는지 여부에 따라 컨텍스트 정보 생성
        String alertContext = session.alertId() != null
                ? "\n[현재 알림 ID: " + session.alertId() + "]\n이 알림과 관련된 대화를 이어가고 있어.\n"
                : "\n[자유 대화 모드]\n특정 알림 없이 인프라 상태를 조회하거나 문의할 수 있어.\n";

        // LLM에게 부여할 구체적인 역할과 규칙 정의 (ReAct 패턴 및 제약 사항)
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