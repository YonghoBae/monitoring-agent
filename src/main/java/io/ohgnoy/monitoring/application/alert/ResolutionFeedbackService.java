package io.ohgnoy.monitoring.application.alert;

import io.ohgnoy.monitoring.domain.alert.AlertEvent;
import io.ohgnoy.monitoring.domain.alert.AlertEventRepository;
import io.ohgnoy.monitoring.domain.resolution.ResolutionRecord;
import io.ohgnoy.monitoring.domain.resolution.ResolutionRecordRepository;

import io.ohgnoy.monitoring.infrastructure.rag.AlertVectorService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Discord 피드백을 수신하여 해결 기록을 저장하고 RAG 지식베이스를 갱신한다.
 *
 * 지원 커맨드:
 * - "resolved <alertId> [해결 방법]"  → RESOLVED 기록
 * - "false-positive <alertId>"        → FALSE_POSITIVE 기록
 */
@Service
public class ResolutionFeedbackService {

    private static final Logger log = LoggerFactory.getLogger(ResolutionFeedbackService.class);

    private final AlertEventRepository alertEventRepository;
    private final ResolutionRecordRepository resolutionRecordRepository;
    private final AlertVectorService alertVectorService;

    public ResolutionFeedbackService(AlertEventRepository alertEventRepository,
                                     ResolutionRecordRepository resolutionRecordRepository,
                                     AlertVectorService alertVectorService) {
        this.alertEventRepository = alertEventRepository;
        this.resolutionRecordRepository = resolutionRecordRepository;
        this.alertVectorService = alertVectorService;
    }

    @Transactional
    public String recordOutcome(long alertId, String outcome, String resolutionNote) {
        AlertEvent alert = alertEventRepository.findById(alertId).orElse(null);
        if (alert == null) {
            return "❌ 알람을 찾을 수 없음: alertId=" + alertId;
        }

        // 이미 피드백이 등록된 경우
        if (alert.getResolutionRecordId() != null) {
            return "⚠️ 이미 피드백이 등록된 알람: alertId=" + alertId;
        }

        String alertSummary = buildSummary(alert);
        String resolutionSteps = resolutionNote.isBlank()
                ? (alert.getAnalysisResult() != null ? alert.getAnalysisResult() : "기록 없음")
                : resolutionNote;

        ResolutionRecord record = new ResolutionRecord(
                alertId,
                alert.getAlertName(),
                alertSummary,
                alert.getReasoningChain(),
                resolutionSteps,
                outcome,
                alert.getLabelsJson()
        );

        ResolutionRecord saved = resolutionRecordRepository.save(record);

        // PGVector에 인덱싱 (다음 search_rag에서 검색 가능)
        String vectorDocId = alertVectorService.indexResolution(saved);
        saved.setVectorDocId(vectorDocId);
        resolutionRecordRepository.save(saved);

        // AlertEvent에 ResolutionRecord 연결
        alert.setResolutionRecordId(saved.getId());
        alertEventRepository.save(alert);

        log.info("[FeedbackService] 해결 기록 저장 — alertId={}, outcome={}, vectorDocId={}",
                alertId, outcome, vectorDocId);

        return "✅ 피드백 기록 완료 — alertId=" + alertId + ", outcome=" + outcome;
    }

    private String buildSummary(AlertEvent alert) {
        return Stream.of(alert.getAlertName(), alert.getMessage(), alert.getAnnotationSummary())
                .filter(s -> s != null && !s.isBlank())
                .collect(Collectors.joining(" | "));
    }
}
