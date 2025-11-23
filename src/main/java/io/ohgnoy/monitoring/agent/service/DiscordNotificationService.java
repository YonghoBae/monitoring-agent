package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class DiscordNotificationService {

    private final RestClient restClient;
    private final String webhookUrl;

    public DiscordNotificationService(RestClient.Builder builder,
                                      @Value("${discord.webhook.url}") String webhookUrl) {
        this.restClient = builder.build();
        this.webhookUrl = webhookUrl;
    }

    public void sendAlert(AlertEvent alert, String agentAnalysis) {
        String content = """
                🔔 *Monitoring Alert*
                • Level: `%s`
                • Message: %s
                • Time: %s
                • ID: %s

                🤖 *Agent Analysis*
                %s
                """.formatted(
                alert.getLevel(),
                alert.getMessage(),
                alert.getCreatedAt(),
                alert.getId(),
                agentAnalysis == null || agentAnalysis.isBlank()
                        ? "_분석 결과를 생성하지 못했습니다._"
                        : agentAnalysis
        );

        Map<String, Object> payload = Map.of("content", content);

        restClient.post()
                .uri(webhookUrl)
                .body(payload)
                .retrieve()
                .toBodilessEntity();
    }

    // 필요하면 옛 인터페이스 유지용 헬퍼
    public void sendAlert(AlertEvent alert) {
        sendAlert(alert, null);
    }
}

