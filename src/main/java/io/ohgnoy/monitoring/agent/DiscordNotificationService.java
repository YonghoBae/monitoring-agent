package io.ohgnoy.monitoring.agent;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.time.format.DateTimeFormatter;
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

    public void sendAlert(AlertEvent alert) {
        String content = """
                🔔 *Monitoring Alert*
                • Level: `%s`
                • Message: %s
                • Time: %s
                • ID: %s
                """.formatted(
                alert.getLevel(),
                alert.getMessage(),
                alert.getCreatedAt(),
                alert.getId()
        );

        Map<String, Object> payload = Map.of(
                "content", content
        );

        restClient.post()
                .uri(webhookUrl)
                .body(payload)
                .retrieve()
                .toBodilessEntity();
    }
}

