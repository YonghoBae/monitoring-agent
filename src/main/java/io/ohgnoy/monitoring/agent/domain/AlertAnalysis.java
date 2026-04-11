package io.ohgnoy.monitoring.agent.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import lombok.Getter;
import lombok.Setter;

/**
 * ReAct 에이전트 분석 결과를 담는 임베디드 값 객체.
 * AlertEvent 엔티티에 포함되어 분석 관련 필드를 응집시킨다.
 */
@Embeddable
@Getter
@Setter
public class AlertAnalysis {

    @Column(name = "analysis_result", columnDefinition = "TEXT")
    private String analysisResult;

    @Column(name = "verification_status", length = 32)
    private String verificationStatus;

    @Column(name = "reasoning_chain", columnDefinition = "TEXT")
    private String reasoningChain;

    @Column(name = "agent_iterations")
    private int agentIterations;

    @Column(name = "reflection_result", columnDefinition = "TEXT")
    private String reflectionResult;
}
