package io.ohgnoy.monitoring.agent.domain;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "resolution_record")
public class ResolutionRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "alert_event_id")
    private Long alertEventId;

    @Column(name = "alert_name", length = 255)
    private String alertName;

    // 원본 알림 요약 (alertName + message + annotationSummary)
    @Column(name = "alert_summary", columnDefinition = "TEXT")
    private String alertSummary;

    // ReAct 루프에서 에이전트가 수집한 추론 과정
    @Column(name = "reasoning_chain", columnDefinition = "TEXT")
    private String reasoningChain;

    // 실제로 문제를 해결한 방법 (Discord 피드백 또는 에이전트 권고)
    @Column(name = "resolution_steps", columnDefinition = "TEXT")
    private String resolutionSteps;

    // RESOLVED / FALSE_POSITIVE / AUTO_RESOLVED
    @Column(name = "outcome", length = 32)
    private String outcome;

    @Column(name = "labels_json", columnDefinition = "TEXT")
    private String labelsJson;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    // PGVector에 저장된 문서 UUID (업데이트/삭제 시 사용)
    @Column(name = "vector_doc_id", length = 64)
    private String vectorDocId;

    protected ResolutionRecord() {
    }

    public ResolutionRecord(Long alertEventId, String alertName, String alertSummary,
                             String reasoningChain, String resolutionSteps,
                             String outcome, String labelsJson) {
        this.alertEventId = alertEventId;
        this.alertName = alertName;
        this.alertSummary = alertSummary;
        this.reasoningChain = reasoningChain;
        this.resolutionSteps = resolutionSteps;
        this.outcome = outcome;
        this.labelsJson = labelsJson;
        this.createdAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public Long getAlertEventId() { return alertEventId; }
    public String getAlertName() { return alertName; }
    public String getAlertSummary() { return alertSummary; }
    public String getReasoningChain() { return reasoningChain; }
    public String getResolutionSteps() { return resolutionSteps; }
    public String getOutcome() { return outcome; }
    public String getLabelsJson() { return labelsJson; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public String getVectorDocId() { return vectorDocId; }
    public void setVectorDocId(String vectorDocId) { this.vectorDocId = vectorDocId; }
}
