package io.ohgnoy.monitoring.domain.alert;

import jakarta.persistence.*;

import java.time.Instant;

@Entity
@Table(name = "alert_event")
public class AlertEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 32)
    private String level;   // INFO / WARN / ERROR 등

    @Column(nullable = false, length = 500)
    private String message; // 알람 메시지 원문

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(nullable = false)
    private boolean resolved;

    @Column(length = 255)
    private String alertName;

    @Column(columnDefinition = "TEXT")
    private String labelsJson;

    @Column(length = 500)
    private String annotationSummary;

    @Column(columnDefinition = "TEXT")
    private String annotationDescription;

    @Column(name = "starts_at")
    private Instant startsAt;

    @Column(length = 1000)
    private String generatorURL;

    @Column(name = "resolved_at")
    private Instant resolvedAt;

    @Embedded
    private AlertAnalysis analysis = new AlertAnalysis();

    // 피드백 수신 후 연결된 ResolutionRecord ID
    @Column(name = "resolution_record_id")
    private Long resolutionRecordId;

    @PrePersist
    protected void prePersist() {
        if (createdAt == null) {
            createdAt = Instant.now();
        }
    }

    protected AlertEvent() {
    }

    public AlertEvent(String level, String message) {
        this.level = level;
        this.message = message;
        this.resolved = false;
    }

    public AlertEvent(String level, String message,
                      String alertName, String labelsJson,
                      String annotationSummary, String annotationDescription,
                      Instant startsAt, String generatorURL) {
        this.level = level;
        this.message = message;
        this.alertName = alertName;
        this.labelsJson = labelsJson;
        this.annotationSummary = annotationSummary;
        this.annotationDescription = annotationDescription;
        this.startsAt = startsAt;
        this.generatorURL = generatorURL;
        this.resolved = false;
    }

    public Long getId() {
        return id;
    }

    public String getLevel() {
        return level;
    }

    public String getMessage() {
        return message;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public boolean isResolved() {
        return resolved;
    }

    public String getAlertName() {
        return alertName;
    }

    public String getLabelsJson() {
        return labelsJson;
    }

    public String getAnnotationSummary() {
        return annotationSummary;
    }

    public String getAnnotationDescription() {
        return annotationDescription;
    }

    public Instant getStartsAt() {
        return startsAt;
    }

    public String getGeneratorURL() {
        return generatorURL;
    }

    public Instant getResolvedAt() {
        return resolvedAt;
    }

    public AlertAnalysis getAnalysis() { return analysis; }

    public String getAnalysisResult() { return analysis.getAnalysisResult(); }
    public void setAnalysisResult(String analysisResult) { analysis.setAnalysisResult(analysisResult); }

    public String getVerificationStatus() { return analysis.getVerificationStatus(); }
    public void setVerificationStatus(String verificationStatus) { analysis.setVerificationStatus(verificationStatus); }

    public String getReasoningChain() { return analysis.getReasoningChain(); }
    public void setReasoningChain(String reasoningChain) { analysis.setReasoningChain(reasoningChain); }

    public int getAgentIterations() { return analysis.getAgentIterations(); }
    public void setAgentIterations(int agentIterations) { analysis.setAgentIterations(agentIterations); }

    public String getReflectionResult() { return analysis.getReflectionResult(); }
    public void setReflectionResult(String reflectionResult) { analysis.setReflectionResult(reflectionResult); }

    public Long getResolutionRecordId() { return resolutionRecordId; }
    public void setResolutionRecordId(Long resolutionRecordId) { this.resolutionRecordId = resolutionRecordId; }

    public void resolve() {
        this.resolved = true;
        this.resolvedAt = Instant.now();
    }

}
