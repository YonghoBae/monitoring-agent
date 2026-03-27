package io.ohgnoy.monitoring.agent.service.agent;

import io.ohgnoy.monitoring.agent.service.ActionRecommendation;

public record AgentResult(
        String conclusion,
        String reasoningChain,
        int iterationCount,
        String reflectionResult,
        ActionRecommendation recommendation
) {
}
