package io.ohgnoy.monitoring.agent;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class AlertService {

    private final AlertEventRepository alertEventRepository;
    private final AlertVectorService alertVectorService;

    public AlertService(AlertEventRepository alertEventRepository,
                        AlertVectorService alertVectorService) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
    }

    @Transactional
    public AlertEvent createAlert(String level, String message) {
        AlertEvent alert = new AlertEvent(level, message);
        AlertEvent saved = alertEventRepository.save(alert);

        // 트랜잭션 안에서 인덱싱까지 같이 수행
        alertVectorService.indexAlert(saved);

        return saved;
    }

    @Transactional(readOnly = true)
    public List<AlertEvent> getRecentOpenAlerts() {
        return alertEventRepository.findTop20ByResolvedFalseOrderByCreatedAtDesc();
    }
}
