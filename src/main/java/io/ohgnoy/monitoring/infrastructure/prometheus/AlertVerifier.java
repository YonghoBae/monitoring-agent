package io.ohgnoy.monitoring.infrastructure.prometheus;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class AlertVerifier {

    private static final Logger log = LoggerFactory.getLogger(AlertVerifier.class);

    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    public AlertVerifier(RestClient.Builder builder,
                         @Value("${prometheus.url}") String prometheusUrl,
                         ObjectMapper objectMapper) {
        this.restClient = builder.baseUrl(prometheusUrl).build();
        this.objectMapper = objectMapper;
    }

    /**
     * AgentTools에서 직접 호출하기 위한 오버로드
     */
    public VerificationResult verify(String alertName, String labelsJson) {
        if (alertName == null || alertName.isBlank()) {
            return VerificationResult.unknown();
        }
        try {
            String response = restClient.get()
                    .uri("/api/v1/alerts")
                    .retrieve()
                    .body(String.class);

            JsonNode alerts = objectMapper.readTree(response)
                    .path("data").path("alerts");

            Map<String, String> labels = parseLabels(labelsJson);
            if (labels.isEmpty()) {
                return VerificationResult.unknown();
            }

            for (JsonNode firing : alerts) {
                JsonNode firingLabels = firing.path("labels");
                if (!alertName.equals(firingLabels.path("alertname").asText())) continue;
                if (!allLabelsMatch(labels, firingLabels)) continue;

                return VerificationResult.confirmed(
                        firing.path("value").asText("N/A"),
                        firing.path("activeAt").asText("N/A")
                );
            }
            return VerificationResult.stale();
        } catch (Exception e) {
            log.warn("알람 검증 실패 [{}]: {}", alertName, e.getMessage());
            return VerificationResult.unknown();
        }
    }

    /**
     * Prometheus /api/v1/alerts 에서 현재 firing 중인 알람과 대조해 검증한다.
     * - CONFIRMED : 지금도 동일 조건으로 firing 중
     * - STALE     : 조건이 해소돼 firing 목록에 없음
     * - UNKNOWN   : Prometheus 통신 실패
     */
    public VerificationResult verify(AlertEvent alert) {
        if (alert.getAlertName() == null || alert.getAlertName().isBlank()) {
            return VerificationResult.unknown();
        }

        try {
            String response = restClient.get()
                    .uri("/api/v1/alerts")
                    .retrieve()
                    .body(String.class);

            JsonNode alerts = objectMapper.readTree(response)
                    .path("data").path("alerts");

            Map<String, String> labels = parseLabels(alert.getLabelsJson());
            if (labels.isEmpty()) {
                return VerificationResult.unknown();
            }

            for (JsonNode firing : alerts) {
                JsonNode firingLabels = firing.path("labels");

                if (!alert.getAlertName().equals(firingLabels.path("alertname").asText())) continue;
                if (!allLabelsMatch(labels, firingLabels)) continue;

                return VerificationResult.confirmed(
                        firing.path("value").asText("N/A"),
                        firing.path("activeAt").asText("N/A")
                );
            }

            return VerificationResult.stale();

        } catch (Exception e) {
            log.warn("알람 검증 실패 [{}]: {}", alert.getAlertName(), e.getMessage());
            return VerificationResult.unknown();
        }
    }

    // Alertmanager가 보낸 원본 labels 전체가 Prometheus firing labels에 포함되어야 같은 알림으로 본다.
    private boolean allLabelsMatch(Map<String, String> alertLabels, JsonNode firingLabels) {
        for (Map.Entry<String, String> entry : alertLabels.entrySet()) {
            String key = entry.getKey();
            String alertVal = entry.getValue();
            if (key == null || key.isBlank() || alertVal == null) {
                return false;
            }
            if (!firingLabels.has(key)) {
                return false;
            }
            if (!alertVal.equals(firingLabels.path(key).asText())) {
                return false;
            }
        }
        return true;
    }

    @SuppressWarnings("unchecked")
    private Map<String, String> parseLabels(String labelsJson) {
        if (labelsJson == null || labelsJson.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(labelsJson, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }
}
