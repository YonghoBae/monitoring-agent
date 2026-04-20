package io.ohgnoy.monitoring.application.pipeline;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * AlertCreatedEvent를 수신해 분석 파이프라인을 실행한다.
 *
 * @TransactionalEventListener(AFTER_COMMIT): AlertService의 트랜잭션이 커밋된 후 실행.
 * @Async: 별도 스레드에서 실행 → AlertService 응답을 블로킹하지 않음.
 *
 * 두 조합으로 AlertService의 @Transactional 범위 밖에서 파이프라인이 실행되므로
 * LLM 호출 중 DB 커넥션이 점유되지 않는다.
 */
@Component
public class AlertPipelineListener {

    private static final Logger log = LoggerFactory.getLogger(AlertPipelineListener.class);

    private final AlertAnalysisChain alertAnalysisChain;

    public AlertPipelineListener(AlertAnalysisChain alertAnalysisChain) {
        this.alertAnalysisChain = alertAnalysisChain;
    }

    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onAlertCreated(AlertCreatedEvent event) {
        log.info("[Pipeline] 이벤트 수신 — alertId={}", event.alertId());
        try {
            alertAnalysisChain.run(event.alertId());
        } catch (Exception e) {
            log.error("[Pipeline] 파이프라인 실패 — alertId={}: {}", event.alertId(), e.getMessage(), e);
        }
    }
}
