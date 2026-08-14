package io.ohgnoy.monitoring.application.agent;

import io.ohgnoy.monitoring.application.agent.tools.AgentTools;
import io.ohgnoy.monitoring.application.agent.tools.AgentToolsFactory;
import io.ohgnoy.monitoring.application.agent.tools.WebSearchTool;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.playbook.ActionRecommendation;
import io.ohgnoy.monitoring.application.agent.evaluation.AgentJudgeEvaluator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

/**
 * ReAct 패턴 기반 에이전트.
 * Spring AI ChatClient의 Function Calling 기능을 이용해
 * Gemini가 필요한 도구를 스스로 선택하며 반복 추론한다.
 *
 * Reflection 자기검증은 ReflectionAdvisor가 담당한다.
 * ChatClient는 AgentConfig에서 생성한 단일 빈을 주입받는다.
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
    private final ReflectionAdvisor reflectionAdvisor;
    private final AgentToolsFactory agentToolsFactory;
    private final WebSearchTool webSearchTool;
    private final AgentJudgeEvaluator judgeEvaluator;
    private final String systemPrompt;

    public ReActAgent(@Qualifier("agentChatClient") ObjectProvider<ChatClient> chatClientProvider,
                      ObjectProvider<ReflectionAdvisor> reflectionAdvisorProvider,
                      AgentToolsFactory agentToolsFactory,
                      WebSearchTool webSearchTool,
                      AgentJudgeEvaluator judgeEvaluator,
                      @Value("${agent.prompt-version:v1}") String promptVersion) {
        this.chatClient = chatClientProvider.getIfAvailable();
        this.reflectionAdvisor = reflectionAdvisorProvider.getIfAvailable();
        this.agentToolsFactory = agentToolsFactory;
        this.webSearchTool = webSearchTool;
        this.judgeEvaluator = judgeEvaluator;
        this.systemPrompt = loadSystemPrompt(promptVersion);
    }

    /**
     * 시스템 프롬프트를 classpath 리소스에서 버전별로 로드한다.
     * v1: 초기 프롬프트 — 라이브 평가 결과(38 시나리오 x 3반복, flash 기준) 통과율 65%로 최고 성능. 현재 운영 기본값
     * v2: Tool-Over-Ask 및 종료 기준 포함 — 동일 평가에서 통과율 11% (계획만 서술하고 결론 없이 종료하는 회귀), 운영 제외
     * v3: 결론 강제 지시 추가 — 통과율 64%로 v1과 동급이나 도구 호출 22% 증가, 채택 보류
     */
    static String loadSystemPrompt(String version) {
        String path = "/prompts/react-system-" + version + ".txt";
        try (InputStream in = ReActAgent.class.getResourceAsStream(path)) {
            if (in == null) {
                throw new IllegalStateException("시스템 프롬프트 리소스 없음: " + path);
            }
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException("시스템 프롬프트 로드 실패: " + path, e);
        }
    }

    public AgentResult run(AlertEvent alert, ActionRecommendation recommendation) {
        AgentResult result = runInternal(alert, buildAlertDescription(alert, recommendation));
        judgeEvaluator.evaluate(alert, result);
        return result;
    }

    public AgentResult runWithContext(AlertEvent alert, ActionRecommendation recommendation, String additionalContext) {
        AgentResult result = runInternal(alert, buildAlertDescription(alert, recommendation) + additionalContext);
        judgeEvaluator.evaluate(alert, result);
        return result;
    }

    private AgentResult runInternal(AlertEvent alert, String userMessage) {
        if (chatClient == null) {
            return new AgentResult(
                    "에이전트 분석 기능이 비활성화되어 있습니다. (Gemini API 키 미설정)",
                    "", 0, null
            );
        }

        log.info("[ReActAgent] 분석 시작 — alertId={}, alertName={}", alert.getId(), alert.getAlertName());

        AgentTools agentTools = agentToolsFactory.createAgentTools();
        AtomicReference<String> reflectionResultHolder = new AtomicReference<>();

        try {
            String conclusion = chatClient.prompt()
                    .advisors(spec -> {
                        spec.param(ReflectionAdvisor.CTX_ALERT, alert)
                                .param(ReflectionAdvisor.CTX_AGENT_TOOLS, agentTools)
                                .param(ReflectionAdvisor.CTX_REFLECTION_RESULT, reflectionResultHolder);
                        if (reflectionAdvisor != null) {
                            spec.advisors(reflectionAdvisor);
                        }
                    })
                    .system(buildSystemPrompt())
                    .user(userMessage)
                    .tools(agentTools, webSearchTool)
                    .call()
                    .content();

            int iterationCount = agentTools.getCallCount();
            String reasoningChain = agentTools.getReasoningLog();
            String reflectionResult = reflectionResultHolder.get();
            log.info("[ReActAgent] 분석 완료 — alertId={}, toolCalls={}", alert.getId(), iterationCount);

            // Reflection이 근거 불충분으로 판정하면 피드백을 붙여 1회 재분석한다.
            // (advisor 체인은 소모형이라 체인 내부 재호출이 불가능 — 여기서 새 요청으로 수행)
            if (reflectionResult != null && reflectionResult.startsWith("INSUFFICIENT")) {
                log.info("[ReActAgent] Reflection 재분석 시작 — alertId={}", alert.getId());

                AgentTools retryTools = agentToolsFactory.createAgentTools();
                String retriedConclusion = chatClient.prompt()
                        .system(buildSystemPrompt())
                        .user(userMessage
                                + "\n\n[이전 분석 검토 결과]\n" + reflectionResult
                                + "\n\n[이전 분석에서 수집한 데이터]\n" + (reasoningChain.isBlank() ? "없음" : reasoningChain)
                                + "\n\n위 피드백을 반영하고, 이미 수집한 데이터는 재조회하지 말고 추가로 필요한 데이터만 수집해서 다시 분석해줘.")
                        .tools(retryTools, webSearchTool)
                        .call()
                        .content();

                int totalCalls = iterationCount + retryTools.getCallCount();
                log.info("[ReActAgent] 재분석 완료 — alertId={}, totalToolCalls={}", alert.getId(), totalCalls);

                // 모델이 도구 호출 후 텍스트 없이 종료하면 content()가 null일 수 있다.
                // 빈 재분석 결론으로 최초 결론을 덮어쓰지 않는다.
                if (retriedConclusion == null || retriedConclusion.isBlank()) {
                    log.warn("[ReActAgent] 재분석 결론이 비어 있음 — 최초 결론 유지. alertId={}", alert.getId());
                    retriedConclusion = conclusion;
                }
                return new AgentResult(retriedConclusion,
                        reasoningChain + "\n[Reflection 재분석]\n" + retryTools.getReasoningLog(),
                        totalCalls, reflectionResult);
            }

            return new AgentResult(conclusion, reasoningChain, iterationCount, reflectionResult);

        } catch (Exception e) {
            log.error("[ReActAgent] 분석 실패 — alertId={}: {}", alert.getId(), e.getMessage());
            return new AgentResult(
                    "AI 분석 실패: " + e.getMessage(),
                    agentTools.getReasoningLog(), agentTools.getCallCount(), null
            );
        }
    }

    private String buildSystemPrompt() {
        return systemPrompt;
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
