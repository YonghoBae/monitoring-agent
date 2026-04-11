package io.ohgnoy.monitoring.agent.domain;

import jakarta.persistence.*;
import lombok.Getter;

import java.time.Instant;

@Entity
@Table(name = "resolution_record")
@Getter
public class ResolutionRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "alert_event_id")
    private Long alertEventId;

    @Column(name = "alert_name", length = 255)
    private String alertName;

    @Column(name = "alert_summary", columnDefinition = "TEXT")
    private String alertSummary;

    @Column(name = "reasoning_chain", columnDefinition = "TEXT")
    private String reasoningChain;

    @Column(name = "resolution_steps", columnDefinition = "TEXT")
    private String resolutionSteps;

    // RESOLVED / FALSE_POSITIVE / AUTO_RESOLVED
    @Column(name = "outcome", length = 32)
    private String outcome;

    @Column(name = "labels_json", columnDefinition = "TEXT")
    private String labelsJson;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

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
        this.createdAt = Instant.now();
    }

    public void setVectorDocId(String vectorDocId) { this.vectorDocId = vectorDocId; }
}
