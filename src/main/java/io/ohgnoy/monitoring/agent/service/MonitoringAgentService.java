package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Service
public class MonitoringAgentService {

    private static final Logger log = LoggerFactory.getLogger(MonitoringAgentService.class);

    private final ChatModel chatModel;
    private final AlertVectorService alertVectorService;
    private final AlertContextCollector contextCollector;

    public MonitoringAgentService(
            @Qualifier("googleGenAiChatModel") @Nullable ChatModel chatModel,
            AlertVectorService alertVectorService,
            AlertContextCollector contextCollector) {
        this.chatModel = chatModel;
        this.alertVectorService = alertVectorService;
        this.contextCollector = contextCollector;
    }

    /**
     * Step 2 (Investigate) + Step 3 (Resolve)
     * - 실시간 컨텍스트 수집 후 Gemini에게 분석 요청
     * - verification/recommendation 을 프롬프트에 포함해 AI가 상황을 정확히 인지하게 함
     */
    public String buildAgentAnalysis(AlertEvent alert,
                                     VerificationResult verification,
                                     ActionRecommendation recommendation) {
        if (chatModel == null) {
            return "에이전트 분석 기능이 비활성화되어 기본 메시지만 전송합니다.";
        }

        // Step 2: Investigate — 실시간 컨텍스트 수집
        log.info("[Pipeline] Step2 Investigate — alertId={}", alert.getId());
        AlertContext context = contextCollector.collect(alert);

        // 유사 과거 알람 검색
        String searchQuery = Stream.of(alert.getAlertName(), alert.getMessage(), alert.getAnnotationSummary())
                .filter(s -> s != null && !s.isBlank())
                .collect(Collectors.joining(" | "));
        if (searchQuery.isBlank()) searchQuery = alert.getMessage();

        List<Document> similar = alertVectorService.searchSimilar(searchQuery, 5);
        String similarSummary = similar.isEmpty()
                ? "유사 알람 없음"
                : similar.stream().map(doc -> "- " + doc.getText()).collect(Collectors.joining("\n"));

        // Step 3: Resolve — 프롬프트 구성
        String promptText = buildPrompt(alert, verification, recommendation, context, similarSummary);

        try {
            var response = chatModel.call(new Prompt(new UserMessage(promptText)));
            return response.getResult().getOutput().getText();
        } catch (Exception e) {
            log.error("Gemini 분석 실패 [alertId={}]: {}", alert.getId(), e.getMessage());
            return "AI 분석 실패: " + e.getMessage();
        }
    }

    private String buildPrompt(AlertEvent alert,
                                VerificationResult verification,
                                ActionRecommendation recommendation,
                                AlertContext context,
                                String similarSummary) {
        StringBuilder sb = new StringBuilder();
        sb.append("너는 인프라/서비스 모니터링 에이전트야.\n\n");

        // 발생 알람
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
        sb.append("\n");

        // 검증 결과
        sb.append("[검증 결과]\n");
        sb.append("- ").append(verification.toPromptLine()).append("\n\n");

        // 권장 조치 (Playbook)
        sb.append("[권장 조치]\n");
        sb.append("- ").append(recommendation.toPromptLine()).append("\n\n");

        // 실시간 메트릭
        if (!context.metricSummaries().isEmpty()) {
            sb.append("[실시간 메트릭]\n");
            context.metricSummaries().forEach(m -> sb.append("  ").append(m).append("\n"));
            sb.append("\n");
        }

        // 최근 로그
        if (!context.logLines().isEmpty()) {
            sb.append("[최근 로그]\n");
            context.logLines().stream().limit(20).forEach(l -> sb.append("  ").append(l).append("\n"));
            sb.append("\n");
        }

        // 동시 발생 알람
        if (!context.concurrentAlertNames().isEmpty()) {
            sb.append("[동시 발생 알람] ")
              .append(String.join(", ", context.concurrentAlertNames()))
              .append("\n\n");
        }

        // 유사 과거 알람
        sb.append("[유사 과거 알람]\n").append(similarSummary).append("\n\n");

        // 답변 지시
        sb.append("""
                위 정보를 바탕으로 다음을 작성해줘:
                1) 근본 원인: 한 줄 요약
                2) 상황 분석: 메트릭/로그 데이터를 근거로 구체적으로 설명
                3) 즉시 조치: 바로 시도할 수 있는 항목 2~3가지 (bullet 리스트)
                4) 심각도 판단: 낮음/보통/높음/치명적 + 이유 한 줄

                답변은 짧고 실용적으로, 한국어로 써.
                """);

        return sb.toString();
    }
}
