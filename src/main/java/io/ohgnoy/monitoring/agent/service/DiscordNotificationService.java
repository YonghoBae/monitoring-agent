package io.ohgnoy.monitoring.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class DiscordNotificationService {

    private static final Logger log = LoggerFactory.getLogger(DiscordNotificationService.class);

    private final RestClient restClient;
    private final String webhookUrl;
    private final ObjectMapper objectMapper;

    public DiscordNotificationService(RestClient.Builder builder,
                                      @Value("${discord.webhook.url}") String webhookUrl,
                                      ObjectMapper objectMapper) {
        this.restClient = builder.build();
        this.webhookUrl = webhookUrl;
        this.objectMapper = objectMapper;
    }

    public void sendAlert(AlertEvent alert,
                          String agentAnalysis,
                          VerificationResult verification,
                          ActionRecommendation recommendation) {

        String verificationLine = verification != null
                ? "🔍 **검증**: " + verification.toPromptLine()
                : "🔍 **검증**: -";

        String actionLine = buildActionLine(recommendation, alert);

        String content = """
                🔔 **Monitoring Alert**
                • Level: `%s`  |  Alert: `%s`
                • %s
                • Time: `%s`  |  ID: `%s`

                %s

                🤖 **Agent Analysis**
                %s
                """.formatted(
                alert.getLevel(),
                alert.getAlertName() != null ? alert.getAlertName() : alert.getMessage(),
                verificationLine,
                alert.getCreatedAt(),
                alert.getId(),
                actionLine,
                agentAnalysis == null || agentAnalysis.isBlank()
                        ? "_분석 결과를 생성하지 못했습니다._"
                        : agentAnalysis
        );

        sendToDiscord(content);
    }

    private String buildActionLine(ActionRecommendation rec, AlertEvent alert) {
        if (rec == null) return "";
        String command = resolveCommand(rec.command(), alert);
        return switch (rec.category()) {
            case AUTO ->
                    "✅ **자동 조치**: " + rec.description()
                    + (command != null ? "\n```" + command + "```" : "");
            case NEEDS_APPROVAL ->
                    "⚠️ **승인 필요**: " + rec.description()
                    + (command != null ? "\n```" + command + "```" : "")
                    + (command != null ? "\n> 허가하려면 Discord에 **`approve " + command + "`** 를 입력하세요." : "");
            case READ_ONLY ->
                    "📊 **정보 수집**: " + rec.description();
            case NONE ->
                    "🔧 **수동 조치 필요**: " + rec.description();
        };
    }

    /** 커맨드 템플릿의 {key} 를 alert labels 값으로 치환 */
    @SuppressWarnings("unchecked")
    private String resolveCommand(String command, AlertEvent alert) {
        if (command == null) return null;
        if (alert.getLabelsJson() == null || alert.getLabelsJson().isBlank()) return command;
        try {
            Map<String, String> labels = objectMapper.readValue(alert.getLabelsJson(), Map.class);
            for (Map.Entry<String, String> e : labels.entrySet()) {
                command = command.replace("{" + e.getKey() + "}", e.getValue());
            }
        } catch (Exception ignored) {}
        return command;
    }

    private void sendToDiscord(String content) {
        // Discord 메시지 최대 2000자 제한
        if (content.length() > 2000) {
            content = content.substring(0, 1990) + "\n...(생략)";
        }
        try {
            restClient.post()
                    .uri(webhookUrl)
                    .body(Map.of("content", content))
                    .retrieve()
                    .toBodilessEntity();
        } catch (Exception e) {
            log.error("Discord 전송 실패: {}", e.getMessage());
        }
    }
}
