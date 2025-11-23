package io.ohgnoy.monitoring.agent.service;

import io.ohgnoy.monitoring.agent.domain.AlertEvent;
import io.ohgnoy.monitoring.agent.repository.AlertEventRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class AlertService {

    private final AlertEventRepository alertEventRepository;
    private final AlertVectorService alertVectorService;
    private final DiscordNotificationService discordNotificationService;
    private final MonitoringAgentService monitoringAgentService;

    public AlertService(AlertEventRepository alertEventRepository,
                        AlertVectorService alertVectorService,
                        DiscordNotificationService discordNotificationService,
                        MonitoringAgentService monitoringAgentService) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
        this.discordNotificationService = discordNotificationService;
        this.monitoringAgentService = monitoringAgentService;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        AlertEvent alert = new AlertEvent(level, message);
        AlertEvent saved = alertEventRepository.save(alert);

        // 1) 벡터 인덱싱
        alertVectorService.indexAlert(saved);

        // 2) 심각한 알람만 에이전트 분석 + 디스코드 전송
        if (shouldNotify(level)) {
            String analysis = monitoringAgentService.buildAgentAnalysis(saved);
            discordNotificationService.sendAlert(saved, analysis);
        }

        return saved;
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }

    private boolean shouldNotify(String level) {
        if (level == null) return false;
        String upper = level.toUpperCase();
        return "ERROR".equals(upper) || "CRITICAL".equals(upper);
    }
}

