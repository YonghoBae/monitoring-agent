package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.service.ActionRecommendation;
import io.ohgnoy.monitoring.agent.service.evaluation.AgentJudgeEvaluator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;


/**
 * ReAct 패턴 기반 에이전트.
 * Spring AI ChatClient의 Function Calling 기능을 이용해
 * Gemini가 필요한 도구를 스스로 선택하며 반복 추론한다.
 *
 * 도구 우선순위 (시스템 프롬프트로 명시):
 *   1. search_rag — 우리 서버 과거 사례 우선
 *   2. Gemini 자체 지식
 *   3. web_search — 1,2로 불충분할 때 최후의 수단
 */
@Service
public class ReActAgent {

    private static final Logger log = LoggerFactory.getLogger(ReActAgent.class);

    private final ChatClient chatClient;
    private final AgentToolsFactory agentToolsFactory;
    private final WebSearchTool webSearchTool;
    private final ReflectionAgent reflectionAgent;
    private final AgentJudgeEvaluator judgeEvaluator;

    public ReActAgent(@Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel,
                      AgentToolsFactory agentToolsFactory,
                      WebSearchTool webSearchTool,
                      ReflectionAgent reflectionAgent,
                      AgentJudgeEvaluator judgeEvaluator) {
        this.chatClient = chatModel != null ? ChatClient.builder(chatModel).build() : null;
        this.agentToolsFactory = agentToolsFactory;
        this.webSearchTool = webSearchTool;
        this.reflectionAgent = reflectionAgent;
        this.judgeEvaluator = judgeEvaluator;
    }

    /**
     * 알람 분석 실행. Spring AI가 내부적으로 Gemini tool call 루프를 처리한다.
     *
     * @param alert          분석 대상 알람
     * @param recommendation Playbook 기반 권장 조치 (safety ceiling)
     * @return 추론 결과 (결론, 추론 로그, 호출 횟수)
     */
    public AgentResult run(AlertEvent alert, ActionRecommendation recommendation) {
        AgentResult result = runInternal(alert, recommendation, buildAlertDescription(alert, recommendation));
        judgeEvaluator.evaluate(alert, result);
        return result;
    }

    /**
     * OrchestratorAgent에서 그룹 컨텍스트를 추가해 실행할 때 사용.
     */
    public AgentResult runWithContext(AlertEvent alert, ActionRecommendation recommendation, String additionalContext) {
        return runInternal(alert, recommendation, buildAlertDescription(alert, recommendation) + additionalContext);
    }

    /**
     * ReAct 루프 실행 + Reflection 자기검증 (1회 한도).
     */
    private AgentResult runInternal(AlertEvent alert, ActionRecommendation recommendation, String userMessage) {
        if (chatClient == null) {
            return new AgentResult(
                    "에이전트 분석 기능이 비활성화되어 있습니다. (Gemini API 키 미설정)",
                    "", 0, null, recommendation
            );
        }

        log.info("[ReActAgent] 분석 시작 — alertId={}, alertName={}", alert.getId(), alert.getAlertName());

        AgentTools agentTools = agentToolsFactory.createAgentTools();
        String systemPrompt = buildSystemPrompt();

        try {
            String conclusion = chatClient.prompt()
                    .system(systemPrompt)
                    .user(userMessage)
                    .tools(agentTools, webSearchTool)
                    .call()
                    .content();

            String reasoningChain = agentTools.getReasoningLog();
            int iterationCount = agentTools.getCallCount();
            log.info("[ReActAgent] 1차 분석 완료 — alertId={}, toolCalls={}", alert.getId(), iterationCount);

            // Reflection: 결론 자기검증
            String reflectionOutput = reflectionAgent.reflect(alert,
                    new AgentResult(conclusion, reasoningChain, iterationCount, null, recommendation));

            if (reflectionOutput != null && reflectionOutput.startsWith("INSUFFICIENT")) {
                log.info("[ReActAgent] Reflection 재분석 트리거 — alertId={}", alert.getId());

                AgentTools retryTools = agentToolsFactory.createAgentTools();
                String retriedConclusion = chatClient.prompt()
                        .system(systemPrompt)
                        .user(userMessage + "\n\n[이전 분석 검토 결과]\n" + reflectionOutput + "\n\n위 피드백을 반영해서 다시 분석해줘.")
                        .tools(retryTools, webSearchTool)
                        .call()
                        .content();

                int totalCalls = iterationCount + retryTools.getCallCount();
                log.info("[ReActAgent] 재분석 완료 — alertId={}, totalToolCalls={}", alert.getId(), totalCalls);
                return new AgentResult(retriedConclusion,
                        reasoningChain + "\n[Reflection 재분석]\n" + retryTools.getReasoningLog(),
                        totalCalls, reflectionOutput, recommendation);
            }

            return new AgentResult(conclusion, reasoningChain, iterationCount, reflectionOutput, recommendation);

        } catch (Exception e) {
            log.error("[ReActAgent] 분석 실패 — alertId={}: {}", alert.getId(), e.getMessage());
            return new AgentResult(
                    "AI 분석 실패: " + e.getMessage(),
                    agentTools.getReasoningLog(), agentTools.getCallCount(), null, recommendation
            );
        }
    }

