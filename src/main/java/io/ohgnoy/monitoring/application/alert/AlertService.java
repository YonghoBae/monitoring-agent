package io.ohgnoy.monitoring.application.alert;

import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.alert.AlertEventRepository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ohgnoy.monitoring.application.pipeline.AlertCreatedEvent;
import io.ohgnoy.monitoring.application.pipeline.AlertIndexingEvent;
import io.ohgnoy.monitoring.web.dto.AlertmanagerAlert;
import io.ohgnoy.monitoring.web.dto.AlertmanagerWebhookPayload;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private final AlertEventRepository alertEventRepository;
    private final ApplicationEventPublisher eventPublisher;
    private final ObjectMapper objectMapper;

    public AlertService(AlertEventRepository alertEventRepository,
                        ApplicationEventPublisher eventPublisher,
                        ObjectMapper objectMapper) {
        this.alertEventRepository = alertEventRepository;
        this.eventPublisher = eventPublisher;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        AlertEvent alert = new AlertEvent(level, message);
        AlertEvent saved = alertEventRepository.save(alert);
        eventPublisher.publishEvent(new AlertIndexingEvent(saved.getId()));
        if (shouldNotify(level)) {
            eventPublisher.publishEvent(new AlertCreatedEvent(saved.getId()));
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

        // Alertmanager repeat_interval 재전송 중복 제거: 같은 알림 인스턴스(startsAt 동일)가
        // 미해결 상태로 이미 있으면 새 이벤트를 만들지 않는다. startsAt이 다르면 새 발화로 취급.
        List<AlertEvent> open = alertEventRepository
                .findByAlertNameAndLabelsJsonAndResolvedFalse(alertName, labelsJson);
        for (AlertEvent existing : open) {
            if (existing.getStartsAt() != null && existing.getStartsAt().equals(alert.getStartsAt())) {
                log.info("중복 알람 스킵: {} (기존 미해결 id={}, startsAt={})",
                        alertName, existing.getId(), alert.getStartsAt());
                return existing;
            }
        }

        AlertEvent event = new AlertEvent(severity, message,
                alertName, labelsJson, summary, desc,
                alert.getStartsAt(), alert.getGeneratorURL());
        AlertEvent saved = alertEventRepository.save(event);
        eventPublisher.publishEvent(new AlertIndexingEvent(saved.getId()));

        if (shouldNotify(severity)) {
            eventPublisher.publishEvent(new AlertCreatedEvent(saved.getId()));
        }
        return saved;
    }

    private void resolveMatchingAlerts(AlertmanagerAlert alert) {
        String alertName  = alert.getLabels().getOrDefault("alertname", "");
        String labelsJson = toSortedJson(alert.getLabels());
        List<AlertEvent> open = alertEventRepository
                .findByAlertNameAndLabelsJsonAndResolvedFalse(alertName, labelsJson);
        open.forEach(AlertEvent::resolve);
        alertEventRepository.saveAll(open);
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }

    private boolean shouldNotify(String level) {
        if (level == null) return false;
        String upper = level.toUpperCase();
        return "ERROR".equals(upper) || "CRITICAL".equals(upper)
                || "WARNING".equals(upper) || "WARN".equals(upper);
    }

    private String toSortedJson(Map<String, String> map) {
        try {
            return objectMapper.writeValueAsString(new TreeMap<>(map));
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }
}
