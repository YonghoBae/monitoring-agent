package io.ohgnoy.monitoring.agent.domain;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * LLM-as-a-Judge 평가 결과 저장 엔티티.
 * ReActAgent의 응답 품질을 4개 차원으로 측정한다.
 */
@Entity
@Table(name = "agent_evaluation")
public class AgentEvaluation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Version
    private Long version;

    @Column(name = "alert_event_id")
    private Long alertEventId;

    @Column(name = "alert_name", length = 255)
    private String alertName;

    // 에이전트 최종 결론
    @Column(name = "conclusion", columnDefinition = "TEXT")
    private String conclusion;

    // 도구 호출 횟수
    @Column(name = "tool_call_count")
    private int toolCallCount;

    // 1~10점: 수집된 데이터로 결론을 뒷받침하는지
    @Column(name = "factuality_score")
    private int factualityScore;

    // 1~10점: 필요한 도구를 적절히 사용했는지 (과다/과소 모두 감점)
    @Column(name = "tool_use_score")
    private int toolUseScore;

    // 1~10점: 권고 조치가 구체적이고 실행 가능한지
    @Column(name = "actionability_score")
    private int actionabilityScore;

    // 1~10점: 오탐 위험이 없는지 (10=위험 없음, 1=높은 오탐 위험)
    @Column(name = "hallucination_risk_score")
    private int hallucinationRiskScore;

    // 4개 차원 평균 (소수점 1자리)
    @Column(name = "overall_score")
    private double overallScore;

    // judge 상세 피드백
    @Column(name = "judge_feedback", columnDefinition = "TEXT")
    private String judgeFeedback;

    @Column(name = "evaluated_at", nullable = false)
    private LocalDateTime evaluatedAt;

    protected AgentEvaluation() {
    }

    public AgentEvaluation(Long alertEventId, String alertName, String conclusion,
                           int toolCallCount,
                           int factualityScore, int toolUseScore,
                           int actionabilityScore, int hallucinationRiskScore,
                           String judgeFeedback) {
        this.alertEventId = alertEventId;
        this.alertName = alertName;
        this.conclusion = conclusion;
        this.toolCallCount = toolCallCount;
        this.factualityScore = factualityScore;
        this.toolUseScore = toolUseScore;
        this.actionabilityScore = actionabilityScore;
        this.hallucinationRiskScore = hallucinationRiskScore;
        this.overallScore = (factualityScore + toolUseScore + actionabilityScore + hallucinationRiskScore) / 4.0;
        this.judgeFeedback = judgeFeedback;
        this.evaluatedAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public Long getAlertEventId() { return alertEventId; }
    public String getAlertName() { return alertName; }
    public String getConclusion() { return conclusion; }
    public int getToolCallCount() { return toolCallCount; }
    public int getFactualityScore() { return factualityScore; }
    public int getToolUseScore() { return toolUseScore; }
    public int getActionabilityScore() { return actionabilityScore; }
    public int getHallucinationRiskScore() { return hallucinationRiskScore; }
    public double getOverallScore() { return overallScore; }
    public String getJudgeFeedback() { return judgeFeedback; }
    public LocalDateTime getEvaluatedAt() { return evaluatedAt; }

    public boolean isHighQuality() {
        return overallScore >= 7.0;
    }

    @Override
    public String toString() {
        return String.format(
                "AgentEvaluation{alertId=%d, alertName='%s', overall=%.1f/10, " +
                "factuality=%d, toolUse=%d, actionability=%d, hallucinationRisk=%d}",
                alertEventId, alertName, overallScore,
                factualityScore, toolUseScore, actionabilityScore, hallucinationRiskScore
        );
    }
}
