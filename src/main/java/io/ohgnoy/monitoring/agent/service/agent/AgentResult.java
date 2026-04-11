package io.ohgnoy.monitoring.agent.service.agent;

public record AgentResult(
        String conclusion,
        String reasoningChain,
        int iterationCount,
        String reflectionResult
) {
}
