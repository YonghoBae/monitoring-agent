package io.ohgnoy.monitoring.agent.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.dto.AlertmanagerAlert;
import io.ohgnoy.monitoring.agent.dto.AlertmanagerWebhookPayload;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private final AlertEventRepository alertEventRepository;
    private final AlertVectorService alertVectorService;
    private final DiscordNotificationService discordNotificationService;
    private final MonitoringAgentService monitoringAgentService;
    private final AlertVerifier alertVerifier;
    private final AlertPlaybook alertPlaybook;
    private final ObjectMapper objectMapper;

    public AlertService(AlertEventRepository alertEventRepository,
                        AlertVectorService alertVectorService,
                        DiscordNotificationService discordNotificationService,
                        MonitoringAgentService monitoringAgentService,
                        AlertVerifier alertVerifier,
                        AlertPlaybook alertPlaybook,
                        ObjectMapper objectMapper) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
        this.discordNotificationService = discordNotificationService;
        this.monitoringAgentService = monitoringAgentService;
        this.alertVerifier = alertVerifier;
        this.alertPlaybook = alertPlaybook;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        AlertEvent alert = new AlertEvent(level, message);
        AlertEvent saved = alertEventRepository.save(alert);
        alertVectorService.indexAlert(saved);

        if (shouldNotify(level)) {
            runAgentPipeline(saved);
        }
        return saved;
    }

    @Transactional
    public void processWebhookPayload(AlertmanagerWebhookPayload payload) {
        for (AlertmanagerAlert alert : payload.getAlerts()) {
            try {
                if ("resolved".equals(alert.getStatus())) {
                    resolveMatchingAlerts(alert);
                } else {
                    createAlertFromWebhook(alert);
                }
            } catch (Exception e) {
                log.error("알람 처리 실패: {}", alert, e);
            }
        }
    }

    private AlertEvent createAlertFromWebhook(AlertmanagerAlert alert) {
        String alertName  = alert.getLabels().getOrDefault("alertname", "");
        String severity   = alert.getLabels().getOrDefault("severity", "warn").toUpperCase();
        String summary    = alert.getAnnotations() != null
                ? alert.getAnnotations().getOrDefault("summary", "") : "";
        String desc       = alert.getAnnotations() != null
                ? alert.getAnnotations().getOrDefault("description", "") : "";
        String message    = "[" + alertName + "] " + summary;
        String labelsJson = toSortedJson(alert.getLabels());

        AlertEvent event = new AlertEvent(severity, message,
                alertName, labelsJson, summary, desc,
                alert.getStartsAt(), alert.getGeneratorURL());
        AlertEvent saved = alertEventRepository.save(event);
        alertVectorService.indexAlert(saved);

        if (shouldNotify(severity)) {
            runAgentPipeline(saved);
        }
        return saved;
    }

    /**
     * 4단계 에이전트 파이프라인
     *
     * 1. Verify     — 알람이 실제로 유효한가? (Prometheus 재확인)
     * 2. Investigate — 어떤 상황인가? (메트릭 + 로그 수집)
     * 3. Resolve    — 어떻게 해결하나? (Gemini 분석, Playbook 기반 권장 조치 포함)
     * 4. Authorize  — 자동 처리 vs 사용자 승인 필요 여부 결정 후 Discord 전송
     */
    private void runAgentPipeline(AlertEvent alert) {
        // Step 1: Verify
        log.info("[Pipeline] Step1 Verify — alertId={}, alertName={}", alert.getId(), alert.getAlertName());
        VerificationResult verification = alertVerifier.verify(alert);
        alert.setVerificationStatus(verification.status().name());
        log.info("[Pipeline] Verification result: {}", verification.status());

        // Step 2: Investigate (context collection happens inside MonitoringAgentService)
        // Step 3: Resolve — Gemini analysis with verification context
        ActionRecommendation recommendation = alertPlaybook.lookup(alert.getAlertName());
        log.info("[Pipeline] Step3 Resolve — recommendation={} ({})", recommendation.description(), recommendation.category());

        String analysis = monitoringAgentService.buildAgentAnalysis(alert, verification, recommendation);
        alert.setAnalysisResult(analysis);

        // Step 4: Authorize — notify Discord with full context
        log.info("[Pipeline] Step4 Authorize — category={}", recommendation.category());
        discordNotificationService.sendAlert(alert, analysis, verification, recommendation);
    }

    private void resolveMatchingAlerts(AlertmanagerAlert alert) {
        String alertName  = alert.getLabels().getOrDefault("alertname", "");
        String labelsJson = toSortedJson(alert.getLabels());
        List<AlertEvent> open = alertEventRepository
                .findByAlertNameAndLabelsJsonAndResolvedFalse(alertName, labelsJson);
        open.forEach(e -> {
            e.resolve();
            alertEventRepository.save(e);
        });
    }

    private String toSortedJson(Map<String, String> map) {
        try {
            return objectMapper.writeValueAsString(new TreeMap<>(map));
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }

    private boolean shouldNotify(String level) {
        if (level == null) return false;
        String upper = level.toUpperCase();
        return "ERROR".equals(upper) || "CRITICAL".equals(upper) || "WARNING".equals(upper) || "WARN".equals(upper);
    }
}
