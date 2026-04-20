package io.ohgnoy.monitoring.application.pipeline;

import io.ohgnoy.monitoring.domain.alert.AlertEventRepository;
import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Component
public class AlertIndexingListener {

    private static final Logger log = LoggerFactory.getLogger(AlertIndexingListener.class);

    private final AlertEventRepository alertEventRepository;
    private final AlertVectorService alertVectorService;

    public AlertIndexingListener(AlertEventRepository alertEventRepository,
                                 AlertVectorService alertVectorService) {
        this.alertEventRepository = alertEventRepository;
        this.alertVectorService = alertVectorService;
    }

    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onAlertIndexing(AlertIndexingEvent event) {
        alertEventRepository.findById(event.alertId()).ifPresent(alert -> {
            try {
                log.info("[Indexing] 벡터 인덱싱 시작 — alertId={}", alert.getId());
                alertVectorService.indexAlert(alert);
            } catch (Exception e) {
                log.error("[Indexing] 벡터 인덱싱 실패 — alertId={}: {}", alert.getId(), e.getMessage());
            }
        });
    }
}
