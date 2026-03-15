package io.ohgnoy.monitoring.agent.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;

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
    private LocalDateTime createdAt;

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
    private LocalDateTime startsAt;

    @Column(length = 1000)
    private String generatorURL;

    @Column(name = "resolved_at")
    private LocalDateTime resolvedAt;

    @Column(name = "analysis_result", columnDefinition = "TEXT")
    private String analysisResult;

    @Column(name = "verification_status", length = 32)
    private String verificationStatus;

    protected AlertEvent() {
    }

    public AlertEvent(String level, String message) {
        this.level = level;
        this.message = message;
        this.createdAt = LocalDateTime.now();
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
        this.startsAt = startsAt != null
                ? LocalDateTime.ofInstant(startsAt, ZoneId.systemDefault())
                : null;
        this.generatorURL = generatorURL;
        this.createdAt = LocalDateTime.now();
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

    public LocalDateTime getCreatedAt() {
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

    public LocalDateTime getStartsAt() {
        return startsAt;
    }

    public String getGeneratorURL() {
        return generatorURL;
    }

    public LocalDateTime getResolvedAt() {
        return resolvedAt;
    }

    public String getAnalysisResult() {
        return analysisResult;
    }

    public void setAnalysisResult(String analysisResult) {
        this.analysisResult = analysisResult;
    }

    public String getVerificationStatus() {
        return verificationStatus;
    }

    public void setVerificationStatus(String verificationStatus) {
        this.verificationStatus = verificationStatus;
    }

    public void resolve() {
        this.resolved = true;
        this.resolvedAt = LocalDateTime.now();
    }
}
