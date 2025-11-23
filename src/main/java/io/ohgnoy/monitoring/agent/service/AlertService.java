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

    public AlertService(AlertEventRepository alertEventRepository,
                        AlertVectorService alertVectorService,
                        DiscordNotificationService discordNotificationService) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
        this.discordNotificationService = discordNotificationService;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        // 1) 도메인 객체 생성
        AlertEvent alert = new AlertEvent(level, message);

        // 2) RDB 저장
        AlertEvent saved = alertEventRepository.save(alert);

        // 3) 벡터 스토어 인덱싱
        alertVectorService.indexAlert(saved);

        // 4) 심각도에 따라 Discord 전송 (원하면 조건 더 추가 가능)
        if (shouldNotify(level)) {
            discordNotificationService.sendAlert(saved);
        }

        return saved;
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }

    private boolean shouldNotify(String level) {
        if (level == null) {
            return false;
        }
        String upper = level.toUpperCase();
        // 필요하면 INFO/WARN도 포함해서 조정
        return "ERROR".equals(upper) || "CRITICAL".equals(upper);
    }
}
