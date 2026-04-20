package io.ohgnoy.monitoring.application.agent;

public record AgentResult(
        String conclusion,
        String reasoningChain,
        int iterationCount,
        String reflectionResult
) {
}
