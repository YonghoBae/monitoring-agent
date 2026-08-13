package io.ohgnoy.monitoring.domain.alert;

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

    // 분석 전 저장된 행은 NULL — primitive면 재시작 후 미처리 알람 재로드가 실패한다
    @Column(name = "agent_iterations")
    private Integer agentIterations;

    @Column(name = "reflection_result", columnDefinition = "TEXT")
    private String reflectionResult;
}