    private String buildSystemPrompt() {
        return """
                너는 인프라 모니터링 1차 대응자야. 발생한 알람을 자율적으로 분석하고 근본 원인과 해결 방법을 찾아.
                알람 정보(레벨, 이름, 레이블, 요약)는 이미 제공되어 있어. 조사를 시작하는 데 추가 허락이 필요 없어.

                [도구 호출 순서]
                1. search_rag — 우리 서버 과거 사례 먼저 확인. 유사 사례 있으면 현재 상황과 차이점 분석.
                2. verify_alert — 알람이 현재도 발생 중인지 확인.
                3. query_prometheus / query_loki — 가설 검증에 필요한 메트릭·로그만 선택 조회.
                4. web_search — 1~3으로 해결 방법을 못 찾았을 때만 사용하는 최후의 수단.

                [종료 기준: 이 조건을 만족하면 즉시 결론 내려]
                - 근본 원인 가설이 데이터로 확인되거나 배제됐을 때
                - 같은 방향을 가리키는 데이터 포인트 2~3개가 모였을 때
                이 기준을 넘어서 계속 수집하지 마. 데이터가 많다고 결론이 좋아지지 않아.

                [도구 호출 원칙]
                - 각 도구 결과를 받은 후 현재 가설을 확인/반박/불명확 중 하나로 평가하고 다음 행동을 결정해.
                - 로그에서 보안 이상징후(외부 IP, 인증 실패 반복, 비정상 패턴)를 확인해.
                - 과거 사례가 있어도 현재 컨텍스트와 다른 점이 있는지 반드시 검토해.

                [최종 답변 형식]
                1) 근본 원인: 한 줄 요약
                2) 상황 분석: 수집된 데이터 기반 구체적 설명 (과거 사례와의 차이 포함)
                3) 즉시 조치: 실행 가능한 항목 2~3개 (bullet 리스트)
                4) 심각도: 낮음/보통/높음/치명적 + 이유 한 줄

                답변은 짧고 실용적으로, 한국어로 써.
                """;
    }

    private String buildAlertDescription(AlertEvent alert, ActionRecommendation recommendation) {
        StringBuilder sb = new StringBuilder();
        sb.append("[발생 알람]\n");
        sb.append("- 레벨: ").append(alert.getLevel()).append("\n");
        if (alert.getAlertName() != null)
            sb.append("- 알람명: ").append(alert.getAlertName()).append("\n");
        sb.append("- 메시지: ").append(alert.getMessage()).append("\n");
        if (alert.getAnnotationSummary() != null && !alert.getAnnotationSummary().isBlank())
            sb.append("- 요약: ").append(alert.getAnnotationSummary()).append("\n");
        if (alert.getAnnotationDescription() != null && !alert.getAnnotationDescription().isBlank())
            sb.append("- 설명: ").append(alert.getAnnotationDescription()).append("\n");
        if (alert.getLabelsJson() != null && !alert.getLabelsJson().isBlank())
            sb.append("- 레이블: ").append(alert.getLabelsJson()).append("\n");
        if (alert.getStartsAt() != null)
            sb.append("- 발생 시각: ").append(alert.getStartsAt()).append("\n");

        sb.append("\n[Playbook 권장 조치]\n");
        sb.append("- ").append(recommendation.toPromptLine()).append("\n");
        sb.append("(이 조치는 safety ceiling이야. 현재 상황에 맞게 판단해서 더 보수적인 접근이 필요하다면 그렇게 권고해.)\n");

        return sb.toString();
    }
}
