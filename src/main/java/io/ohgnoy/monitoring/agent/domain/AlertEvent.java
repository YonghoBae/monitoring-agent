package io.ohgnoy.monitoring.agent.domain;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.Map;

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

    /**
     * 커맨드 템플릿의 {key}를 이 알람의 labels 값으로 치환한다.
     * 예: "docker restart {name}" → "docker restart nginx"
     */
    @SuppressWarnings("unchecked")
    public static String resolveTemplate(String template, String labelsJson, ObjectMapper objectMapper) {
        if (template == null || labelsJson == null || labelsJson.isBlank()) {
            return template;
        }
        try {
            Map<String, String> labels = objectMapper.readValue(labelsJson, Map.class);
            for (Map.Entry<String, String> e : labels.entrySet()) {
                template = template.replace("{" + e.getKey() + "}", e.getValue());
            }
        } catch (Exception e) {
            LoggerFactory.getLogger(AlertEvent.class)
                    .warn("라벨 JSON 파싱 실패 — template='{}', labelsJson='{}': {}",
                            template, labelsJson, e.getMessage());
        }
        return template;
    }
}
